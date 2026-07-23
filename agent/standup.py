"""
Shared standup logic: cutoff persistence and report generation.

Used by both entrypoints:
  - main.py --standup   : interactive standup session (report, then chat)
  - daily_summary.py    : headless scheduled run (report, save, webhook)

The report window opens at the LAST ATTENDED STANDUP: after each successful
report the cutoff is stored as <today> STANDUP_END (default 10:00) in the
memory DB. This handles weekends, vacations and sick days with no calendar
logic - the first run after any gap covers the whole gap.
"""

from __future__ import annotations

import os
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

from langchain_core.messages import HumanMessage

ROOT = Path(__file__).resolve().parent.parent
SUMMARIES_DIR = ROOT / "data" / "summaries"
CUTOFF_KEY = "last_summary_cutoff"

sys.path.insert(0, str(ROOT / "server"))
import memory_dao  # noqa: E402


def standup_end() -> time:
    """When the daily standup ends; configurable via STANDUP_END (default 10:00)."""
    h, m = os.getenv("STANDUP_END", "10:00").split(":")
    return time(int(h), int(m))


def load_cutoff(today: date) -> tuple[datetime, bool]:
    """Return (window start, is_fallback). Normally the persisted cutoff of
    the last attended standup; on first run, previous working day at
    STANDUP_END."""
    value = memory_dao.get_preference(CUTOFF_KEY)
    if value:
        return datetime.fromisoformat(value), False
    prev = today - timedelta(days=3 if today.weekday() == 0 else 1)
    return datetime.combine(prev, standup_end()), True


def save_cutoff(today: date) -> None:
    """Advance the cutoff to <today> STANDUP_END. Call only after success."""
    cutoff = datetime.combine(today, standup_end()).isoformat()
    memory_dao.set_preference(CUTOFF_KEY, cutoff)


def build_report_prompt(now: datetime, since: datetime) -> str:
    gap_days = (now.date() - since.date()).days
    gap_note = (
        f"Note: the window spans {gap_days} days - the user was likely away "
        "(weekend/vacation). Group the DONE section by day or theme."
        if gap_days > 3
        else ""
    )
    return f"""Today is {now.date().isoformat()} ({now.strftime('%A')}), the time is
{now.strftime('%H:%M')}.
Prepare my standup report covering everything since my last attended standup:
from {since.strftime('%Y-%m-%d %H:%M')} up to now. {gap_note}

Steps:
1. Call list_tracked_repos and get_recent_standups to load my context.
2. Call list_expectations to see what is currently expected from me.
3. If GitHub tools are available, list my commits, pull requests and issue
   activity in the tracked repos since
   {since.strftime('%Y-%m-%dT%H:%M:%S')} (use this as the ISO timestamp
   filter where the tool supports it).
4. Check get_preferences and respect any stored style preference.
5. Write the report with sections:
   DONE (since {since.strftime('%Y-%m-%d %H:%M')}),
   IN PROGRESS,
   EXPECTED FROM ME (open expectations - flag any whose due date is near or past),
   BLOCKERS.
   Be concrete - reference repo names, PR/issue numbers and commit messages.
6. Call save_standup with yesterday=the DONE section, today=the IN PROGRESS
   section, blockers=the BLOCKERS section, so the archive keeps growing.

Reply with only the final report text."""


async def generate_report(agent, now: datetime, since: datetime, config: dict) -> str:
    """Run one agent turn producing the standup report text.

    config must carry the thread_id of the session that should own the
    report - callers that continue chatting afterward (main.py --standup)
    need that same thread_id passed to subsequent calls, or the follow-up
    chat has no memory of the report it just produced.
    """
    result = await agent.ainvoke(
        {"messages": [HumanMessage(content=build_report_prompt(now, since))]},
        config=config,
    )
    summary = result["messages"][-1].content
    if isinstance(summary, list):  # some models return content blocks
        summary = "\n".join(
            b.get("text", "") for b in summary if isinstance(b, dict)
        )
    return summary


def archive_report(today: date, since: datetime, summary: str) -> Path:
    SUMMARIES_DIR.mkdir(parents=True, exist_ok=True)
    out_file = SUMMARIES_DIR / f"{today.isoformat()}.md"
    out_file.write_text(
        f"# Standup {today.isoformat()} "
        f"(window since {since:%Y-%m-%d %H:%M})\n\n{summary}\n"
    )
    return out_file
