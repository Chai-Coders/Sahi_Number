from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import yaml

from sahi.config import ROOT
from sahi.extract.phones import PhoneClass, find_phones
from sahi.extract.walker import registrable_domain
from sahi.store import Store


@dataclass(frozen=True, slots=True)
class Brand:
    id: str
    name: str
    official_domain: str | None = None
    aliases: tuple[str, ...] = ()
    contact_urls: tuple[str, ...] = ()
    official_numbers: tuple[dict[str, str], ...] = ()
    domain_verified: bool = False


@dataclass(frozen=True, slots=True)
class ReferenceNumber:
    canonical: str
    kind: PhoneClass
    source_kind: str
    source_url: str
    seen_at: str | None = None


def load_brands(path: Path | None = None) -> list[Brand]:
    entries = yaml.safe_load((path or ROOT / "seeds" / "brands.yaml").read_text()) or []
    return [
        Brand(
            id=item["id"],
            name=item["name"],
            official_domain=item.get("official_domain"),
            aliases=tuple(item.get("aliases", [])),
            contact_urls=tuple(item.get("contact_urls", [])),
            official_numbers=tuple(item.get("official_numbers", [])),
            domain_verified=bool(item.get("domain_verified", False)),
        )
        for item in entries
    ]


def _plain_text(html: str) -> str:
    text = re.sub(r"<(script|style).*?>.*?</\1>", " ", html, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", unescape(text))


async def _contact_body(url: str, store: Store | None) -> str:
    if store:
        with store.connect() as connection:
            row = connection.execute(
                "SELECT fetched_at, body FROM contact_cache WHERE url=?", (url,)
            ).fetchone()
        if row and datetime.fromisoformat(row["fetched_at"]) >= datetime.now(UTC) - timedelta(
            hours=24
        ):
            return str(row["body"])
    async with httpx.AsyncClient(
        timeout=5, headers={"User-Agent": "SahiNumber/0.1 (+local evidence verifier)"}
    ) as client:
        response = await client.get(url, follow_redirects=True)
    response.raise_for_status()
    if registrable_domain(str(response.url)) != registrable_domain(url):
        raise ValueError("contact page redirected outside the official domain")
    body = _plain_text(response.text)
    if store:
        with store.connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO contact_cache(url, fetched_at, body) VALUES (?, ?, ?)",
                (url, datetime.now(UTC).isoformat(), body),
            )
    return body


async def build_reference_set(
    brand: Brand,
    official_search: dict[str, Any],
    store: Store | None = None,
) -> tuple[list[ReferenceNumber], list[str]]:
    if not brand.official_domain:
        return [], ["No official domain is configured"]
    official_domain = registrable_domain(brand.official_domain)
    references: list[ReferenceNumber] = []
    failures: list[str] = []
    seen: set[str] = set()

    def add(number_text: str, source_kind: str, source_url: str, seen_at: str | None = None):
        for match in find_phones(number_text):
            if match.canonical not in seen:
                references.append(
                    ReferenceNumber(match.canonical, match.kind, source_kind, source_url, seen_at)
                )
                seen.add(match.canonical)

    for item in brand.official_numbers:
        source_url = item.get("source_url", "")
        if (
            item.get("number")
            and source_url
            and item.get("verified_on")
            and registrable_domain(source_url) == official_domain
        ):
            add(item["number"], "SEED", source_url, item["verified_on"])
    for url in brand.contact_urls:
        if registrable_domain(url) != official_domain:
            failures.append(f"Skipped cross-domain contact URL: {url}")
            continue
        try:
            add(await _contact_body(url, store), "CONTACT_PAGE", url)
        except (httpx.HTTPError, ValueError) as error:
            failures.append(f"Contact page failed: {url} ({error})")
    for item in official_search.get("organic_results", []):
        link = item.get("link", "")
        if registrable_domain(link) != official_domain:
            continue
        text = " ".join(str(item.get(key, "")) for key in ("title", "snippet"))
        add(text, "OFFICIAL_SEARCH", link)
    return references, failures


def _trusted_source_kind(url: str) -> str | None:
    host = (urlsplit(url).hostname or "").casefold()
    config = yaml.safe_load((ROOT / "seeds" / "trusted_sources.yaml").read_text()) or {}
    for domain in config.get("statutory_regulator_domains", []):
        domain = str(domain).casefold()
        if host == domain or host.endswith(f".{domain}"):
            return "STATUTORY_REGULATOR"
    for suffix in config.get("public_authority_suffixes", []):
        suffix = str(suffix).casefold()
        if host.endswith(suffix):
            return "GOVERNMENT_DIRECTORY"
    return None


def _brand_terms(name: str) -> set[str]:
    return {term for term in re.findall(r"[a-z0-9]{3,}", name.casefold())}


async def build_public_directory_references(
    brand: Brand,
    directory_search: dict[str, Any],
    store: Store | None = None,
) -> tuple[list[ReferenceNumber], list[str]]:
    """Collect numbers from matching Indian public-authority and regulator pages.

    These remain explicitly labelled as government-directory evidence rather
    than being silently represented as pages controlled by the brand.
    """

    references: list[ReferenceNumber] = []
    failures: list[str] = []
    required_terms = _brand_terms(brand.name)
    seen: set[str] = set()
    for item in directory_search.get("organic_results", []):
        link = str(item.get("link", ""))
        source_kind = _trusted_source_kind(link)
        if not source_kind:
            continue
        snippet = " ".join(str(item.get(key, "")) for key in ("title", "snippet"))
        matched_terms = {term for term in required_terms if term in snippet.casefold()}
        if len(matched_terms) < min(2, len(required_terms)):
            continue
        for match in find_phones(snippet):
            if match.kind != PhoneClass.SHORT_CODE and match.canonical not in seen:
                references.append(
                    ReferenceNumber(match.canonical, match.kind, source_kind, link)
                )
                seen.add(match.canonical)
        try:
            body = await _contact_body(link, store)
        except (httpx.HTTPError, ValueError) as error:
            failures.append(f"Public directory page failed: {link} ({error})")
            continue
        page_terms = {term for term in required_terms if term in body.casefold()}
        if len(page_terms) < min(2, len(required_terms)):
            failures.append(f"Public directory identity did not match: {link}")
            continue
        page_numbers = [
            match for match in find_phones(body) if match.kind != PhoneClass.SHORT_CODE
        ]
        if len(page_numbers) > 5:
            failures.append(
                f"Public directory page was too broad to use as one brand reference: {link}"
            )
            continue
        for match in page_numbers:
            if match.canonical not in seen:
                references.append(
                    ReferenceNumber(
                        match.canonical,
                        match.kind,
                        source_kind,
                        link,
                    )
                )
                seen.add(match.canonical)
    return references, failures
