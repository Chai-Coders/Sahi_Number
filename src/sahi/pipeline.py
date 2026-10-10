from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

import yaml

from sahi.config import ROOT, Settings
from sahi.extract.phones import PhoneClass, discovery_query, primary_search_query
from sahi.extract.walker import Sighting, registrable_domain, walk_response
from sahi.reference import (
    Brand,
    ReferenceNumber,
    build_public_directory_references,
    build_reference_set,
)
from sahi.serp.account import resolve_location
from sahi.serp.client import (
    BudgetExceeded,
    ReplayMiss,
    SearchBudget,
    SearchResult,
    SerpApiError,
    SerpClient,
)
from sahi.serp.engines import (
    fetch_reviews,
    redeem_ai_overview,
    search_ads,
    search_brand_identity,
    search_helpline,
    search_maps,
    search_number,
    search_number_contextual,
    search_number_discovery,
    search_number_with_brand,
    search_official_site,
    search_public_directory,
)
from sahi.signals import compute_signals
from sahi.store import Store
from sahi.verdict import Verdict, decide


@dataclass(frozen=True, slots=True)
class NumberResult:
    canonical: str
    kind: PhoneClass
    verdict: Verdict
    reasons: tuple[str, ...]
    signals: dict[str, dict[str, Any]]
    sightings: tuple[Sighting, ...]


@dataclass(frozen=True, slots=True)
class CheckResult:
    id: str
    brand: Brand
    city: str
    lang: str
    reference_numbers: tuple[ReferenceNumber, ...]
    numbers: tuple[NumberResult, ...]
    skipped: tuple[str, ...]
    searches_used: int


@dataclass(frozen=True, slots=True)
class NumberCheckResult:
    id: str
    canonical: str
    kind: PhoneClass
    domains: dict[str, tuple[Sighting, ...]]
    verdict: Verdict | None
    reasons: tuple[str, ...]
    searches_used: int


