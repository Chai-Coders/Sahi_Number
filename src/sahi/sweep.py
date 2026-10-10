from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sahi.reference import Brand
from sahi.store import Store


class SweepBudgetError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SweepResult:
    id: str
    completed_cells: int
    skipped_cells: int
    searches_used: int


def estimate_searches(
    brand_count: int, city_count: int, language_count: int, per_check_cap: int = 8
) -> int:
    return brand_count * city_count * language_count * per_check_cap


async def run_sweep(
    pipeline: Any,
    store: Store,
    brands: list[Brand],
    cities: list[str],
    languages: list[str],
    hard_budget: int,
    *,
    per_check_cap: int = 8,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> SweepResult:
    existing = {
        (row["brand_id"], row["city"], row["lang"])
        for row in store.list_checks()
        if row["mode"] == "brand"
    }
    cells = [
        (brand, city, language) for brand in brands for city in cities for language in languages
    ]
    pending = [cell for cell in cells if (cell[0].id, cell[1], cell[2]) not in existing]
    estimate = len(pending) * per_check_cap
    if estimate > hard_budget:
        raise SweepBudgetError(
            f"Planned maximum is {estimate} searches, above hard budget {hard_budget}"
        )
    sweep_id = uuid.uuid4().hex
    started = datetime.now(UTC).isoformat()
    completed = 0
    used = 0
    for brand, city, language in pending:
        settings = getattr(pipeline, "settings", None)
        if settings and settings.effective_mode == "live":
            required_slots = min(per_check_cap, hard_budget - used, settings.hourly_search_limit)
            recent = store.count_recent_live_searches()
            if recent + required_slots > settings.hourly_search_limit:
                await sleep(
                    store.seconds_until_hourly_slot(settings.hourly_search_limit, required_slots)
                )
        result = await pipeline.brand_check(brand, city, language)
        used += result.searches_used
        completed += 1
        if used > hard_budget:
            raise SweepBudgetError(f"Sweep used {used}, above hard budget {hard_budget}")
    finished = datetime.now(UTC).isoformat()
    with store.connect() as connection:
        connection.execute(
            "INSERT INTO sweeps(id, started_at, finished_at, plan_json, searches_used) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                sweep_id,
                started,
                finished,
                json.dumps(
                    {
                        "brands": [brand.id for brand in brands],
                        "cities": cities,
                        "languages": languages,
                        "budget": hard_budget,
                    },
                    ensure_ascii=False,
                ),
                used,
            ),
        )
    return SweepResult(sweep_id, completed, len(cells) - len(pending), used)
