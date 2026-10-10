import pytest

from sahi.config import Settings
from sahi.extract.phones import normalise_phone
from sahi.pipeline import Pipeline
from sahi.reference import Brand
from sahi.serp.client import SerpClient, make_cache_key
from sahi.store import Store
from sahi.verdict import Verdict


def seed_number_search(store, value):
    match = normalise_phone(value)
    params = {
        "gl": "in",
        "google_domain": "google.co.in",
        "q": " OR ".join(match.search_variants),
        "hl": "en",
    }
    body = {
        "search_metadata": {"id": "number-receipt", "status": "Success"},
        "organic_results": [
            {
                "position": 1,
                "title": "Example Air contact",
                "link": "https://example-air.test/contact",
                "snippet": f"Call {value}",
            },
            {
                "position": 2,
                "title": "Directory",
                "link": "https://directory.test/listing",
                "snippet": f"Phone {value}",
            },
        ],
    }
    store.add_search(
        make_cache_key("google", params), "google", params, "number-receipt", "Success", False, body
    )


@pytest.mark.asyncio
async def test_number_check_without_brand_groups_appearance_domains(db_path):
    settings = Settings(serpapi_mode="replay", serpapi_api_key="")
    store = Store(db_path)
    seed_number_search(store, "1800 123 456")
    result = await Pipeline(settings, store, SerpClient(settings, store)).number_check(
        "1800 123 456"
    )
    assert result.canonical == "1800123456"
    assert result.verdict is None
    assert set(result.domains) == {"example-air.test", "directory.test"}


@pytest.mark.asyncio
async def test_number_check_with_brand_uses_same_verdict_function(db_path):
    settings = Settings(serpapi_mode="replay", serpapi_api_key="")
    store = Store(db_path)
    seed_number_search(store, "1800 123 456")
    brand = Brand(
        id="example-air",
        name="Example Air",
        official_domain="example-air.test",
        official_numbers=(
            {
                "number": "1800 123 456",
                "source_url": "https://example-air.test/contact",
                "verified_on": "2026-10-10",
            },
        ),
    )
    result = await Pipeline(settings, store, SerpClient(settings, store)).number_check(
        "1800 123 456", brand
    )
    assert result.verdict == Verdict.OFFICIAL_MATCH


@pytest.mark.asyncio
async def test_number_check_rejects_non_phone_input(db_path):
    settings = Settings(serpapi_mode="replay", serpapi_api_key="")
    store = Store(db_path)
    with pytest.raises(ValueError, match="valid phone"):
        await Pipeline(settings, store, SerpClient(settings, store)).number_check("order 123456")


@pytest.mark.asyncio
async def test_number_check_reports_replay_miss_without_a_traceback(db_path, tmp_path):
    settings = Settings(
        serpapi_mode="replay",
        serpapi_api_key="",
        fixture_path=tmp_path / "empty-fixtures",
    )
    store = Store(db_path)
    with pytest.raises(ValueError, match="Number search unavailable.*No replay receipt"):
        await Pipeline(settings, store, SerpClient(settings, store)).number_check("98765 43210")