class Pipeline:
    def __init__(self, settings: Settings, store: Store, client: SerpClient):
        self.settings = settings
        self.store = store
        self.client = client

    async def brand_check(
        self,
        brand: Brand,
        city: str,
        lang: str,
        *,
        fresh: bool = False,
        check_id: str | None = None,
    ) -> CheckResult:
        check_id = check_id or uuid.uuid4().hex
        started = datetime.now(UTC)
        budget = SearchBudget(self.settings.max_searches_per_check)
        skipped: list[str] = []
        queries = yaml.safe_load((ROOT / "seeds" / "queries.yaml").read_text())
        templates = queries.get(lang) or queries["en"]
        query = templates[0].format(brand=brand.name)
        search_location: str | None = city
        latitude: float | None = None
        longitude: float | None = None
        if self.settings.effective_mode == "live":
            try:
                resolved = await resolve_location(city, self.store)
            except Exception as error:
                skipped.append(f"Location resolution skipped: {error}")
            else:
                if resolved:
                    search_location = str(resolved["canonical_name"])
                    latitude = resolved.get("lat")
                    longitude = resolved.get("lng")
                else:
                    search_location = None
                    query = f"{query} {city}"
                    skipped.append(
                        "No canonical SerpApi location matched the place; "
                        "running a country-wide query with the place words instead"
                    )

        async def attempt(
            label: str, call: Callable[[], Awaitable[SearchResult]] | None
        ) -> SearchResult | None:
            if call is None:
                skipped.append(f"{label} disabled by configuration")
                self.store.save_check_step(check_id, label, "skipped", "Disabled by configuration")
                return None
            self.store.save_check_step(check_id, label, "running")
            try:
                result = await call()
                self.store.link_check_search(check_id, result.search_id, label)
                self.store.save_check_step(
                    check_id,
                    label,
                    "complete",
                    f"Receipt {result.search_id}{' (cache)' if result.cached else ''}",
                )
                return result
            except (BudgetExceeded, ReplayMiss, SerpApiError) as error:
                skipped.append(f"{label} skipped: {error}")
                self.store.save_check_step(check_id, label, "skipped", str(error))
                return None

        initial = await asyncio.gather(
            attempt(
                "Search",
                lambda: search_helpline(
                    self.client,
                    budget,
                    query,
                    search_location,
                    lang,
                    self.settings,
                    fresh=fresh,
                ),
            ),
            (
                attempt(
                    "Official-site search",
                    lambda: search_official_site(
                        self.client, budget, brand.official_domain or "", fresh=fresh
                    ),
                )
                if brand.official_domain
                else asyncio.sleep(0, result=None)
            ),
            attempt(
                "Maps",
                lambda: search_maps(
                    self.client,
                    budget,
                    f"{brand.name} {city}" if search_location is None else brand.name,
                    search_location,
                    lang,
                    latitude,
                    longitude,
                ),
            ),
            attempt(
                "Ads",
                (lambda: search_ads(self.client, budget, query, search_location, lang))
                if self.settings.enable_ads
                else None,
            ),
            attempt(
                "Public-directory search",
                lambda: search_public_directory(
                    self.client,
                    budget,
                    f"{brand.name} {city}" if search_location is None else brand.name,
                    search_location,
                    fresh=fresh,
                ),
            ),
        )
        helpline_result, official_result, maps_result, ads_result, directory_result = initial

        effective_brand = brand
        if not brand.official_domain and helpline_result:
            knowledge_graph = helpline_result.body.get("knowledge_graph", {})
            website = knowledge_graph.get("website") if isinstance(knowledge_graph, dict) else None
            candidate_domain = registrable_domain(str(website)) if website else None
            if candidate_domain:
                effective_brand = replace(
                    brand, official_domain=candidate_domain, domain_verified=False
                )
                skipped.append(f"Using unconfirmed domain from knowledge graph: {candidate_domain}")
                official_result = await attempt(
                    "Official-site search",
                    lambda: search_official_site(
                        self.client, budget, candidate_domain, fresh=fresh
                    ),
                )

        # SerpApi's AI Overview token is short-lived, so redeem it before doing
        # any slower reference-page work. A missing token is a normal outcome.
        collected_results = [result for result in initial if result]
        if official_result and official_result not in collected_results:
            collected_results.append(official_result)
        ai_overview = helpline_result.body.get("ai_overview", {}) if helpline_result else {}
        page_token = ai_overview.get("page_token") if isinstance(ai_overview, dict) else None
        if self.settings.enable_ai_overview and page_token:
            ai_result = await attempt(
                "AI Overview",
                lambda: redeem_ai_overview(self.client, budget, str(page_token)),
            )
            if ai_result:
                collected_results.append(ai_result)
        elif not self.settings.enable_ai_overview:
            skipped.append("AI Overview disabled by configuration")
            self.store.save_check_step(
                check_id, "AI Overview", "skipped", "Disabled by configuration"
            )
        else:
            self.store.save_check_step(
                check_id, "AI Overview", "not_available", "No token in the search response"
            )

        references, reference_failures = await build_reference_set(
            effective_brand, official_result.body if official_result else {}, self.store
        )
        trusted_results = {
            "organic_results": [
                *((directory_result.body if directory_result else {}).get("organic_results", [])),
                *((helpline_result.body if helpline_result else {}).get("organic_results", [])),
            ]
        }
        directory_references, directory_failures = await build_public_directory_references(
            effective_brand, trusted_results, self.store
        )
        references.extend(directory_references)
        self.store.save_brand_references(effective_brand, references)
        skipped.extend(reference_failures)
        skipped.extend(directory_failures)
        self.store.save_check_step(
            check_id,
            "Official references",
            "complete" if references else "not_available",
            f"{len(references)} published number(s)",
        )
        sightings: list[Sighting] = []
        for result in collected_results:
            sightings.extend(walk_response(result.body, result.search_id, result.engine))
        by_number: dict[str, list[Sighting]] = {}
        for item in sightings:
            by_number.setdefault(item.canonical, []).append(item)
        reference_values = {item.canonical for item in references}
        reference_sources: dict[str, set[str]] = {}
        for item in references:
            reference_sources.setdefault(item.canonical, set()).add(item.source_kind)

        number_bodies: dict[str, list[dict[str, Any]]] = {}
        for canonical, _items in sorted(
            by_number.items(), key=lambda pair: min(item.position or 999 for item in pair[1])
        ):
            if canonical in reference_values or len(number_bodies) >= 2:
                continue
            from sahi.extract.phones import normalise_phone

            normalized = normalise_phone(canonical)
            if not normalized:
                continue
            result = await attempt(
                f"Number search for {canonical}",
                lambda normalized=normalized: search_number(
                    self.client, budget, primary_search_query(normalized)
                ),
            )
            if result:
                number_bodies[canonical] = [result.body]
                sightings.extend(walk_response(result.body, result.search_id, result.engine))

        # Number-search and AI responses can introduce new numbers. Rebuild the
        # grouping so those sightings are included in the final verdict table.
        by_number = {}
        for item in sightings:
            by_number.setdefault(item.canonical, []).append(item)

        review_bodies: dict[str, list[dict[str, Any]]] = {}
        reviewed_data_ids: set[str] = set()
        if self.settings.enable_reviews:
            for canonical, items in by_number.items():
                if canonical in reference_values:
                    continue
                data_id = next(
                    (
                        str(item.item["data_id"])
                        for item in items
                        if item.surface in {"MAPS_LISTING", "LOCAL_PACK"}
                        and item.item.get("data_id")
                    ),
                    None,
                )
                if not data_id or data_id in reviewed_data_ids:
                    continue
                review_result = await attempt(
                    f"Reviews for {canonical}",
                    lambda data_id=data_id: fetch_reviews(self.client, budget, data_id, lang),
                )
                reviewed_data_ids.add(data_id)
                if review_result:
                    review_bodies.setdefault(canonical, []).append(review_result.body)
                break
            if not reviewed_data_ids:
                self.store.save_check_step(
                    check_id,
                    "Reviews",
                    "not_available",
                    "No eligible Maps listing carried a data_id",
                )
        else:
            skipped.append("Reviews disabled by configuration")
            self.store.save_check_step(check_id, "Reviews", "skipped", "Disabled by configuration")
        lexicon = yaml.safe_load((ROOT / "seeds" / "lexicon.yaml").read_text())
        warning_terms = [term for values in lexicon.values() for term in values]
        results: list[NumberResult] = []
        all_signals: dict[str, dict[str, dict[str, Any]]] = {}
        for canonical, items in by_number.items():
            kind = items[0].kind
            signals = compute_signals(
                canonical,
                kind,
                references,
                items,
                effective_brand.official_domain,
                number_results=number_bodies.get(canonical, []),
                review_results=review_bodies.get(canonical, []),
                warning_terms=warning_terms,
                number_search_ran=canonical in number_bodies,
            )
            decision = decide(canonical, reference_values, signals, reference_sources)
            all_signals[canonical] = signals
            results.append(
                NumberResult(
                    canonical, kind, decision.verdict, decision.reasons, signals, tuple(items)
                )
            )
        finished = datetime.now(UTC)
        self.store.save_check(
            {
                "id": check_id,
                "mode": "brand",
                "brand_id": effective_brand.id,
                "brand_text": effective_brand.name,
                "city": city,
                "lang": lang,
                "started_at": started.isoformat(),
                "finished_at": finished.isoformat(),
                "searches_used": budget.used if self.settings.effective_mode == "live" else 0,
                "skipped": skipped,
            },
            sightings,
            all_signals,
            results,
        )
        self.store.save_check_step(check_id, "Verdicts", "complete", f"{len(results)} number(s)")
        return CheckResult(
            check_id,
            effective_brand,
            city,
            lang,
            tuple(references),
            tuple(results),
            tuple(skipped),
            budget.used if self.settings.effective_mode == "live" else 0,
        )

    async def number_check(
        self,
        value: str,
        brand: Brand | None = None,
        location: str | None = None,
        *,
        fresh: bool = False,
    ) -> NumberCheckResult:
        from sahi.extract.phones import normalise_phone

        normalized = normalise_phone(value)
        if not normalized:
            raise ValueError("Enter a valid phone number")
        started = datetime.now(UTC)
        check_id = uuid.uuid4().hex
        budget = SearchBudget(self.settings.max_searches_per_check)
        skipped: list[str] = []
        try:
            result = await search_number(
                self.client, budget, primary_search_query(normalized), location
            )
        except (BudgetExceeded, ReplayMiss, SerpApiError) as error:
            raise ValueError(f"Number search unavailable: {error}") from error
        self.store.link_check_search(check_id, result.search_id, "Number search")
        number_results = [result]
        sightings = [
            item
            for item in walk_response(result.body, result.search_id, result.engine)
            if item.canonical == normalized.canonical
        ]
        fallback_query = discovery_query(normalized)
        if not sightings and fallback_query != primary_search_query(normalized):
            try:
                fallback = await search_number_discovery(
                    self.client, budget, fallback_query, location
                )
            except (BudgetExceeded, ReplayMiss, SerpApiError) as error:
                skipped.append(f"Plain-number fallback skipped: {error}")
            else:
                number_results.append(fallback)
                self.store.link_check_search(
                    check_id, fallback.search_id, "Plain-number fallback search"
                )
                sightings = [
                    item
                    for item in walk_response(fallback.body, fallback.search_id, fallback.engine)
                    if item.canonical == normalized.canonical
                ]
        if not sightings:
            try:
                contextual = await search_number_contextual(
                    self.client, budget, fallback_query, location
                )
            except (BudgetExceeded, ReplayMiss, SerpApiError) as error:
                skipped.append(f"Contact-context number search skipped: {error}")
            else:
                number_results.append(contextual)
                self.store.link_check_search(
                    check_id, contextual.search_id, "Contact-context number search"
                )
                sightings = [
                    item
                    for item in walk_response(
                        contextual.body, contextual.search_id, contextual.engine
                    )
                    if item.canonical == normalized.canonical
                ]
        if not sightings and brand:
            try:
                contextual = await search_number_with_brand(
                    self.client, budget, brand.name, fallback_query, location
                )
            except (BudgetExceeded, ReplayMiss, SerpApiError) as error:
                skipped.append(f"Brand-qualified number search skipped: {error}")
            else:
                number_results.append(contextual)
                self.store.link_check_search(
                    check_id, contextual.search_id, "Brand-qualified number search"
                )
                sightings = [
                    item
                    for item in walk_response(
                        contextual.body, contextual.search_id, contextual.engine
                    )
                    if item.canonical == normalized.canonical
                ]
        if not sightings:
            # A brand check can capture a local, trusted listing that a later
            # number-only Google query fails to rank.  Reuse the saved receipt
            # so Number Check remains evidence-based and does not pretend that
            # this previously recorded appearance never existed.
            for item in self.store.historical_brand_sightings(normalized.canonical):
                try:
                    kind = PhoneClass(item["class"])
                except ValueError:
                    kind = normalized.kind
                sightings.append(
                    Sighting(
                        canonical=item["canonical"],
                        raw=item["raw"],
                        kind=kind,
                        surface=item["surface"],
                        json_path=item["json_path"],
                        title=item["title"],
                        link=item["link"],
                        domain=item["domain"],
                        position=item["position"],
                        receipt_id=item["search_id"],
                        item={},
                    )
                )
        domains: dict[str, list[Sighting]] = {}
        for item in sightings:
            domains.setdefault(item.domain or "unknown", []).append(item)
        references: list[ReferenceNumber] = []
        signals: dict[str, dict[str, Any]] = {}
        decision = None
        effective_brand = brand
        if brand:
            directory_result: SearchResult | None = None
            try:
                directory_result = await search_public_directory(
                    self.client, budget, brand.name, fresh=fresh
                )
                self.store.link_check_search(
                    check_id, directory_result.search_id, "Public-directory search"
                )
            except (BudgetExceeded, ReplayMiss, SerpApiError) as error:
                skipped.append(f"Public-directory search skipped: {error}")
            if directory_result:
                existing = {
                    (item.receipt_id, item.json_path, item.canonical) for item in sightings
                }
                for item in walk_response(
                    directory_result.body,
                    directory_result.search_id,
                    directory_result.engine,
                ):
                    key = (item.receipt_id, item.json_path, item.canonical)
                    if item.canonical != normalized.canonical or key in existing:
                        continue
                    sightings.append(item)
                    domains.setdefault(item.domain or "unknown", []).append(item)
                    existing.add(key)
            if not brand.official_domain:
                try:
                    identity_result = await search_brand_identity(
                        self.client,
                        budget,
                        brand.name,
                        self.settings,
                        fresh=fresh,
                    )
                    self.store.link_check_search(
                        check_id, identity_result.search_id, "Brand identity search"
                    )
                except (BudgetExceeded, ReplayMiss, SerpApiError) as error:
                    skipped.append(f"Brand identity search skipped: {error}")
                else:
                    knowledge_graph = identity_result.body.get("knowledge_graph", {})
                    website = (
                        knowledge_graph.get("website")
                        if isinstance(knowledge_graph, dict)
                        else None
                    )
                    candidate_domain = registrable_domain(str(website)) if website else None
                    if candidate_domain:
                        effective_brand = replace(
                            brand,
                            official_domain=candidate_domain,
                            domain_verified=False,
                        )
                        skipped.append(
                            f"Using unconfirmed domain from knowledge graph: {candidate_domain}"
                        )
                    else:
                        skipped.append(
                            "No official-domain candidate appeared in the brand knowledge graph"
                        )
            official_body: dict[str, Any] = {}
            if effective_brand and effective_brand.official_domain:
                try:
                    official_result = await search_official_site(
                        self.client,
                        budget,
                        effective_brand.official_domain,
                        fresh=fresh,
                    )
                    official_body = official_result.body
                    self.store.link_check_search(
                        check_id, official_result.search_id, "Official-site search"
                    )
                except (BudgetExceeded, ReplayMiss, SerpApiError) as error:
                    skipped.append(f"Official-site search skipped: {error}")
            references, failures = await build_reference_set(
                effective_brand, official_body, self.store
            )
            trusted_results = {
                "organic_results": [
                    *(
                        (directory_result.body if directory_result else {}).get(
                            "organic_results", []
                        )
                    ),
                    *(
                        item
                        for number_result in number_results
                        for item in number_result.body.get("organic_results", [])
                    ),
                ]
            }
            directory_references, directory_failures = await build_public_directory_references(
                effective_brand, trusted_results, self.store
            )
            references.extend(directory_references)
            skipped.extend(failures)
            skipped.extend(directory_failures)
            self.store.save_brand_references(effective_brand, references)
            signals = compute_signals(
                normalized.canonical,
                normalized.kind,
                references,
                sightings,
                effective_brand.official_domain,
                number_results=[item.body for item in number_results],
                number_search_ran=True,
            )
            reference_sources: dict[str, set[str]] = {}
            for item in references:
                reference_sources.setdefault(item.canonical, set()).add(item.source_kind)
            decision = decide(
                normalized.canonical,
                {item.canonical for item in references},
                signals,
                reference_sources,
            )
        finished = datetime.now(UTC)
        stored_verdicts: list[Any] = []
        if decision:
            stored_verdicts.append(
                type(
                    "StoredNumberDecision",
                    (),
                    {
                        "canonical": normalized.canonical,
                        "verdict": decision.verdict,
                        "reasons": decision.reasons,
                    },
                )()
            )
        self.store.save_check(
            {
                "id": check_id,
                "mode": "number",
                "brand_id": effective_brand.id if effective_brand else None,
                "brand_text": effective_brand.name if effective_brand else value,
                "city": "Web",
                "lang": "en",
                "started_at": started.isoformat(),
                "finished_at": finished.isoformat(),
                "searches_used": budget.used if self.settings.effective_mode == "live" else 0,
                "skipped": skipped if brand else ["No verdict without a brand"],
            },
            sightings,
            {normalized.canonical: signals},
            stored_verdicts,
        )
        return NumberCheckResult(
            check_id,
            normalized.canonical,
            normalized.kind,
            {domain: tuple(items) for domain, items in domains.items()},
            decision.verdict if decision else None,
            decision.reasons if decision else ("No verdict without a brand",),
            budget.used if self.settings.effective_mode == "live" else 0,
        )
