"""
Daily property digest — 4-node LangGraph pipeline.

Graph
─────
load_prefs → fetch_listings → rank_listings → compose_email → send_email

Manual run:
    cd backend
    uv run python -m app.agents.digest
"""

from __future__ import annotations

import asyncio
import html as _html
import logging
import math
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from langgraph.graph import END, StateGraph
from sqlalchemy import text
from typing_extensions import TypedDict

from app.config import settings
from app.db.database import SessionLocal
from app.db.models import UserPreferences
from app.services.email import send_email_digest

logger = logging.getLogger(__name__)

TOP_PER_AREA = 3
TOP_OVERALL  = 15


def _force_white_text_on_view_links(html: str) -> str:
    """Ensure CTA-style 'View ...' links stay white in email clients.

    Some email clients aggressively recolor <a> elements to blue unless the
    inline style includes `color:#ffffff !important`.
    """

    def _patch_style(style: str) -> str:
        # Remove any existing color/text-decoration rules, then append ours.
        style = re.sub(r"\bcolor\s*:\s*[^;]+;?", "", style, flags=re.IGNORECASE)
        style = re.sub(r"\btext-decoration\s*:\s*[^;]+;?", "", style, flags=re.IGNORECASE)
        style = style.strip()
        if style and not style.endswith(";"):
            style += ";"
        style += "color:#ffffff !important;text-decoration:none;"
        return style

    a_tag = re.compile(r"<a\b(?P<attrs>[^>]*)>(?P<text>.*?)</a>", re.IGNORECASE | re.DOTALL)

    def _repl(m: re.Match) -> str:
        attrs = m.group("attrs")
        inner = m.group("text")
        text_only = re.sub(r"<[^>]+>", "", inner)
        text_only = _html.unescape(text_only)
        if "view" not in text_only.lower():
            return m.group(0)

        style_attr = re.search(r"\bstyle\s*=\s*(\".*?\"|'.*?')", attrs, flags=re.IGNORECASE | re.DOTALL)
        if style_attr:
            raw = style_attr.group(1)
            quote = raw[0]
            style_val = raw[1:-1]
            patched = _patch_style(style_val)
            attrs2 = (
                attrs[: style_attr.start(1)]
                + quote
                + patched
                + quote
                + attrs[style_attr.end(1) :]
            )
        else:
            attrs2 = attrs + ' style="color:#ffffff !important;text-decoration:none;"'

        return f"<a{attrs2}>{inner}</a>"

    return a_tag.sub(_repl, html)


# ── State ─────────────────────────────────────────────────────────────────────

class DigestState(TypedDict):
    preferences:  Optional[dict]
    metro_pois:   Optional[list]
    mall_pois:    Optional[list]
    listings:     Optional[list]
    ranked:       Optional[list]
    html:         Optional[str]
    sent:         Optional[bool]
    error:        Optional[str]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


def _walk_minutes(km: float) -> float:
    return (km * 1000) / 80


def _nearest(pois: list, lat: Any, lon: Any) -> tuple[float, str]:
    if lat is None or lon is None or not pois:
        return 999.0, ""
    best_km, best_name = min(
        (_haversine_km(lat, lon, p["lat"], p["lon"]), p["name"])
        for p in pois
    )
    return _walk_minutes(best_km), best_name


