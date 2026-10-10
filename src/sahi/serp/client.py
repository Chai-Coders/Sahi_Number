from __future__ import annotations

import hashlib
import inspect
import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from sahi.config import Settings
from sahi.store import Store


class ReplayMiss(RuntimeError):
    pass


class BudgetExceeded(RuntimeError):
    pass


class SerpApiError(RuntimeError):
    pass


@dataclass(slots=True)
class SearchBudget:
    limit: int
    used: int = 0

    def spend(self) -> None:
        if self.used >= self.limit:
            raise BudgetExceeded(f"per-check limit of {self.limit} searches reached")
        self.used += 1


@dataclass(frozen=True, slots=True)
class SearchResult:
    search_id: int
    cache_key: str
    engine: str
    body: dict[str, Any]
    serpapi_id: str | None
    cached: bool


Transport = Callable[[str, dict[str, Any]], Awaitable[tuple[int, dict[str, Any]]]]


def _scrub_url(value: str) -> str:
    if "api_key=" not in value.lower():
        return value
    try:
        parts = urlsplit(value)
        query = [(key, val) for key, val in parse_qsl(parts.query) if key.lower() != "api_key"]
        cleaned = urlunsplit(
            (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
        )
        if "api_key=" in cleaned.lower():
            cleaned = re.sub(r"(?i)api_key=[^&\s]+", "", cleaned).rstrip("?&")
        return cleaned
    except ValueError:
        return value.split("api_key=", 1)[0].rstrip("?&")


def scrub_payload(value: Any, *, in_reviews: bool = False) -> Any:
    """Return a JSON-safe copy without secret query parameters or reviewer identity."""

    if isinstance(value, dict):
        result: dict[str, Any] = {}
        review_fields = {"snippet", "extracted_snippet", "iso_date", "rating", "link"}
        for key, item in value.items():
            if key.lower() == "api_key" or (in_reviews and key not in review_fields):
                continue
            result[key] = scrub_payload(item, in_reviews=in_reviews or key == "reviews")
        return result
    if isinstance(value, list):
        return [scrub_payload(item, in_reviews=in_reviews) for item in value]
    if isinstance(value, str):
        return _scrub_url(value)
    return value


def make_cache_key(engine: str, params: dict[str, Any]) -> str:
    safe = {key: value for key, value in params.items() if key.lower() != "api_key"}
    packed = json.dumps({"engine": engine, **safe}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(packed.encode()).hexdigest()


class SerpClient:
    endpoint = "https://serpapi.com/search"

    def __init__(
        self,
        settings: Settings,
        store: Store,
        *,
        transport: Transport | None = None,
        account_reader: Callable[[], int | Awaitable[int]] | None = None,
    ):
        self.settings = settings
        self.store = store
        self.transport = transport or self._http_transport
        self.account_reader = account_reader or self._read_account
        self._account_cache: tuple[datetime, int] | None = None

    async def _http_transport(self, url: str, params: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        last_error: Exception | None = None
        last_response: tuple[int, dict[str, Any]] | None = None
        for _attempt in range(2):
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    response = await client.get(url, params=params)
                try:
                    body = response.json()
                except ValueError:
                    body = {"error": "SerpApi returned a non-JSON response"}
                last_response = (response.status_code, body)
                if response.status_code not in {401, 429}:
                    return response.status_code, body
            except (httpx.TimeoutException, httpx.TransportError) as error:
                last_error = error
        if last_response:
            return last_response
        if last_error:
            raise SerpApiError(
                f"SerpApi request failed after one retry: {last_error}"
            ) from last_error
        raise SerpApiError("SerpApi request failed without a response")

    async def _read_account(self) -> int:
        now = datetime.now(UTC)
        if self._account_cache and (now - self._account_cache[0]).total_seconds() < 60:
            return self._account_cache[1]
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                "https://serpapi.com/account.json",
                params={"api_key": self.settings.serpapi_api_key},
            )
        if response.status_code == 401:
            raise SerpApiError("SerpApi rejected the configured API key")
        response.raise_for_status()
        left = int(response.json().get("total_searches_left", 0))
        self._account_cache = (now, left)
        return left

    async def credits_left(self) -> int | None:
        if self.settings.effective_mode != "live":
            return None
        value = self.account_reader()
        return int(await value) if inspect.isawaitable(value) else int(value)

    async def _guard(self, budget: SearchBudget) -> None:
        budget.spend()
        if self.store.count_recent_live_searches() >= self.settings.hourly_search_limit:
            budget.used -= 1
            raise BudgetExceeded(
                f"hourly limit of {self.settings.hourly_search_limit} live searches reached"
            )
        left = await self.credits_left()
        if left is not None and left < self.settings.min_credits_reserve:
            budget.used -= 1
            raise BudgetExceeded(
                f"Credit reserve protected: {left} left, reserve is "
                f"{self.settings.min_credits_reserve}"
            )

    async def search(
        self,
        engine: str,
        params: dict[str, Any],
        budget: SearchBudget,
        *,
        ttl: int | None = None,
        fresh: bool = False,
    ) -> SearchResult:
        safe_params = {
            key: value for key, value in params.items() if key.lower() not in {"api_key", "output"}
        }
        key = make_cache_key(engine, safe_params)
        cached = self.store.latest_search(key)
        if cached and not fresh:
            age = datetime.now(UTC) - datetime.fromisoformat(cached["fetched_at"])
            if self.settings.effective_mode == "replay" or age.total_seconds() < (
                ttl if ttl is not None else self.settings.cache_ttl_seconds
            ):
                body = json.loads(cached["body_json"])
                return SearchResult(
                    cached["id"], key, engine, body, cached["serpapi_id"], cached=True
                )
        if self.settings.effective_mode == "replay":
            fixture = self._matching_fixture(key, engine, safe_params)
            if fixture:
                body = scrub_payload(fixture)
                metadata = body.get("search_metadata", {})
                search_id = self.store.add_search(
                    key,
                    engine,
                    safe_params,
                    metadata.get("id"),
                    metadata.get("status", "Success"),
                    False,
                    body,
                )
                return SearchResult(
                    search_id,
                    key,
                    engine,
                    body,
                    metadata.get("id"),
                    cached=True,
                )
            raise ReplayMiss(f"No replay receipt for {engine} cache key {key[:12]}")
        await self._guard(budget)
        request_params = {
            **safe_params,
            "engine": engine,
            "output": "json",
            "api_key": self.settings.serpapi_api_key,
        }
        status_code, raw_body = await self.transport(self.endpoint, request_params)
        body = scrub_payload(raw_body)
        if status_code == 401:
            raise SerpApiError("SerpApi rejected the configured API key")
        if status_code == 429:
            raise SerpApiError("SerpApi rate limit reached")
        if status_code >= 400:
            raise SerpApiError(f"SerpApi HTTP {status_code}: {body.get('error', 'request failed')}")
        metadata = body.get("search_metadata", {})
        status = metadata.get("status", "Success")
        error = str(body.get("error", ""))
        if status == "Error" and "no result" not in error.lower():
            raise SerpApiError(error or "SerpApi search failed")
        search_id = self.store.add_search(
            key,
            engine,
            safe_params,
            metadata.get("id"),
            status,
            True,
            body,
        )
        return SearchResult(search_id, key, engine, body, metadata.get("id"), cached=False)

    def _matching_fixture(
        self, cache_key: str, engine: str, params: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Load a fixture envelope exported by ``sahi fixtures export``."""

        fixture_root = self.settings.fixture_path
        if not fixture_root.exists():
            return None
        for path in fixture_root.rglob("*.json"):
            try:
                payload = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            fixture_meta = payload.get("_sahi_fixture") if isinstance(payload, dict) else None
            if not isinstance(fixture_meta, dict):
                continue
            key_matches = fixture_meta.get("cache_key") == cache_key
            request_matches = (
                fixture_meta.get("engine") == engine and fixture_meta.get("params") == params
            )
            if key_matches or request_matches:
                response = payload.get("response")
                return response if isinstance(response, dict) else None
        return None
