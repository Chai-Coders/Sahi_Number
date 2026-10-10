from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from enum import StrEnum


class Verdict(StrEnum):
    OFFICIAL_MATCH = "OFFICIAL_MATCH"
    NOT_CORROBORATED = "NOT_CORROBORATED"
    CONFLICT = "CONFLICT"
    CANNOT_VERIFY = "CANNOT_VERIFY"


SIGNAL_REASONS = {
    "TYPE_MISMATCH": "Number type differs from every published reference number",
    "LISTING_DOMAIN_MISMATCH": "Listing website does not match the official domain",
    "UNCLAIMED_LISTING": "The Maps listing is marked unclaimed",
    "AD_DOMAIN_MISMATCH": "Ad landing domain does not match the official domain",
    "REVIEW_WARNINGS": "Recent listing reviews contain warning phrases",
    "FOREIGN_NUMBER": "The number uses a non-Indian country code",
    "NO_OFFICIAL_SOURCE": "No result on the official domain showed this number",
}


@dataclass(frozen=True, slots=True)
class Decision:
    verdict: Verdict
    reasons: tuple[str, ...]


def decide(
    canonical: str,
    reference_set: Collection[str],
    signals: Mapping[str, object],
    reference_sources: Mapping[str, Collection[str]] | None = None,
) -> Decision:
    if not reference_set:
        return Decision(Verdict.CANNOT_VERIFY, ("No published reference number was available",))
    if canonical in reference_set:
        sources = set((reference_sources or {}).get(canonical, ()))
        if sources == {"GOVERNMENT_DIRECTORY"}:
            return Decision(
                Verdict.OFFICIAL_MATCH,
                ("Found in a matching Indian public-authority directory",),
            )
        if sources == {"STATUTORY_REGULATOR"}:
            return Decision(
                Verdict.OFFICIAL_MATCH,
                ("Found on a matching statutory-regulator or national-infrastructure page",),
            )
        return Decision(Verdict.OFFICIAL_MATCH, ("Found in the brand's published references",))
    reasons = ["Checked the brand's published reference numbers"]
    reasons.extend(
        SIGNAL_REASONS[signal]
        for signal in SIGNAL_REASONS
        if signal in signals and bool(signals[signal])
    )
    verdict = Verdict.CONFLICT if len(signals) >= 2 else Verdict.NOT_CORROBORATED
    return Decision(verdict, tuple(reasons))
