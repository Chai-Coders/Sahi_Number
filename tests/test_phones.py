import pytest

from sahi.extract.phones import (
    PhoneClass,
    discovery_query,
    find_phones,
    normalise_phone,
    primary_search_query,
)


@pytest.mark.parametrize(
    ("text", "canonical", "kind"),
    [
        ("Call 9876543210", "+919876543210", PhoneClass.MOBILE),
        ("Call +91 98765 43210", "+919876543210", PhoneClass.MOBILE),
        ("Call 91-98765-43210", "+919876543210", PhoneClass.MOBILE),
        ("Call 09876543210", "+919876543210", PhoneClass.MOBILE),
        ("कॉल ९८७६५४३२१०", "+919876543210", PhoneClass.MOBILE),
        ("কল ৯৮৭৬৫৪৩২১০", "+919876543210", PhoneClass.MOBILE),
        ("அழைக்க ௯௮௭௬௫௪௩௨௧௦", "+919876543210", PhoneClass.MOBILE),
        ("కాల్ ౯౮౭౬౫౪౩౨౧౦", "+919876543210", PhoneClass.MOBILE),
        ("Call 1800 123 456", "1800123456", PhoneClass.TOLL_FREE),
        ("Call 1800-123-4567", "18001234567", PhoneClass.TOLL_FREE),
        ("Toll free: १८०० १२३ ४५६", "1800123456", PhoneClass.TOLL_FREE),
        ("Helpline 1860 123 4567", "18601234567", PhoneClass.UAN),
        ("Dial १८६०-१२३-४५६७", "18601234567", PhoneClass.UAN),
        ("Office 011 2345 6789", "+911123456789", PhoneClass.LANDLINE),
        ("Office +91 11 2345 6789", "+911123456789", PhoneClass.LANDLINE),
        ("Office 080 2345 6789", "+918023456789", PhoneClass.LANDLINE),
        ("Call +1 202 555 0147", "+12025550147", PhoneClass.FOREIGN),
        ("Call +44 20 7946 0958", "+442079460958", PhoneClass.FOREIGN),
        ("Dial 1930 now", "1930", PhoneClass.SHORT_CODE),
        ("Helpline: 112", "112", PhoneClass.SHORT_CODE),
        ("कॉल १०९१", "1091", PhoneClass.SHORT_CODE),
        ("डायल १००", "100", PhoneClass.SHORT_CODE),
        ("हेल्पलाइन १०८", "108", PhoneClass.SHORT_CODE),
        ("Call 181", "181", PhoneClass.SHORT_CODE),
        ("Call 123456", "123456", PhoneClass.SHORT_CODE),
    ],
)
def test_accepts_and_classifies_indian_and_explicit_foreign_numbers(text, canonical, kind):
    matches = find_phones(text)
    assert [(match.canonical, match.kind) for match in matches] == [(canonical, kind)]


@pytest.mark.parametrize(
    "text",
    [
        "Mumbai PIN 400001",
        "Delhi 110001",
        "Founded in 2024",
        "₹ 9876543210",
        "Rs 9876543210",
        "INR 9876543210",
        "Order ID AB9876543210",
        "PNR 9876543210",
        "ticket9876543210x",
        "123456789012",
        "1800 12345",
        "1860 123 456",
        "987654321",
        "5987654321",
        "Reference number 1930",
        "The rating was 1800",
        "gps 19.0760,72.8777",
        "Price 1,800 only",
        "ID 123456789012345",
        "Code 123456",
        "Year 1999",
    ],
)
def test_rejects_numeric_lookalikes(text):
    assert find_phones(text) == []


def test_finds_several_numbers_without_duplicates():
    matches = find_phones("Call 1800 123 456 or +91 98765 43210; mobile 9876543210")
    assert [match.canonical for match in matches] == ["1800123456", "+919876543210"]


def test_short_code_calling_cue_must_be_in_the_same_sentence():
    assert find_phones("Call the office tomorrow. Reference number 1930") == []


def test_search_variants_are_quoted_and_human_readable():
    match = normalise_phone("1800-123-4567")
    assert match is not None
    assert match.search_variants == (
        '"18001234567"',
        '"1800 123 4567"',
        '"1800-123-4567"',
    )


def test_indian_landline_has_a_human_readable_display_format():
    match = normalise_phone("0482-2258058")
    assert match is not None
    assert match.canonical == "+914822258058"
    assert match.kind == PhoneClass.LANDLINE
    assert match.display == "+91 4822 258 058"
    assert '"04822 258058"' in match.search_variants
    assert '"04822-258058"' in match.search_variants


def test_primary_number_search_uses_the_compact_number_the_person_entered():
    match = normalise_phone("9400063494")

    assert match is not None
    assert primary_search_query(match) == "9400063494"


def test_mobile_discovery_search_does_not_add_a_landline_trunk_prefix():
    match = normalise_phone("9400063494")

    assert match is not None
    assert discovery_query(match) == "94000 63494"
