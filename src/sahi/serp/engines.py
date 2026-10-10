from __future__ import annotations

import yaml

from sahi.config import ROOT, Settings
from sahi.serp.client import SearchBudget, SearchResult, SerpClient

GOOGLE_COMMON = {"gl": "in", "google_domain": "google.co.in"}


async def search_helpline(
    client: SerpClient,
    budget: SearchBudget,
    query: str,
    location: str | None,
    language: str,
    settings: Settings,
    *,
    fresh: bool = False,
) -> SearchResult:
    params = {
        **GOOGLE_COMMON,
        "q": query,
        "hl": language,
        "device": settings.device,
    }
    if location:
        params["location"] = location
    return await client.search("google", params, budget, fresh=fresh)


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


async def search_brand_identity(
    client: SerpClient,
    budget: SearchBudget,
    brand: str,
    settings: Settings,
    *,
    fresh: bool = False,
) -> SearchResult:
    """Find a knowledge-graph website for an unseeded brand."""

    return await client.search(
        "google",
        {
            **GOOGLE_COMMON,
            "q": f'"{brand}" official website contact',
            "hl": "en",
            "device": settings.device,
        },
        budget,
        ttl=86400,
        fresh=fresh,
    )


async def search_public_directory(
    client: SerpClient,
    budget: SearchBudget,
    brand: str,
    location: str | None = None,
    *,
    fresh: bool = False,
) -> SearchResult:
    """Find a matching public-authority directory entry for a local branch."""

    config = yaml.safe_load((ROOT / "seeds" / "trusted_sources.yaml").read_text()) or {}
    authority_sites = [
        str(suffix).removeprefix(".")
        for suffix in config.get("public_authority_suffixes", [])
    ]
    scope = " OR ".join(f"site:{domain}" for domain in dict.fromkeys(authority_sites))
    params = {
        **GOOGLE_COMMON,
        "q": f"{brand} phone contact ({scope})",
        "hl": "en",
    }
    if location:
        params["location"] = location
    return await client.search("google", params, budget, ttl=86400, fresh=fresh)


async def search_maps(
    client: SerpClient,
    budget: SearchBudget,
    brand: str,
    location: str | None,
    language: str,
    lat: float | None = None,
    lng: float | None = None,
) -> SearchResult:
    params = {"type": "search", "q": f"{brand} customer care", "hl": language}
    if lat is not None and lng is not None:
        params["ll"] = f"@{lat},{lng},12z"
    elif location:
        params.update({"location": location, "z": 12})
    return await client.search("google_maps", params, budget)


async def search_ads(
    client: SerpClient,
    budget: SearchBudget,
    query: str,
    location: str | None,
    language: str,
) -> SearchResult:
    params = {"q": query, "hl": language}
    if location:
        params["location"] = location
    return await client.search("google_ads", params, budget)


async def search_number(
    client: SerpClient, budget: SearchBudget, query: str, location: str | None = None
) -> SearchResult:
    # Keep the query as a single human-readable number.  A broad OR expression
    # lets Google rank unrelated product codes containing fragments of a number.
    # These options also preserve exact-number intent and expose omitted results.
    params = {
        **GOOGLE_COMMON,
        "q": query,
        "hl": "en",
        "nfpr": "1",
        "filter": "0",
    }
    if location:
        params["location"] = location
    return await client.search("google", params, budget)


async def search_number_discovery(
    client: SerpClient, budget: SearchBudget, query: str, location: str | None = None
) -> SearchResult:
    """Retry an empty exact search the same way a person normally searches Google."""

    return await search_number(client, budget, query, location)


async def search_number_contextual(
    client: SerpClient, budget: SearchBudget, number: str, location: str | None = None
) -> SearchResult:
    """Ask Google for the number in a contact context when an exact search is noisy."""

    return await search_number(client, budget, f'"{number}" contact', location)


async def search_number_with_brand(
    client: SerpClient,
    budget: SearchBudget,
    brand: str,
    number: str,
    location: str | None = None,
) -> SearchResult:
    """Use owner words to disambiguate a number that Google parsed as another identifier."""

    familiar = number.replace(" ", "-", 1)
    query = f'{brand} "{familiar}"'
    return await search_number(client, budget, query, location)


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
