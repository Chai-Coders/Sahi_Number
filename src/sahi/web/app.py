from __future__ import annotations

import json
import re
import uuid
from html import escape
from pathlib import Path
from typing import Any

import yaml
from fastapi import BackgroundTasks, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from sahi.config import ROOT, Settings, get_settings
from sahi.extract.phones import PhoneClass, display_phone, normalise_phone
from sahi.extract.walker import walk_response
from sahi.pipeline import Pipeline
from sahi.reference import Brand, load_brands
from sahi.serp.client import SerpClient, make_cache_key
from sahi.signals import compute_signals
from sahi.store import Store
from sahi.verdict import decide

TEMPLATE_DIR = Path(__file__).with_name("templates")
STATIC_DIR = Path(__file__).with_name("static")
templates = Jinja2Templates(directory=TEMPLATE_DIR)
templates.env.filters["phone_display"] = display_phone

COPY = {
    "en": {
        "title": "Check a helpline number",
        "dek": "Compare every number Google showed with what the brand publishes.",
        "brand_tab": "Brand check",
        "number_tab": "Number check",
        "run": "Run check",
        "evidence": "View evidence",
        "up_to": "Up to 8 searches",
        "cache_zero": "Cached receipts cost 0",
        "replay_budget": "Replay check: 0 live searches",
        "live_budget": "This check will use up to {cap} searches; you have {left} left",
        "brand": "Brand",
        "brand_hint": "Choose or type a brand",
        "city": "City",
        "city_hint": "Type any Indian city, town or locality",
        "search_language": "Search language",
        "phone": "Phone number",
        "brand_optional": "Brand (optional)",
        "brand_optional_hint": "Type a brand or leave blank",
        "no_brand": "No brand — appearances only",
        "how_title": "What the result means",
        "how_body": (
            "We preserve each search receipt, show every signal separately, and use one "
            "readable decision table. Missing from an official site never means wrongdoing."
        ),
        "sweep": "Sweep",
        "limits": "Limits",
        "guarantee": "Evidence, not a safety guarantee.",
        "new_check": "New check",
        "no_verdict": "No verdict without a brand",
        "no_verdict_body": (
            "Showing where this number appeared. Choose a brand to compare it with "
            "published references."
        ),
        "domains": "Domains showing this number",
        "no_appearances": "No appearances were found in the stored receipt.",
        "back": "Back to check",
        "sightings": "Sightings",
        "signals": "Signals",
        "no_signal": "No conflict signal fired.",
        "references": "Reference sources checked",
        "collecting": "Collecting evidence…",
        "collecting_body": ("This page updates as Search, Ads, Maps and AI evidence completes."),
        "published_refs": "Brand and public-directory references",
        "unconfirmed": "Unconfirmed domain",
        "compared_brand": "Compared with brand",
        "no_reference": "No stored reference number was available.",
        "no_numbers": "No phone numbers found",
        "no_numbers_body": "The stored search receipts did not contain an extractable number.",
        "skipped": "Skipped or limited steps",
        "first_seen": "First seen",
        "live_searches": "live searches",
        "stored_matrix": "Stored sweep matrix",
        "matrix_body": "The web view never triggers a sweep. It reads completed cells only.",
        "no_matrix": "No stored sweep cells yet.",
        "search_receipt": "Search receipt",
        "engine": "Engine",
        "serpapi_id": "SerpApi ID",
        "unavailable": "Unavailable",
        "fetched": "Fetched",
        "parameters": "Parameters",
        "scrubbed": "Scrubbed response",
        "used_by_check": "searches used by this check",
        "replay_mode": "Replay mode: no searches used",
        "live_mode": "Live mode",
        "month_left": "searches left this month",
        "hour_left": "this hour",
        "balance_unavailable": "account balance unavailable",
        "verdict_labels": {
            "OFFICIAL_MATCH": "Found in a trusted reference",
            "NOT_CORROBORATED": "Not found on the brand's official site",
            "CONFLICT": "Conflicts with what the brand publishes",
            "CANNOT_VERIFY": "Cannot verify",
        },
        "advice": (
            "When in doubt, use the number printed on your card or bill, or inside "
            "the brand's official app. To report cyber fraud in India, call 1930 or "
            "visit cybercrime.gov.in."
        ),
    },
    "hi": {
        "title": "हेल्पलाइन नंबर जाँचें",
        "dek": "Google पर दिखे नंबरों की तुलना ब्रांड की वेबसाइट पर दिए नंबरों से करें।",
        "brand_tab": "ब्रांड जाँच",
        "number_tab": "नंबर जाँच",
        "run": "जाँच शुरू करें",
        "evidence": "सबूत देखें",
        "up_to": "अधिकतम 8 खोजें",
        "cache_zero": "कैश रसीदों की लागत 0",
        "replay_budget": "रीप्ले जाँच: 0 लाइव खोजें",
        "live_budget": "यह जाँच अधिकतम {cap} खोजें करेगी; आपके पास {left} बची हैं",
        "brand": "ब्रांड",
        "brand_hint": "ब्रांड चुनें या लिखें",
        "city": "शहर",
        "city_hint": "भारत का कोई भी शहर, कस्बा या इलाका लिखें",
        "search_language": "खोज की भाषा",
        "phone": "फ़ोन नंबर",
        "brand_optional": "ब्रांड (वैकल्पिक)",
        "brand_optional_hint": "ब्रांड लिखें या खाली छोड़ें",
        "no_brand": "कोई ब्रांड नहीं — केवल दिखने के स्थान",
        "how_title": "नतीजे का अर्थ",
        "how_body": (
            "हम हर खोज रसीद सुरक्षित रखते हैं, हर संकेत अलग दिखाते हैं और साफ़ निर्णय "
            "तालिका इस्तेमाल करते हैं। आधिकारिक साइट पर नंबर न मिलना गलत काम का प्रमाण नहीं है।"
        ),
        "sweep": "समूह जाँच",
        "limits": "सीमाएँ",
        "guarantee": "यह सबूत है, सुरक्षा की गारंटी नहीं।",
        "new_check": "नई जाँच",
        "no_verdict": "ब्रांड के बिना निर्णय संभव नहीं",
        "no_verdict_body": (
            "यह नंबर कहाँ दिखा, वह बताया जा रहा है। प्रकाशित संदर्भों से तुलना के लिए ब्रांड चुनें।"
        ),
        "domains": "यह नंबर दिखाने वाले डोमेन",
        "no_appearances": "संग्रहीत रसीद में यह नंबर नहीं मिला।",
        "back": "जाँच पर वापस जाएँ",
        "sightings": "दिखने के स्थान",
        "signals": "संकेत",
        "no_signal": "कोई विरोध संकेत नहीं मिला।",
        "references": "जाँचे गए संदर्भ स्रोत",
        "collecting": "सबूत जुटाए जा रहे हैं…",
        "collecting_body": "Search, Ads, Maps और AI सबूत पूरा होते ही यह पेज अपडेट होता है।",
        "published_refs": "ब्रांड और सार्वजनिक निर्देशिका संदर्भ",
        "unconfirmed": "अपुष्ट डोमेन",
        "compared_brand": "इस ब्रांड से तुलना",
        "no_reference": "कोई संग्रहीत संदर्भ नंबर उपलब्ध नहीं था।",
        "no_numbers": "कोई फ़ोन नंबर नहीं मिला",
        "no_numbers_body": "संग्रहीत खोज रसीदों में निकालने योग्य नंबर नहीं था।",
        "skipped": "छोड़े गए या सीमित चरण",
        "first_seen": "पहली बार दिखा",
        "live_searches": "लाइव खोजें",
        "stored_matrix": "संग्रहीत समूह-जाँच मैट्रिक्स",
        "matrix_body": "वेब दृश्य समूह जाँच शुरू नहीं करता; यह केवल पूरी कोशिकाएँ पढ़ता है।",
        "no_matrix": "अभी कोई संग्रहीत समूह-जाँच कोशिका नहीं है।",
        "search_receipt": "खोज रसीद",
        "engine": "इंजन",
        "serpapi_id": "SerpApi आईडी",
        "unavailable": "उपलब्ध नहीं",
        "fetched": "प्राप्त समय",
        "parameters": "पैरामीटर",
        "scrubbed": "साफ़ की गई प्रतिक्रिया",
        "used_by_check": "इस जाँच में इस्तेमाल खोजें",
        "replay_mode": "रीप्ले मोड: कोई खोज इस्तेमाल नहीं हुई",
        "live_mode": "लाइव मोड",
        "month_left": "इस महीने बची खोजें",
        "hour_left": "इस घंटे बची खोजें",
        "balance_unavailable": "खाता शेष उपलब्ध नहीं",
        "verdict_labels": {
            "OFFICIAL_MATCH": "विश्वसनीय संदर्भ में मिला",
            "NOT_CORROBORATED": "आधिकारिक वेबसाइट पर नहीं मिला",
            "CONFLICT": "ब्रांड की प्रकाशित जानकारी से मेल नहीं खाता",
            "CANNOT_VERIFY": "जाँच नहीं हो सकी",
        },
        "advice": (
            "संदेह होने पर अपने कार्ड, बिल या ब्रांड के आधिकारिक ऐप में दिया नंबर इस्तेमाल करें। "
            "साइबर धोखाधड़ी की रिपोर्ट के लिए 1930 पर कॉल करें या cybercrime.gov.in खोलें।"
        ),
    },
}


