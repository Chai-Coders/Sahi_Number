# Decisions

## 2026-10-10 — Deterministic runtime

Verdicts are computed by a pure function. No language model runs in the product.

## 2026-10-10 — No safety label

The product reports corroboration, conflict, or inability to verify. It does not
claim a number is safe, genuine, fraudulent, or a scam.

## 2026-10-10 — Two-signal conflict threshold

A non-reference number becomes `CONFLICT` only when at least two independent
signals fire. Absence from the official site alone is not an accusation.

## 2026-10-10 — Mobile Google results by default

The primary user is likely mid-errand on a phone, so `DEVICE=mobile` is the default.

## 2026-10-10 — REST instead of an SDK

Direct `httpx` calls make parameters, receipts, scrubbing, caching, and replay
observable in this repository.

## 2026-10-10 — Documentation checks

Current SerpApi documentation confirms `/search?engine=google`, `output=json`,
`search_metadata.status`, `search_metadata.id`, and `error` on failed searches.
Current FastAPI documentation confirms request-first `TemplateResponse`, mounted
`StaticFiles`, and lifespan-aware `TestClient` usage.

Official engine pages checked the same day confirm `google_ads` requires both
`q` and `location`; `google_maps` requires `type` when `q` is set; Maps reviews
use `google_maps_reviews` with `sort_by`; AI Overview redemption uses
`google_ai_overview` with `page_token`; and Locations returns `gps` alongside
`canonical_name`, `country_code`, and `target_type`. These match the build brief.

## 2026-10-10 — Async ASGI route tests

The installed FastAPI/Starlette stack deprecates its legacy synchronous
`TestClient` transport and deadlocked even for a minimal app. Route tests use
HTTPX's native async `ASGITransport`, exercising the same application directly.

## 2026-10-10 — Replay is the distributable default

The example environment defaults to replay, rather than the brief's live-mode
snippet, so a fresh clone cannot accidentally spend credits and satisfies the
zero-key startup requirement. Live mode still requires both an explicit mode
change and a key in the untracked `.env` file.

## 2026-10-10 — Progressive status is persisted

Pipeline steps write small status records while concurrent calls run. The HTMX
fragment reads those records once per second, so Search, Ads, Maps, AI, reference,
number-search, and review outcomes remain visible even when a step is skipped.

## 2026-10-10 — Free-text domains remain unconfirmed

For a non-seeded brand, the knowledge-graph website can supply a candidate
registrable domain. It is stored and displayed as unconfirmed; it never silently
becomes a human-verified seed domain.
