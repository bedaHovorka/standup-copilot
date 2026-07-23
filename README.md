# MCP + LangGraph Agent: Developer Standup Copilot

A tool-using AI agent built with **LangGraph**, where all tools are provided by **Model Context Protocol (MCP)** servers instead of framework-specific tool bindings. The LLM runs **locally via Ollama** (`gemma4:latest`) — no API key, no cloud costs.

**Use case:** a *standup copilot* that combines
- **long-term memory** in a local SQLite database (tracked repos, standup history, user preferences), and
- **live data** from GitHub's official **remote MCP server over HTTPS**.

Ask "prepare my standup" — the agent loads context from memory, checks recent GitHub activity in your tracked repos, drafts yesterday/today/blockers in your preferred style, and saves the result back to memory.

## Why MCP instead of framework-specific tools?

The assignment suggested considering MCP — this project takes that route deliberately. The tools live in a standalone MCP server (`server/memory_server.py`) that any MCP client can use: this LangGraph agent, Claude Desktop, an IDE, or a different framework entirely. The agent discovers the tools at startup via `langchain-mcp-adapters`, so adding a tool means editing only the server, never the agent code.

## Architecture

```
┌────────────┐   messages    ┌─────────────────────────────┐
│    CLI     │ ────────────► │   LangGraph ReAct agent     │
│  main.py   │ ◄──────────── │  (Ollama + InMemorySaver)   │
└────────────┘               └─────────────┬───────────────┘
                                           │ MCP (stdio)
                                           ▼
                             ┌─────────────────────────────┐
                             │  local MCP server (stdio)   │
                             │  memory:  track_repo,       │
                             │    save_standup, prefs ...  │
                             └──────────┬──────────────────┘
                                        │ + streamable HTTP (HTTPS)
                                        ▼
                             ┌─────────────────────────────┐
                             │  GitHub official remote MCP │
                             │  api.githubcopilot.com/mcp  │
                             │  (issues, PRs, commits...)  │
                             └─────────────────────────────┘
```

The agent runs the classic ReAct loop built by `create_agent`: the model decides whether to answer or call a tool, tool results are fed back as messages, and the loop repeats until the model produces a final answer. `InMemorySaver` + a `thread_id` give it multi-turn conversation memory. In `main.py --standup`, the standup report and the note-taking chat that follows it share the same `thread_id`, so you can refer back to what the report said.

## Tools

| Tool | Server | Description |
|---|---|---|
| `track_repo` / `untrack_repo` / `list_tracked_repos` | memory (SQLite) | Repos the user cares about |
| `save_standup` / `get_recent_standups` | memory (SQLite) | Standup history: yesterday / today / blockers |
| `set_preference` / `get_preferences` | memory (SQLite) | Style and other user preferences |
| GitHub tools (issues, PRs, commits, ...) | **remote HTTPS MCP** | GitHub official server; enabled when `GITHUB_PAT` is set; `/readonly` endpoint by default (smaller tool set = friendlier to small local models) |

