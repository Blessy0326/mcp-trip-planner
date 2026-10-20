"""
Milestone 2: talk to all three servers by hand, no LLM involved.

    python explore.py                 # list every tool from every server
    python explore.py demo            # run a hard-coded "orchestration" by hand
    python explore.py call places__find_places city=Munich setting=indoor

The "demo" shows what the LLM will later do on its own: you decide which
tool to call next based on the previous result.
"""

import asyncio
import json
import sys
from datetime import date, timedelta

from mcp_hub import McpHub


def parse_args(parts: list[str]) -> dict:
    """Accept either key=value pairs or one JSON object.

    key=value avoids shell quoting trouble (PowerShell strips the quotes
    inside '{"city": "Munich"}' before Python sees them).
    """
    if len(parts) == 1 and parts[0].lstrip().startswith("{"):
        return json.loads(parts[0])
    args = {}
    for part in parts:
        key, sep, value = part.partition("=")
        if not sep:
            raise SystemExit(f"Expected key=value, got '{part}'")
        try:
            args[key] = json.loads(value)   # numbers, true/false, null
        except json.JSONDecodeError:
            args[key] = value               # plain text like Munich
    return args


def next_saturday() -> str:
    today = date.today()
    return (today + timedelta(days=(5 - today.weekday()) % 7 or 7)).isoformat()


async def list_tools(hub: McpHub) -> None:
    for name, route in hub.routes.items():
        params = ", ".join(route.input_schema.get("properties", {}))
        print(f"{name}({params})")
        print(f"    {route.description.strip().splitlines()[0] if route.description else ''}")


async def demo(hub: McpHub) -> None:
    day = next_saturday()
    print(f"Planning Munich on {day}\n")

    weather = await hub.call("weather__get_daily_forecast", {"city": "Munich", "day": day})
    print("1. weather ->", weather.text)
    if weather.is_error:
        return
    good = json.loads(weather.text)["good_for_outdoor"]

    setting = "outdoor" if good else "indoor"
    places = await hub.call("places__find_places", {"city": "Munich", "setting": setting})
    print(f"\n2. places ({setting}) ->", places.text)
    first = json.loads(places.text)[0]

    busy = await hub.call("calendar__list_events", {"day": day})
    print("\n3. calendar ->", busy.text)

    added = await hub.call("calendar__add_event", {
        "day": day, "start": "10:00", "end": "11:30",
        "title": first["name"], "location": "Munich",
    })
    print("\n4. add_event ->", added.text, "(error)" if added.is_error else "")


async def main() -> None:
    async with McpHub() as hub:
        if len(sys.argv) == 1:
            await list_tools(hub)
        elif sys.argv[1] == "demo":
            await demo(hub)
        elif sys.argv[1] == "call" and len(sys.argv) >= 3:
            out = await hub.call(sys.argv[2], parse_args(sys.argv[3:]))
            print(("ERROR: " if out.is_error else "") + out.text)
        else:
            print(__doc__)


if __name__ == "__main__":
    asyncio.run(main())