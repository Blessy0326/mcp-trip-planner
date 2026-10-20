"""
Weather MCP server.

Wraps the free Open-Meteo API (no API key needed):
  - geocoding:  https://geocoding-api.open-meteo.com/v1/search
  - forecast:   https://api.open-meteo.com/v1/forecast

Set WEATHER_MOCK=1 to return fake data (handy offline or while debugging
the orchestrator, so you aren't hitting the API on every run).
"""

import os
from datetime import date

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

mcp = FastMCP("weather")

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# WMO weather codes -> short description. Open-Meteo returns these numbers.
WMO_CODES = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "freezing fog",
    51: "light drizzle", 53: "drizzle", 55: "heavy drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain",
    71: "light snow", 73: "snow", 75: "heavy snow",
    80: "light showers", 81: "showers", 82: "violent showers",
    95: "thunderstorm", 96: "thunderstorm with hail", 99: "thunderstorm with heavy hail",
}
WET_CODES = {51, 53, 55, 61, 63, 65, 71, 73, 75, 80, 81, 82, 95, 96, 99}


def _mock_forecast(city: str, day: str) -> dict:
    # Deterministic fake: even day-of-month = rainy, odd = sunny.
    rainy = date.fromisoformat(day).day % 2 == 0
    return {
        "city": city, "date": day,
        "summary": "rain" if rainy else "clear sky",
        "temp_max_c": 11 if rainy else 17, "temp_min_c": 6 if rainy else 8,
        "precipitation_probability_pct": 80 if rainy else 5,
        "good_for_outdoor": not rainy,
        "source": "MOCK DATA",
    }


async def _geocode(client: httpx.AsyncClient, city: str) -> dict:
    r = await client.get(GEOCODE_URL, params={"name": city, "count": 1, "language": "en"})
    r.raise_for_status()
    results = r.json().get("results")
    if not results:
        # ToolError messages are sent back to the LLM as an error result,
        # so it can react (e.g. ask the user to spell the city differently).
        raise ToolError(f"Could not find a city called '{city}'.")
    return results[0]


@mcp.tool
async def get_daily_forecast(city: str, day: str) -> dict:
    """Get the weather forecast for one city on one day.

    Args:
        city: City name, e.g. "Munich".
        day: Date in YYYY-MM-DD format. Must be within the next 14 days.
    """
    try:
        date.fromisoformat(day)
    except ValueError:
        raise ToolError(f"'{day}' is not a valid date. Use YYYY-MM-DD.")

    if os.getenv("WEATHER_MOCK") == "1":
        return _mock_forecast(city, day)

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            place = await _geocode(client, city)
            r = await client.get(FORECAST_URL, params={
                "latitude": place["latitude"],
                "longitude": place["longitude"],
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                "timezone": "auto",
                "start_date": day,
                "end_date": day,
            })
            if r.status_code == 400:
                raise ToolError(f"No forecast available for {day} (only the next ~14 days are supported).")
            r.raise_for_status()
            daily = r.json()["daily"]
    except httpx.HTTPError as exc:
        # Turn network failures into a clear message for the LLM.
        raise ToolError(f"Weather service unreachable ({type(exc).__name__}). Try again later.")

    code = daily["weather_code"][0]
    rain_pct = daily["precipitation_probability_max"][0]
    return {
        "city": place["name"],
        "date": day,
        "summary": WMO_CODES.get(code, f"weather code {code}"),
        "temp_max_c": daily["temperature_2m_max"][0],
        "temp_min_c": daily["temperature_2m_min"][0],
        "precipitation_probability_pct": rain_pct,
        # A simple rule the LLM can lean on. Tweak it and watch the plans change!
        "good_for_outdoor": code not in WET_CODES and (rain_pct or 0) < 50,
    }


if __name__ == "__main__":
    mcp.run(show_banner=False)  # stdio transport by default
