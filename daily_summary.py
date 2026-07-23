"""
Headless one-shot standup report for scheduled runs (cron / Task Scheduler).

Generates the report since the last attended standup, archives it to
data/summaries/, prints it, optionally pushes to SUMMARY_WEBHOOK_URL,
and advances the cutoff. See agent/standup.py for the window logic.

For the interactive standup session (report + note-taking chat), use:
    python main.py --standup
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import date, datetime

import requests
from dotenv import load_dotenv

from agent.graph import build_agent
from agent.standup import archive_report, generate_report, load_cutoff, save_cutoff

load_dotenv()


async def run() -> int:
    today = date.today()
    if today.weekday() >= 5:
        print("Weekend - skipping.")
        return 0

    now = datetime.now()
    since, is_fallback = load_cutoff(today)
    if is_fallback:
        print("[first run - falling back to previous working day]", file=sys.stderr)

    agent = await build_agent()
    try:
        config = {
            "configurable": {"thread_id": f"daily-{today.isoformat()}"},
            "recursion_limit": 40,
        }
        summary = await generate_report(agent, now, since, config)

        out_file = archive_report(today, since, summary)
        print(summary)
        print(f"\n[saved to {out_file}]", file=sys.stderr)

        webhook = os.getenv("SUMMARY_WEBHOOK_URL")
        if webhook:
            try:
                requests.post(webhook, json={"text": summary}, timeout=10)
                print("[pushed to webhook]", file=sys.stderr)
            except requests.RequestException as exc:
                print(f"[webhook failed: {exc}]", file=sys.stderr)

        # Only after full success does the cutoff advance - a failed run
        # leaves it untouched, so the next run re-covers the same window.
        save_cutoff(today)
        print(f"[cutoff advanced to {today} {os.getenv('STANDUP_END', '10:00')}]", file=sys.stderr)
        return 0
    finally:
        # Must close before this coroutine returns and asyncio.run() tears
        # down the event loop - see agent/graph.py build_agent().
        await agent.checkpoint_conn.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
