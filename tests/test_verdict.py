import pytest

from sahi.verdict import Verdict, decide


@pytest.mark.parametrize(
    ("references", "signals", "expected"),
    [
        (set(), {"FOREIGN_NUMBER": True, "NO_OFFICIAL_SOURCE": True}, Verdict.CANNOT_VERIFY),
        ({"+919876543210"}, {"FOREIGN_NUMBER": True}, Verdict.OFFICIAL_MATCH),
        ({"1800123456"}, {}, Verdict.NOT_CORROBORATED),
        ({"1800123456"}, {"TYPE_MISMATCH": True}, Verdict.NOT_CORROBORATED),
        (
            {"1800123456"},
            {"TYPE_MISMATCH": True, "NO_OFFICIAL_SOURCE": True},
            Verdict.CONFLICT,
        ),
    ],
)
def test_decision_table_boundaries(references, signals, expected):
    decision = decide("+919876543210", references, signals)
    assert decision.verdict == expected


def test_reasons_are_fixed_and_signal_order_is_stable():
    decision = decide(
        "+919876543210",
        {"1800123456"},
        {"NO_OFFICIAL_SOURCE": True, "TYPE_MISMATCH": True},
    )
    assert decision.reasons == (
        "Checked the brand's published reference numbers",
        "Number type differs from every published reference number",
        "No result on the official domain showed this number",
    )


def test_public_directory_match_is_explained_as_public_authority_evidence():
    decision = decide(
        "+914822258058",
        {"+914822258058"},
        {},
        {"+914822258058": {"GOVERNMENT_DIRECTORY"}},
    )
    assert decision.verdict == Verdict.OFFICIAL_MATCH
    assert decision.reasons == ("Found in a matching Indian public-authority directory",)


def test_regulator_match_is_explained_as_regulator_evidence():
    decision = decide(
        "18002667575",
        {"18002667575"},
        {},
        {"18002667575": {"STATUTORY_REGULATOR"}},
    )
    assert decision.verdict == Verdict.OFFICIAL_MATCH
    assert decision.reasons == (
        "Found on a matching statutory-regulator or national-infrastructure page",
    )
