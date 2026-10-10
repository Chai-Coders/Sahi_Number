import pytest

from sahi.serp.account import resolve_location
from sahi.store import Store


@pytest.mark.asyncio
async def test_location_resolver_prefers_indian_city_and_preserves_gps_order(db_path, monkeypatch):
    calls = 0

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return [
                {
                    "canonical_name": "Mumbai,Other",
                    "country_code": "US",
                    "target_type": "City",
                    "gps": [-80.0, 25.0],
                },
                {
                    "canonical_name": "Mumbai,Maharashtra,India",
                    "country_code": "IN",
                    "target_type": "City",
                    "gps": [72.8777, 19.076],
                },
            ]

    class Client:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, url, params):
            nonlocal calls
            calls += 1
            assert params == {"q": "Mumbai", "limit": 5}
            return Response()

    monkeypatch.setattr("sahi.serp.account.httpx.AsyncClient", Client)
    store = Store(db_path)

    first = await resolve_location("Mumbai", store)
    second = await resolve_location("Mumbai", store)

    assert first == second
    assert first["canonical_name"] == "Mumbai,Maharashtra,India"
    assert first["lat"] == 19.076
    assert first["lng"] == 72.8777
    assert calls == 1
