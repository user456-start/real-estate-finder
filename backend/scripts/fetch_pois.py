"""
Fetch real POI data from OpenStreetMap (Overpass API) for all listing areas.

Fetches: restaurants, cafes, gyms, supermarkets, hospitals, pharmacies, schools
Stores results in the pois table using PostGIS geometry.

Usage:
    cd backend
    uv run python scripts/fetch_pois.py

Free, no API key needed. Rate-limited to 1 request/second to be polite.
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
from geoalchemy2.elements import WKTElement
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.database import SessionLocal
from app.db.models import POI

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
RADIUS_METERS = 1500

# OSM amenity tags → our POI type labels
CATEGORIES = {
    "restaurant":   "restaurant",
    "cafe":         "cafe",
    "fast_food":    "restaurant",
    "gym":          "gym",
    "fitness_centre": "gym",
    "supermarket":  "supermarket",
    "grocery":      "supermarket",
    "hospital":     "hospital",
    "clinic":       "hospital",
    "pharmacy":     "pharmacy",
    "school":       "school",
    "college":      "school",
    "university":   "school",
    "beach":        "beach",
    "park":         "park",
}


def fetch_pois_for_area(lat: float, lon: float, radius: int = RADIUS_METERS) -> list[dict]:
    """Query Overpass API for all relevant POIs within radius of lat/lon."""
    tags = "|".join(CATEGORIES.keys())
    query = f"""
[out:json][timeout:30];
(
  node["amenity"~"{tags}"](around:{radius},{lat},{lon});
  node["leisure"="fitness_centre"](around:{radius},{lat},{lon});
  node["natural"="beach"](around:{radius},{lat},{lon});
  node["leisure"="park"](around:{radius},{lat},{lon});
);
out body;
"""
    try:
        response = httpx.post(
            OVERPASS_URL,
            data={"data": query},
            headers={"User-Agent": "curl/8.5.0", "Accept": "*/*"},
            timeout=35,
        )
        response.raise_for_status()
        elements = response.json().get("elements", [])

        pois = []
        for el in elements:
            tags_data = el.get("tags", {})
            name = tags_data.get("name") or tags_data.get("name:en")
            if not name:
                continue  # skip unnamed places

            amenity = tags_data.get("amenity") or tags_data.get("leisure") or tags_data.get("natural")
            poi_type = CATEGORIES.get(amenity, amenity)

            pois.append({
                "name": name,
                "type": poi_type,
                "lat":  el["lat"],
                "lon":  el["lon"],
            })
        return pois
    except Exception as e:
        logger.error("Overpass query failed: %s", e)
        return []


def get_unique_area_centroids(db) -> list[tuple[str, float, float]]:
    """Get one representative lat/lon per area_name from listings."""
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
        point = WKTElement(f"POINT({poi['lon']} {poi['lat']})", srid=4326)
        stmt = (
            pg_insert(POI)
            .values(
                name=poi["name"],
                type=poi["type"],
                location=point,
                source="overpass",
            )
            .on_conflict_do_nothing()
        )
        db.execute(stmt)
        inserted += 1
    db.commit()
    return inserted


def main():
    db = SessionLocal()
    try:
        areas = get_unique_area_centroids(db)
        logger.info("Found %d unique areas to fetch POIs for", len(areas))

        total = 0
        for area_name, lat, lon in areas:
            logger.info("Fetching POIs for %s (%.4f, %.4f) ...", area_name, lat, lon)
            pois = fetch_pois_for_area(lat, lon)
            count = upsert_pois(db, pois)
            total += count
            logger.info("  → %d POIs stored for %s", count, area_name)
            time.sleep(1)  # polite rate limiting

        logger.info("Done. Total POIs stored: %d", total)
    finally:
        db.close()


if __name__ == "__main__":
    main()
