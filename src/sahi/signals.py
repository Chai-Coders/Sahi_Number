from __future__ import annotations

import re
from typing import Any

from sahi.extract.phones import PhoneClass
from sahi.extract.walker import Sighting, registrable_domain
from sahi.reference import ReferenceNumber

SERVICE_CLASSES = {PhoneClass.TOLL_FREE, PhoneClass.UAN, PhoneClass.SHORT_CODE}


def compute_signals(
    canonical: str,
    kind: PhoneClass,
    references: list[ReferenceNumber],
    sightings: list[Sighting],
    official_domain: str | None,
    *,
    number_results: list[dict[str, Any]] | None = None,
    review_results: list[dict[str, Any]] | None = None,
    warning_terms: list[str] | None = None,
    number_search_ran: bool = False,
) -> dict[str, dict[str, Any]]:
    signals: dict[str, dict[str, Any]] = {}
    if (
        kind == PhoneClass.MOBILE
        and references
        and all(reference.kind in SERVICE_CLASSES for reference in references)
    ):
        signals["TYPE_MISMATCH"] = {
            "number_class": kind.value,
            "reference_classes": sorted({reference.kind.value for reference in references}),
        }
    official = registrable_domain(official_domain)
    listing_mismatches = []
    for item in sightings:
        if item.surface not in {"MAPS_LISTING", "LOCAL_PACK"}:
            continue
        website = item.item.get("website")
        if not website or registrable_domain(website) != official:
            listing_mismatches.append(
                {"title": item.title, "website": website, "receipt_id": item.receipt_id}
            )
        if item.item.get("unclaimed_listing"):
            signals["UNCLAIMED_LISTING"] = {
                "title": item.title,
                "receipt_id": item.receipt_id,
            }
    if listing_mismatches:
        signals["LISTING_DOMAIN_MISMATCH"] = {"listings": listing_mismatches}
    ad_mismatches = [
        {"domain": item.domain, "receipt_id": item.receipt_id}
        for item in sightings
        if item.surface == "AD" and item.domain != official
    ]
    if ad_mismatches:
        signals["AD_DOMAIN_MISMATCH"] = {"ads": ad_mismatches}
    terms = [term.casefold() for term in (warning_terms or [])]

    def has_warning(text: str) -> bool:
        return any(
            re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text, flags=re.IGNORECASE)
            for term in terms
        )

    matched_reviews = []
    for result in review_results or []:
        for review in result.get("reviews", []):
            text = " ".join(
                str(review.get(key, "")) for key in ("snippet", "extracted_snippet")
            ).casefold()
            if has_warning(text):
                matched_reviews.append(review)
    if matched_reviews:
        dates = [
            str(review.get("iso_date")) for review in matched_reviews if review.get("iso_date")
        ]
        signals["REVIEW_WARNINGS"] = {
            "count": len(matched_reviews),
            "newest_date": max(dates) if dates else None,
        }
    if kind == PhoneClass.FOREIGN:
        signals["FOREIGN_NUMBER"] = {"class": kind.value}
    if number_search_ran:
        official_seen = any(
            registrable_domain(result.get("link")) == official
            for body in number_results or []
            for result in body.get("organic_results", [])
        )
        if not official_seen:
            signals["NO_OFFICIAL_SOURCE"] = {"official_domain": official}
    return signals