**Trust note:** remote MCP servers should be verified in the [official MCP Registry](https://registry.modelcontextprotocol.io/), which uses namespace authentication tying server names to verified domains/GitHub accounts. This project uses GitHub's vendor-official server, which inherits GitHub's own OAuth/PAT permission model.

## Setup

Requires [uv](https://docs.astral.sh/uv/) (`curl -LsSf https://astral.sh/uv/install.sh | sh`).

```bash
git clone <this-repo>
cd standup-copilot
uv sync                     # creates .venv and installs pinned dependencies
ollama pull gemma4:latest   # requires Ollama >= 0.20.2 (tool-call parsing fix)
cp .env.example .env        # optionally set GITHUB_PAT for the GitHub remote MCP
uv run main.py              # plain chat
uv run main.py --standup    # standup session
```

(`requirements.txt` is kept for pip users: `pip install -r requirements.txt`.)

The MCP server is spawned automatically over stdio — you don't start it separately.

## Example session

```
you > Track the repo langchain-ai/langgraph and remember I like short casual standups.
  [tool call] track_repo({'repo': 'langchain-ai/langgraph'})
  [tool call] set_preference({'key': 'standup_style', 'value': 'short, casual'})

agent > Done - tracking langchain-ai/langgraph, and I'll keep standups short and casual.

you > Prepare my standup.
  [tool call] get_recent_standups({})
  [tool call] list_tracked_repos({})
  [tool call] <github> list recent commits / assigned issues ...

agent > Here's a draft: ...
```

## Scheduled daily summary (9:30, Mon-Fri)

`daily_summary.py` is a headless one-shot entrypoint. The report window opens
at the **last attended standup**: after each successful run the script stores
a cutoff (`today` at `STANDUP_END`, default 10:00) in the memory DB, and the
next run covers everything since that cutoff. This handles weekends (Monday
covers Friday 10:00 -> now), vacations and sick days with zero calendar logic -
the first run after any gap covers the whole gap. A failed run does not
advance the cutoff, so no work is ever silently skipped. It runs the agent
once, saves the result
to `data/summaries/YYYY-MM-DD.md`, prints it, optionally pushes it to a webhook
(`SUMMARY_WEBHOOK_URL`), and archives it into the memory DB via `save_standup`.

**Linux/macOS (cron):** `crontab -e` and add

```cron
# morning standup report (fallback if you don't run `main.py --standup` yourself)
30 9 * * 1-5   cd /path/to/mcp-langgraph-agent && uv run daily_summary.py >> data/summaries/cron.log 2>&1
# daytime watcher: every 30 min during the working day, deterministic (no LLM)
*/30 6-14 * * 1-5  cd /path/to/mcp-langgraph-agent && uv run watcher.py >> data/summaries/watcher.log 2>&1
```

**Daytime watcher (`watcher.py`)** runs continuously through the working day
but deliberately never invokes the LLM - it is a cheap deterministic check of
the expectations table. Inside working hours (`WORK_START`-`WORK_END`, Mon-Fri)
it reminds about open expectations that are due today or overdue, at most once
per item per day, via stdout and the optional webhook. Due dates are parsed
from ISO dates ("2026-07-23") or weekday names ("Thursday" = next Thursday
after the expectation was created); unparsable due texts are never reminded.

**Linux (systemd timer)** is the more robust option - unlike cron it can wait
for network and you get journald logs. Create a service running the same
command plus a timer with `OnCalendar=Mon..Fri 09:30`.

**Windows (Task Scheduler):** create a task, trigger Weekly (Mon-Fri) 9:30,
action `uv` with arguments `run daily_summary.py`, start-in the project
folder (or point directly at `.venv\Scripts\python.exe`).

Requirements for unattended runs: Ollama must be running as a service
(`ollama serve`, default on standard installs), and the machine must be awake -
on a laptop, consider `anacron` or a systemd timer with `Persistent=true` so a
missed 9:30 run fires on next boot.

## Extending

- **More MCP tools** — add another `@mcp.tool()` function in `server/memory_server.py` (or a new server module); the agent picks it up automatically on next start.
- **More MCP servers** — add entries to the dict in `build_mcp_client()` (e.g. a remote server over `streamable_http`, or official servers for Gmail, Tavily, filesystem...).
- **Different LLM** — swap `ChatOllama` in `agent/graph.py` for any LangChain chat model that supports tool calling.

## Project layout

```
standup-copilot/
├── main.py                 # CLI chat loop, streams tool calls
├── agent/
│   ├── graph.py            # MCP client + LangGraph ReAct agent
│   └── standup.py          # shared cutoff persistence + report generation
├── server/
│   ├── memory_server.py    # FastMCP server: MCP tool contracts
│   └── memory_dao.py       # all SQL for data/memory.db
├── db/
│   └── init.sql            # memory.db schema (Liquibase Formatted SQL)
├── data/                   # memory.db + summaries/ (auto-created)
├── watcher.py              # daytime reminder loop (no LLM)
├── daily_summary.py        # headless scheduled standup report
├── pyproject.toml          # uv project definition (uv sync / uv run)
├── requirements.txt        # fallback for pip users
├── CLAUDE.md               # guidance for Claude Code in this repo
└── .env.example
```
