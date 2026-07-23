# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A developer **standup copilot**: a LangGraph ReAct agent whose tools are supplied
entirely by **MCP servers** rather than framework-specific tool bindings. The LLM
runs **locally via Ollama** (`gemma4:latest`) — no API key, no cloud cost. It keeps
long-term memory in local SQLite and can pull live GitHub activity via GitHub's
official remote MCP server.

## Commands

Uses [uv](https://docs.astral.sh/uv/). `requirements.txt` mirrors `pyproject.toml` for pip users.

```bash
uv sync                     # create .venv, install pinned deps
ollama pull gemma4:latest   # needs Ollama >= 0.20.2 (tool-call parsing fix)
cp .env.example .env        # optional: set GITHUB_PAT, webhook, hours

uv run main.py              # interactive chat
uv run main.py --standup    # standup session: report since last standup, then note-taking chat
uv run daily_summary.py     # headless one-shot report (for cron/systemd/Task Scheduler)
uv run watcher.py           # deterministic due-item reminder check (no LLM)

# Debug the MCP server standalone (normally auto-spawned over stdio):
uv run server/memory_server.py
```

There is no test suite, linter config, or build step. Python >= 3.11 (`.python-version` pins 3.12).

## Architecture

The defining choice: **tools are not defined in the agent**. They live in standalone
MCP servers; the agent discovers them at startup via `langchain-mcp-adapters`.
Adding a tool means editing a server, never the agent. Any MCP client (Claude
Desktop, an IDE, another framework) could use the same servers.

**`agent/graph.py`** is the wiring hub:
- `build_mcp_client()` — declares the MCP servers in one dict. The local stdio
  `memory` server is always on; the `github` remote server (`streamable_http`
  over HTTPS) is added only when `GITHUB_PAT` is set, so the project runs fully
  offline without it. **Extend the agent by adding entries here.**
- `build_agent()` — pulls tools from all servers, builds a `create_agent`
  ReAct loop over `ChatOllama`, with an `AsyncSqliteSaver` checkpointer
  (`data/checkpoints.db`, separate from `memory.db`) for multi-turn memory that
  survives process restarts. Swap `ChatOllama` for any tool-calling LangChain
  model to change the LLM. The sync `SqliteSaver` isn't an option here — it
  raises `NotImplementedError` on `aget_tuple`/`aput`, and every call site in
  this codebase (`agent.ainvoke`/`agent.astream`) is async-only. The returned
  agent carries `agent.checkpoint_conn`; callers **must**
  `await agent.checkpoint_conn.close()` before their coroutine returns (see
  `main.py`/`daily_summary.py`), otherwise aiosqlite's background thread logs
  a spurious "Event loop is closed" traceback at interpreter shutdown.
- `SYSTEM_PROMPT` encodes the standup workflow and the rule to log "expectations"
  (things expected *from the user*) whenever they surface in conversation.

**`server/memory_server.py`** (`FastMCP`, stdio) is the long-term memory MCP
server. `@mcp.tool()` functions there are the API — `track_repo`/`untrack_repo`/
`list_tracked_repos`, `save_standup`/`get_recent_standups`, `set_preference`/
`get_preferences`, `add_expectation`/`list_expectations`/`resolve_expectation` —
but each function only formats the response; it delegates every SQL statement to
**`server/memory_dao.py`**.

**`server/memory_dao.py`** is the single place all SQL against `data/memory.db`
lives. `agent/standup.py` (cutoff persistence) and `watcher.py` (due-item
reminders) both import it too — via a `sys.path.insert(0, ".../server")` shim,
since the project has no package layout for `server/` — rather than embedding
SQL of their own. **Any new SQL against memory.db belongs in this file, not in
its callers.** `get_connection()` is a `@contextlib.contextmanager` (not a bare
`sqlite3.connect`) so every `with get_connection() as con:` block commits on
success, rolls back on exception, and always closes the connection — do not
revert it to returning a raw connection object. The schema itself lives in `db/init.sql` (tables `tracked_repos`,
`standups`, `preferences`, `expectations`, `reminders`), written as a Liquibase
Formatted SQL changelog for future compatibility with real `liquibase update`
runs, but currently just applied by `memory_dao.get_connection()` via
`executescript()` on every connection — idempotent (`CREATE TABLE IF NOT
EXISTS`), so there's no separate migration step to run. `expectations.status`
has an index (`idx_expectations_status`, changeset 6) since it's filtered in
both `list_expectations` and `list_due_candidates`; the other four tables'
primary keys already cover every query pattern in `memory_dao.py`, so they
intentionally have no extra indexes — don't add one without a real query to
back it. `db/checkpoints_init.sql` is a separate, **non-executed**
Liquibase file documenting the checkpointer's own schema (`checkpoints`,
`writes`) — that schema is actually owned and created by
`AsyncSqliteSaver.setup()` in `agent/graph.py`, not by this DAO or `init.sql`.

**Entrypoints:**
- `main.py` — CLI chat loop; streams each tool call/result so you can watch the
  agent reason. `--standup` runs a report first, then chat.
- `daily_summary.py` — headless scheduled report; prints, archives to
  `data/summaries/YYYY-MM-DD.md`, optionally POSTs to `SUMMARY_WEBHOOK_URL`,
  then advances the cutoff. Skips weekends.
- `watcher.py` — runs every ~30 min in working hours; **deliberately never calls
  the LLM**. Pure SQLite check of `expectations` for items due today/overdue,
  reminding at most once per item per day (tracked in a `reminders` table).

**`agent/standup.py`** holds logic shared by both standup entrypoints.

## The cutoff mechanism (important, non-obvious)

The report window opens at the **last attended standup**, not "yesterday". After
each *successful* report, the cutoff is persisted as `<today> STANDUP_END` (default
10:00) in the `preferences` table (`last_summary_cutoff`). The next run covers
everything since that stored cutoff. Consequences to preserve when editing
`agent/standup.py` or `daily_summary.py`:

- Weekends, vacations, sick days need **zero calendar logic** — the first run after
  any gap naturally covers the whole gap. `build_report_prompt` adds a grouping
  hint when the window spans > 3 days.
- **A failed run must not advance the cutoff.** `save_cutoff()` is called only after
  the report is fully generated and archived, so nothing is ever silently skipped.
- First-ever run (no stored cutoff) falls back to the previous working day at `STANDUP_END`.
- **`generate_report()` takes the caller's `config` rather than picking a `thread_id`
  itself.** `main.py --standup` passes its own session config so the report and the
  note-taking chat that follows share one `InMemorySaver` thread — the chat can refer
  back to what the report just said. `daily_summary.py` is one-shot (no follow-up
  chat), so it builds its own `daily-<date>` thread_id and discards it after the run.

## Configuration (.env)

`OLLAMA_MODEL`, `OLLAMA_BASE_URL`; `GITHUB_PAT` + optional `GITHUB_MCP_URL` (defaults
to the `/readonly` endpoint — fewer tools, friendlier to small local models);
`SUMMARY_WEBHOOK_URL`; `STANDUP_END` (report cutoff time); `WORK_START`/`WORK_END`
(watcher window).

`data/` (`memory.db` and `data/summaries/`) is created automatically at runtime
and is not committed.
