from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS searches(
  id INTEGER PRIMARY KEY, cache_key TEXT, engine TEXT, params_json TEXT,
  serpapi_id TEXT, status TEXT, live INTEGER, fetched_at TEXT, body_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_searches_cache ON searches(cache_key, fetched_at DESC);
CREATE TABLE IF NOT EXISTS brands(
  id TEXT PRIMARY KEY, name TEXT, official_domain TEXT, domain_verified INTEGER
);
CREATE TABLE IF NOT EXISTS reference_numbers(
  brand_id TEXT, canonical TEXT, class TEXT, source_kind TEXT, source_url TEXT, seen_at TEXT
);
CREATE TABLE IF NOT EXISTS checks(
  id TEXT PRIMARY KEY, mode TEXT, brand_id TEXT, brand_text TEXT, city TEXT, lang TEXT,
  started_at TEXT, finished_at TEXT, searches_used INTEGER, skipped_json TEXT
);
CREATE TABLE IF NOT EXISTS sightings(
  id INTEGER PRIMARY KEY, check_id TEXT, canonical TEXT, raw TEXT, class TEXT, surface TEXT,
  json_path TEXT, title TEXT, link TEXT, domain TEXT, position INTEGER, search_id INTEGER
);
CREATE TABLE IF NOT EXISTS signals(
  check_id TEXT, canonical TEXT, signal TEXT, evidence_json TEXT
);
CREATE TABLE IF NOT EXISTS verdicts(
  check_id TEXT, canonical TEXT, verdict TEXT, reasons_json TEXT
);
CREATE TABLE IF NOT EXISTS number_history(
  canonical TEXT, brand_id TEXT, surface TEXT, city TEXT, lang TEXT,
  first_seen TEXT, last_seen TEXT, times_seen INTEGER,
  UNIQUE(canonical, brand_id, surface, city, lang)
);
CREATE TABLE IF NOT EXISTS locations(
  city TEXT PRIMARY KEY, canonical_name TEXT, lat REAL, lng REAL
);
CREATE TABLE IF NOT EXISTS sweeps(
  id TEXT PRIMARY KEY, started_at TEXT, finished_at TEXT, plan_json TEXT, searches_used INTEGER
);
CREATE TABLE IF NOT EXISTS check_steps(
  check_id TEXT, step TEXT, status TEXT, detail TEXT, updated_at TEXT,
  PRIMARY KEY(check_id, step)
);
CREATE TABLE IF NOT EXISTS check_searches(
  check_id TEXT, search_id INTEGER, step TEXT, PRIMARY KEY(check_id, search_id)
);
CREATE TABLE IF NOT EXISTS contact_cache(
  url TEXT PRIMARY KEY, fetched_at TEXT, body TEXT
);
"""


class Store:
    """Small SQLite repository used by both live collection and replay."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def add_search(
        self,
        cache_key: str,
        engine: str,
        params: dict[str, Any],
        serpapi_id: str | None,
        status: str,
        live: bool,
        body: dict[str, Any],
    ) -> int:
        now = datetime.now(UTC).isoformat()
        with self.connect() as connection:
            cursor = connection.execute(
                """INSERT INTO searches
                (cache_key, engine, params_json, serpapi_id, status, live, fetched_at, body_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    cache_key,
                    engine,
                    json.dumps(params, sort_keys=True, ensure_ascii=False),
                    serpapi_id,
                    status,
                    int(live),
                    now,
                    json.dumps(body, sort_keys=True, ensure_ascii=False),
                ),
            )
            return int(cursor.lastrowid)

    def latest_search(self, cache_key: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM searches WHERE cache_key=? "
                "ORDER BY fetched_at DESC, id DESC LIMIT 1",
                (cache_key,),
            ).fetchone()
        return dict(row) if row else None

    def get_search(self, search_id: int) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM searches WHERE id=?", (search_id,)).fetchone()
        return dict(row) if row else None

    def count_recent_live_searches(self, minutes: int = 60) -> int:
        cutoff = (datetime.now(UTC) - timedelta(minutes=minutes)).isoformat()
        with self.connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM searches WHERE live=1 AND fetched_at>=?", (cutoff,)
            ).fetchone()
        return int(row["count"])

    def seconds_until_hourly_slot(self, limit: int, required_slots: int = 1) -> float:
        """Return the wait until a rolling-hour window has the requested capacity."""

        cutoff = datetime.now(UTC) - timedelta(minutes=60)
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT fetched_at FROM searches WHERE live=1 AND fetched_at>=? "
                "ORDER BY fetched_at",
                (cutoff.isoformat(),),
            ).fetchall()
        expire_count = len(rows) + required_slots - limit
        if expire_count <= 0:
            return 0.0
        boundary = datetime.fromisoformat(rows[expire_count - 1]["fetched_at"])
        return max(0.0, (boundary + timedelta(minutes=60) - datetime.now(UTC)).total_seconds() + 1)

    def set_search_time(self, search_id: int, value: datetime) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE searches SET fetched_at=? WHERE id=?", (value.isoformat(), search_id)
            )

    def list_searches(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM searches ORDER BY id").fetchall()
        return [dict(row) for row in rows]

    def save_brand_references(self, brand: Any, references: list[Any]) -> None:
        """Persist the effective brand identity and its current reference set."""

        with self.connect() as connection:
            connection.execute(
                """INSERT INTO brands(id, name, official_domain, domain_verified)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET name=excluded.name,
                  official_domain=excluded.official_domain,
                  domain_verified=excluded.domain_verified""",
                (
                    brand.id,
                    brand.name,
                    brand.official_domain,
                    int(brand.domain_verified),
                ),
            )
            connection.execute("DELETE FROM reference_numbers WHERE brand_id=?", (brand.id,))
            for item in references:
                connection.execute(
                    """INSERT INTO reference_numbers
                    (brand_id, canonical, class, source_kind, source_url, seen_at)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        brand.id,
                        item.canonical,
                        item.kind.value,
                        item.source_kind,
                        item.source_url,
                        item.seen_at,
                    ),
                )

    def save_check_step(
        self, check_id: str, step: str, status: str, detail: str | None = None
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO check_steps(check_id, step, status, detail, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(check_id, step) DO UPDATE SET status=excluded.status,
                  detail=excluded.detail, updated_at=excluded.updated_at""",
                (check_id, step, status, detail, datetime.now(UTC).isoformat()),
            )

    def link_check_search(self, check_id: str, search_id: int, step: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO check_searches(check_id, search_id, step) VALUES (?, ?, ?)",
                (check_id, search_id, step),
            )

    def check_steps(self, check_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM check_steps WHERE check_id=? ORDER BY updated_at, step", (check_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def save_check(
        self,
        check: dict[str, Any],
        sightings: list[Any],
        signals: dict[str, dict[str, dict[str, Any]]],
        verdicts: list[Any],
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """INSERT OR REPLACE INTO checks
                (id, mode, brand_id, brand_text, city, lang, started_at, finished_at,
                 searches_used, skipped_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    check["id"],
                    check["mode"],
                    check.get("brand_id"),
                    check["brand_text"],
                    check["city"],
                    check["lang"],
                    check["started_at"],
                    check["finished_at"],
                    check["searches_used"],
                    json.dumps(check["skipped"], ensure_ascii=False),
                ),
            )
            connection.execute("DELETE FROM sightings WHERE check_id=?", (check["id"],))
            for item in sightings:
                connection.execute(
                    """INSERT INTO sightings
                    (check_id, canonical, raw, class, surface, json_path, title, link,
                     domain, position, search_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        check["id"],
                        item.canonical,
                        item.raw,
                        item.kind.value,
                        item.surface,
                        item.json_path,
                        item.title,
                        item.link,
                        item.domain,
                        item.position,
                        item.receipt_id,
                    ),
                )
                connection.execute(
                    """INSERT INTO number_history
                    (canonical, brand_id, surface, city, lang, first_seen, last_seen, times_seen)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                    ON CONFLICT(canonical, brand_id, surface, city, lang) DO UPDATE SET
                      last_seen=excluded.last_seen, times_seen=times_seen+1""",
                    (
                        item.canonical,
                        check.get("brand_id") or "",
                        item.surface,
                        check["city"],
                        check["lang"],
                        check["finished_at"],
                        check["finished_at"],
                    ),
                )
            connection.execute("DELETE FROM signals WHERE check_id=?", (check["id"],))
            for canonical, number_signals in signals.items():
                for signal, evidence in number_signals.items():
                    connection.execute(
                        "INSERT INTO signals(check_id, canonical, signal, evidence_json) "
                        "VALUES (?, ?, ?, ?)",
                        (check["id"], canonical, signal, json.dumps(evidence, ensure_ascii=False)),
                    )
            connection.execute("DELETE FROM verdicts WHERE check_id=?", (check["id"],))
            for item in verdicts:
                connection.execute(
                    "INSERT INTO verdicts(check_id, canonical, verdict, reasons_json) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        check["id"],
                        item.canonical,
                        item.verdict.value,
                        json.dumps(item.reasons, ensure_ascii=False),
                    ),
                )

    def get_check(self, check_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM checks WHERE id=?", (check_id,)).fetchone()
        return dict(row) if row else None

    def check_details(self, check_id: str) -> dict[str, Any] | None:
        check = self.get_check(check_id)
        if not check:
            return None
        with self.connect() as connection:
            check["sightings"] = [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM sightings WHERE check_id=? ORDER BY position, id", (check_id,)
                ).fetchall()
            ]
            check["signals"] = [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM signals WHERE check_id=?", (check_id,)
                ).fetchall()
            ]
            check["verdicts"] = [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM verdicts WHERE check_id=?", (check_id,)
                ).fetchall()
            ]
            check["steps"] = [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM check_steps WHERE check_id=? ORDER BY updated_at, step",
                    (check_id,),
                ).fetchall()
            ]
        return check

    def list_checks(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM checks ORDER BY started_at DESC").fetchall()
        return [dict(row) for row in rows]

    def matrix_rows(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT c.id, c.brand_text, c.city, c.lang, c.finished_at,
                SUM(CASE WHEN v.verdict='OFFICIAL_MATCH' THEN 1 ELSE 0 END) AS official_match,
                SUM(CASE WHEN v.verdict='NOT_CORROBORATED' THEN 1 ELSE 0 END) AS not_corroborated,
                SUM(CASE WHEN v.verdict='CONFLICT' THEN 1 ELSE 0 END) AS conflict,
                SUM(CASE WHEN v.verdict='CANNOT_VERIFY' THEN 1 ELSE 0 END) AS cannot_verify
                FROM checks c LEFT JOIN verdicts v ON v.check_id=c.id
                WHERE c.mode='brand'
                GROUP BY c.id ORDER BY c.finished_at DESC"""
            ).fetchall()
        return [dict(row) for row in rows]
