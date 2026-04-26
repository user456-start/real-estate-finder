"""
Bayut scraper — uses Playwright to load the search page, then intercepts
the internal listing API call the page makes to capture the JSON directly.

This bypasses CloudFront + CAPTCHA challenges that block plain HTTP clients.

Coverage: Bayut + Dubizzle UAE (same backend, same listings).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from app.tools.scrapers.base import BaseScraper
from app.tools.scrapers.normalizer import RawListing, to_float, to_int

logger = logging.getLogger(__name__)

# Search URL pattern — Playwright navigates here as a real browser would
_SEARCH_URL = "https://www.bayut.com/to-{purpose}/apartments/{location}/"

AREA_SLUGS: dict[str, str] = {
    "JLT":                 "jumeirah-lake-towers-jlt",
    "Dubai Marina":        "dubai-marina",
    "Downtown Dubai":      "downtown-dubai",
    "Business Bay":        "business-bay",
    "DIFC":                "difc",
    "Palm Jumeirah":       "palm-jumeirah",
    "Jumeirah":            "jumeirah",
    "Al Barsha":           "al-barsha",
    "Deira":               "deira",
    "Bur Dubai":           "bur-dubai",
    "Mirdif":              "mirdif",
    "Dubai Silicon Oasis": "dubai-silicon-oasis",
}


class BayutScraper(BaseScraper):
    platform_name = "bayut"
    page_size = 25

    async def fetch_page(self, preferences: dict[str, Any], page: int) -> list[RawListing]:
        areas = preferences.get("areas") or ["Dubai Marina"]
        results: list[RawListing] = []

        for area in areas:
            slug = AREA_SLUGS.get(area, "dubai")
            purpose = "rent" if preferences.get("is_rental", True) else "sale"
            url = _SEARCH_URL.format(purpose=purpose, location=slug)

            params = self._build_query(preferences, page)
            full_url = url + "?" + "&".join(f"{k}={v}" for k, v in params.items())

            listings = await self._fetch_area_page(full_url)
            results.extend(listings)

        return results

    async def _fetch_area_page(self, url: str) -> list[RawListing]:
        """
        Navigate to the search URL and intercept the listing API response.
        Bayut's Next.js frontend fetches listings via a JSON endpoint —
        we capture that response rather than parsing the HTML.
        """
        captured: list[dict] = []
        page = await self._new_page()

        async def handle_response(response):
            # Intercept the internal listing data endpoint
            if "/api/v4/listings" in response.url and response.status == 200:
                try:
                    body = await response.json()
                    hits = body.get("hits") or body.get("results") or []
                    captured.extend(hits)
                except Exception:
                    pass

        page.on("response", handle_response)

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            # Wait up to 10s for the listing API call to fire; stop early if it does
            for _ in range(20):
                await asyncio.sleep(0.5)
                if captured:
                    break
        except Exception as exc:
            logger.warning("[bayut] page load error for %s: %s", url, exc)
        finally:
            await page.close()

        if not captured:
            # Fallback: try to extract __NEXT_DATA__ from the page HTML
            captured = await self._extract_next_data(url)

        return [self._parse(hit) for hit in captured]

    async def _extract_next_data(self, url: str) -> list[dict]:
        """Fallback: parse __NEXT_DATA__ JSON embedded in the HTML."""
        import re
        page = await self._new_page()
        hits = []
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            html = await page.content()
            m = re.search(
                r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
                html, re.DOTALL
            )
            if m:
                data = json.loads(m.group(1))
                # Walk the props tree to find the listing array
                props = data.get("props", {}).get("pageProps", {})
                search_result = (
                    props.get("searchResult")
                    or props.get("data", {}).get("searchResult", {})
                )
                hits = (search_result or {}).get("hits", [])
        except Exception as exc:
            logger.warning("[bayut] __NEXT_DATA__ extraction failed: %s", exc)
        finally:
            await page.close()
        return hits

    @staticmethod
    def _build_query(prefs: dict[str, Any], page: int) -> dict[str, str]:
        params: dict[str, str] = {
            "sort": "date_desc",
            "page": str(page),
        }
        if prefs.get("min_price"):
            params["price_min"] = str(int(prefs["min_price"]))
        if prefs.get("max_price"):
            params["price_max"] = str(int(prefs["max_price"]))
        if prefs.get("min_beds"):
            params["beds_min"] = str(prefs["min_beds"])
        return params

    @staticmethod
    def _parse(hit: dict[str, Any]) -> RawListing:
        lat = lon = None
        geo = hit.get("geography") or {}
        if geo:
            lat = to_float(geo.get("lat"))
            lon = to_float(geo.get("lng"))

        area_name: str | None = None
        for loc in (hit.get("location") or []):
            if loc.get("type") == "neighbourhood":
                area_name = loc.get("name")
                break
        if not area_name:
            locations = hit.get("location") or []
            if locations:
                area_name = locations[-1].get("name")

        return RawListing(
            platform="bayut",
            external_id=str(hit.get("id", "")),
            url=f"https://www.bayut.com{hit.get('slug', '')}",
            title=hit.get("title", ""),
            description=hit.get("description", ""),
            price_aed=to_float(hit.get("price")),
            is_rental=hit.get("purpose") != "for-sale",
            beds=to_int(hit.get("rooms")),
            baths=to_int(hit.get("baths")),
            size_sqft=to_float(hit.get("area")),
            area_name=area_name,
            lat=lat,
            lon=lon,
            updated_at=hit.get("updatedAt") or hit.get("addedAt"),
        )
