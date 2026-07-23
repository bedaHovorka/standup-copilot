"""
Memory MCP server (stdio) — the agent's long-term memory in local SQLite.

Stores per-user state for the standup copilot:
  - tracked repos the user cares about
  - standup history (yesterday / today / blockers)
  - free-form preferences (e.g. standup style, timezone)

Backed by data/memory.db, created automatically. All SQL lives in
memory_dao.py; this module only defines the MCP tool contracts.
"""

from __future__ import annotations

import memory_dao
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("memory")


@mcp.tool()
def track_repo(repo: str) -> str:
    """Remember a GitHub repository the user cares about.

    Args:
        repo: repository in "owner/name" format, e.g. "torvalds/linux"
    """
    if "/" not in repo:
        return "Error: repo must be in 'owner/name' format."
    memory_dao.track_repo(repo.strip())
    return f"Now tracking {repo}."


@mcp.tool()
def untrack_repo(repo: str) -> str:
    """Stop tracking a GitHub repository."""
    removed = memory_dao.untrack_repo(repo.strip())
    return f"Stopped tracking {repo}." if removed else f"{repo} was not tracked."


@mcp.tool()
def list_tracked_repos() -> str:
    """List all GitHub repositories the user is tracking."""
    rows = memory_dao.list_tracked_repos()
    if not rows:
        return "No repos tracked yet. Use track_repo to add one."
    return "\n".join(f"- {r} (since {d})" for r, d in rows)


@mcp.tool()
def save_standup(yesterday: str, today: str, blockers: str = "") -> str:
    """Save today's standup report to memory.

    Args:
        yesterday: what was done yesterday
        today: plan for today
        blockers: current blockers, empty string if none
    """
    memory_dao.save_standup(yesterday, today, blockers)
    return "Standup saved."


@mcp.tool()
def get_recent_standups(limit: int = 5) -> str:
    """Get the most recent standup reports, newest first.

    Args:
        limit: how many reports to return (default 5)
    """
    rows = memory_dao.get_recent_standups(max(1, min(limit, 30)))
    if not rows:
        return "No standup history yet."
    out = []
    for day, y, t, b in rows:
        out.append(f"[{day}]\n  yesterday: {y}\n  today: {t}\n  blockers: {b or 'none'}")
    return "\n\n".join(out)


@mcp.tool()
def set_preference(key: str, value: str) -> str:
    """Remember a user preference (e.g. key='standup_style', value='bullet points, casual')."""
    memory_dao.set_preference(key.strip(), value)
    return f"Preference '{key}' saved."


@mcp.tool()
def get_preferences() -> str:
    """List all stored user preferences."""
    rows = memory_dao.get_preferences()
    if not rows:
        return "No preferences stored."
    return "\n".join(f"- {k}: {v}" for k, v in rows)


@mcp.tool()
def add_expectation(item: str, requested_by: str = "", due: str = "") -> str:
    """Remember something that is expected from the user (typically noted
    during a standup meeting).

    Args:
        item: what is expected, e.g. "review PR #42 in acme/api"
        requested_by: who asked for it (optional)
        due: deadline, ISO date or free-form like "Thursday" (optional)
    """
    eid = memory_dao.add_expectation(item.strip(), requested_by.strip(), due.strip())
    return f"Expectation #{eid} saved: {item}"


@mcp.tool()
def list_expectations(include_done: bool = False) -> str:
    """List what is expected from the user. By default only open items."""
    rows = memory_dao.list_expectations(include_done)
    if not rows:
        return "No open expectations." if not include_done else "No expectations recorded."
    out = []
    for i, created, item, who, due, status in rows:
        extra = ", ".join(x for x in (f"from {who}" if who else "",
                                      f"due {due}" if due else "",
                                      status if status != "open" else "") if x)
        out.append(f"#{i} [{created}] {item}" + (f" ({extra})" if extra else ""))
    return "\n".join(out)


@mcp.tool()
def resolve_expectation(expectation_id: int, status: str = "done") -> str:
    """Mark an expectation as 'done' or 'dropped'.

    Args:
        expectation_id: the #id from list_expectations
        status: 'done' (default) or 'dropped'
    """
    if status not in ("done", "dropped"):
        return "Error: status must be 'done' or 'dropped'."
    resolved = memory_dao.resolve_expectation(expectation_id, status)
    return (f"Expectation #{expectation_id} marked {status}."
            if resolved else f"No expectation #{expectation_id} found.")


if __name__ == "__main__":
    mcp.run(transport="stdio")
