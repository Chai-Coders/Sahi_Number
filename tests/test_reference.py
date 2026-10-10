import pytest

from sahi.reference import Brand, build_public_directory_references, build_reference_set
from sahi.store import Store


@pytest.mark.asyncio
async def test_reference_accepts_only_seed_and_same_domain_search_results():
    brand = Brand(
        id="example-air",
        name="Example Air",
        official_domain="example-air.test",
        domain_verified=True,
        contact_urls=(),
        official_numbers=(
            {
                "number": "1800 123 456",
                "source_url": "https://example-air.test/contact",
                "verified_on": "2026-10-10",
            },
        ),
    )
    official_search = {
        "organic_results": [
            {
                "link": "https://example-air.test/support",
                "snippet": "Helpline 1860 123 4567",
            },
            {"link": "https://impostor.test", "snippet": "Call 98765 43210"},
        ]
    }

    references, failures = await build_reference_set(brand, official_search)

    assert {item.canonical for item in references} == {"1800123456", "18601234567"}
    assert failures == []


@pytest.mark.asyncio
async def test_reference_is_empty_without_an_official_domain():
    brand = Brand(id="free", name="Free text", official_domain=None)
    references, failures = await build_reference_set(brand, {})
    assert references == []
    assert failures == ["No official domain is configured"]


@pytest.mark.asyncio
async def test_contact_page_cache_expires_after_24_hours(db_path, monkeypatch):
    from datetime import UTC, datetime, timedelta

    class Response:
        url = "https://example-air.test/contact"
        text = "<p>Call 1800 765 432</p>"

        def raise_for_status(self):
            return None

    class Client:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, url, follow_redirects):
            return Response()

    monkeypatch.setattr("sahi.reference.httpx.AsyncClient", Client)
    store = Store(db_path)
    with store.connect() as connection:
        connection.execute(
            "INSERT INTO contact_cache(url, fetched_at, body) VALUES (?, ?, ?)",
            (
                "https://example-air.test/contact",
                (datetime.now(UTC) - timedelta(hours=25)).isoformat(),
                "Call 1800 111 111",
            ),
        )
    brand = Brand(
        id="example-air",
        name="Example Air",
        official_domain="example-air.test",
        contact_urls=("https://example-air.test/contact",),
    )

    references, failures = await build_reference_set(brand, {}, store)

    assert failures == []
    assert {item.canonical for item in references} == {"1800765432"}


@pytest.mark.asyncio
async def test_public_directory_reference_requires_indian_authority_and_brand_match(monkeypatch):
    async def fake_page(url, _store):
        assert url == "https://kottayam.nic.in/en/public-utility/state-bank-of-india-132/"
        return "STATE BANK OF INDIA VALAVOOR Phone: 0482-2258058"

    monkeypatch.setattr("sahi.reference._contact_body", fake_page)
    brand = Brand(id="free-sbi-valavoor", name="SBI Bank Valavoor")
    search = {
        "organic_results": [
            {
                "title": "State Bank of India - Valavoor",
                "snippet": "Bank Valavoor phone 0482-2258058",
                "link": "https://kottayam.nic.in/en/public-utility/state-bank-of-india-132/",
            },
            {
                "title": "SBI Bank Valavoor",
                "snippet": "Phone 0482-2258058",
                "link": "https://directory.example.test/sbi-valavoor",
            },
        ]
    }

    references, failures = await build_public_directory_references(brand, search)

    assert failures == []
    assert [(item.canonical, item.source_kind) for item in references] == [
        ("+914822258058", "GOVERNMENT_DIRECTORY")
    ]
