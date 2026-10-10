import json

import pytest

from sahi.config import Settings
from sahi.serp.client import SearchResult, make_cache_key
from sahi.store import Store
from scripts.probe import build_probe_plan, run_probe


def test_probe_plan_is_bounded_to_ten_searches():
    plan = build_probe_plan("Owner Brand", ["Mumbai", "Delhi"], ["en", "hi"])
    assert len(plan) == 10
    assert {step["engine"] for step in plan} == {"google", "google_maps", "google_ads"}


def test_probe_requires_a_real_brand_name():
    try:
        build_probe_plan(" ", ["Mumbai"], ["en"])
    except ValueError as error:
        assert "brand" in str(error).lower()
    else:  # pragma: no cover - assertion path
        raise AssertionError("blank brand must be rejected")


@pytest.mark.asyncio
async def test_probe_records_scrubbed_replay_envelopes_and_capabilities(db_path, tmp_path):
    class FakeClient:
        def __init__(self):
            self.calls = 0

        async def search(self, engine, params, budget, fresh=False):
            self.calls += 1
            budget.spend()
            body = {
                "search_metadata": {"id": f"probe-{self.calls}", "status": "Success"},
                "organic_results": [{"snippet": "Call 1800 123 456"}],
            }
            if engine == "google_maps":
                body["local_results"] = [
                    {
                        "phone": "98765 43210",
                        "website": "https://owner-brand.test",
                        "unclaimed_listing": True,
                    }
                ]
            return SearchResult(
                self.calls,
                make_cache_key(engine, params),
                engine,
                body,
                f"probe-{self.calls}",
                False,
            )

    recorded = tmp_path / "recorded"
    settings = Settings(serpapi_mode="live", serpapi_api_key="test-key")
    fake = FakeClient()
    results = await run_probe(
        "Owner Brand",
        ["Mumbai", "Delhi"],
        ["en", "hi"],
        settings,
        Store(db_path),
        client=fake,
        recorded_dir=recorded,
        report_path=tmp_path / "PROBE.md",
    )

    assert len(results) == 10
    assert len(list(recorded.glob("*.json"))) == 10
    payload = json.loads(next(recorded.glob("*.json")).read_text())
    assert payload["_sahi_fixture"]["cache_key"]
    assert "response" in payload
    assert all("phone_paths" in result for result in results)
    report = (tmp_path / "PROBE.md").read_text()
    assert "Status: **completed**" in report
    assert "Searches spent: **10**" in report
