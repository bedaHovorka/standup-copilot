"""
CLI chat app for the MCP-powered LangGraph agent.

Usage:
    python main.py             # plain chat
    python main.py --standup   # standup session: opens with the report
                               # since your last attended standup, then
                               # chat - dictate notes about what is
                               # expected from you; the agent stores them
                               # in the expectations memory table.

Type your question; 'exit' or Ctrl+C quits.
Tool calls are printed as they happen so you can watch the agent reason.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import date, datetime

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agent.graph import build_agent
from agent.standup import archive_report, generate_report, load_cutoff, save_cutoff

load_dotenv()

BANNER = """
================================================================
 MCP + LangGraph Standup Copilot (local gemma4 via Ollama)
 Memory: SQLite | Live data: GitHub remote MCP (if GITHUB_PAT set)
 Try:
   - Track repo owner/name and remember I like short standups.
   - Prepare my standup.
   - What were my blockers this week?
 Type 'exit' to quit.
================================================================
"""


async def chat(standup_mode: bool = False) -> None:
    agent = await build_agent()
    config = {
        "configurable": {"thread_id": str(uuid.uuid4())},
        "recursion_limit": 40,
    }
    print(BANNER)

    if standup_mode:
        today = date.today()
        now = datetime.now()
        since, _ = load_cutoff(today)
        print(f"Preparing your standup report (window since {since:%Y-%m-%d %H:%M})...\n")
        summary = await generate_report(agent, now, since, config)
        print(summary)
        archive_report(today, since, summary)
        save_cutoff(today)
        print("\n[report archived, cutoff advanced]")
        print("Now tell me what you hear at the standup - I'll remember what's")
        print("expected from you (e.g. 'Petr wants me to review PR #42 by Thursday').\n")

    while True:
        try:
            user_input = input("you > ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nBye!")
            return
        if not user_input:
            continue
        if user_input.lower() in {"exit", "quit"}:
            print("Bye!")
            return

        async for event in agent.astream(
            {"messages": [HumanMessage(content=user_input)]},
            config=config,
            stream_mode="values",
        ):
            msg = event["messages"][-1]
            if isinstance(msg, AIMessage) and msg.tool_calls:
                for tc in msg.tool_calls:
                    print(f"  [tool call] {tc['name']}({tc['args']})")
            elif isinstance(msg, ToolMessage):
                preview = str(msg.content).replace("\n", " ")[:120]
                print(f"  [tool result] {preview}")
            elif isinstance(msg, AIMessage) and msg.content:
                print(f"\nagent > {msg.content}\n")


if __name__ == "__main__":
    asyncio.run(chat(standup_mode="--standup" in sys.argv))
