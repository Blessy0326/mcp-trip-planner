"""
Places MCP server.

Serves a small local catalogue of things to do (data/places.json), each
tagged "indoor" or "outdoor". Add your own cities to the JSON file and the
LLM will pick them up on the next run, no code changes needed.
"""

import json
from pathlib import Path
from typing import Literal

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

mcp = FastMCP("places")

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "places.json"


def _load() -> list[dict]:
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))


@mcp.tool
def list_cities() -> list[str]:
    """List the cities this server has places for."""
    return sorted({p["city"] for p in _load()})


@mcp.tool
def find_places(
    city: str,
    setting: Literal["indoor", "outdoor", "any"] = "any",
    category: str | None = None,
) -> list[dict]:
    """Find things to do in a city.

    Args:
        city: City name, e.g. "Munich".
        setting: "indoor" for bad weather, "outdoor" for good weather, or "any".
        category: Optional filter such as "museum", "park", "food", "history".
    """
    places = [p for p in _load() if p["city"].lower() == city.lower()]
    if not places:
        raise ToolError(f"No places known for '{city}'. Call list_cities to see what's available.")
    if setting != "any":
        places = [p for p in places if p["setting"] == setting]
    if category:
        places = [p for p in places if p["category"].lower() == category.lower()]
    # Keep results small: the LLM doesn't need every field to choose.
    return [
        {"id": p["id"], "name": p["name"], "setting": p["setting"],
         "category": p["category"], "duration_hours": p["duration_hours"]}
        for p in places
    ]


@mcp.tool
def get_place_details(place_id: str) -> dict:
    """Get the full details for one place, using the id returned by find_places."""
    for p in _load():
        if p["id"] == place_id:
            return p
    raise ToolError(f"Unknown place id '{place_id}'.")


if __name__ == "__main__":
    mcp.run(show_banner=False)  # stdio transport by default
