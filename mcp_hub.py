"""
McpHub: the orchestration core.

Responsibilities:
  1. Start and connect to every MCP server listed in servers.json.
  2. Discover each server's tools and merge them into one catalogue.
  3. Give every tool a unique, namespaced name ("weather__get_daily_forecast")
     so two servers can both have e.g. a "search" tool without clashing.
  4. Route a call for a namespaced name back to the right server.

FastMCP can do 1-4 for you in one line (Client(mcp_config) prefixes tools
automatically). We do it by hand here because this IS the part you're
trying to learn.
"""

import asyncio
import json
import os
import sys
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path

from fastmcp import Client
from fastmcp.client.transports import StdioTransport

ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "logs"
SEP = "__"  # namespace separator: <server>__<tool>


@dataclass
class ToolRoute:
    server: str          # which server owns the tool
    tool: str            # the tool's original name on that server
    description: str
    input_schema: dict


@dataclass
class ToolOutcome:
    text: str
    is_error: bool


class McpHub:
    def __init__(self, config_path: Path = ROOT / "servers.json"):
        self.config = json.loads(config_path.read_text(encoding="utf-8"))
        self.clients: dict[str, Client] = {}
        self.routes: dict[str, ToolRoute] = {}
        self._stack = AsyncExitStack()

    # ---- lifecycle -------------------------------------------------------

    async def __aenter__(self) -> "McpHub":
        for name, spec in self.config.items():
            # Only pass what the server needs. Servers are separate processes
            # and shouldn't see your ANTHROPIC_API_KEY.
            env = {k: v for k, v in os.environ.items() if k == "WEATHER_MOCK"}
            env.update(spec.get("env", {}))
            LOG_DIR.mkdir(exist_ok=True)
            transport = StdioTransport(
                command=sys.executable,           # same Python that runs us
                args=[str(ROOT / spec["script"])],
                env=env,
                cwd=str(ROOT),
                # stdout carries the MCP protocol messages; the server's own
                # logs go to stderr, which we send to logs/<server>.log.
                log_file=LOG_DIR / f"{name}.log",
            )
            client = Client(transport)
            # Entering the client spawns the process and does the MCP handshake.
            await self._stack.enter_async_context(client)
            self.clients[name] = client
        await self.refresh_tools()
        return self

    async def __aexit__(self, *exc) -> None:
        await self._stack.aclose()

    # ---- discovery -------------------------------------------------------

    async def refresh_tools(self) -> None:
        """Ask every server for its tools (in parallel) and rebuild the routing table."""
        names = list(self.clients)
        tool_lists = await asyncio.gather(*(self.clients[n].list_tools() for n in names))
        self.routes.clear()
        for server, tools in zip(names, tool_lists):
            for t in tools:
                self.routes[f"{server}{SEP}{t.name}"] = ToolRoute(
                    server=server,
                    tool=t.name,
                    description=t.description or "",
                    input_schema=t.input_schema,
                )

    def tools_for_claude(self) -> list[dict]:
        """The merged catalogue in the shape the Anthropic Messages API expects."""
        return [
            {
                "name": full_name,
                "description": f"[{r.server} server] {r.description}",
                "input_schema": r.input_schema,
            }
            for full_name, r in self.routes.items()
        ]

    # ---- routing ---------------------------------------------------------

    async def call(self, full_name: str, arguments: dict) -> ToolOutcome:
        route = self.routes.get(full_name)
        if route is None:
            return ToolOutcome(f"Unknown tool '{full_name}'.", is_error=True)
        client = self.clients[route.server]
        try:
            # raise_on_error=False: tool failures come back as data, so we can
            # hand them to the LLM instead of crashing the whole loop.
            result = await client.call_tool(route.tool, arguments, raise_on_error=False, timeout=30)
        except Exception as exc:  # transport problems, timeouts, dead server...
            return ToolOutcome(f"Calling {full_name} failed: {exc}", is_error=True)
        text = "\n".join(getattr(c, "text", str(c)) for c in result.content)
        return ToolOutcome(text=text, is_error=result.is_error)
