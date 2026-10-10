import json
from pathlib import Path

from sahi.config import Settings
from sahi.serp.client import scrub_payload
from sahi.store import Store


def test_scrub_removes_api_keys_from_nested_urls_and_parameters():
    payload = {
        "search_parameters": {"q": "help", "api_key": "secret-value"},
        "link": "https://example.test/path?x=1&api_key=secret-value&y=2",
        "nested": ["https://example.test/?api_key=another", "ordinary text"],
        "plain": "api_key=plain-secret",
    }

    scrubbed = scrub_payload(payload)
    rendered = json.dumps(scrubbed)

    assert "secret-value" not in rendered
    assert "another" not in rendered
    assert "plain-secret" not in rendered
    assert "api_key" not in rendered
    assert "x=1" in rendered and "y=2" in rendered


def test_scrub_drops_reviewer_identity_but_keeps_minimal_review_evidence():
    payload = {
        "reviews": [
            {
                "user": {"name": "Private Person", "link": "https://profiles.test/person"},
                "snippet": "asked for OTP",
                "rating": 1,
                "iso_date": "2026-10-01",
                "link": "https://maps.test/review",
                "likes": 99,
                "response": {"snippet": "Private owner response"},
            }
        ]
    }

    scrubbed = scrub_payload(payload)

    assert "user" not in scrubbed["reviews"][0]
    assert "likes" not in scrubbed["reviews"][0]
    assert "response" not in scrubbed["reviews"][0]
    assert scrubbed["reviews"][0]["snippet"] == "asked for OTP"


def test_repository_fixtures_contain_no_configured_key_or_reviewer_objects():
    settings = Settings()
    for path in Path("tests/fixtures").rglob("*.json"):
        text = path.read_text()
        assert "api_key=" not in text
        assert '"user"' not in text
        if settings.serpapi_api_key:
            assert settings.serpapi_api_key not in text


def test_database_dump_contains_no_key_material_or_reviewer_identity(db_path):
    store = Store(db_path)
    secret = "test-secret-never-store"
    body = scrub_payload(
        {
            "link": f"https://example.test/?api_key={secret}",
            "reviews": [
                {
                    "user": {"name": "Private Person"},
                    "snippet": "asked for OTP",
                    "rating": 1,
                }
            ],
        }
    )
    store.add_search("key", "google_maps_reviews", {}, "receipt", "Success", False, body)

    with store.connect() as connection:
        dump = "\n".join(connection.iterdump())

    assert secret not in dump
    assert "api_key=" not in dump
    assert "Private Person" not in dump
