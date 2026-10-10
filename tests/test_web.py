import httpx
import pytest

from sahi.config import Settings
from sahi.store import Store
from sahi.web.app import create_app, seed_demo_check


def build_client(db_path):
    settings = Settings(serpapi_mode="replay", serpapi_api_key="", database_path=db_path)
    store = Store(db_path)
    demo_id = seed_demo_check(store)
    app = create_app(settings, store)
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test"), store, demo_id


@pytest.mark.asyncio
async def test_home_renders_brand_and_number_modes_in_both_languages(db_path):
    client, _store, _demo_id = build_client(db_path)
    english = await client.get("/")
    hindi = await client.get("/?ui=hi")
    assert english.status_code == 200
    assert "Check a helpline number" in english.text
    assert "Brand check" in english.text and "Number check" in english.text
    assert "Replay mode: no searches used" in english.text
    assert hindi.status_code == 200
    assert "हेल्पलाइन नंबर जाँचें" in hindi.text
    await client.aclose()


@pytest.mark.asyncio
async def test_result_evidence_receipt_limits_and_sweep_routes_render(db_path):
    client, store, demo_id = build_client(db_path)
    details = store.check_details(demo_id)
    canonical = details["verdicts"][0]["canonical"]
    search_id = store.list_searches()[0]["id"]
    routes = [
        f"/check/{demo_id}",
        f"/check/{demo_id}/number/{canonical}",
        f"/receipt/{search_id}",
        "/limits",
        "/sweep",
    ]
    for route in routes:
        response = await client.get(route)
        assert response.status_code == 200, route
    assert "OFFICIAL_MATCH" in (await client.get(f"/check/{demo_id}")).text
    assert "OFFICIAL_MATCH" in (await client.get("/sweep")).text
    assert "CONFLICT" in (await client.get("/sweep")).text
    receipt = (await client.get(f"/receipt/{search_id}")).text
    assert "demo-receipt" in receipt
    assert "api_key" not in receipt
    await client.aclose()


@pytest.mark.asyncio
async def test_post_check_redirects_to_persisted_result(db_path):
    client, _store, _demo_id = build_client(db_path)
    response = await client.post(
        "/check",
        data={"brand": "example-air", "city": "Mumbai", "lang": "en"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"].startswith("/check/")
    result = await client.get(response.headers["location"])
    assert "OFFICIAL_MATCH" in result.text
    assert "CONFLICT" in result.text
    assert "TOLL_FREE" in result.text
    assert "First seen" in result.text
    assert "Official references" in result.text
    await client.aclose()


@pytest.mark.asyncio
async def test_hindi_replay_check_has_complete_fictional_verdicts(db_path):
    client, _store, _demo_id = build_client(db_path)
    response = await client.post(
        "/check",
        data={"brand": "example-air", "city": "Mumbai", "lang": "hi"},
        follow_redirects=False,
    )

    result = await client.get(response.headers["location"] + "?ui=hi")

    assert result.status_code == 200
    assert "OFFICIAL_MATCH" in result.text
    assert "CONFLICT" in result.text
    assert "ब्रांड की आधिकारिक वेबसाइट पर मिला" in result.text
    await client.aclose()


@pytest.mark.asyncio
async def test_fragment_renders_incremental_step_status_before_check_finishes(db_path):
    client, store, _demo_id = build_client(db_path)
    store.save_check_step("pending-check", "Search", "running", "Collecting Google results")

    response = await client.get("/check/pending-check/fragment")

    assert response.status_code == 202
    assert "Search" in response.text
    assert "Running" in response.text
    assert 'hx-trigger="every 1s"' in response.text
    await client.aclose()


@pytest.mark.asyncio
async def test_post_check_accepts_a_free_text_brand(db_path):
    client, _store, _demo_id = build_client(db_path)
    response = await client.post(
        "/check",
        data={"brand": "Owner Supplied Brand", "city": "Mumbai", "lang": "en"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    result = await client.get(response.headers["location"])
    assert result.status_code == 200
    assert "Owner Supplied Brand" in result.text
    assert "No official domain is configured" in result.text
    await client.aclose()


@pytest.mark.asyncio
async def test_live_footer_shows_monthly_and_hourly_quota(db_path, monkeypatch):
    async def fake_credits(_self):
        return 123

    monkeypatch.setattr("sahi.web.app.SerpClient.credits_left", fake_credits)
    settings = Settings(
        serpapi_mode="live",
        serpapi_api_key="test-key",
        database_path=db_path,
        hourly_search_limit=45,
    )
    app = create_app(settings, Store(db_path))
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    response = await client.get("/")
    assert "123 searches left this month" in response.text
    assert "45 this hour" in response.text
    await client.aclose()


@pytest.mark.asyncio
async def test_unknown_receipt_returns_404(db_path):
    client, _store, _demo_id = build_client(db_path)
    assert (await client.get("/receipt/999999")).status_code == 404
    await client.aclose()


@pytest.mark.asyncio
async def test_number_tab_submits_and_explains_brandless_result(db_path):
    client, _store, _demo_id = build_client(db_path)
    response = await client.post(
        "/number", data={"number": "1800 123 456", "brand": ""}, follow_redirects=False
    )
    assert response.status_code == 303
    result = await client.get(response.headers["location"])
    assert result.status_code == 200
    assert "No verdict without a brand" in result.text
    assert "example-air.test" in result.text
    await client.aclose()
