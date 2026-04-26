"""
Google Places API helpers.

Nearby Search  — populate the pois table with accurate chain data (supermarkets, malls…)
Text Search    — live lookup at chat time for specific named places (Din Tai Fung, Lulu…)
"""

from __future__ import annotations

import logging
import math
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_NEARBY_URL = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
_TEXT_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"

# Google place types → our POI type labels
GOOGLE_TYPE_MAP = {
    "supermarket": "supermarket",
    "grocery_or_supermarket": "supermarket",
    "restaurant": "restaurant",
    "cafe": "cafe",
    "gym": "gym",
    "hospital": "hospital",
    "pharmacy": "pharmacy",
    "school": "school",
    "university": "school",
    "shopping_mall": "mall",
    "subway_station": "metro",
    "train_station": "metro",
    "park": "park",
    "beach": "beach",
}


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> int:
    """Approximate distance in metres between two WGS-84 points."""
    r = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return round(r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))


async def nearby_search(
    lat: float,
    lon: float,
    place_type: str,
    radius_meters: int = 3000,
    keyword: str | None = None,
) -> list[dict[str, Any]]:
    """
    Google Places Nearby Search.
    Returns raw place dicts suitable for upserting into the pois table.
    """
    if not settings.GOOGLE_MAPS_API_KEY:
        logger.warning("GOOGLE_MAPS_API_KEY not set — skipping nearby_search")
        return []

    params: dict[str, Any] = {
        "location": f"{lat},{lon}",
        "radius": radius_meters,
        "type": place_type,
        "key": settings.GOOGLE_MAPS_API_KEY,
    }
    if keyword:
        params["keyword"] = keyword

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(_NEARBY_URL, params=params)
            resp.raise_for_status()
            data = resp.json()

        results = []
        for p in data.get("results", []):
            loc = p.get("geometry", {}).get("location", {})
            p_lat, p_lon = loc.get("lat"), loc.get("lng")
            if p_lat is None or p_lon is None:
                continue
            results.append({
                "name": p.get("name"),
                "type": GOOGLE_TYPE_MAP.get(place_type, place_type),
                "lat": p_lat,
                "lon": p_lon,
                "rating": p.get("rating"),
                "source": "google_places",
            })
        return results

    except Exception as e:
        logger.error("Google Places nearby_search failed: %s", e)
        return []


async def text_search(
    query: str,
    lat: float,
    lon: float,
    radius_meters: int = 15_000,
) -> list[dict[str, Any]]:
    """
    Google Places Text Search — find specific named places near coordinates.
    Ideal for queries like 'Din Tai Fung' or 'Lulu Hypermarket'.
    """
    if not settings.GOOGLE_MAPS_API_KEY:
        logger.warning("GOOGLE_MAPS_API_KEY not set — skipping text_search")
        return []

    params = {
        "query": query,
        "location": f"{lat},{lon}",
        "radius": radius_meters,
        "key": settings.GOOGLE_MAPS_API_KEY,
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(_TEXT_URL, params=params)
            resp.raise_for_status()
            data = resp.json()

        results = []
        for p in data.get("results", [])[:5]:
            loc = p.get("geometry", {}).get("location", {})
            p_lat, p_lon = loc.get("lat"), loc.get("lng")
            if p_lat is None or p_lon is None:
                continue
            results.append({
                "name": p.get("name"),
                "address": p.get("formatted_address"),
                "lat": p_lat,
                "lon": p_lon,
                "rating": p.get("rating"),
                "distance_m": _haversine_m(lat, lon, p_lat, p_lon),
            })

        return sorted(results, key=lambda x: x["distance_m"])

    except Exception as e:
        logger.error("Google Places text_search failed: %s", e)
        return []
