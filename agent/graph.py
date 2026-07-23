"""
LangGraph ReAct agent whose tools come from an MCP server.

Flow:
  MultiServerMCPClient spawns server/memory_server.py over stdio,
  discovers its tools, and converts them into LangChain tools.
  create_agent then builds the standard  agent -> tools -> agent  loop
  with an in-memory checkpointer for multi-turn conversation memory.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from langchain.agents import create_agent
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_ollama import ChatOllama
from langgraph.checkpoint.memory import InMemorySaver

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MEMORY_SERVER = PROJECT_ROOT / "server" / "memory_server.py"

SYSTEM_PROMPT = """You are a developer standup copilot with tools via MCP.

MEMORY tools (local SQLite - the user's long-term memory):
- track_repo / untrack_repo / list_tracked_repos
- save_standup / get_recent_standups
- add_expectation / list_expectations / resolve_expectation
- set_preference / get_preferences

GITHUB tools (remote MCP, available when GITHUB_PAT is configured):
- live repository data: issues, pull requests, commits, CI status

GitHub tools are not limited to standup preparation: whenever the user directly
asks about recent commits, pull requests, issues, or CI status (in or outside a
standup), call the GitHub tools if they are available, rather than only listing
tracked repos from memory.

Standup workflow when the user asks to prepare a standup:
1. list_tracked_repos and get_recent_standups to load context from memory
2. If GitHub tools are available, fetch recent activity (commits, PRs,
   assigned issues) in the tracked repos
3. Draft the standup (yesterday / today / blockers) respecting any stored
   preferences about style
4. After the user confirms, save_standup to memory

During or after a standup meeting, the user will tell you what was said.
Whenever they mention something expected FROM THEM (a task, review,
deadline, promise), call add_expectation with item, requested_by and due
if stated. When they say something is finished or cancelled, call
resolve_expectation. Confirm briefly what you stored.
When the user mentions a repo or a preference, proactively store it.
Answer in the same language the user writes in."""


def build_mcp_client() -> MultiServerMCPClient:
    """Configure the MCP client. Add more servers here to extend the agent."""
    servers: dict = {
        "memory": {
            "transport": "stdio",
            "command": sys.executable,
            "args": [str(MEMORY_SERVER)],
        },
    }

    # GitHub's official remote MCP server (HTTPS, streamable HTTP transport).
    # Enabled only when GITHUB_PAT is set, so the project runs without it.
    # Verify the endpoint in the official MCP Registry / GitHub docs.
    # The /readonly variant exposes fewer tools, which suits small local
    # models better than the full read-write tool set.
    pat = os.getenv("GITHUB_PAT")
    if pat:
        servers["github"] = {
            "transport": "streamable_http",
            "url": os.getenv(
                "GITHUB_MCP_URL", "https://api.githubcopilot.com/mcp/readonly"
            ),
            "headers": {"Authorization": f"Bearer {pat}"},
        }

    return MultiServerMCPClient(servers)


async def build_agent():
    """Create the LangGraph agent with tools discovered from MCP."""
    client = build_mcp_client()
    tools = await client.get_tools()

    # Local model via Ollama. Gemma 4 supports tool calling natively,
    # but requires Ollama >= 0.20.2 and the OFFICIAL gemma4 tag
    # (community GGUF quants shipped with broken tool-call templates).
    # If tool calls fail, disable reasoning mode.
    #   ollama pull gemma4:latest
    model = ChatOllama(
        model=os.getenv("OLLAMA_MODEL", "gemma4:latest"),
        base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        temperature=0,
    )

    return create_agent(
        model=model,
        tools=tools,
        system_prompt=SYSTEM_PROMPT,
        checkpointer=InMemorySaver(),
    )
