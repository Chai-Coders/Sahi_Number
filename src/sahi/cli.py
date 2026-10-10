from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer

from sahi.config import ROOT, Settings
from sahi.pipeline import Pipeline
from sahi.reference import load_brands
from sahi.serp.account import resolve_location
from sahi.serp.client import SerpClient
from sahi.store import Store

app = typer.Typer(no_args_is_help=True, help="Evidence-first helpline verification for India")
locations_app = typer.Typer(help="Resolve configured Indian cities")
fixtures_app = typer.Typer(help="Manage scrubbed replay fixtures")
app.add_typer(locations_app, name="locations")
app.add_typer(fixtures_app, name="fixtures")


def _runtime() -> tuple[Settings, Store, SerpClient]:
    settings = Settings()
    store = Store(settings.database_path)
    return settings, store, SerpClient(settings, store)


@app.command()
def probe(
    brand: str = typer.Option(..., help="Real owner-supplied brand name"),
    cities: str = "Mumbai,Delhi",
    langs: str = "en,hi",
) -> None:
    """Run the bounded SerpApi capability probe (maximum ten searches)."""

    from scripts.probe import run_probe

    settings, store, _client = _runtime()
    results = asyncio.run(run_probe(brand, cities.split(","), langs.split(","), settings, store))
    typer.echo(json.dumps(results, indent=2, ensure_ascii=False))


@locations_app.command("resolve")
def locations_resolve() -> None:
    settings, store, _client = _runtime()
    import yaml

    city_names = yaml.safe_load((ROOT / "seeds" / "cities.yaml").read_text())

    async def resolve_all():
        return [await resolve_location(city, store) for city in city_names]

    typer.echo(json.dumps(asyncio.run(resolve_all()), indent=2, ensure_ascii=False))


@app.command()
def check(
    brand: str = typer.Option(...),
    city: str = typer.Option(...),
    lang: str = typer.Option("en"),
    fresh: bool = typer.Option(False),
) -> None:
    """Check one seeded brand in one city and language."""

    brands = {item.id: item for item in load_brands()}
    if brand not in brands:
        typer.echo(f"Unknown brand: {brand}")
        raise typer.Exit(2)
    settings, store, client = _runtime()
    result = asyncio.run(
        Pipeline(settings, store, client).brand_check(brands[brand], city, lang, fresh=fresh)
    )
    typer.echo(f"Check {result.id}: {result.searches_used} live searches")
    for item in result.numbers:
        typer.echo(f"{item.canonical}\t{item.kind.value}\t{item.verdict.value}")
    for skipped in result.skipped:
        typer.echo(f"SKIPPED\t{skipped}")


@app.command()
def number(value: str, brand: str | None = typer.Option(None)) -> None:
    """Show where a number appears and optionally compare it with a brand."""

    selected = None
    if brand:
        brands = {item.id: item for item in load_brands()}
        if brand not in brands:
            typer.echo(f"Unknown brand: {brand}")
            raise typer.Exit(2)
        selected = brands[brand]
    settings, store, client = _runtime()
    try:
        result = asyncio.run(Pipeline(settings, store, client).number_check(value, selected))
    except ValueError as error:
        typer.echo(str(error))
        raise typer.Exit(2) from error
    typer.echo(f"{result.canonical}\t{result.verdict.value if result.verdict else 'NO_VERDICT'}")
    for domain, items in result.domains.items():
        typer.echo(f"{domain}\t{len(items)} appearance(s)")


@app.command()
def sweep(
    brands: str = "all",
    cities: str = "Mumbai,Delhi",
    langs: str = "en,hi",
    budget: int = 40,
    yes: bool = False,
) -> None:
    """Run a resumable brand/city/language matrix under a hard budget."""

    from sahi.sweep import SweepBudgetError, estimate_searches, run_sweep

    available = load_brands()
    selected = (
        available
        if brands == "all"
        else [
            item for item in available if item.id in {value.strip() for value in brands.split(",")}
        ]
    )
    city_values = [value.strip() for value in cities.split(",") if value.strip()]
    lang_values = [value.strip() for value in langs.split(",") if value.strip()]
    planned = estimate_searches(len(selected), len(city_values), len(lang_values))
    typer.echo(f"Planned maximum: {planned} searches; hard budget: {budget}")
    if not yes and not typer.confirm("Run this sweep?"):
        raise typer.Abort()
    settings, store, client = _runtime()
    try:
        result = asyncio.run(
            run_sweep(
                Pipeline(settings, store, client),
                store,
                selected,
                city_values,
                lang_values,
                budget,
                per_check_cap=settings.max_searches_per_check,
            )
        )
    except SweepBudgetError as error:
        typer.echo(str(error))
        raise typer.Exit(2) from error
    typer.echo(
        f"Sweep {result.id}: {result.completed_cells} completed, "
        f"{result.skipped_cells} resumed, {result.searches_used} searches used"
    )


@fixtures_app.command("export")
def fixtures_export(check: str = typer.Option(...)) -> None:
    """Export stored scrubbed search bodies for a check."""

    _settings, store, _client = _runtime()
    from sahi.fixtures import export_check_fixtures

    try:
        paths = export_check_fixtures(store, check, Path("tests/fixtures/recorded"))
    except ValueError as error:
        typer.echo(str(error))
        raise typer.Exit(2) from error
    for path in paths:
        typer.echo(str(path))


@app.command()
def account() -> None:
    """Show the current SerpApi credit balance."""

    settings, _store, client = _runtime()
    if settings.effective_mode != "live":
        typer.echo("Replay mode: no searches used")
        return
    typer.echo(f"Searches left: {asyncio.run(client.credits_left())}")
