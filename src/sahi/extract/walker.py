from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import tldextract

from sahi.extract.phones import PhoneClass, find_phones

_EXTRACT = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)
SKIP_TOP = {
    "search_metadata",
    "search_parameters",
    "search_information",
    "pagination",
    "serpapi_pagination",
}
SKIP_KEYS = {
    "link",
    "thumbnail",
    "image",
    "lsig",
    "gps_coordinates",
    "position",
    "rating",
    "reviews",
    "price",
}
SURFACES = {
    "organic_results": "ORGANIC",
    "answer_box": "ANSWER_BOX",
    "answer_box_list": "ANSWER_BOX",
    "knowledge_graph": "KNOWLEDGE_GRAPH",
    "ai_overview": "AI_OVERVIEW",
    "local_results": "LOCAL_PACK",
    "ads": "AD",
    "local_ads": "AD",
    "related_questions": "RELATED_QUESTION",
}


@dataclass(frozen=True, slots=True)
class Sighting:
    canonical: str
    raw: str
    kind: PhoneClass
    surface: str
    json_path: str
    title: str | None
    link: str | None
    domain: str | None
    position: int | None
    receipt_id: int
    item: dict[str, Any]


def registrable_domain(url_or_host: str | None) -> str | None:
    if not url_or_host:
        return None
    host = urlsplit(url_or_host).hostname or url_or_host.split("/")[0]
    host = host.lower().strip(".")
    extracted = _EXTRACT(host)
    if extracted.suffix:
        return ".".join(part for part in (extracted.domain, extracted.suffix) if part)
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def _item_context(value: dict[str, Any], previous: dict[str, Any]) -> dict[str, Any]:
    if any(key in value for key in ("title", "position", "link", "website", "phone")):
        return value
    return previous


def walk_response(body: dict[str, Any], receipt_id: int, engine: str) -> list[Sighting]:
    sightings: list[Sighting] = []

    def walk(
        value: Any,
        path: str,
        top_key: str,
        context: dict[str, Any],
        key: str | None = None,
    ) -> None:
        if isinstance(value, dict):
            next_context = _item_context(value, context)
            for child_key, child in value.items():
                if child_key in SKIP_TOP and not path:
                    continue
                if child_key in SKIP_KEYS or child_key.endswith(("_id", "_cid", "_token", "_link")):
                    continue
                child_path = f"{path}.{child_key}" if path else child_key
                walk(child, child_path, top_key or child_key, next_context, child_key)
            return
        if isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{path}[{index}]", top_key, context, key)
            return
        if not isinstance(value, str):
            return
        if value.startswith(("http://", "https://")):
            return
        parse_value = value[4:] if value.lower().startswith("tel:") else value
        surface = SURFACES.get(top_key)
        if engine == "google_maps" and top_key == "local_results":
            surface = "MAPS_LISTING"
        if engine == "google_maps_reviews":
            surface = "MAPS_LISTING"
        if engine == "google_ai_overview":
            surface = "AI_OVERVIEW"
        if not surface:
            return
        item_link = context.get("link") or context.get("website")
        for phone in find_phones(parse_value):
            sightings.append(
                Sighting(
                    canonical=phone.canonical,
                    raw=phone.raw,
                    kind=phone.kind,
                    surface=surface,
                    json_path=path,
                    title=context.get("title"),
                    link=item_link,
                    domain=registrable_domain(item_link),
                    position=context.get("position"),
                    receipt_id=receipt_id,
                    item=context,
                )
            )

    walk(body, "", "", {})
    return sightings