async def _enrich_og_images(listings: list[dict]) -> list[dict]:
    """
    Fetch og:image for each listing using a shared Playwright browser.
    Plain httpx is blocked by AWS WAF — Playwright passes the JS challenge.
    Uses networkidle so JS-rendered meta tags are present before querying.
    Max 3 pages open in parallel to avoid memory pressure.
    """
    from playwright.async_api import async_playwright

    sem = asyncio.Semaphore(3)

    async def _fetch_one(context, listing: dict) -> dict:
        page = await context.new_page()
        try:
            await page.goto(listing["url"], wait_until="domcontentloaded", timeout=30_000)
            # Wait for og:image to appear — handles WAF JS challenge completing after initial load
            try:
                await page.wait_for_selector('meta[property="og:image"]', timeout=20_000)
            except Exception:
                pass  # tag never appeared — will return None below
            img = await page.evaluate(
                "document.querySelector('meta[property=\"og:image\"]')?.getAttribute('content')"
            )
            await asyncio.sleep(1.0)
            return {**listing, "og_image_url": img}
        except Exception as exc:
            logger.debug("og:image fetch failed for %s: %s", listing["url"], exc)
            return {**listing, "og_image_url": None}
        finally:
            await page.close()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            viewport={"width": 1440, "height": 900},
            locale="en-US",
            timezone_id="Asia/Dubai",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

        # Warm-up: establish WAF cookie before hitting listing pages.
        # The first cold request gets a JS challenge; subsequent pages in the
        # same context reuse the solved cookie and load fully.
        warmup = await context.new_page()
        try:
            await warmup.goto("https://www.propertyfinder.ae/", wait_until="networkidle", timeout=30_000)
            await asyncio.sleep(2)
        except Exception:
            pass
        finally:
            await warmup.close()

        # Sequential — concurrent pages in same context confuse the WAF challenge cookie
        results = []
        for listing in listings:
            results.append(await _fetch_one(context, listing))

        await browser.close()

    found = sum(1 for r in results if r.get("og_image_url"))
    logger.info("enrich_og_images: %d/%d images fetched", found, len(listings))
    return list(results)


# ── Nodes (all async) ─────────────────────────────────────────────────────────

async def load_prefs(state: DigestState) -> dict:
    db = SessionLocal()
    try:
        prefs = db.query(UserPreferences).first()
        if not prefs:
            return {"error": "No user preferences found. Run the seeder first."}

        pref_dict = {
            "min_price":      float(prefs.min_price) if prefs.min_price else None,
            "max_price":      float(prefs.max_price) if prefs.max_price else None,
            "min_beds":       prefs.min_beds,
            "bedrooms":       list(prefs.bedrooms) if prefs.bedrooms else [],
            "min_bathrooms":  prefs.min_bathrooms,
            "furnished":      prefs.furnished,
            "is_rental":      prefs.is_rental,
            "areas":          list(prefs.areas) if prefs.areas else [],
            "extra_criteria": prefs.extra_criteria or {},
        }

        rows = db.execute(
            text("""
                SELECT name, type,
                       ST_Y(location::geometry) AS lat,
                       ST_X(location::geometry) AS lon
                FROM pois WHERE type IN ('metro', 'mall')
            """)
        ).fetchall()

        metro_pois = [{"name": r.name, "lat": r.lat, "lon": r.lon} for r in rows if r.type == "metro"]
        mall_pois  = [{"name": r.name, "lat": r.lat, "lon": r.lon} for r in rows if r.type == "mall"]

        logger.info("load_prefs: areas=%s, metro=%d, mall=%d", pref_dict["areas"], len(metro_pois), len(mall_pois))
        return {
            "preferences": pref_dict,
            "metro_pois":  metro_pois,
            "mall_pois":   mall_pois,
            "error":       None,
        }
    except Exception as exc:
        logger.error("load_prefs failed: %s", exc, exc_info=True)
        return {"error": str(exc)}
    finally:
        db.close()


