import json
from datetime import UTC, datetime, timedelta

import pytest

from sahi.config import Settings
from sahi.serp.client import ReplayMiss, SearchBudget, SerpClient, make_cache_key
from sahi.store import Store


@pytest.mark.asyncio
async def test_live_cache_hit_avoids_second_transport_call(db_path):
    calls = []

    async def transport(url, params):
        calls.append((url, params))
        return 200, {"search_metadata": {"id": "receipt-1", "status": "Success"}, "x": 1}

    store = Store(db_path)
    settings = Settings(serpapi_api_key="test-key", serpapi_mode="live")
    client = SerpClient(settings, store, transport=transport, account_reader=lambda: 200)

    first = await client.search("google", {"q": "Example Air"}, SearchBudget(8))
    second = await client.search("google", {"q": "Example Air"}, SearchBudget(8))

    assert first.body == second.body
    assert len(calls) == 1
    assert "api_key" not in store.latest_search(first.cache_key)["params_json"]


@pytest.mark.asyncio
async def test_expired_cache_calls_transport_again(db_path):
    counter = 0

    async def transport(url, params):
        nonlocal counter
        counter += 1
        return 200, {"search_metadata": {"id": f"receipt-{counter}", "status": "Success"}}

    store = Store(db_path)
    settings = Settings(serpapi_api_key="test-key", serpapi_mode="live", cache_ttl_seconds=1)
    client = SerpClient(settings, store, transport=transport, account_reader=lambda: 200)
    result = await client.search("google", {"q": "help"}, SearchBudget(8))
    store.set_search_time(result.search_id, datetime.now(UTC) - timedelta(seconds=2))

    await client.search("google", {"q": "help"}, SearchBudget(8))

    assert counter == 2


@pytest.mark.asyncio
async def test_fresh_bypasses_valid_cache(db_path):
    calls = 0

    async def transport(url, params):
        nonlocal calls
        calls += 1
        return 200, {"search_metadata": {"id": str(calls), "status": "Success"}}

    client = SerpClient(
        Settings(serpapi_api_key="test-key", serpapi_mode="live"),
        Store(db_path),
        transport=transport,
        account_reader=lambda: 200,
    )
    budget = SearchBudget(8)
    await client.search("google", {"q": "help"}, budget)
    await client.search("google", {"q": "help"}, budget, fresh=True)

    assert calls == 2


@pytest.mark.asyncio
async def test_replay_miss_never_calls_transport(db_path):
    async def forbidden_transport(url, params):  # pragma: no cover - assertion path
        raise AssertionError("network must not be touched")

    client = SerpClient(
        Settings(serpapi_mode="replay", serpapi_api_key=""),
        Store(db_path),
        transport=forbidden_transport,
    )

    with pytest.raises(ReplayMiss, match="No replay receipt"):
        await client.search("google", {"q": "missing"}, SearchBudget(8))


@pytest.mark.asyncio
async def test_replay_imports_matching_fixture_without_network(db_path, tmp_path):
    fixture_path = tmp_path / "fixtures"
    fixture_path.mkdir()
    params = {"q": "Example Air"}
    cache_key = make_cache_key("google", params)
    (fixture_path / "google.json").write_text(
        json.dumps(
            {
                "_sahi_fixture": {
                    "cache_key": cache_key,
                    "engine": "google",
                    "params": params,
                },
                "response": {
                    "search_metadata": {"id": "fixture-receipt", "status": "Success"},
                    "organic_results": [],
                },
            }
        )
    )

    async def forbidden_transport(url, request_params):  # pragma: no cover
        raise AssertionError("network must not be touched")

    store = Store(db_path)
    client = SerpClient(
        Settings(serpapi_mode="replay", serpapi_api_key="", fixture_path=fixture_path),
        store,
        transport=forbidden_transport,
    )
    result = await client.search("google", params, SearchBudget(8))

    assert result.serpapi_id == "fixture-receipt"
    assert result.cached is True
    assert store.latest_search(cache_key) is not None


@pytest.mark.asyncio
async def test_http_transport_retries_rate_limit_once(db_path, monkeypatch):
    statuses = [429, 200]

    class Response:
        def __init__(self, status_code):
            self.status_code = status_code

        def json(self):
            return {"search_metadata": {"status": "Success"}}

    class Client:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, url, params):
            return Response(statuses.pop(0))

    monkeypatch.setattr("sahi.serp.client.httpx.AsyncClient", Client)
    client = SerpClient(Settings(serpapi_mode="replay"), Store(db_path))

    status, _body = await client._http_transport("https://example.test", {})

    assert status == 200
    assert statuses == []
