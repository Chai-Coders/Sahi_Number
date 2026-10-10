from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from html import unescape
from pathlib import Path
from typing import Any

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
