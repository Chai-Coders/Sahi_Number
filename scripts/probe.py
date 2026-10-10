from __future__ import annotations

import asyncio
import json
from pathlib import Path

from sahi.config import ROOT, Settings
from sahi.extract.walker import walk_response
from sahi.serp.client import SearchBudget, SerpClient, scrub_payload
from sahi.store import Store


def build_probe_plan(
    brand: str, cities: list[str], languages: list[str]
) -> list[dict[str, object]]:
    """Build the fixed capability probe without making a network request."""

    if not brand.strip():
        raise ValueError("A real owner-supplied brand is required")
    combinations = [(city, language) for city in cities for language in languages]
    plan: list[dict[str, object]] = []
    for city, language in combinations:
        plan.append(
            {
                "engine": "google",
                "params": {
                    "q": f"{brand} customer care number",
                    "location": city,
                    "hl": language,
                    "gl": "in",
                    "google_domain": "google.co.in",
                    "device": "mobile",
                },
            }
        )
        plan.append(
            {
                "engine": "google_maps",
                "params": {
                    "type": "search",
                    "q": f"{brand} customer care",
                    "location": city,
                    "z": 12,
                    "hl": language,
                },
            }
        )
    for city in cities[:2]:
        plan.append(
            {
                "engine": "google_ads",
                "params": {
                    "q": f"{brand} customer care number",
                    "location": city,
                    "hl": "en",
                },
            }
        )
    if len(plan) > 10:
        raise ValueError("Probe plan exceeds the ten-search hard cap")
    return plan


async def run_probe(
    brand: str,
    cities: list[str],
    languages: list[str],
    settings: Settings,
    store: Store,
    *,
    client: SerpClient | None = None,
    recorded_dir: Path | None = None,
    report_path: Path | None = None,
) -> list[dict[str, object]]:
    if settings.effective_mode != "live":
        raise RuntimeError("The probe requires live mode and a configured key")
    plan = build_probe_plan(brand, cities, languages)
    budget = SearchBudget(10)
    client = client or SerpClient(settings, store)
    results = []
    recorded_dir = recorded_dir or settings.fixture_path / "recorded"
    recorded_dir.mkdir(parents=True, exist_ok=True)
    for step in plan:
        result = await client.search(str(step["engine"]), dict(step["params"]), budget, fresh=True)
        sightings = walk_response(result.body, result.search_id, result.engine)
        local_results = result.body.get("local_results", [])
        if isinstance(local_results, dict):
            local_results = local_results.get("places", [])
        fixture = {
            "_sahi_fixture": {
                "cache_key": result.cache_key,
                "engine": result.engine,
                "params": step["params"],
            },
            "response": scrub_payload(result.body),
        }
        fixture_path = recorded_dir / f"probe-{result.engine}-{result.cache_key}.json"
        fixture_path.write_text(json.dumps(fixture, indent=2, ensure_ascii=False) + "\n")
        results.append(
            {
                "engine": result.engine,
                "search_id": result.search_id,
                "serpapi_id": result.serpapi_id,
                "keys": sorted(result.body),
                "phone_paths": sorted({item.json_path for item in sightings}),
                "ai_overview": "ai_overview" in result.body,
                "maps_fields": {
                    field: any(isinstance(item, dict) and field in item for item in local_results)
                    for field in ("phone", "website", "data_id", "unclaimed_listing")
                },
                "result_count": len(result.body.get("ads", []))
                + len(result.body.get("local_ads", []))
                if result.engine == "google_ads"
                else len(local_results),
                "language": step["params"].get("hl"),
                "recorded_fixture": str(fixture_path),
            }
        )
    report_path = report_path or ROOT / "docs" / "PROBE.md"
    ads_results = sum(
        int(item["result_count"]) for item in results if item["engine"] == "google_ads"
    )
    hindi_ai = any(item["language"] == "hi" and item["ai_overview"] for item in results)
    phone_paths = sorted(
        {path for item in results for path in item["phone_paths"]}  # type: ignore[union-attr]
    )
    maps_fields = {
        field: any(
            bool(item["maps_fields"].get(field))  # type: ignore[union-attr]
            for item in results
            if item["engine"] == "google_maps"
        )
        for field in ("phone", "website", "data_id", "unclaimed_listing")
    }
    report_path.write_text(
        "\n".join(
            [
                "# Capability probe",
                "",
                "Status: **completed**.",
                "",
                f"Owner-supplied brand: **{brand}**.",
                f"Searches spent: **{budget.used}** (hard cap: 10).",
                f"Google Ads results observed: **{ads_results}**.",
                f"Hindi AI Overview observed: **{'yes' if hindi_ai else 'no'}**.",
                f"Phone-bearing JSON paths: `{', '.join(phone_paths) or 'none'}`.",
                "Maps field availability: "
                + ", ".join(
                    f"`{field}`={'yes' if present else 'no'}"
                    for field, present in maps_fields.items()
                )
                + ".",
                "",
                "Recommended flags from this bounded observation:",
                "",
                f"- `ENABLE_ADS={'true' if ads_results else 'false'}`",
                f"- `ENABLE_AI_OVERVIEW={'true' if hindi_ai else 'false'}`",
                f"- `ENABLE_REVIEWS={'true' if maps_fields['data_id'] else 'false'}`",
                "",
                "All raw responses were key-scrubbed and saved under `tests/fixtures/recorded/`.",
                "",
            ]
        )
    )
    return results


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--brand", required=True)
    parser.add_argument("--cities", default="Mumbai,Delhi")
    parser.add_argument("--langs", default="en,hi")
    args = parser.parse_args()
    settings = Settings()
    store = Store(settings.database_path)
    results = asyncio.run(
        run_probe(args.brand, args.cities.split(","), args.langs.split(","), settings, store)
    )
    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
