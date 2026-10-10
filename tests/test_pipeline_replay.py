import json

import pytest

from sahi.config import Settings
from sahi.pipeline import Pipeline
from sahi.reference import Brand
from sahi.serp.client import SerpClient, make_cache_key
from sahi.store import Store
from sahi.verdict import Verdict


def cache(store, engine, params, body, receipt):
    key = make_cache_key(engine, params)
    return store.add_search(key, engine, params, receipt, "Success", False, body)


@pytest.mark.asyncio
async def test_complete_brand_check_replays_to_official_match_and_conflict(db_path):
    store = Store(db_path)
    settings = Settings(serpapi_mode="replay", serpapi_api_key="")
    brand = Brand(
        id="example-air",
        name="Example Air",
        official_domain="example-air.test",
        domain_verified=True,
        official_numbers=(
            {
                "number": "1800 123 456",
                "source_url": "https://example-air.test/contact",
                "verified_on": "2026-10-10",
            },
        ),
    )
    common = {"gl": "in", "google_domain": "google.co.in"}
    cache(
        store,
        "google",
        {
            **common,
            "q": "Example Air customer care number",
            "location": "Mumbai",
            "hl": "en",
            "device": "mobile",
        },
        {
            "search_metadata": {"id": "helpline", "status": "Success"},
            "ai_overview": {"page_token": "demo-ai-token"},
            "organic_results": [
                {
                    "position": 1,
                    "title": "Example Air",
                    "link": "https://example-air.test/contact",
                    "snippet": "Call 1800 123 456",
                }
            ],
        },
        "helpline",
    )
    cache(
        store,
        "google",
        {
            **common,
            "q": 'site:example-air.test customer care OR helpline OR "toll free" OR contact',
            "hl": "en",
        },
        {"search_metadata": {"id": "official", "status": "Success"}, "organic_results": []},
        "official",
    )
    cache(
        store,
        "google_maps",
        {
            "type": "search",
            "q": "Example Air customer care",
            "hl": "en",
            "location": "Mumbai",
            "z": 12,
        },
        {
            "search_metadata": {"id": "maps", "status": "Success"},
            "local_results": [
                {
                    "position": 1,
                    "title": "Example Air Help",
                    "phone": "98765 43210",
                    "data_id": "place-1",
                    "unclaimed_listing": True,
                }
            ],
        },
        "maps",
    )
    cache(
        store,
        "google_ads",
        {"q": "Example Air customer care number", "location": "Mumbai", "hl": "en"},
        {
            "search_metadata": {"id": "ads", "status": "Success"},
            "ads": [
                {
                    "position": 1,
                    "title": "Help",
                    "link": "https://wrong.test",
                    "description": "Call 98765 43210",
                }
            ],
        },
        "ads",
    )
    cache(
        store,
        "google_ai_overview",
        {"page_token": "demo-ai-token"},
        {
            "search_metadata": {"id": "ai", "status": "Success"},
            "text_blocks": [{"snippet": "AI answer showed 1800 765 432"}],
        },
        "ai",
    )
    cache(
        store,
        "google_maps_reviews",
        {"data_id": "place-1", "sort_by": "newestFirst", "hl": "en"},
        {
            "search_metadata": {"id": "reviews", "status": "Success"},
            "reviews": [
                {
                    "snippet": "Fake number, asked for OTP",
                    "iso_date": "2026-10-01",
                    "rating": 1,
                    "link": "https://maps.test/review",
                }
            ],
        },
        "reviews",
    )
    pipeline = Pipeline(settings, store, SerpClient(settings, store))

    result = await pipeline.brand_check(brand, "Mumbai", "en")

    by_number = {item.canonical: item for item in result.numbers}
    assert by_number["1800123456"].verdict == Verdict.OFFICIAL_MATCH
    assert by_number["+919876543210"].verdict == Verdict.CONFLICT
    assert "REVIEW_WARNINGS" in by_number["+919876543210"].signals
    assert "1800765432" in by_number
    assert "number search" in " ".join(result.skipped).lower()
    stored = store.get_check(result.id)
    assert stored is not None
    assert json.loads(stored["skipped_json"])
    with store.connect() as connection:
        stored_reference = connection.execute(
            "SELECT * FROM reference_numbers WHERE brand_id='example-air'"
        ).fetchone()
    assert stored_reference["canonical"] == "1800123456"


@pytest.mark.asyncio
async def test_free_text_brand_uses_unconfirmed_knowledge_graph_domain(db_path):
    store = Store(db_path)
    settings = Settings(
        serpapi_mode="replay",
        serpapi_api_key="",
        enable_ads=False,
        enable_ai_overview=False,
        enable_reviews=False,
    )
    brand = Brand(id="free-owner-brand", name="Owner Brand")
    common = {"gl": "in", "google_domain": "google.co.in"}
    cache(
        store,
        "google",
        {
            **common,
            "q": "Owner Brand customer care number",
            "location": "Mumbai",
            "hl": "en",
            "device": "mobile",
        },
        {
            "search_metadata": {"id": "helpline", "status": "Success"},
            "knowledge_graph": {
                "website": "https://owner-brand.test",
                "phone": "1800 555 000",
            },
        },
        "helpline",
    )
    cache(
        store,
        "google_maps",
        {
            "type": "search",
            "q": "Owner Brand customer care",
            "hl": "en",
            "location": "Mumbai",
            "z": 12,
        },
        {"search_metadata": {"id": "maps", "status": "Success"}, "local_results": []},
        "maps",
    )
    cache(
        store,
        "google",
        {
            **common,
            "q": 'site:owner-brand.test customer care OR helpline OR "toll free" OR contact',
            "hl": "en",
        },
        {
            "search_metadata": {"id": "official", "status": "Success"},
            "organic_results": [
                {
                    "title": "Contact",
                    "link": "https://owner-brand.test/contact",
                    "snippet": "Call 1800 555 000",
                }
            ],
        },
        "official",
    )

    result = await Pipeline(settings, store, SerpClient(settings, store)).brand_check(
        brand, "Mumbai", "en"
    )

    assert result.brand.official_domain == "owner-brand.test"
    assert result.brand.domain_verified is False
    assert result.numbers[0].verdict == Verdict.OFFICIAL_MATCH
    assert "unconfirmed domain" in " ".join(result.skipped).lower()
