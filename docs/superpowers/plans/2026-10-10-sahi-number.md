# Sahi Number Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the complete Sahi Number helpline-verification application from the supplied specification.

**Architecture:** A single FastAPI/CLI process uses focused Python modules around a guarded SerpApi client and SQLite receipt store. Pure extraction, signal, and verdict modules remain independent of transport and UI so replay tests exercise the same runtime path as live checks.

**Tech Stack:** Python 3.11+, FastAPI, Jinja2, HTMX, sqlite3, httpx, phonenumbers, tldextract, pydantic-settings, Typer, pytest, ruff, uv.

**Spec:** `/home/jxhhhnnnnyyyyy/Downloads/Sahi-Number-build-prompt.md`

## Global Constraints

- Runtime verdicts are deterministic; no LLM and no blended trust score.
- Use exactly `OFFICIAL_MATCH`, `NOT_CORROBORATED`, `CONFLICT`, and `CANNOT_VERIFY`.
- Never store or render the SerpApi key; scrub reviewer identity objects.
- Tests run offline without an API key and use fictional phone/domain data.
- Only fetch configured official contact pages and validate registrable-domain equality.
- Live work is budget guarded; do not spend more than 10 probe searches without approval.
- Keep the application runnable and tests green at each milestone.

## Review Focus

- Unicode and malformed numeric text must not become false phone sightings.
- Cache freshness, replay misses, and per-check/hourly/account budgets must be deterministic.
- Engine payload shape drift must degrade into skipped steps rather than invent evidence.
- An empty reference set must dominate signals and return `CANNOT_VERIFY`.
- Every route must avoid leaking secret-bearing URLs or personal reviewer data.

---

### Task 0: Repository and capability probe

**Files:** `pyproject.toml`, seeds, `scripts/probe.py`, `docs/PROBE.md`, fixture directories.

**Interfaces:** Produces runnable project metadata, `sahi probe`, and scrubbed capability receipts.

- [x] Add project configuration, seed schemas, and a key-safe probe CLI.
- [x] Test probe planning and scrubbing without network.
- [ ] Run a live probe only after a real owner-supplied brand is available, with a hard cap of 10 searches.
- [ ] Record live findings and commit milestone 0 (blocked: owner brand absent; `.git` is read-only).

### Task 1: Store and guarded SerpApi client

**Files:** `src/sahi/config.py`, `store.py`, `serp/client.py`, `serp/account.py`, `serp/engines.py`; client, scrub, and budget tests.

**Interfaces:** `Store`, `SerpClient.search()`, `SearchBudget`, typed engine functions, location/account helpers.

- [x] Write failing cache, replay, scrub, retry, and budget tests.
- [x] Implement schema, configuration, guarded transport, and engine parameter builders.
- [x] Run milestone tests and the full suite. Commit blocked by read-only `.git`.

### Task 2: Phone extraction and response walker

**Files:** `src/sahi/extract/phones.py`, `walker.py`; phone and walker fixtures/tests.

**Interfaces:** `find_phones(text)`, `normalise_phone(value)`, `walk_response(body, receipt_id, engine)`.

- [x] Write 40+ literal table cases and per-surface walker cases; verify failures.
- [x] Implement Unicode digit folding, classification, rejections, canonical/display/search variants, and recursive exclusions.
- [x] Run milestone tests and the full suite. Commit blocked by read-only `.git`.

### Task 3: Decision core, reference set, pipeline, and CLI

**Files:** `reference.py`, `signals.py`, `verdict.py`, `pipeline.py`, `cli.py`; decision and replay-pipeline tests.

**Interfaces:** `build_reference_set()`, `compute_signals()`, `decide()`, `Pipeline.brand_check()`.

- [x] Write failing decision-table, signal, reference-domain, and replay integration tests.
- [x] Implement the pure decision core, orchestration, persistence, and `sahi check`.
- [x] Verify replay CLI output and full tests. Commit blocked by read-only `.git`.

### Task 4: Brand-check web interface

**Files:** `web/app.py`, templates, `web/static/styles.css`, `tests/test_web.py`.

**Interfaces:** Routes defined in section 15 of the specification.

- [x] Write failing bilingual route, form, evidence, receipt, and limits tests.
- [x] Implement mobile-first templates, HTMX status fragments, non-colour verdict cues, receipts, and credit/mode footer.
- [x] Validate desktop/mobile behavior in a real browser. Commit blocked by read-only `.git`.

### Task 5: Number check

**Files:** pipeline/CLI/web additions and tests.

**Interfaces:** `Pipeline.number_check()` and `sahi number` plus the home-page number tab.

- [x] Write failing normalization, no-brand, branded-verdict, CLI, and route tests.
- [x] Implement number lookup and grouped-domain evidence.
- [x] Run full gates. Commit blocked by read-only `.git`.

### Task 6: Sweep and history

**Files:** `sweep.py`, CLI/web matrix additions, tests.

**Interfaces:** resumable `run_sweep(plan, budget)` and read-only `/sweep`.

- [x] Write failing plan-cost, hard-budget, resume, history, and matrix tests.
- [x] Implement resumable cells, confirmation, persistence, hourly-limit waiting, and matrix rendering.
- [x] Run full gates. Commit blocked by read-only `.git`.

### Task 7: Submission documentation and final verification

**Files:** `README.md`, `docs/DECISIONS.md`, `docs/LIMITS.md`, `docs/DEMO.md`, CI, MIT license, requirements export.

**Interfaces:** Fresh clone runs in replay mode without a key.

- [x] Complete documentation in the mandated order and export scrubbed fixtures.
- [x] Run `ruff check .`, `pytest`, CLI smoke tests, browser checks, and secret scans.
- [x] Verify every local definition-of-done gate. Live-brand verification awaits the owner brand; commit is blocked by read-only `.git`.