def seed_demo_check(store: Store) -> str:
    """Install one fictional, deterministic replay check for a fresh clone."""

    existing = store.list_checks()
    helpline_body = {
        "search_metadata": {"id": "demo-receipt", "status": "Success"},
        "organic_results": [
            {
                "position": 1,
                "title": "Example Air contact",
                "link": "https://example-air.test/contact",
                "snippet": "Call 1800 123 456",
            }
        ],
    }
    maps_body = {
        "search_metadata": {"id": "demo-maps", "status": "Success"},
        "local_results": [
            {
                "position": 1,
                "title": "Example Air Help",
                "phone": "98765 43210",
                "unclaimed_listing": True,
            }
        ],
    }
    ads_body = {
        "search_metadata": {"id": "demo-ads", "status": "Success"},
        "ads": [
            {
                "position": 1,
                "title": "Customer help",
                "link": "https://directory.test/help",
                "description": "Call 98765 43210",
            }
        ],
    }
    official_body = {
        "search_metadata": {"id": "demo-official", "status": "Success"},
        "organic_results": [
            {
                "position": 1,
                "title": "Contact Example Air",
                "link": "https://example-air.test/contact",
                "snippet": "Toll free 1800 123 456",
            }
        ],
    }
    common = {"gl": "in", "google_domain": "google.co.in"}
    cached_steps = [
        (
            "google",
            {
                **common,
                "q": "Example Air customer care number",
                "location": "Mumbai",
                "hl": "en",
                "device": "mobile",
            },
            helpline_body,
            "demo-receipt",
        ),
        (
            "google",
            {
                **common,
                "q": 'site:example-air.test customer care OR helpline OR "toll free" OR contact',
                "hl": "en",
            },
            official_body,
            "demo-official",
        ),
        (
            "google_maps",
            {
                "type": "search",
                "q": "Example Air customer care",
                "hl": "en",
                "location": "Mumbai",
                "z": 12,
            },
            maps_body,
            "demo-maps",
        ),
        (
            "google_ads",
            {"q": "Example Air customer care number", "location": "Mumbai", "hl": "en"},
            ads_body,
            "demo-ads",
        ),
    ]
    hindi_query = "Example Air कस्टमर केयर नंबर"
    cached_steps.extend(
        [
            (
                "google",
                {
                    **common,
                    "q": hindi_query,
                    "location": "Mumbai",
                    "hl": "hi",
                    "device": "mobile",
                },
                helpline_body,
                "demo-receipt-hi",
            ),
            (
                "google_maps",
                {
                    "type": "search",
                    "q": "Example Air customer care",
                    "hl": "hi",
                    "location": "Mumbai",
                    "z": 12,
                },
                maps_body,
                "demo-maps-hi",
            ),
            (
                "google_ads",
                {"q": hindi_query, "location": "Mumbai", "hl": "hi"},
                ads_body,
                "demo-ads-hi",
            ),
        ]
    )
    number_match = normalise_phone("1800 123 456")
    number_params = {**common, "q": " OR ".join(number_match.search_variants), "hl": "en"}
    cached_steps.append(("google", number_params, helpline_body, "demo-number"))
    for engine, parameters, response_body, receipt in cached_steps:
        key = make_cache_key(engine, parameters)
        if not store.latest_search(key):
            store.add_search(key, engine, parameters, receipt, "Success", False, response_body)
    demo = next((check for check in existing if check["id"] == "demo-example-air"), None)
    if demo:
        return str(demo["id"])
    body = {
        **helpline_body,
        "local_results": {
            "places": [
                {
                    "position": 1,
                    "title": "Example Air Help",
                    "phone": "98765 43210",
                    "unclaimed_listing": True,
                }
            ]
        },
        "ads": ads_body["ads"],
    }
    params = {
        "q": "Example Air customer care number",
        "location": "Mumbai",
        "hl": "en",
        "device": "mobile",
    }
    search_id = store.add_search(
        make_cache_key("demo", params), "demo", params, "demo-aggregate", "Success", False, body
    )
    sightings = walk_response(body, search_id, "google")
    references = {"1800123456"}
    results = []
    signals_by_number = {}
    for canonical in dict.fromkeys(item.canonical for item in sightings):
        number_sightings = [item for item in sightings if item.canonical == canonical]
        signals = compute_signals(
            canonical,
            number_sightings[0].kind,
            [],
            number_sightings,
            "example-air.test",
        )
        signals_by_number[canonical] = signals
        decision = decide(canonical, references, signals)
        results.append(
            type(
                "StoredVerdict",
                (),
                {
                    "canonical": canonical,
                    "verdict": decision.verdict,
                    "reasons": decision.reasons,
                },
            )()
        )
    check_id = "demo-example-air"
    store.save_check(
        {
            "id": check_id,
            "mode": "brand",
            "brand_id": "example-air",
            "brand_text": "Example Air",
            "city": "Mumbai",
            "lang": "en",
            "started_at": "2026-10-10T00:00:00+00:00",
            "finished_at": "2026-10-10T00:00:01+00:00",
            "searches_used": 0,
            "skipped": ["Synthetic replay demonstration; no live search was made"],
        },
        sightings,
        signals_by_number,
        results,
    )
    with store.connect() as connection:
        connection.execute(
            """INSERT OR REPLACE INTO brands(id, name, official_domain, domain_verified)
            VALUES (?, ?, ?, ?)""",
            ("example-air", "Example Air", "example-air.test", 0),
        )
        connection.execute(
            """INSERT INTO reference_numbers
            (brand_id, canonical, class, source_kind, source_url, seen_at)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (
                "example-air",
                "1800123456",
                PhoneClass.TOLL_FREE.value,
                "SYNTHETIC_DEMO",
                "https://example-air.test/contact",
                "2026-10-10",
            ),
        )
    return check_id


def _decode_rows(details: dict[str, Any]) -> dict[str, Any]:
    details["skipped"] = json.loads(details.get("skipped_json") or "[]")
    for row in details["verdicts"]:
        row["reasons"] = json.loads(row["reasons_json"])
    for row in details["signals"]:
        row["evidence"] = json.loads(row["evidence_json"])
    return details


def _render_simple_markdown(source: str) -> Markup:
    """Render the small, trusted headings-and-list subset used by LIMITS.md."""

    output: list[str] = []
    in_list = False
    for raw_line in source.splitlines():
        line = raw_line.strip()
        if line.startswith("# "):
            if in_list:
                output.append("</ul>")
                in_list = False
            output.append(f"<h1>{escape(line[2:])}</h1>")
        elif line.startswith("- "):
            if not in_list:
                output.append("<ul>")
                in_list = True
            output.append(f"<li>{escape(line[2:])}</li>")
        elif line:
            if in_list:
                output.append("</ul>")
                in_list = False
            output.append(f"<p>{escape(line)}</p>")
    if in_list:
        output.append("</ul>")
    return Markup("".join(output))


def create_app(settings: Settings | None = None, store: Store | None = None) -> FastAPI:
    settings = settings or get_settings()
    store = store or Store(settings.database_path)
    seed_demo_check(store)
    application = FastAPI(title="Sahi Number")
    application.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    application.state.settings = settings
    application.state.store = store
    serp_client = SerpClient(settings, store)

    async def base_context(request: Request, ui: str = "en") -> dict[str, Any]:
        language = ui if ui in COPY else "en"
        copy = COPY[language]
        mode_label = copy["replay_mode"]
        budget_line = copy["replay_budget"]
        if settings.effective_mode == "live":
            budget_line = copy["live_budget"].format(cap=settings.max_searches_per_check, left="?")
            hourly_left = max(0, settings.hourly_search_limit - store.count_recent_live_searches())
            try:
                monthly_left = await serp_client.credits_left()
                mode_label = (
                    f"{copy['live_mode']} · {monthly_left} {copy['month_left']} · "
                    f"{hourly_left} {copy['hour_left']}"
                )
                budget_line = copy["live_budget"].format(
                    cap=settings.max_searches_per_check, left=monthly_left
                )
            except Exception:
                mode_label = (
                    f"{copy['live_mode']} · {copy['balance_unavailable']} · "
                    f"{hourly_left} {copy['hour_left']}"
                )
        return {
            "request": request,
            "copy": copy,
            "ui": language,
            "mode": settings.effective_mode,
            "mode_label": mode_label,
            "budget_line": budget_line,
        }

    def resolve_brand(value: str) -> Brand:
        cleaned = value.strip()
        for item in load_brands():
            names = {
                item.id.casefold(),
                item.name.casefold(),
                *(alias.casefold() for alias in item.aliases),
            }
            if cleaned.casefold() in names:
                return item
        brand_id = re.sub(r"[^a-z0-9]+", "-", cleaned.casefold()).strip("-")
        if not brand_id:
            raise HTTPException(400, "Enter a brand name")
        return Brand(id=f"free-{brand_id}", name=cleaned)

    @application.get("/", response_class=HTMLResponse)
    async def home(request: Request, ui: str = "en"):
        context = await base_context(request, ui)
        cities = yaml.safe_load((ROOT / "seeds" / "cities.yaml").read_text()) or []
        context.update({"brands": load_brands(), "cities": cities})
        return templates.TemplateResponse(request, "index.html", context)

    @application.post("/check")
    async def create_check(
        background_tasks: BackgroundTasks,
        brand: str = Form(...),
        city: str = Form(...),
        lang: str = Form("en"),
    ):
        selected_brand = resolve_brand(brand)
        cleaned_city = " ".join(city.split())
        if not cleaned_city:
            raise HTTPException(400, "Enter an Indian city, town or locality")
        check_id = uuid.uuid4().hex

        async def run() -> None:
            await Pipeline(settings, store, serp_client).brand_check(
                selected_brand, cleaned_city, lang, check_id=check_id
            )

        background_tasks.add_task(run)
        return RedirectResponse(f"/check/{check_id}", status_code=303)

    @application.post("/number")
    async def create_number_check(number: str = Form(...), brand: str = Form("")):
        selected = resolve_brand(brand) if brand.strip() else None
        try:
            result = await Pipeline(settings, store, serp_client).number_check(number, selected)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        return RedirectResponse(f"/number/{result.id}", status_code=303)

    @application.get("/number/{check_id}", response_class=HTMLResponse)
    async def number_result(request: Request, check_id: str, ui: str = "en"):
        details = store.check_details(check_id)
        if not details or details["mode"] != "number":
            raise HTTPException(404, "Number check not found")
        details = _decode_rows(details)
        domains: dict[str, list[dict[str, Any]]] = {}
        for item in details["sightings"]:
            domains.setdefault(item["domain"] or "unknown", []).append(item)
        brand_record = None
        references: list[dict[str, Any]] = []
        if details["brand_id"]:
            with store.connect() as connection:
                brand_row = connection.execute(
                    "SELECT * FROM brands WHERE id=?", (details["brand_id"],)
                ).fetchone()
                reference_rows = connection.execute(
                    "SELECT * FROM reference_numbers WHERE brand_id=? ORDER BY source_kind",
                    (details["brand_id"],),
                ).fetchall()
            brand_record = dict(brand_row) if brand_row else None
            references = [dict(row) for row in reference_rows]
        canonical = (
            details["verdicts"][0]["canonical"]
            if details["verdicts"]
            else details["sightings"][0]["canonical"]
            if details["sightings"]
            else details["brand_text"]
        )
        context = await base_context(request, ui)
        context.update(
            {
                "check": details,
                "domains": domains,
                "canonical": canonical,
                "display": display_phone(canonical),
                "brand_record": brand_record,
                "references": references,
            }
        )
        return templates.TemplateResponse(request, "number_result.html", context)

    @application.get("/check/{check_id}", response_class=HTMLResponse)
    async def check_result(request: Request, check_id: str, ui: str = "en"):
        details = store.check_details(check_id)
        if not details:
            context = await base_context(request, ui)
            context["check_id"] = check_id
            context["steps"] = store.check_steps(check_id)
            return templates.TemplateResponse(request, "pending.html", context, status_code=202)
        details = _decode_rows(details)
        with store.connect() as connection:
            references = [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM reference_numbers WHERE brand_id=?", (details["brand_id"],)
                ).fetchall()
            ]
            brand_row = connection.execute(
                "SELECT * FROM brands WHERE id=?", (details["brand_id"],)
            ).fetchone()
            history_rows = connection.execute(
                """SELECT canonical, MIN(first_seen) AS first_seen
                FROM number_history WHERE brand_id=? AND city=? AND lang=?
                GROUP BY canonical""",
                (details["brand_id"], details["city"], details["lang"]),
            ).fetchall()
        number_meta = {
            row["canonical"]: {
                "first_seen": row["first_seen"],
                "surfaces": sorted(
                    {
                        item["surface"]
                        for item in details["sightings"]
                        if item["canonical"] == row["canonical"]
                    }
                ),
                "class": next(
                    (
                        item["class"]
                        for item in details["sightings"]
                        if item["canonical"] == row["canonical"]
                    ),
                    "UNKNOWN",
                ),
                "display": display_phone(row["canonical"]),
            }
            for row in history_rows
        }
        context = await base_context(request, ui)
        context.update(
            {
                "check": details,
                "references": references,
                "brand_record": dict(brand_row) if brand_row else None,
                "number_meta": number_meta,
            }
        )
        return templates.TemplateResponse(request, "result.html", context)

    @application.get("/check/{check_id}/fragment", response_class=HTMLResponse)
    async def check_fragment(request: Request, check_id: str, ui: str = "en"):
        response = await check_result(request, check_id, ui)
        template_name = (
            "_result_content.html" if store.get_check(check_id) else "_pending_content.html"
        )
        return templates.TemplateResponse(
            request,
            template_name,
            response.context,
            status_code=response.status_code,
        )

    @application.get("/check/{check_id}/number/{canonical:path}", response_class=HTMLResponse)
    async def number_evidence(request: Request, check_id: str, canonical: str, ui: str = "en"):
        details = store.check_details(check_id)
        if not details:
            raise HTTPException(404, "Check not found")
        details = _decode_rows(details)
        verdict = next((row for row in details["verdicts"] if row["canonical"] == canonical), None)
        if not verdict:
            raise HTTPException(404, "Number not found")
        context = await base_context(request, ui)
        with store.connect() as connection:
            references = [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM reference_numbers WHERE brand_id=?",
                    (details["brand_id"],),
                ).fetchall()
            ]
        context.update(
            {
                "check": details,
                "verdict": verdict,
                "sightings": [row for row in details["sightings"] if row["canonical"] == canonical],
                "signals": [row for row in details["signals"] if row["canonical"] == canonical],
                "references": references,
            }
        )
        return templates.TemplateResponse(request, "evidence.html", context)

    @application.get("/receipt/{search_id}", response_class=HTMLResponse)
    async def receipt(request: Request, search_id: int, ui: str = "en"):
        row = store.get_search(search_id)
        if not row:
            raise HTTPException(404, "Receipt not found")
        context = await base_context(request, ui)
        context.update(
            {
                "receipt": row,
                "params": json.dumps(json.loads(row["params_json"]), indent=2, ensure_ascii=False),
                "body": json.dumps(json.loads(row["body_json"]), indent=2, ensure_ascii=False),
            }
        )
        return templates.TemplateResponse(request, "receipt.html", context)

    @application.get("/sweep", response_class=HTMLResponse)
    async def sweep_matrix(request: Request, ui: str = "en"):
        context = await base_context(request, ui)
        checks = store.matrix_rows()
        columns = sorted({(row["city"], row["lang"]) for row in checks})
        brand_names = list(dict.fromkeys(row["brand_text"] for row in checks))
        latest = {(row["brand_text"], row["city"], row["lang"]): row for row in reversed(checks)}
        context.update(
            {
                "columns": columns,
                "matrix_rows": [
                    {
                        "brand": brand,
                        "cells": [latest.get((brand, city, lang)) for city, lang in columns],
                    }
                    for brand in brand_names
                ],
            }
        )
        return templates.TemplateResponse(request, "sweep.html", context)

    @application.get("/limits", response_class=HTMLResponse)
    async def limits(request: Request, ui: str = "en"):
        context = await base_context(request, ui)
        limits_file = "LIMITS.hi.md" if context["ui"] == "hi" else "LIMITS.md"
        context["limits_html"] = _render_simple_markdown((ROOT / "docs" / limits_file).read_text())
        return templates.TemplateResponse(request, "limits.html", context)

    return application


app = create_app()
