"""
Calendar MCP server.

A tiny local calendar stored in data/calendar.json. This is the only server
that *changes* state, which makes it the interesting one for orchestration:
the LLM should check weather and places first, then write here last.
"""

import json
import uuid
from datetime import date, time
from pathlib import Path

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

mcp = FastMCP("calendar")

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "calendar.json"


def _load() -> list[dict]:
    if not DATA_FILE.exists():
        return []
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))


def _save(events: list[dict]) -> None:
    DATA_FILE.write_text(json.dumps(events, indent=2, ensure_ascii=False), encoding="utf-8")


def _parse(day: str, start: str, end: str) -> tuple[time, time]:
    try:
        date.fromisoformat(day)
        t_start, t_end = time.fromisoformat(start), time.fromisoformat(end)
    except ValueError:
        raise ToolError("Use YYYY-MM-DD for the day and HH:MM for times.")
    if t_end <= t_start:
        raise ToolError("End time must be after start time.")
    return t_start, t_end


@mcp.tool
def list_events(day: str) -> list[dict]:
    """List calendar events on a given day (YYYY-MM-DD), sorted by start time."""
    return sorted((e for e in _load() if e["day"] == day), key=lambda e: e["start"])


@mcp.tool
def add_event(day: str, start: str, end: str, title: str, location: str = "") -> dict:
    """Add an event to the calendar.

    Fails if it overlaps an existing event, so check list_events first.

    Args:
        day: YYYY-MM-DD
        start: HH:MM (24h)
        end: HH:MM (24h)
        title: What the event is, e.g. "Deutsches Museum".
        location: Optional place or city.
    """
    t_start, t_end = _parse(day, start, end)
    events = _load()
    for e in events:
        if e["day"] != day:
            continue
        e_start, e_end = time.fromisoformat(e["start"]), time.fromisoformat(e["end"])
        if t_start < e_end and e_start < t_end:
            # The LLM sees this message and should pick another time slot.
            raise ToolError(
                f"Overlaps with '{e['title']}' ({e['start']}-{e['end']}). Choose a different time."
            )
    event = {"id": uuid.uuid4().hex[:8], "day": day, "start": start, "end": end,
             "title": title, "location": location}
    events.append(event)
    _save(events)
    return event


@mcp.tool
def delete_event(event_id: str) -> str:
    """Delete an event by its id."""
    events = _load()
    remaining = [e for e in events if e["id"] != event_id]
    if len(remaining) == len(events):
        raise ToolError(f"No event with id '{event_id}'.")
    _save(remaining)
    return f"Deleted event {event_id}."


if __name__ == "__main__":
    mcp.run(show_banner=False)  # stdio transport by default
