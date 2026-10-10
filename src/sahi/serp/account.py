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
    if not choices:
        return None
    query = city.casefold().strip()

    def relevance(item: dict[str, Any]) -> tuple[int, int]:
        name = str(item.get("name", "")).casefold().strip()
        canonical_head = str(item.get("canonical_name", "")).split(",", 1)[0].casefold().strip()
        if query in {name, canonical_head}:
            text_rank = 0
        elif name.startswith(query) or canonical_head.startswith(query):
            text_rank = 1
        else:
            text_rank = 2
        type_rank = 0 if item.get("target_type") == "City" else 1
        return text_rank, type_rank

    choices.sort(key=relevance)
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
