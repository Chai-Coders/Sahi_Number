from __future__ import annotations

from typing import Any

import httpx

from sahi.store import Store


async def resolve_location(city: str, store: Store) -> dict[str, Any] | None:
    """Resolve an Indian city using SerpApi's free Locations endpoint."""

    with store.connect() as connection:
        cached = connection.execute("SELECT * FROM locations WHERE city=?", (city,)).fetchone()
    if cached:
        return dict(cached)
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(
            "https://serpapi.com/locations.json", params={"q": city, "limit": 5}
        )
    response.raise_for_status()
    choices = [item for item in response.json() if item.get("country_code") == "IN"]
    choices.sort(key=lambda item: item.get("target_type") != "City")
    if not choices:
        return None
    selected = choices[0]
    gps = selected.get("gps") or [None, None]
    longitude, latitude = (gps + [None, None])[:2]
    with store.connect() as connection:
        connection.execute(
            "INSERT OR REPLACE INTO locations(city, canonical_name, lat, lng) VALUES (?, ?, ?, ?)",
            (city, selected["canonical_name"], latitude, longitude),
        )
    return {
        "city": city,
        "canonical_name": selected["canonical_name"],
        "lat": latitude,
        "lng": longitude,
    }
