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


@pytest.mark.asyncio
async def test_trusted_reference_accepts_allowlisted_statutory_regulator(monkeypatch):
    async def fake_page(url, _store):
        assert url == "https://www.sebi.gov.in/toll-free-helpline.html"
        return "SEBI investor helpline: 1800-266-7575"

    monkeypatch.setattr("sahi.reference._contact_body", fake_page)
    search = {
        "organic_results": [
            {
                "title": "SEBI Helpline",
                "snippet": "SEBI investor toll free helpline 1800-266-7575",
                "link": "https://www.sebi.gov.in/toll-free-helpline.html",
            }
        ]
    }

    references, failures = await build_public_directory_references(
        Brand(id="sebi", name="SEBI"), search
    )

    assert failures == []
    assert [(item.canonical, item.source_kind) for item in references] == [
        ("18002667575", "STATUTORY_REGULATOR")
    ]


@pytest.mark.asyncio
async def test_trusted_government_search_snippet_is_a_reference_when_identity_matches(monkeypatch):
    async def unavailable_page(_url, _store):
        raise ValueError("PDF body unavailable")

    monkeypatch.setattr("sahi.reference._contact_body", unavailable_page)
    brand = Brand(id="sbi-valavoor", name="SBI Bank Valavoor")
    results = {
        "organic_results": [
            {
                "title": "public financial",
                "link": "https://tribal.gov.in/orders/branch.pdf",
                "snippet": (
                    "STATE BANK OF INDIA VALAVOOR. Branch Phone: 04822-258058. "
                    "IFSC Code: SBIN0070539."
                ),
            }
        ]
    }

    references, failures = await build_public_directory_references(brand, results)

    assert [item.canonical for item in references] == ["+914822258058"]
    assert references[0].source_kind == "GOVERNMENT_DIRECTORY"
    assert failures


@pytest.mark.asyncio
async def test_broad_government_directory_page_does_not_import_unrelated_numbers(monkeypatch):
    async def broad_page(_url, _store):
        return "STATE BANK OF INDIA VALAVOOR " + " ".join(
            f"Phone 011-2345-{number:04d}" for number in range(1000, 1007)
        )

    monkeypatch.setattr("sahi.reference._contact_body", broad_page)
    results = {
        "organic_results": [
            {
                "title": "State Bank of India Valavoor",
                "link": "https://kottayam.nic.in/public-utility-category/banks/",
                "snippet": "SBI Bank Valavoor Phone 04822-258058",
            }
        ]
    }

    references, failures = await build_public_directory_references(
        Brand(id="sbi-valavoor", name="SBI Bank Valavoor"), results
    )

    assert [item.canonical for item in references] == ["+914822258058"]
    assert any("too broad" in failure for failure in failures)
