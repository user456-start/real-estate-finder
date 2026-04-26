"""
Supplement the pois table with Google Places data for common categories.

More accurate than Overpass for Dubai commercial chains (Lulu, Carrefour,
Spinneys, malls, metro stations, etc.).

Usage:
    cd backend
    uv run python scripts/fetch_pois_google.py

Costs: ~$0.032 per 1 000 Nearby Search results (free $200/month credit).
For a handful of Dubai areas this is effectively free.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from geoalchemy2.elements import WKTElement
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.config import settings
from app.db.database import SessionLocal
from app.db.models import POI
from app.tools.google_places import nearby_search

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Google Places types to fetch per area
FETCH_TYPES = [
    "supermarket",
    "restaurant",
    "cafe",
    "gym",
    "hospital",
    "pharmacy",
    "school",
    "shopping_mall",
    "subway_station",
    "park",
]

RADIUS_METERS = 3000  # wider than Overpass to catch bigger chains


def get_unique_area_centroids(db) -> list[tuple[str, float, float]]:
    rows = db.execute(text("""
        SELECT area_name,
               AVG(ST_Y(location::geometry)) AS lat,
               AVG(ST_X(location::geometry)) AS lon
        FROM listings
        WHERE location IS NOT NULL
          AND area_name IS NOT NULL
        GROUP BY area_name
    """)).fetchall()
    return [(r.area_name, r.lat, r.lon) for r in rows]


def upsert_pois(db, pois: list[dict]) -> int:
    inserted = 0
    for poi in pois:
        if not poi.get("name"):
            continue
        point = WKTElement(f"POINT({poi['lon']} {poi['lat']})", srid=4326)
        stmt = (
            pg_insert(POI)
            .values(
                name=poi["name"],
                type=poi["type"],
                location=point,
                rating=poi.get("rating"),
                source="google_places",
            )
            .on_conflict_do_nothing()
        )
        db.execute(stmt)
        inserted += 1
    db.commit()
    return inserted


async def fetch_all():
    if not settings.GOOGLE_MAPS_API_KEY:
        logger.error("GOOGLE_MAPS_API_KEY is not set in .env — aborting")
        sys.exit(1)

    db = SessionLocal()
    try:
        areas = get_unique_area_centroids(db)
        logger.info("Fetching Google Places POIs for %d areas", len(areas))

        total = 0
        for area_name, lat, lon in areas:
            logger.info("Area: %s (%.4f, %.4f)", area_name, lat, lon)
            area_total = 0
            for place_type in FETCH_TYPES:
                pois = await nearby_search(lat, lon, place_type, radius_meters=RADIUS_METERS)
                count = upsert_pois(db, pois)
                area_total += count
                await asyncio.sleep(0.2)  # stay within QPS limit
            logger.info("  → %d POIs for %s", area_total, area_name)
            total += area_total

        logger.info("Done. Total POIs stored: %d", total)
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(fetch_all())