async def fetch_listings(state: DigestState) -> dict:
    if state.get("error"):
        return {"listings": []}

    prefs  = state["preferences"]
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

    # All column refs prefixed with l. — area_guides join makes bare names ambiguous
    filters = ["l.available = TRUE", "l.fetched_at >= :cutoff"]
    params: dict[str, Any] = {"cutoff": cutoff}

    if prefs.get("min_price"):
        filters.append("l.price_aed >= :min_price")
        params["min_price"] = prefs["min_price"]
    if prefs.get("max_price"):
        filters.append("l.price_aed <= :max_price")
        params["max_price"] = prefs["max_price"]

    # Use IN (...) with literal values — SQLAlchemy text() doesn't handle
    # Python lists for ANY(:param) without explicit array casting
    bedrooms = prefs.get("bedrooms") or []
    if bedrooms:
        placeholders = ",".join(str(int(b)) for b in bedrooms)
        filters.append(f"l.beds IN ({placeholders})")
    elif prefs.get("min_beds") is not None:
        filters.append("l.beds >= :min_beds")
        params["min_beds"] = prefs["min_beds"]

    if prefs.get("min_bathrooms"):
        filters.append("l.baths >= :min_bathrooms")
        params["min_bathrooms"] = prefs["min_bathrooms"]

    areas = prefs.get("areas") or []
    if areas:
        # Escape single quotes in area names and build IN clause
        escaped = [a.replace("'", "''") for a in areas]
        area_list = ",".join(f"'{a}'" for a in escaped)
        filters.append(f"l.area_name IN ({area_list})")

    sql = text(f"""
        SELECT l.id::text, l.url, l.title, l.price_aed, l.beds, l.baths, l.size_sqft,
               l.area_name, l.fetched_at,
               ST_Y(l.location::geometry) AS lat,
               ST_X(l.location::geometry) AS lon,
               p.name AS platform_name,
               ag.content AS area_blurb
        FROM listings l
        LEFT JOIN platforms p ON p.id = l.platform_id
        LEFT JOIN area_guides ag ON ag.area_name = l.area_name
        WHERE {" AND ".join(filters)}
        ORDER BY l.fetched_at DESC
    """)

    db = SessionLocal()
    try:
        rows = db.execute(sql, params).fetchall()
        listings = [dict(r._mapping) for r in rows]
        logger.info("fetch_listings: %d listings matched filters", len(listings))
        return {"listings": listings}
    except Exception as exc:
        logger.error("fetch_listings failed: %s", exc, exc_info=True)
        return {"listings": [], "error": str(exc)}
    finally:
        db.close()


async def rank_listings(state: DigestState) -> dict:
    if state.get("error"):
        return {"ranked": []}

    listings   = state.get("listings") or []
    metro_pois = state.get("metro_pois") or []
    mall_pois  = state.get("mall_pois") or []
    prefs      = state["preferences"]

    # Drop listings missing any field required for display or scoring
    required = ("price_aed", "beds", "baths", "size_sqft", "area_name", "url", "title")
    before = len(listings)
    listings = [l for l in listings if all(l.get(f) for f in required)]
    dropped = before - len(listings)
    if dropped:
        logger.info("rank_listings: dropped %d listings with missing fields (%d remain)", dropped, len(listings))

    min_p = prefs.get("min_price") or 0
    max_p = prefs.get("max_price") or 999_999
    price_range = max(max_p - min_p, 1)

    scored: list[dict] = []
    for l in listings:
        price = float(l["price_aed"] or 0)
        lat, lon = l.get("lat"), l.get("lon")

        price_score = max(0.0, 40 * (1 - (price - min_p) / price_range))
        metro_min, metro_name = _nearest(metro_pois, lat, lon)
        metro_score = max(0.0, 35 * (1 - metro_min / 15))
        mall_min, mall_name = _nearest(mall_pois, lat, lon)
        mall_score = max(0.0, 25 * (1 - mall_min / 20))

        overall = price_score + metro_score + mall_score
        scored.append({
            **l,
            "score":              round(overall, 1),
            "score_value":        round(price_score / 40 * 100),   # 0–100
            "score_location":     round((metro_score + mall_score) / 60 * 100),  # 0–100
            "metro_name":         metro_name,
            "metro_min":          round(metro_min, 1),
            "mall_name":          mall_name,
            "mall_min":           round(mall_min, 1),
            "price_aed":          price,
        })

    by_area: dict[str, list] = {}
    for l in scored:
        by_area.setdefault(l.get("area_name") or "Other", []).append(l)

    top: list[dict] = []
    for area_list in by_area.values():
        area_list.sort(key=lambda x: x["score"], reverse=True)
        top.extend(area_list[:TOP_PER_AREA])

    top.sort(key=lambda x: x["score"], reverse=True)
    top = top[:TOP_OVERALL]

    logger.info("rank_listings: %d scored → top %d", len(scored), len(top))
    return {"ranked": top}


