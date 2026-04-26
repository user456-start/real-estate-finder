"""
JustProperty scraper — Playwright + network interception.

JustProperty.com is a smaller UAE portal with lower traffic and therefore
lighter bot protection than Bayut / Property Finder.

To verify / update the API endpoint:
    Open justproperty.com in Chrome DevTools → Network → XHR/Fetch
    Look for requests returning JSON arrays of property objects.
    Update _API_PATTERNS below if the endpoint path differs.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from app.tools.scrapers.base import BaseScraper
from app.tools.scrapers.normalizer import RawListing, to_float, to_int

logger = logging.getLogger(__name__)

_BASE = "https://www.justproperty.com"

_API_PATTERNS = ("/api/properties", "/api/search", "/en/api/", "/properties/search", "/api/v")

AREA_SLUGS: dict[str, str] = {
    "JLT":                 "jumeirah-lake-towers",
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


class JustPropertyScraper(BaseScraper):
    platform_name = "justproperty"
    page_size = 20
    max_pages = 5

    async def fetch_page(self, preferences: dict[str, Any], page: int) -> list[RawListing]:
        areas = preferences.get("areas") or ["Dubai Marina"]
        results: list[RawListing] = []
        for area in areas:
            slug = AREA_SLUGS.get(area, "dubai")
            purpose = "for-rent" if preferences.get("is_rental", True) else "for-sale"
            url = f"{_BASE}/en/properties-{purpose}/dubai/{slug}/?page={page}"
            results.extend(await self._fetch_area_page(url, preferences))
        return results

    async def _fetch_area_page(self, url: str, preferences: dict[str, Any]) -> list[RawListing]:
        captured: list[dict] = []
        page = await self._new_page()

        async def handle_response(response):
            if any(p in response.url for p in _API_PATTERNS) and response.status == 200:
                try:
                    body = await response.json()
                    props = (
                        body.get("properties")
                        or body.get("listings")
                        or body.get("hits")
                        or body.get("data", {}).get("properties", [])
                        or body.get("results", [])
                    )
                    if isinstance(props, list) and props:
                        captured.extend(props)
                except Exception:
                    pass

        page.on("response", handle_response)
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            for _ in range(20):
                await asyncio.sleep(0.5)
                if captured:
                    break
        except Exception as exc:
            logger.warning("[justproperty] page load error: %s", exc)
        finally:
            await page.close()

        if not captured:
            captured = await self._extract_next_data(url)

        return [self._parse(p) for p in captured if self._is_active(p)]

    async def _extract_next_data(self, url: str) -> list[dict]:
        page = await self._new_page()
        props_list: list[dict] = []
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            html = await page.content()
            m = re.search(
                r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
                html, re.DOTALL,
            )
            if m:
                data = json.loads(m.group(1))
                page_props = data.get("props", {}).get("pageProps", {})
                props_list = (
                    page_props.get("properties")
                    or page_props.get("listings")
                    or page_props.get("searchResult", {}).get("properties", [])
                    or []
                )
        except Exception as exc:
            logger.warning("[justproperty] __NEXT_DATA__ extraction failed: %s", exc)
        finally:
            await page.close()
        return props_list

    @staticmethod
    def _is_active(prop: dict) -> bool:
        status = (prop.get("status") or prop.get("availability") or "active").lower()
        return status not in ("sold", "let", "inactive", "unavailable", "off_market", "rented")

    @staticmethod
    def _parse(prop: dict[str, Any]) -> RawListing:
        geo = prop.get("coordinates") or prop.get("location") or prop.get("geo") or {}
        if isinstance(geo, dict):
            lat = to_float(geo.get("lat") or geo.get("latitude"))
            lon = to_float(geo.get("lng") or geo.get("lon") or geo.get("longitude"))
        else:
            lat = lon = None

        slug = prop.get("url") or prop.get("slug") or prop.get("permalink") or ""
        url = f"{_BASE}/{slug.lstrip('/')}" if slug and not slug.startswith("http") else slug

        return RawListing(
            platform="justproperty",
            external_id=str(prop.get("id") or prop.get("reference_no") or prop.get("ref", "")),
            url=url,
            title=prop.get("title") or prop.get("name", ""),
            description=prop.get("description", ""),
            price_aed=to_float(prop.get("price") or prop.get("annual_price") or prop.get("rent")),
            is_rental=prop.get("purpose", "rent") not in ("sale", "for-sale"),
            beds=to_int(prop.get("bedrooms") or prop.get("beds")),
            baths=to_int(prop.get("bathrooms") or prop.get("baths")),
            size_sqft=to_float(prop.get("size") or prop.get("area") or prop.get("area_sqft")),
            area_name=prop.get("community") or prop.get("area_name") or prop.get("location"),
            lat=lat,
            lon=lon,
            updated_at=prop.get("updated_at") or prop.get("date_updated") or prop.get("listed_at"),
        )
