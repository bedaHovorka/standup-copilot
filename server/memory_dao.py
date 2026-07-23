"""
Data access layer for the shared memory database (data/memory.db).

Every SQL statement touching memory.db lives here. server/memory_server.py
(MCP tools), agent/standup.py (cutoff persistence) and watcher.py (due-item
reminders) all call into this module instead of embedding SQL of their own.
"""

from __future__ import annotations

import contextlib
import sqlite3
from datetime import date
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "memory.db"
INIT_SQL_PATH = Path(__file__).resolve().parent.parent / "db" / "init.sql"


@contextlib.contextmanager
def get_connection():
    """Yield a connection to memory.db, creating the schema if needed.

    Commits on success, rolls back on exception, and always closes the
    connection - sqlite3.Connection's own context manager only handles the
    transaction, not closing, which otherwise leaves the connection to be
    reclaimed by GC instead of deterministically.
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    try:
        con.executescript(INIT_SQL_PATH.read_text())
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


# --------------------------------------------------------------------------
# tracked_repos
# --------------------------------------------------------------------------
def track_repo(repo: str) -> None:
    with get_connection() as con:
        con.execute(
            "INSERT OR IGNORE INTO tracked_repos VALUES (?, ?)",
            (repo, date.today().isoformat()),
        )


def untrack_repo(repo: str) -> bool:
    with get_connection() as con:
        cur = con.execute("DELETE FROM tracked_repos WHERE repo = ?", (repo,))
    return bool(cur.rowcount)


def list_tracked_repos() -> list[tuple[str, str]]:
    with get_connection() as con:
        return con.execute(
            "SELECT repo, added_on FROM tracked_repos ORDER BY repo"
        ).fetchall()


# --------------------------------------------------------------------------
# standups
# --------------------------------------------------------------------------
def save_standup(yesterday: str, today: str, blockers: str) -> None:
    with get_connection() as con:
        con.execute(
            "INSERT INTO standups (day, yesterday, today, blockers) "
            "VALUES (?,?,?,?)",
            (date.today().isoformat(), yesterday, today, blockers),
        )


def get_recent_standups(limit: int) -> list[tuple[str, str, str, str]]:
    with get_connection() as con:
        return con.execute(
            "SELECT day, yesterday, today, blockers FROM standups "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()


# --------------------------------------------------------------------------
# preferences
# --------------------------------------------------------------------------
def set_preference(key: str, value: str) -> None:
    with get_connection() as con:
        con.execute(
            "INSERT INTO preferences (key, value) VALUES (?,?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def get_preference(key: str) -> str | None:
    with get_connection() as con:
        row = con.execute(
            "SELECT value FROM preferences WHERE key = ?", (key,)
        ).fetchone()
    return row[0] if row else None


def get_preferences() -> list[tuple[str, str]]:
    with get_connection() as con:
        return con.execute(
            "SELECT key, value FROM preferences ORDER BY key"
        ).fetchall()


# --------------------------------------------------------------------------
# expectations
# --------------------------------------------------------------------------
def add_expectation(item: str, requested_by: str, due: str) -> int:
    with get_connection() as con:
        cur = con.execute(
            "INSERT INTO expectations (created_on, item, requested_by, due) "
            "VALUES (?,?,?,?)",
            (date.today().isoformat(), item, requested_by, due),
        )
    return cur.lastrowid


def list_expectations(include_done: bool) -> list[tuple]:
    q = "SELECT id, created_on, item, requested_by, due, status FROM expectations"
    if not include_done:
        q += " WHERE status = 'open'"
    q += " ORDER BY id"
    with get_connection() as con:
        return con.execute(q).fetchall()


def resolve_expectation(expectation_id: int, status: str) -> bool:
    with get_connection() as con:
        cur = con.execute(
            "UPDATE expectations SET status = ? WHERE id = ?",
            (status, expectation_id),
        )
    return bool(cur.rowcount)


def list_due_candidates(today: str) -> list[tuple]:
    """Open expectations not yet reminded about today (or ever)."""
    with get_connection() as con:
        return con.execute(
            "SELECT e.id, e.item, e.requested_by, e.due, e.created_on "
            "FROM expectations e "
            "LEFT JOIN reminders r ON r.expectation_id = e.id "
            "WHERE e.status = 'open' "
            "AND (r.last_reminded IS NULL OR r.last_reminded < ?)",
            (today,),
        ).fetchall()


# --------------------------------------------------------------------------
# reminders
# --------------------------------------------------------------------------
def mark_reminded(expectation_id: int, today: str) -> None:
    with get_connection() as con:
        con.execute(
            "INSERT INTO reminders (expectation_id, last_reminded) VALUES (?, ?) "
            "ON CONFLICT(expectation_id) DO UPDATE "
            "SET last_reminded = excluded.last_reminded",
            (expectation_id, today),
        )