async def compose_email(state: DigestState) -> dict:
    if state.get("error"):
        return {"html": _no_listings_html()}

    ranked = state.get("ranked") or []
    prefs  = state["preferences"]

    if not ranked:
        logger.info("compose_email: no ranked listings — sending empty digest")
        return {"html": _no_listings_html()}

    # Enrich top listings with og:image URLs before composing
    ranked = await _enrich_og_images(ranked)

    run_date      = datetime.now(timezone.utc).strftime("%d %B %Y")
    filters_summary = (
        f"Furnished 1BR, {', '.join(prefs.get('areas') or [])}, "
        f"AED {int(prefs.get('min_price') or 0):,}–{int(prefs.get('max_price') or 0):,}/year"
    )

    # Build a structured JSON block per listing for the prompt
    import json as _json
    properties_json = _json.dumps([
        {
            "title":                          l.get("title", ""),
            "platform_name":                  l.get("platform_name") or "Property Portal",
            "listing_url":                    l.get("url", ""),
            "opengraph_image_url":            l.get("og_image_url"),
            "price_aed":                      int(l["price_aed"]),
            "beds":                           l.get("beds"),
            "baths":                          l.get("baths"),
            "size_sqft":                      int(l.get("size_sqft") or 0),
            "area_name":                      l.get("area_name", ""),
            "score_overall":                  int(l.get("score", 0)),
            "score_location":                 l.get("score_location", 0),
            "score_value_for_money":          l.get("score_value", 0),
            "nearest_metro_name":             l.get("metro_name", ""),
            "nearest_metro_distance_minutes": l.get("metro_min"),
            "nearest_mall_name":              l.get("mall_name", ""),
            "nearest_mall_distance_minutes":  l.get("mall_min"),
            "short_area_blurb":               (l.get("area_blurb") or "")[:300],
        }
        for l in ranked
    ], indent=2)

    prompt = f"""You are an expert product copywriter and HTML email designer.
Your job is to generate a clean, mobile-friendly HTML email for a daily "Top Properties in Dubai" digest.

### Inputs

user_profile:
  name: null
  primary_areas: {_json.dumps(prefs.get('areas') or [])}
  budget_range: "AED {int(prefs.get('min_price') or 0):,}–{int(prefs.get('max_price') or 0):,}/year"

run_metadata:
  run_date: "{run_date}"
  total_properties_considered: (filtered from database, ranked by score)
  filters_summary: "{filters_summary}"

properties:
{properties_json}

### Goals

1. Create a single HTML email that:
   - Renders well on mobile and desktop.
   - Uses simple, text-based icons (e.g. ✓, ◆, ●, ▪, ★) instead of emojis.
   - Shows scores in a compact, readable way without big tables or clutter.
   - Uses opengraph_image_url as the main thumbnail when available; if null, show a styled placeholder div with text "No image available".
2. The email should feel like a professional real-estate digest, not marketing spam.

### Content requirements

1. Subject line comment at the very top of the HTML:
   <!-- SUBJECT: Top {len(ranked)} Dubai properties picked for you – {run_date} -->

2. Intro section (short):
   - In 1–2 sentences explain: this is their daily shortlist, the filters used, and why these listings were chosen (mention location and value scores in plain language).

3. Property cards (one per property):
   - OG image: use <img src="..."> if opengraph_image_url is present; otherwise a styled <div> placeholder.
   - Title + price: e.g. "2BHK in JLT – 75,000 AED / year"
   - Key facts: beds, baths, size, area on one line.
   - Scores (one line): ✓ Overall: 82 | ★ Location: 88 | ◆ Value: 79
   - Nearby: Metro: DMCC (8 min walk) · Mall: Dubai Marina Mall (10 min walk)
   - Short area blurb (1–2 sentences from short_area_blurb).
    - CTA button:
        - Render the button as a small HTML table with an <a> inside, to be email‑client friendly.
        - Use this structure and styling (you may adjust sizes but keep the pattern):

        <table border="0" cellspacing="0" cellpadding="0" role="presentation" style="margin-top:12px;">
            <tr>
            <td align="center" style="border-radius:4px; background-color:#0055AA;">
                <a
                href="{{listing_url}}"
                style="
                    display:inline-block;
                    padding:12px 16px;
                    font-family:Arial, sans-serif;
                    font-size:14px;
                    font-weight:bold;
                    color:#ffffff !important;
                    text-decoration:none;
                "
                >
                View full details on {{platform_name}}
                </a>
            </td>
            </tr>
        </table>

        - The clickable element must be the <a> tag.
        - The <a> must always include: background-color on the wrapping <td>, and color:#ffffff !important; text-decoration:none; on the <a> itself.
    ...

### HTML and styling constraints

- Inline CSS only (email-safe).
- Single-column layout, max-width 600px centered.
- Responsive images: max-width: 100%; height: auto.
- White background, dark text (#1a1a1a), accent color #0055AA for buttons and dividers.
- No emojis. Simple Unicode icons only: ✓ ◆ ● ▪ ★
- Ensure all buttons use the pattern above so that email clients cannot override the button text color to blue.
- Wrap in <html><head>...</head><body>...</body></html>.
- Output valid HTML only — no markdown, no explanation text outside the HTML."""

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        # Compose email
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=8192,
            messages=[{"role": "user", "content": prompt}],
        )
        html = message.content[0].text
        html = _force_white_text_on_view_links(html)
        logger.info("compose_email: generated %d chars of HTML", len(html))
        return {"html": html}
    except Exception as exc:
        logger.error("compose_email failed: %s", exc, exc_info=True)
        return {"html": _no_listings_html(), "error": str(exc)}


