"""
One-time seed script for Phase 1.

Seeds:
  1. User preferences (your search criteria)
  2. Area guides for 12 key Dubai neighborhoods
  3. Stub POIs (metro stations + major malls) — later replaced by Geoapify bulk load

Run:
    cd backend
    python -m app.services.seeder

Idempotent — safe to re-run. Existing rows are skipped via ON CONFLICT / upsert.
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.database import SessionLocal
from app.db.models import AreaGuide, POI, UserPreferences

logger = logging.getLogger(__name__)


# ── User preferences ─────────────────────────────────────────────────────────

DEFAULT_PREFERENCES = {
    "min_price": 40_000,
    "max_price": 120_000,
    "min_beds": 1,
    "bedrooms": [1],
    "min_bathrooms": 1,
    "furnished": 1,          # 1 = furnished only
    "is_rental": True,
    "areas": ["JLT", "Dubai Marina", "Downtown Dubai", "Business Bay", "DIFC",
              "Palm Jumeirah", "Jumeirah", "Al Barsha"],
    "extra_criteria": {
        "prefer_metro_proximity": True,
        "max_metro_walk_min": 15,
        "prefer_mall_proximity": True,
        "lifestyle_note": "Young professional, values walkability, furnished 1BR near metro and mall",
    },
}


# ── Area guides ───────────────────────────────────────────────────────────────

AREA_GUIDES: list[dict] = [
    {
        "area_name": "JLT",
        "content": (
            "Jumeirah Lake Towers (JLT) is a high-rise residential and commercial district "
            "built around three artificial lakes. It is one of Dubai's most walkable "
            "neighborhoods, with a lively cluster of cafés, restaurants, gyms, and "
            "coworking spaces along the lake promenade. The DMCC and JLT metro stations "
            "are within walking distance of most towers, making commutes to Sheikh Zayed "
            "Road easy. The area is popular with young professionals and expats who want "
            "urban convenience without the price tag of Dubai Marina or Downtown. "
            "Traffic can be heavy during rush hour on the feeder roads. "
            "Pet-friendly parks dot the lakeside. Avg rent for a 1BR: AED 55k–75k/year."
        ),
    },
    {
        "area_name": "Dubai Marina",
        "content": (
            "Dubai Marina is a purpose-built waterfront district stretching along a 3 km "
            "canal lined with skyscrapers, restaurants, and boutiques. The Marina Walk "
            "promenade is excellent for running and cycling. JBR beach is a 5-minute walk. "
            "Two metro stations (DMCC and Sobha Realty) provide good transit access. "
            "The area is vibrant and social but parking is notoriously difficult. "
            "Noise levels are higher than inland neighborhoods. "
            "Popular with European expats and hospitality workers. "
            "Avg rent for a 1BR: AED 75k–110k/year."
        ),
    },
    {
        "area_name": "Downtown Dubai",
        "content": (
            "Downtown Dubai is the city's showpiece district, home to the Burj Khalifa, "
            "The Dubai Mall, and the Dubai Fountain. It offers a cosmopolitan, "
            "walkable environment with a high density of fine dining, luxury retail, "
            "and cultural attractions. The Burj Khalifa/Dubai Mall metro station provides "
            "a direct link to the rest of the network. "
            "Premium prices reflect the prestige address. "
            "Avg rent for a 1BR: AED 90k–140k/year."
        ),
    },
    {
        "area_name": "Business Bay",
        "content": (
            "Business Bay is a mixed-use district bordering Downtown on the Dubai Water "
            "Canal. It has grown rapidly in the last decade with a blend of offices, "
            "hotels, and residential towers. The Business Bay metro station sits at the "
            "edge of the district. The canal boardwalk is a pleasant running route. "
            "Slightly more affordable than Downtown with comparable infrastructure. "
            "Avg rent for a 1BR: AED 70k–100k/year."
        ),
    },
    {
        "area_name": "DIFC",
        "content": (
            "The Dubai International Financial Centre (DIFC) is Dubai's financial hub "
            "and a common destination for professionals working in banking, law, and "
            "consulting. It has a high-end retail and dining corridor (Gate Avenue). "
            "The Financial Centre metro station is steps from Gate Village. "
            "Very limited residential supply keeps rents among the highest in the city. "
            "Avg rent for a 1BR: AED 110k–165k/year."
        ),
    },
    {
        "area_name": "Palm Jumeirah",
        "content": (
            "Palm Jumeirah is Dubai's iconic man-made island shaped like a palm tree, "
            "offering beachfront villas and high-rise apartments. Residents enjoy "
            "private beach access, luxury hotels, and the Nakheel Mall. "
            "The Palm Monorail connects to the Dubai Metro at Atlantis/The Palm Jumeirah "
            "station. Car dependency is high for daily errands. "
            "One of Dubai's most prestigious addresses. "
            "Avg rent for a 1BR: AED 100k–160k/year."
        ),
    },
    {
        "area_name": "Jumeirah",
        "content": (
            "Jumeirah is a traditional residential neighborhood along the coast, "
            "characterised by low-rise villas and townhouses. It has a relaxed, "
            "suburban feel with good international schools, independent cafés, "
            "and the popular Jumeirah Beach Park. Not well-served by metro; "
            "a car or taxi is needed for most errands. "
            "Favoured by families and long-term expats. "
            "Avg rent for a villa: AED 150k–350k/year."
        ),
    },
    {
        "area_name": "Al Barsha",
        "content": (
            "Al Barsha is a mid-range residential area behind Mall of the Emirates, "
            "offering good value for mid-size apartments and villas. "
            "Mall of the Emirates metro station is a short walk or drive away. "
            "The area has good access to supermarkets, schools, and the metro network "
            "without the premium of beachfront districts. "
            "Avg rent for a 1BR: AED 50k–70k/year."
        ),
    },
    {
        "area_name": "Deira",
        "content": (
            "Deira is one of Dubai's oldest commercial districts, home to the gold "
            "and spice souks, the dhow wharfage, and Fish Roundabout. "
            "It is among the most affordable areas in the city and has high cultural "
            "diversity. Several metro stations run through Deira on the Red Line. "
            "Infrastructure is older; traffic can be chaotic. "
            "Popular with blue-collar workers and budget-conscious residents. "
            "Avg rent for a 1BR: AED 28k–45k/year."
        ),
    },
    {
        "area_name": "Bur Dubai",
        "content": (
            "Bur Dubai sits on the western bank of the Dubai Creek, blending historic "
            "heritage (Al Fahidi Fort, Textile Souk) with dense residential and "
            "commercial activity. Good metro coverage along the Green Line. "
            "More affordable than the new districts with a genuine community feel. "
            "Avg rent for a 1BR: AED 32k–52k/year."
        ),
    },
    {
        "area_name": "Mirdif",
        "content": (
            "Mirdif is a quiet, family-oriented suburb near Dubai International Airport. "
            "It is popular with families for its spacious villas, Mushrif Park, and "
            "Mirdif City Centre mall. Metro coverage is indirect (bus connection from "
            "Union station). Low traffic and good community facilities. "
            "Avg rent for a 3BR villa: AED 110k–160k/year."
        ),
    },
    {
        "area_name": "Dubai Silicon Oasis",
        "content": (
            "Dubai Silicon Oasis (DSO) is a free-zone tech hub with integrated "
            "residential, commercial, and retail space. It offers affordable rents "
            "and a self-contained lifestyle. A shuttle service connects to the metro. "
            "Popular with tech workers and families seeking value. "
            "Avg rent for a 1BR: AED 35k–55k/year."
        ),
    },
]


# ── Stub POIs (metro + major malls) ──────────────────────────────────────────
# lat/lon sourced from publicly available map data.
# Full Geoapify bulk load will replace/supplement these in Phase 2.

STUB_POIS: list[dict] = [
    # Metro stations (Dubai Metro Red Line selection)
    {"name": "DMCC Metro Station",            "type": "metro", "lat": 25.0698, "lon": 55.1396},
    {"name": "JLT Metro Station",             "type": "metro", "lat": 25.0766, "lon": 55.1384},
    {"name": "Dubai Marina Metro Station",    "type": "metro", "lat": 25.0789, "lon": 55.1398},
    {"name": "Sobha Realty Metro Station",    "type": "metro", "lat": 25.0948, "lon": 55.1508},
    {"name": "Burj Khalifa/Dubai Mall Metro", "type": "metro", "lat": 25.1972, "lon": 55.2797},
    {"name": "Business Bay Metro Station",    "type": "metro", "lat": 25.1867, "lon": 55.2605},
    {"name": "Financial Centre Metro",        "type": "metro", "lat": 25.2048, "lon": 55.2726},
    {"name": "Mall of the Emirates Metro",    "type": "metro", "lat": 25.1180, "lon": 55.2002},
    {"name": "Union Metro Station",           "type": "metro", "lat": 25.2694, "lon": 55.3100},
    {"name": "Al Rigga Metro Station",        "type": "metro", "lat": 25.2647, "lon": 55.3200},
    # Major malls
    {"name": "Dubai Mall",                    "type": "mall", "lat": 25.1985, "lon": 55.2796},
    {"name": "Mall of the Emirates",          "type": "mall", "lat": 25.1180, "lon": 55.2002},
    {"name": "Ibn Battuta Mall",              "type": "mall", "lat": 25.0434, "lon": 55.1169},
    {"name": "Nakheel Mall",                  "type": "mall", "lat": 25.1122, "lon": 55.1388},
    {"name": "Mirdif City Centre",            "type": "mall", "lat": 25.2188, "lon": 55.4127},
    {"name": "Dubai Festival City Mall",      "type": "mall", "lat": 25.2239, "lon": 55.3541},
    {"name": "BurJuman Centre",               "type": "mall", "lat": 25.2535, "lon": 55.2993},
    {"name": "Deira City Centre",             "type": "mall", "lat": 25.2520, "lon": 55.3305},
]


# ── Seeder ────────────────────────────────────────────────────────────────────

def seed_all() -> None:
    db = SessionLocal()
    try:
        _seed_preferences(db)
        _seed_area_guides(db)
        _seed_pois(db)
        db.commit()
        logger.info("Seeding complete.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _seed_preferences(db) -> None:
    existing = db.query(UserPreferences).first()
    if existing:
        logger.info("UserPreferences already exist — skipping.")
        return
    db.add(UserPreferences(**DEFAULT_PREFERENCES))
    logger.info("Inserted default UserPreferences.")


def _seed_area_guides(db) -> None:
    for guide in AREA_GUIDES:
        stmt = (
            pg_insert(AreaGuide)
            .values(**guide)
            .on_conflict_do_nothing(index_elements=["area_name"])
        )
        db.execute(stmt)
    logger.info("Upserted %d area guides.", len(AREA_GUIDES))


def _seed_pois(db) -> None:
    from geoalchemy2.elements import WKTElement

    for poi in STUB_POIS:
        point = WKTElement(f"POINT({poi['lon']} {poi['lat']})", srid=4326)
        stmt = (
            pg_insert(POI)
            .values(
                name=poi["name"],
                type=poi["type"],
                location=point,
                source="manual_seed",
            )
            # De-duplicate by name so re-runs are safe
            .on_conflict_do_nothing()
        )
        db.execute(stmt)
    logger.info("Upserted %d stub POIs.", len(STUB_POIS))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    seed_all()
