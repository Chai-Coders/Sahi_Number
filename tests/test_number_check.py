import pytest

from sahi.config import Settings
from sahi.extract.phones import normalise_phone, primary_search_query
from sahi.extract.walker import Sighting
from sahi.pipeline import Pipeline
from sahi.reference import Brand, load_brands
from sahi.serp.client import SearchResult, SerpClient, make_cache_key
from sahi.store import Store
from sahi.verdict import Verdict


def seed_number_search(store, value):
    match = normalise_phone(value)
    params = {
        "gl": "in",
        "google_domain": "google.co.in",
        "q": primary_search_query(match),
        "hl": "en",
        "nfpr": "1",
        "filter": "0",
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
async def test_seeded_sbi_toll_free_number_uses_verified_official_reference(db_path):
    settings = Settings(serpapi_mode="replay", serpapi_api_key="")
    store = Store(db_path)
    seed_number_search(store, "1800 11 2211")
    sbi = next(brand for brand in load_brands() if brand.id == "sbi")

    result = await Pipeline(settings, store, SerpClient(settings, store)).number_check(
        "1800 11 2211", sbi
    )

    assert result.kind.value == "TOLL_FREE"
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


@pytest.mark.asyncio
async def test_number_check_accepts_matching_public_directory_reference(monkeypatch, db_path):
    async def government_page(url, _store):
        assert url == "https://kottayam.nic.in/en/public-utility/state-bank-of-india-132/"
        return "STATE BANK OF INDIA VALAVOOR Phone: 0482-2258058"

    monkeypatch.setattr("sahi.reference._contact_body", government_page)

    class Client:
        def __init__(self):
            self.calls = 0

        async def search(self, engine, _params, _budget, **_kwargs):
            self.calls += 1
            body = {"search_metadata": {"status": "Success"}, "organic_results": []}
            if "site:" in str(_params.get("q", "")):
                body["organic_results"] = [
                    {
                        "title": "State Bank of India - Valavoor",
                        "snippet": "Bank Valavoor phone 0482-2258058",
                        "link": "https://kottayam.nic.in/en/public-utility/state-bank-of-india-132/",
                    }
                ]
            return SearchResult(self.calls, str(self.calls), engine, body, None, False)

    settings = Settings(serpapi_mode="live", serpapi_api_key="test-key")
    result = await Pipeline(settings, Store(db_path), Client()).number_check(
        "0482-2258058", Brand(id="free-sbi-valavoor", name="SBI Bank Valavoor")
    )

    assert result.verdict == Verdict.OFFICIAL_MATCH
    assert result.reasons == ("Found in a matching Indian public-authority directory",)


@pytest.mark.asyncio
async def test_number_check_retries_empty_exact_search_with_unquoted_local_number(db_path):
    class Client:
        def __init__(self):
            self.queries: list[str] = []

        async def search(self, engine, params, _budget, **_kwargs):
            self.queries.append(str(params["q"]))
            body = {"search_metadata": {"status": "Success"}, "organic_results": []}
            if len(self.queries) == 2:
                body["organic_results"] = [
                    {
                        "position": 1,
                        "title": "State Bank of India Valavoor",
                        "link": "https://directory.test/valavoor",
                        "snippet": "Branch phone 04822-258058",
                    }
                ]
            return SearchResult(
                len(self.queries), str(len(self.queries)), engine, body, None, False
            )

    client = Client()
    settings = Settings(serpapi_mode="live", serpapi_api_key="test-key")
    result = await Pipeline(settings, Store(db_path), client).number_check("0482-2258058")

    assert len(client.queries) == 2
    assert client.queries[0] == "04822258058"
    assert client.queries[1] == "04822 258058"
    assert len(result.domains["directory.test"]) == 1


@pytest.mark.asyncio
async def test_number_check_retries_a_mobile_with_its_correct_local_format(db_path):
    class Client:
        def __init__(self):
            self.queries: list[str] = []
            self.params: list[dict] = []

        async def search(self, engine, params, _budget, **_kwargs):
            self.queries.append(str(params["q"]))
            self.params.append(params)
            body = {"search_metadata": {"status": "Success"}, "organic_results": []}
            if params["q"] == "94000 63494":
                body["organic_results"] = [
                    {
                        "position": 1,
                        "title": "AIC-IIITKottayam Incubation Centre",
                        "link": "https://centre.iiitkottayam.ac.in/contact",
                        "snippet": "Phone/Whatsapp: +91-9400063494",
                    }
                ]
            return SearchResult(
                len(self.queries), str(len(self.queries)), engine, body, None, False
            )

    client = Client()
    settings = Settings(serpapi_mode="live", serpapi_api_key="test-key")
    result = await Pipeline(settings, Store(db_path), client).number_check("9400063494")

    assert client.queries == ["9400063494", "94000 63494"]
    assert client.params[0]["filter"] == "0"
    assert client.params[0]["nfpr"] == "1"
    assert "iiitkottayam.ac.in" in result.domains


@pytest.mark.asyncio
async def test_number_check_uses_contact_context_when_google_returns_unrelated_pages(db_path):
    class Client:
        def __init__(self):
            self.queries: list[str] = []

        async def search(self, engine, params, _budget, **_kwargs):
            self.queries.append(str(params["q"]))
            body = {"search_metadata": {"status": "Success"}, "organic_results": []}
            if params["q"] == '"94000 63494" contact':
                body["organic_results"] = [
                    {
                        "title": "AIC-IIITKottayam Incubation Centre",
                        "link": "https://centre.iiitkottayam.ac.in/contact",
                        "snippet": "Phone/Whatsapp +91-9400063494",
                    }
                ]
            return SearchResult(
                len(self.queries), str(len(self.queries)), engine, body, None, False
            )

    client = Client()
    settings = Settings(serpapi_mode="live", serpapi_api_key="test-key")
    result = await Pipeline(settings, Store(db_path), client).number_check("9400063494")

    assert client.queries == [
        "9400063494",
        "94000 63494",
        '"94000 63494" contact',
    ]
    assert "iiitkottayam.ac.in" in result.domains


@pytest.mark.asyncio
async def test_number_check_reuses_saved_brand_evidence_when_new_search_is_empty(db_path):
    store = Store(db_path)
    canonical = "+914822216381"
    store.save_check(
        {
            "id": "previous-brand-check",
            "mode": "brand",
            "brand_id": "sbi-valavoor",
            "brand_text": "SBI Bank Valavoor",
            "city": "Pala, Kerala, India",
            "lang": "en",
            "started_at": "2026-10-10T10:00:00+00:00",
            "finished_at": "2026-10-10T10:01:00+00:00",
            "searches_used": 1,
            "skipped": [],
        },
        [
            Sighting(
                canonical=canonical,
                raw="04822 216381",
                kind=normalise_phone("04822 216381").kind,
                surface="ORGANIC",
                json_path="organic_results[0].snippet",
                title="STATE BANK OF INDIA | Kottayam District",
                link="https://kottayam.nic.in/public-utility/sbi",
                domain="kottayam.nic.in",
                position=1,
                receipt_id=7,
                item={},
            )
        ],
        {},
        [],
    )

    class Client:
        async def search(self, engine, _params, _budget, **_kwargs):
            return SearchResult(
                9,
                "empty",
                engine,
                {"search_metadata": {"status": "Success"}, "organic_results": []},
                None,
                False,
            )

    settings = Settings(serpapi_mode="live", serpapi_api_key="test-key")
    result = await Pipeline(settings, store, Client()).number_check("04822 216381")

    assert result.canonical == canonical
    assert "kottayam.nic.in" in result.domains


@pytest.mark.asyncio
async def test_number_check_passes_an_optional_location_to_each_number_search(db_path):
    class Client:
        def __init__(self):
            self.params: list[dict] = []

        async def search(self, engine, params, _budget, **_kwargs):
            self.params.append(params)
            return SearchResult(
                1,
                "receipt",
                engine,
                {
                    "search_metadata": {"status": "Success"},
                    "organic_results": [
                        {
                            "title": "Local contact",
                            "link": "https://example.test/contact",
                            "snippet": "Call +91 9400063494",
                        }
                    ],
                },
                None,
                False,
            )

    client = Client()
    settings = Settings(serpapi_mode="live", serpapi_api_key="test-key")
    result = await Pipeline(settings, Store(db_path), client).number_check(
        "9400063494", location="Kottayam, Kerala, India"
    )

    assert "example.test" in result.domains
    assert client.params[0]["q"] == "9400063494"
    assert client.params[0]["location"] == "Kottayam, Kerala, India"


@pytest.mark.asyncio
async def test_number_check_uses_brand_words_when_google_treats_area_code_as_an_id(
    db_path, monkeypatch
):
    async def unavailable_page(_url, _store):
        raise ValueError("fixture uses the stored snippet")

    monkeypatch.setattr("sahi.reference._contact_body", unavailable_page)

    class Client:
        def __init__(self):
            self.queries: list[str] = []

        async def search(self, engine, params, _budget, **_kwargs):
            query = str(params["q"])
            self.queries.append(query)
            body = {"search_metadata": {"status": "Success"}, "organic_results": []}
            if query == 'SBI Bank Valavoor "04822-258058"':
                body["organic_results"] = [
                    {
                        "position": 1,
                        "title": "State Bank of India Valavoor",
                        "link": "https://tribal.gov.in/branch.pdf",
                        "snippet": "STATE BANK OF INDIA VALAVOOR Branch Phone: 04822-258058",
                    }
                ]
            return SearchResult(
                len(self.queries), str(len(self.queries)), engine, body, None, False
            )

    client = Client()
    settings = Settings(serpapi_mode="live", serpapi_api_key="test-key")
    result = await Pipeline(settings, Store(db_path), client).number_check(
        "0482-2258058", Brand(id="sbi-valavoor", name="SBI Bank Valavoor")
    )

    assert 'SBI Bank Valavoor "04822-258058"' in client.queries
    assert "tribal.gov.in" in result.domains
