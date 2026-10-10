from types import SimpleNamespace

import pytest

from sahi.reference import Brand
from sahi.store import Store
from sahi.sweep import SweepBudgetError, estimate_searches, run_sweep


def test_estimate_searches_uses_full_per_check_cap_per_cell():
    assert estimate_searches(2, 2, 2) == 64


@pytest.mark.asyncio
async def test_sweep_refuses_plan_above_hard_budget_before_running(db_path):
    store = Store(db_path)
    pipeline = SimpleNamespace(brand_check=None)
    brands = [Brand(id="a", name="A"), Brand(id="b", name="B")]
    with pytest.raises(SweepBudgetError, match="64.*20"):
        await run_sweep(pipeline, store, brands, ["Mumbai", "Delhi"], ["en", "hi"], 20)


@pytest.mark.asyncio
async def test_sweep_resumes_by_skipping_stored_cells(db_path):
    store = Store(db_path)
    store.save_check(
        {
            "id": "existing",
            "mode": "brand",
            "brand_id": "example-air",
            "brand_text": "Example Air",
            "city": "Mumbai",
            "lang": "en",
            "started_at": "2026-10-10T00:00:00+00:00",
            "finished_at": "2026-10-10T00:00:01+00:00",
            "searches_used": 0,
            "skipped": [],
        },
        [],
        {},
        [],
    )

    class FakePipeline:
        def __init__(self):
            self.calls = []

        async def brand_check(self, brand, city, lang):
            self.calls.append((brand.id, city, lang))
            return SimpleNamespace(id="new", searches_used=0)

    pipeline = FakePipeline()
    result = await run_sweep(
        pipeline, store, [Brand(id="example-air", name="Example Air")], ["Mumbai"], ["en"], 4
    )
    assert pipeline.calls == []
    assert result.skipped_cells == 1
    assert result.completed_cells == 0


def test_number_history_increments_for_repeated_sighting(db_path):
    from sahi.extract.phones import PhoneClass
    from sahi.extract.walker import Sighting

    store = Store(db_path)
    item = Sighting(
        "+919876543210",
        "98765 43210",
        PhoneClass.MOBILE,
        "ORGANIC",
        "organic_results[0].snippet",
        "Help",
        "https://directory.test",
        "directory.test",
        1,
        1,
        {},
    )
    for check_id in ("one", "two"):
        store.save_check(
            {
                "id": check_id,
                "mode": "brand",
                "brand_id": "example-air",
                "brand_text": "Example Air",
                "city": "Mumbai",
                "lang": "en",
                "started_at": "2026-10-10T00:00:00+00:00",
                "finished_at": f"2026-10-10T00:00:0{1 if check_id == 'one' else 2}+00:00",
                "searches_used": 0,
                "skipped": [],
            },
            [item],
            {},
            [],
        )
    with store.connect() as connection:
        row = connection.execute("SELECT * FROM number_history").fetchone()
    assert row["times_seen"] == 2
    assert row["first_seen"] < row["last_seen"]


@pytest.mark.asyncio
async def test_live_sweep_waits_for_hourly_capacity(db_path):
    store = Store(db_path)
    search_id = store.add_search("key", "google", {"q": "x"}, "receipt", "Success", True, {})
    waits = []

    async def fake_sleep(seconds):
        from datetime import UTC, datetime, timedelta

        waits.append(seconds)
        store.set_search_time(search_id, datetime.now(UTC) - timedelta(hours=2))

    class FakePipeline:
        settings = SimpleNamespace(effective_mode="live", hourly_search_limit=1)

        async def brand_check(self, brand, city, language):
            return SimpleNamespace(searches_used=0)

    result = await run_sweep(
        FakePipeline(),
        store,
        [Brand(id="a", name="A")],
        ["Mumbai"],
        ["en"],
        1,
        per_check_cap=1,
        sleep=fake_sleep,
    )

    assert waits and waits[0] > 0
    assert result.completed_cells == 1
