from __future__ import annotations

import json
from pathlib import Path

from sahi.serp.client import scrub_payload
from sahi.store import Store


def export_check_fixtures(store: Store, check_id: str, output_dir: Path) -> list[Path]:
    """Export the scrubbed receipts referenced by one check."""

    if not store.get_check(check_id):
        raise ValueError(f"Unknown check: {check_id}")
    with store.connect() as connection:
        rows = connection.execute(
            """SELECT DISTINCT s.* FROM searches s
            WHERE s.id IN (
              SELECT search_id FROM check_searches WHERE check_id=?
              UNION SELECT search_id FROM sightings WHERE check_id=?
            ) ORDER BY s.id""",
            (check_id, check_id),
        ).fetchall()
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for row in rows:
        payload = scrub_payload(json.loads(row["body_json"]))
        envelope = {
            "_sahi_fixture": {
                "cache_key": row["cache_key"],
                "engine": row["engine"],
                "params": json.loads(row["params_json"]),
            },
            "response": payload,
        }
        path = output_dir / f"{row['engine']}-{row['cache_key']}.json"
        path.write_text(json.dumps(envelope, indent=2, ensure_ascii=False) + "\n")
        written.append(path)
    return written
