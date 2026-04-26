"""
Property Finder scraper — Navigate search pages and extract from __NEXT_DATA__.
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


_SEARCH_URL = "https://www.propertyfinder.ae/en/search"

# Area IDs (numeric) — verified from Network tab in Chrome DevTools
AREA_SLUGS: dict[str, str] = {
    "JLT":                     "71",
    "Dubai Marina":            "50",
    "Downtown Dubai":          "41",
    "Business Bay":            "36",
    "DIFC":                    "39",
    "Palm Jumeirah":           "86",
    "Jumeirah":                "66",   # Not found yet
    "Al Barsha":               "13",
    "International City":      "63",
    "Al Nahda":                "173",
    "Jumeirah Village Circle": "73",
}


import httpx
from app.config import settings

class PropertyFinderScraper(BaseScraper):
    platform_name = "property_finder"
    page_size = 25
    max_pages = 5

    async def fetch_page(self, preferences: dict[str, Any], page: int) -> list[RawListing]:
        areas = preferences.get("areas")
        if not areas:
            areas = list(AREA_SLUGS.keys())
        
        logger.info("[property_finder] page %d — scraping %d areas: %s", page, len(areas), areas)
        results: list[RawListing] = []
        for area in areas:
            area_id = AREA_SLUGS.get(area)
            if not area_id or area_id == "?":
                continue
            
            listings = await self._fetch_area_rapidapi(area, area_id, preferences, page)
            results.extend(listings)
            
            # Rate limit protection for RapidAPI free tiers (usually 1 req/sec limit)
            await asyncio.sleep(3.0)
        
        return results

    async def _fetch_area_rapidapi(self, area_name: str, area_id: str, 
                                   preferences: dict[str, Any], page: int) -> list[RawListing]:
        """Fetch listings using the RapidAPI endpoint specifically requested by the user."""
        if not settings.RAPIDAPI_KEY:
            logger.error("RAPIDAPI_KEY is not set in environment or config.py!")
            print("ERROR: RapidAPI key required! Add RAPIDAPI_KEY to your .env file.")
            return []

        url = "https://propertyfinder-uae-data.p.rapidapi.com/search-rent"
        
        # Build query specific to RapidAPI
        params: dict[str, str] = {
            "location_id": area_id,
            "page": str(page),
            "sort": "newest",
            "property_type": "apartment",
            "rent_frequency": "yearly"
        }
        
        if preferences.get("min_price"):
            params["price_min"] = str(int(preferences["min_price"]))
        if preferences.get("max_price"):
            params["price_max"] = str(int(preferences["max_price"]))
            
        if preferences.get("bedrooms"):
            params["bedrooms"] = ",".join(str(b) for b in preferences["bedrooms"])
        elif preferences.get("min_beds") is not None:
            params["bedrooms"] = str(preferences["min_beds"])
            
        if preferences.get("furnished") == 1:
            params["furnishing"] = "furnished"
        elif preferences.get("furnished") == 0:
            params["furnishing"] = "unfurnished"

        headers = {
            "x-rapidapi-key": settings.RAPIDAPI_KEY,
            "x-rapidapi-host": "propertyfinder-uae-data.p.rapidapi.com",
            "Content-Type": "application/json"
        }
        
        print(f"\n--- Fetching via RapidAPI: {area_name} (Page {page}) ---")
        print(f"URL: {url}?{'&'.join(f'{k}={v}' for k,v in params.items())}")
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url, headers=headers, params=params)
                print(f"RapidAPI Status: {response.status_code}")
                
                if response.status_code == 429:
                    print("Hit RapidAPI Rate Limit (Too many requests). Waiting 5 seconds before continuing.")
                    await asyncio.sleep(5.0)
                    # Simple single retry
                    response = await client.get(url, headers=headers, params=params)
                    print(f"Retry Status: {response.status_code}")
                
                if response.status_code != 200:
                    print(f"RapidAPI Error Response: {response.text[:200]}")
                    return []
                    
                data = response.json()
                
                # RapidAPI returns list in data["data"]["listings"] or data["content"] depending exactly on which clone of the API
                # Print keys to help user debug
                print(f"RapidAPI Response Keys: {list(data.keys())}")
                
                # Adjust based on observed RapidAPI json schema
                # E.g. usually data["data"] -> array
                listings = data.get("data", []) if "data" in data else data
                if not isinstance(listings, list):
                    print("Unexpected RapidAPI structure. Could not find list of listings.")
                    return []
                    
                print(f"Successfully pulled {len(listings)} listings from RapidAPI!")
                
                # We need to map RapidAPI schema to our Schema
                parsed_listings = []
                for item in listings:
                    parsed_listings.append(self._parse_rapidapi(item, area_name))
                    
                return parsed_listings
        except Exception as e:
            print(f"RapidAPI failed: {e}")
            logger.exception("RapidAPI error")
            return []
            
    @staticmethod
    def _parse_rapidapi(prop: dict[str, Any], fallback_area: str) -> RawListing:
        # Match RapidAPI keys to RawListing
        price_dict = prop.get("price", {})
        price = to_float(price_dict.get("value", 0))
        
        size_dict = prop.get("size", {})
        size = to_float(size_dict.get("value", 0))
        
        # Geolocation
        lat, lon = None, None
        address = prop.get("address", {})
        coords = address.get("coordinates", {})
        if coords:
            lat = to_float(coords.get("lat"))
            lon = to_float(coords.get("lon"))
            
        # Get area from location tree (usually level 1 is community like Dubai Marina)
        area_name = fallback_area
        location_tree = prop.get("location_tree", [])
        for node in location_tree:
            if node.get("level") == "1":
                area_name = node.get("name")
                break
                
        # Bedrooms - could be "studio"
        beds_raw = prop.get("bedrooms")
        beds = 0 if beds_raw == "studio" else to_int(beds_raw)
            
        # Extract first photo — RapidAPI uses several different shapes
        image_url: str | None = None
        photos = prop.get("photos") or prop.get("images") or []
        if photos and isinstance(photos, list):
            first = photos[0]
            if isinstance(first, dict):
                image_url = first.get("url") or first.get("src") or first.get("thumb") or first.get("uri")
            elif isinstance(first, str):
                image_url = first
        if not image_url:
            # Fallback: cover_photo / thumbnail fields
            cover = prop.get("cover_photo") or prop.get("thumbnail") or {}
            if isinstance(cover, dict):
                image_url = cover.get("url") or cover.get("src")
            elif isinstance(cover, str):
                image_url = cover

        return RawListing(
            platform="property_finder",
            external_id=str(prop.get("property_id") or prop.get("reference_number", "")),
            url=prop.get("property_url", ""),
            title=prop.get("title", ""),
            description=prop.get("description", ""),  # Sometimes missing in list view
            price_aed=price,
            is_rental=True, # search-rent endpoint
            beds=beds,
            baths=to_int(prop.get("bathrooms")),
            size_sqft=size,
            area_name=area_name,
            lat=lat,
            lon=lon,
            image_url=image_url,
            updated_at=prop.get("listed_date"),
        )

    async def _fetch_area_via_url(self, area_name: str, area_id: str, 
                                   preferences: dict[str, Any], page: int) -> list[RawListing]:
        """Fetch listings by navigating to the search URL with area parameters."""
        # Build URL with area and other filters
        params = self._build_query(preferences, page, area_id)
        
        # Handle both scalar and array parameters
        import urllib.parse
        query_parts = []
        for k, v in params.items():
            if isinstance(v, list):
                for item in v:
                    # Property Finder does not want URL-encoded brackets for array keys 
                    # so we leave them unencoded manually rather than urlencode(params)
                    query_parts.append(f"{urllib.parse.quote(k, safe='[]')}={urllib.parse.quote(str(item))}")
            else:
                query_parts.append(f"{urllib.parse.quote(k)}={urllib.parse.quote(str(v))}")
                
        # the parameters must be urlencoded but without encoding the array brackets []
        encoded_query = "&".join(query_parts)
        url = _SEARCH_URL + "?" + encoded_query
        
        pfy_page = await self._new_page()
        try:
            # Setup a request interceptor to block images and useless scripts to load faster + look like normal scraper
            await pfy_page.route("**/*", lambda route: route.abort() if route.request.resource_type in ["image", "media", "font"] else route.continue_())
            
            # Setup user agent properly
            await pfy_page.set_extra_http_headers({
                "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
                "accept-language": "en-US,en;q=0.9",
                "sec-ch-ua": "\"Not A(Brand\";v=\"99\", \"Google Chrome\";v=\"121\", \"Chromium\";v=\"121\"",
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": "\"Windows\"",
                "sec-fetch-dest": "document",
                "sec-fetch-mode": "navigate",
                "sec-fetch-site": "none",
                "sec-fetch-user": "?1",
                "upgrade-insecure-requests": "1"
            })
            
            # Random wait to avoid simple bot detection
            await asyncio.sleep(1)
            
            await pfy_page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            
            # Use stealth page interactions to help bypass PerimeterX
            await pfy_page.mouse.move(100, 100)
            await asyncio.sleep(0.5)
            await pfy_page.mouse.move(200, 200)
            await asyncio.sleep(1)

            # Wait exactly for __NEXT_DATA__
            html = await pfy_page.content()
            
            if "px-captcha" in html or "Human Challenge" in html or "Checking if the site connection is secure" in html:
                logger.warning(f"[property_finder] Hit bot protection/captcha on area '{area_name}'! URL: {url}")
                # Optional: await pfy_page.waitForTimeout(10000) to allow solving manually in headed mode
                return []
                
            m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.DOTALL)
            
            if not m:
                # Log a snippet of the HTML to see what we're actually getting (captcha? empty page? different structure?)
                logger.warning(f"[property_finder] Could not find __NEXT_DATA__ for area '{area_name}'. URL: {url}")
                logger.debug(f"[property_finder] HTML snippet: {html[:500]}...")
                return []
            
            data = json.loads(m.group(1))
            logger.debug("[property_finder] __NEXT_DATA__ keys: %s", list(data.keys()))
            
            # Navigate to pageProps.pageProps.results
            # Or in some formats, pageProps.searchResult.properties
            page_props = data.get("props", {}).get("pageProps", {})
            props = page_props.get("searchResult", {}).get("properties", [])
            
            if not props:
                props = page_props.get("properties", [])
            
            if not props:
                props = page_props.get("results", [])
            
            # If props is still empty, look aggressively through the object
            if not props:
                try:
                    for k, v in page_props.items():
                        if isinstance(v, dict) and "properties" in v:
                            props = v["properties"]
                            break
                except Exception:
                    pass
                    
            logger.info("[property_finder] page %d / area='%s' → %d listings from __NEXT_DATA__", page, area_name, len(props))
            return [self._parse(p) for p in props]
            
        except Exception as e:
            logger.warning("[property_finder] Failed to fetch area '%s' (id=%s): %s", area_name, area_id, e)
            return []
        finally:
            await pfy_page.close()

    @staticmethod
    def _build_query(prefs: dict[str, Any], page: int, area_id: str) -> dict[str, Any]:
        """Build query parameters for Property Finder search.
        
        Using core parameters that reliably bypass bot protection.
        """
        params: dict[str, Any] = {
            "c":  "2",                                        # Apartments
            "t":  "42" if prefs.get("is_rental", True) else "3",  # Rental type code
            "l":  area_id,                                    # Location ID (numeric)
            "ob": "mr",                                       # most recent
            "pn": str(page),
        }
        
        # Price range
        if prefs.get("min_price"):
            params["pf"] = str(int(prefs["min_price"]))
        if prefs.get("max_price"):
            params["pt"] = str(int(prefs["max_price"]))
            
        # Bedrooms - using 'b' parameter which is safer
        if prefs.get("bedrooms") and len(prefs["bedrooms"]) > 0:
            # Taking the min value of the array as 'b' usually takes a single string
            params["b"] = str(min(prefs["bedrooms"]))
        elif prefs.get("min_beds") is not None:
            params["b"] = str(prefs["min_beds"])
            
        # Furnished
        if prefs.get("furnished") is not None:
            params["fu"] = str(prefs["furnished"])
            
        return params

    @staticmethod
    def _parse(prop: dict[str, Any]) -> RawListing:
        # Price is a dict: {"value": 120000, "currency": "AED", "period": "yearly", ...}
        price_raw = prop.get("price") or {}
        price_aed = to_float(price_raw.get("value") if isinstance(price_raw, dict) else price_raw)

        # Size is a dict: {"value": 850, "unit": "sqft"}
        size_raw = prop.get("size") or {}
        size_sqft = to_float(size_raw.get("value") if isinstance(size_raw, dict) else size_raw)

        # Area from location_tree — use COMMUNITY level (the neighbourhood)
        # Tree: [CITY, COMMUNITY, SUBCOMMUNITY, TOWER, ...]
        area_name = None
        location_tree = prop.get("location_tree") or []
        for node in location_tree:
            if isinstance(node, dict) and node.get("type") == "COMMUNITY":
                area_name = node.get("name")
                break
        if not area_name and location_tree:
            # Fallback: second entry (index 1) is usually the community
            area_name = location_tree[1].get("name") if len(location_tree) > 1 else location_tree[0].get("name")

        # Coordinates are nested: location.coordinates.{lat, lon}
        loc = prop.get("location") or {}
        coords = loc.get("coordinates") or loc if isinstance(loc, dict) else {}
        lat = to_float(coords.get("lat") or coords.get("latitude"))
        lon = to_float(coords.get("lon") or coords.get("lng") or coords.get("longitude"))

        # URL from details_path: "/en/rent/apartments/dubai-marina/..."
        details_path = prop.get("details_path") or prop.get("share_url") or ""
        if details_path.startswith("/"):
            url = f"https://www.propertyfinder.ae{details_path}"
        elif details_path.startswith("http"):
            url = details_path
        else:
            url = ""

        return RawListing(
            platform="property_finder",
            external_id=str(prop.get("listing_id") or prop.get("reference") or prop.get("id", "")),
            url=url,
            title=prop.get("title") or prop.get("name", ""),
            description=prop.get("description", ""),
            price_aed=price_aed,
            is_rental=prop.get("offering_type") != "sale",
            beds=to_int(prop.get("bedrooms") or prop.get("beds")),
            baths=to_int(prop.get("bathrooms") or prop.get("baths")),
            size_sqft=size_sqft,
            area_name=area_name,
            lat=lat,
            lon=lon,
            updated_at=prop.get("last_refreshed_at") or prop.get("listed_date"),
        )
