"""
Milestone 3, free version: a LOCAL model decides which tools to call.

Uses Ollama (https://ollama.com), which runs open models on your own machine
and exposes an OpenAI-compatible API at http://localhost:11434/v1.
No API key, no cost.

    ollama pull qwen3:8b           # once (~5 GB). Low on RAM? use qwen3:4b
    python orchestrator_local.py

Override with environment variables:
    LLM_MODEL     model name            (default: qwen3:8b)
    LLM_BASE_URL  any OpenAI-compatible endpoint (default: Ollama on localhost)
    LLM_API_KEY   only needed for hosted providers (Ollama ignores it)

Compare this file with orchestrator.py: the MCP side (McpHub) is identical.
Only the LLM "dialect" changes. That separation is the whole point of MCP.
"""

import asyncio
import json
import os
from datetime import date

from openai import AsyncOpenAI

from mcp_hub import McpHub

MODEL = os.getenv("LLM_MODEL", "qwen3:8b")
BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:11434/v1")
MAX_STEPS = 12

SYSTEM_PROMPT = f"""You are a trip-planning assistant with access to three MCP servers:
weather, places, and calendar.

Today is {date.today():%A, %Y-%m-%d}. Resolve relative dates like "Saturday" yourself.

How to plan:
1. Check the weather for the city and day.
2. Pick places that fit: indoor if good_for_outdoor is false, outdoor otherwise.
3. Check the calendar for that day so you don't double-book.
4. Only then add events. If adding fails because of an overlap, choose another slot.
Always use the tools to get facts; never invent weather or places.
Finish with a short summary of the plan."""

DIM, CYAN, RED, RESET = "\033[2m", "\033[36m", "\033[31m", "\033[0m"


def tools_for_openai(hub: McpHub) -> list[dict]:
    """Same catalogue as hub.tools_for_claude(), wrapped in OpenAI's format."""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            },
        }
        for t in hub.tools_for_claude()
    ]


async def run_agent(hub: McpHub, llm, messages: list[dict]) -> str:
    """The orchestration loop. Mutates `messages` so the conversation continues."""
    tools = tools_for_openai(hub)

    for _ in range(MAX_STEPS):
        response = await llm.chat.completions.create(
            model=MODEL,
            messages=[{"role": "system", "content": SYSTEM_PROMPT}, *messages],
            tools=tools,
        )
        msg = response.choices[0].message
        messages.append(msg.model_dump(exclude_none=True))

        if not msg.tool_calls:
            return msg.content or ""

        calls = []
        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = None  # small models sometimes emit broken JSON
            print(f"{CYAN}  -> {tc.function.name}{RESET} {DIM}{tc.function.arguments}{RESET}")
            calls.append((tc, args))

        async def run(tc, args):
            if args is None:
                from mcp_hub import ToolOutcome
                return ToolOutcome("Your arguments were not valid JSON. Try again.", is_error=True)
            return await hub.call(tc.function.name, args)

        outcomes = await asyncio.gather(*(run(tc, a) for tc, a in calls))

        for (tc, _), out in zip(calls, outcomes):
            colour = RED if out.is_error else DIM
            print(f"{colour}  <- {out.text[:200]}{'...' if len(out.text) > 200 else ''}{RESET}")
            # OpenAI's format has no is_error flag, so we say it in the text.
            # Unlike Claude, each result is its own "tool" message.
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": ("ERROR: " if out.is_error else "") + out.text,
            })

    return "(Stopped: too many tool calls in a row.)"


async def main() -> None:
    llm = AsyncOpenAI(base_url=BASE_URL, api_key=os.getenv("LLM_API_KEY", "ollama"))
    async with McpHub() as hub:
        print(f"Connected to {len(hub.clients)} servers, {len(hub.routes)} tools. "
              f"Model: {MODEL} @ {BASE_URL}")
        print("Type a request, or 'quit'.\n")
        messages: list[dict] = []
        while True:
            try:
                user = input("you> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if user.lower() in {"quit", "exit"}:
                break
            if not user:
                continue
            messages.append({"role": "user", "content": user})
            try:
                answer = await run_agent(hub, llm, messages)
            except Exception as exc:
                answer = f"(LLM error: {exc}. Is Ollama running and is '{MODEL}' pulled?)"
            print(f"\nassistant> {answer}\n")


if __name__ == "__main__":
    asyncio.run(main())