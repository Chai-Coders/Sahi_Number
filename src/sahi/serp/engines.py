from __future__ import annotations

from sahi.config import Settings
from sahi.serp.client import SearchBudget, SearchResult, SerpClient

GOOGLE_COMMON = {"gl": "in", "google_domain": "google.co.in"}


async def search_helpline(
    client: SerpClient,
    budget: SearchBudget,
    query: str,
    location: str,
    language: str,
    settings: Settings,
    *,
    fresh: bool = False,
) -> SearchResult:
    return await client.search(
        "google",
        {
            **GOOGLE_COMMON,
            "q": query,
            "location": location,
            "hl": language,
            "device": settings.device,
        },
        budget,
        fresh=fresh,
    )


async def search_official_site(
    client: SerpClient,
    budget: SearchBudget,
    domain: str,
    *,
    fresh: bool = False,
) -> SearchResult:
    query = f'site:{domain} customer care OR helpline OR "toll free" OR contact'
    return await client.search(
        "google",
        {**GOOGLE_COMMON, "q": query, "hl": "en"},
        budget,
        ttl=86400,
        fresh=fresh,
    )


async def search_maps(
    client: SerpClient,
    budget: SearchBudget,
    brand: str,
    location: str,
    language: str,
    lat: float | None = None,
    lng: float | None = None,
) -> SearchResult:
    params = {"type": "search", "q": f"{brand} customer care", "hl": language}
    if lat is not None and lng is not None:
        params["ll"] = f"@{lat},{lng},12z"
    else:
        params.update({"location": location, "z": 12})
    return await client.search("google_maps", params, budget)


async def search_ads(
    client: SerpClient,
    budget: SearchBudget,
    query: str,
    location: str,
    language: str,
) -> SearchResult:
    return await client.search(
        "google_ads", {"q": query, "location": location, "hl": language}, budget
    )


async def search_number(
    client: SerpClient, budget: SearchBudget, variants: list[str]
) -> SearchResult:
    return await client.search(
        "google", {**GOOGLE_COMMON, "q": " OR ".join(variants), "hl": "en"}, budget
    )


async def fetch_reviews(
    client: SerpClient, budget: SearchBudget, data_id: str, language: str
) -> SearchResult:
    return await client.search(
        "google_maps_reviews",
        {"data_id": data_id, "sort_by": "newestFirst", "hl": language},
        budget,
    )


async def redeem_ai_overview(
    client: SerpClient, budget: SearchBudget, page_token: str
) -> SearchResult:
    return await client.search("google_ai_overview", {"page_token": page_token}, budget)
