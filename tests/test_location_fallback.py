import pytest

from sahi.config import Settings
from sahi.pipeline import Pipeline
from sahi.reference import Brand
from sahi.serp.client import SearchBudget, SearchResult
from sahi.store import Store


@pytest.mark.asyncio
async def test_unresolved_place_uses_place_words_without_invalid_location(monkeypatch, db_path):
    async def no_canonical_location(_city, _store):
        return None

    monkeypatch.setattr("sahi.pipeline.resolve_location", no_canonical_location)

    class Client:
        def __init__(self):
            self.calls: list[tuple[str, dict[str, object]]] = []

        async def search(self, engine, params, _budget: SearchBudget, **_kwargs):
            self.calls.append((engine, params))
            return SearchResult(
                len(self.calls),
                str(len(self.calls)),
                engine,
                {"search_metadata": {"status": "Success"}, "organic_results": []},
                None,
                False,
            )

    client = Client()
    settings = Settings(
        serpapi_mode="live",
        serpapi_api_key="test-key",
        enable_ai_overview=False,
        enable_reviews=False,
    )
    result = await Pipeline(settings, Store(db_path), client).brand_check(
        Brand(id="free-sbi-valavoor", name="SBI Bank Valavoor"), "Palai", "en"
    )

    assert all("location" not in params for _engine, params in client.calls)
    assert any("Palai" in str(params["q"]) for _engine, params in client.calls)
    assert "country-wide query" in " ".join(result.skipped)