async def send_email(state: DigestState) -> dict:
    if state.get("error") and not state.get("html"):
        logger.error("Digest pipeline error — no email sent: %s", state["error"])
        return {"sent": False}

    if not state.get("ranked"):
        logger.info("No new listings — skipping email send")
        return {"sent": False}

    html = state["html"]

    # Extract subject from HTML comment injected by compose_email
    # Format: <!-- SUBJECT: ... -->
    import re
    match = re.search(r"<!--\s*SUBJECT:\s*(.+?)\s*-->", html)
    if match:
        subject = match.group(1).strip()
    else:
        today   = datetime.now(timezone.utc).strftime("%A, %d %b %Y")
        subject = f"Your Dubai Property Digest — {today}"

    sent = send_email_digest(html, subject=subject)
    logger.info("send_email: sent=%s, subject=%r", sent, subject)
    return {"sent": sent}


# ── Graph ─────────────────────────────────────────────────────────────────────

def build_graph():
    g = StateGraph(DigestState)

    g.add_node("load_prefs",     load_prefs)
    g.add_node("fetch_listings", fetch_listings)
    g.add_node("rank_listings",  rank_listings)
    g.add_node("compose_email",  compose_email)
    g.add_node("send_email",     send_email)

    g.set_entry_point("load_prefs")
    g.add_edge("load_prefs",     "fetch_listings")
    g.add_edge("fetch_listings", "rank_listings")
    g.add_edge("rank_listings",  "compose_email")
    g.add_edge("compose_email",  "send_email")
    g.add_edge("send_email",     END)

    return g.compile()


async def run_digest() -> dict[str, Any]:
    initial_state: DigestState = {
        "preferences": None,
        "metro_pois":  None,
        "mall_pois":   None,
        "listings":    None,
        "ranked":      None,
        "html":        None,
        "sent":        None,
        "error":       None,
    }

    # Run digest pipeline
    graph  = build_graph()
    result = await graph.ainvoke(initial_state)
    summary = {
        "listings_fetched": len(result.get("listings") or []),
        "listings_ranked":  len(result.get("ranked") or []),
        "email_sent":       result.get("sent", False),
        "error":            result.get("error"),
    }
    logger.info("Digest complete: %s", summary)
    return summary


# ── Fallback HTML ─────────────────────────────────────────────────────────────

def _no_listings_html() -> str:
    return """
<div style="font-family:sans-serif;max-width:600px;margin:auto;padding:24px;">
  <h2 style="color:#0066CC;">Your Dubai Property Digest</h2>
  <p>No new listings matching your criteria were added in the last 24 hours.</p>
  <p>Check back tomorrow — new listings are fetched every 6 hours.</p>
</div>
"""


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import asyncio
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_digest())
