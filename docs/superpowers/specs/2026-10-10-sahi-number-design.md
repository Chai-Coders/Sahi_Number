# Sahi Number design

## Intent

Sahi Number helps a person in India check whether a customer-care number surfaced by Google is also published by the relevant brand. It preserves uncertainty: the runtime uses deterministic code, exposes evidence and receipts, and never labels a number safe, genuine, fraudulent, or a scam.

## Architecture

The application is a single Python process with four deep modules. The SerpApi client owns live/replay transport, scrubbing, caching, receipts, and budgets behind one search interface. Extraction owns Unicode normalization, phone classification, and recursive response walking. The decision core owns reference construction, independent signals, and the pure four-state verdict function. The application layer coordinates checks, persistence, CLI commands, and a mobile-first server-rendered FastAPI interface.

SQLite is the durable seam between live collection and replay. Every SerpApi response is scrubbed before persistence; tests and replay never require a key or network. The web interface renders evidence already stored by the pipeline and never computes a verdict independently.

## Data flow

1. Resolve configuration, brand, and city.
2. Estimate the maximum search cost before execution.
3. Run eligible SerpApi engine calls through the guarded client.
4. Fetch only same-domain official contact pages.
5. Walk scrubbed responses into normalized sightings.
6. Build the official reference set.
7. Compute named signals independently.
8. Call the pure verdict function and persist the complete check.
9. Render result cards, evidence, and local receipt JSON.

## Error and privacy behavior

Budget refusals and engine failures become named skipped steps. Missing reference evidence produces `CANNOT_VERIFY`. The API key is accepted only from environment configuration and is removed from cache keys, stored parameters, response strings, fixtures, and rendered pages. Review author objects are discarded.

## Testing

Unit tests pin normalization, walker exclusions, signals, and every verdict boundary. Client tests use injected HTTP transports and a temporary SQLite database. Integration tests run a full replay check and every route without a key. Final gates are `ruff check .`, `pytest`, secret scans, and a browser pass at mobile and desktop widths.

## Source specification

The authoritative product specification is `/home/jxhhhnnnnyyyyy/Downloads/Sahi-Number-build-prompt.md`.

