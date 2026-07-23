"""
Daytime watcher - runs continuously during working hours via cron.

Deliberately does NOT invoke the LLM: it is a cheap deterministic check
that can run every 30 minutes without cost. It looks at open expectations
in the memory DB and pushes a reminder (stdout + optional webhook) for
items due today or overdue - at most once per item per day.

Cron (every 30 min within the working day, script guards exact hours):
    REPO=/path/to/project
    */30 6-14 * * 1-5  cd $REPO && uv run watcher.py >> data/summaries/watcher.log 2>&1

Due-date parsing: ISO dates (2026-07-23) are compared exactly; weekday
names ("Thursday") resolve to the next occurrence from the day the
expectation was created. Anything else is skipped (never reminded).
"""

from __future__ import annotations

import os
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent

sys.path.insert(0, str(ROOT / "server"))
import memory_dao  # noqa: E402

WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}


def _t(env: str, default: str) -> time:
    h, m = os.getenv(env, default).split(":")
    return time(int(h), int(m))


def within_working_hours(now: datetime) -> bool:
    if now.weekday() >= 5:
        return False
    return _t("WORK_START", "06:30") <= now.time() <= _t("WORK_END", "15:00")


def parse_due(due: str, created_on: str) -> date | None:
    """ISO date, or weekday name resolved to next occurrence after creation."""
    due = due.strip().lower()
    if not due:
        return None
    try:
        return date.fromisoformat(due)
    except ValueError:
        pass
    if due in WEEKDAYS:
        created = date.fromisoformat(created_on)
        ahead = (WEEKDAYS[due] - created.weekday()) % 7
        return created + timedelta(days=ahead or 7)
    return None


def check(today: date) -> list[str]:
    """Return reminder lines for open expectations due today/overdue that
    have not been reminded about today yet. Marks them as reminded."""
    if not memory_dao.DB_PATH.exists():
        return []
    today_iso = today.isoformat()
    rows = memory_dao.list_due_candidates(today_iso)

    lines = []
    for eid, item, who, due, created in rows:
        due_date = parse_due(due, created)
        if due_date is None or due_date > today:
            continue
        state = "OVERDUE" if due_date < today else "due TODAY"
        who_s = f" (for {who})" if who else ""
        lines.append(f"[{state}] #{eid} {item}{who_s} - due {due_date.isoformat()}")
        memory_dao.mark_reminded(eid, today_iso)
    return lines


def main() -> int:
    now = datetime.now()
    if not within_working_hours(now):
        return 0  # outside working hours - stay silent

    lines = check(now.date())
    if not lines:
        return 0

    text = "Expectation reminders:\n" + "\n".join(lines)
    print(f"{now:%H:%M} {text}")

    webhook = os.getenv("SUMMARY_WEBHOOK_URL")
    if webhook:
        try:
            requests.post(webhook, json={"text": text}, timeout=10)
        except requests.RequestException as exc:
            print(f"[webhook failed: {exc}]", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
