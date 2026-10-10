import pytest

from sahi.config import Settings
from sahi.serp.client import BudgetExceeded, SearchBudget, SerpClient
from sahi.store import Store


async def ok_transport(url, params):
    return 200, {"search_metadata": {"id": "ok", "status": "Success"}}


@pytest.mark.asyncio
async def test_per_check_cap_refuses_before_transport(db_path):
    client = SerpClient(
        Settings(serpapi_api_key="key", serpapi_mode="live", max_searches_per_check=1),
        Store(db_path),
        transport=ok_transport,
        account_reader=lambda: 100,
    )
    budget = SearchBudget(1)
    await client.search("google", {"q": "one"}, budget)

    with pytest.raises(BudgetExceeded, match="per-check limit"):
        await client.search("google", {"q": "two"}, budget)


@pytest.mark.asyncio
async def test_hourly_limit_refuses_live_call(db_path):
    store = Store(db_path)
    store.add_search("a", "google", {}, "1", "Success", True, {})
    client = SerpClient(
        Settings(serpapi_api_key="key", serpapi_mode="live", hourly_search_limit=1),
        store,
        transport=ok_transport,
        account_reader=lambda: 100,
    )

    with pytest.raises(BudgetExceeded, match="hourly limit"):
        await client.search("google", {"q": "two"}, SearchBudget(8))


@pytest.mark.asyncio
async def test_credit_reserve_refuses_live_call(db_path):
    client = SerpClient(
        Settings(serpapi_api_key="key", serpapi_mode="live", min_credits_reserve=20),
        Store(db_path),
        transport=ok_transport,
        account_reader=lambda: 19,
    )

    with pytest.raises(BudgetExceeded, match="reserve"):
        await client.search("google", {"q": "one"}, SearchBudget(8))
