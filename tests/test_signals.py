from sahi.extract.phones import PhoneClass
from sahi.extract.walker import Sighting
from sahi.reference import ReferenceNumber
from sahi.signals import compute_signals


def sighting(surface, *, domain=None, website=None, unclaimed=False):
    item = {"website": website, "unclaimed_listing": unclaimed}
    return Sighting(
        canonical="+919876543210",
        raw="98765 43210",
        kind=PhoneClass.MOBILE,
        surface=surface,
        json_path="local_results[0].phone",
        title="Listing",
        link=website,
        domain=domain,
        position=1,
        receipt_id=1,
        item=item,
    )


def test_computes_all_independent_signals():
    references = [
        ReferenceNumber(
            "1800123456", PhoneClass.TOLL_FREE, "SEED", "https://example-air.test/contact"
        )
    ]
    sightings = [
        sighting("MAPS_LISTING", website=None, unclaimed=True),
        sighting("AD", domain="wrong.test", website="https://wrong.test"),
    ]
    reviews = [
        {
            "reviews": [
                {"snippet": "Fake number, asked for OTP", "iso_date": "2026-10-01", "rating": 1}
            ]
        }
    ]
    number_results = [
        {"organic_results": [{"link": "https://directory.test/page", "snippet": "number"}]}
    ]

    signals = compute_signals(
        "+919876543210",
        PhoneClass.MOBILE,
        references,
        sightings,
        "example-air.test",
        number_results=number_results,
        review_results=reviews,
        warning_terms=["fake number", "asked for OTP"],
        number_search_ran=True,
    )

    assert set(signals) == {
        "TYPE_MISMATCH",
        "LISTING_DOMAIN_MISMATCH",
        "UNCLAIMED_LISTING",
        "AD_DOMAIN_MISMATCH",
        "REVIEW_WARNINGS",
        "NO_OFFICIAL_SOURCE",
    }
    assert signals["REVIEW_WARNINGS"]["count"] == 1
    assert signals["REVIEW_WARNINGS"]["newest_date"] == "2026-10-01"


def test_foreign_number_signal_is_independent():
    signals = compute_signals(
        "+12025550147",
        PhoneClass.FOREIGN,
        [],
        [],
        "example-air.test",
    )
    assert signals == {"FOREIGN_NUMBER": {"class": "FOREIGN"}}


def test_review_warning_terms_match_whole_phrases_only():
    signals = compute_signals(
        "+919876543210",
        PhoneClass.MOBILE,
        [],
        [],
        "example-air.test",
        review_results=[{"reviews": [{"snippet": "The fraudster was reported"}]}],
        warning_terms=["fraud"],
    )

    assert "REVIEW_WARNINGS" not in signals
