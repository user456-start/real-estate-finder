"""
Chat agent tools for location-aware property questions.

Provides:
  - get_property_details: Fetch current property info + nearby places
  - search_area_guides: RAG search for location context
  - search_more_listings: Find similar listings
  - nearby_places_tool: Spatial queries for POIs
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from geoalchemy2.functions import ST_DWithin, ST_AsText, ST_X, ST_Y
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config import settings
from app.db.database import SessionLocal
from app.db.models import Listing
from app.services.vector_store import get_qdrant

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────
# Property Details Tool
# ──────────────────────────────────────────────────────────────────────────

async def get_property_details(property_id: str, db: Session | None = None) -> dict[str, Any]:
    """
    Fetch property details including:
      - Basic info (price, beds, baths, size, area)
      - Coordinates for spatial queries
      - URL for reference
    """
    if db is None:
        db = SessionLocal()
    
    try:
        # Convert property_id (UUID string) to UUID
        from uuid import UUID
        try:
            uuid_obj = UUID(property_id)
        except ValueError:
            return {"error": f"Invalid property ID format: {property_id}"}
        
        stmt = select(Listing).where(Listing.id == uuid_obj)
        listing = db.execute(stmt).scalar()
        
        if not listing:
            return {"error": f"Property not found: {property_id}"}
        
        # Extract coordinates from PostGIS geometry
        coords = None
        if listing.location:
            try:
                # location is a WKB Point in SRID 4326
                from geoalchemy2.elements import WKBElement
                if isinstance(listing.location, WKBElement):
                    # Get lat, lon as strings
                    result = db.execute(
                        select(
                            ST_X(Listing.location).label("lon"),
                            ST_Y(Listing.location).label("lat")
                        ).where(Listing.id == uuid_obj)
                    ).first()
                    if result:
                        coords = {"lat": float(result.lat), "lon": float(result.lon)}
            except Exception as e:
                logger.error(f"Failed to extract coordinates: {e}")
        
        return {
            "property_id": str(listing.id),
            "title": listing.title,
            "price_aed": float(listing.price_aed) if listing.price_aed else None,
            "is_rental": listing.is_rental,
            "beds": listing.beds,
            "baths": listing.baths,
            "size_sqft": float(listing.size_sqft) if listing.size_sqft else None,
            "area_name": listing.area_name,
            "url": listing.url,
            "coordinates": coords,
            "available": listing.available,
        }
    finally:
        if db is not SessionLocal:
            db.close()


# ──────────────────────────────────────────────────────────────────────────
# Nearby Places Tool (Spatial Query)
# ──────────────────────────────────────────────────────────────────────────

async def nearby_places_tool(
    property_id: str,
    radius_meters: float = 1000,
    db: Session | None = None,
) -> dict[str, Any]:
    """
    Find real nearby POIs (restaurants, gyms, supermarkets, etc.) using PostGIS ST_DWithin.

    Returns:
      - area: the property's area name
      - pois: grouped list of nearby places by type with names and distances
    """
    if db is None:
        db = SessionLocal()

    try:
        from uuid import UUID
        from app.db.models import POI

        try:
            uuid_obj = UUID(property_id)
        except ValueError:
            return {"error": f"Invalid property ID: {property_id}"}

        ref = db.execute(
            select(Listing).where(Listing.id == uuid_obj)
        ).scalar()

        if not ref or not ref.location:
            return {"error": "Property not found or has no coordinates"}

        # Query real POIs within radius, with distance
        rows = db.execute(
            text("""
                SELECT
                    p.name,
                    p.type,
                    ROUND(ST_Distance(
                        p.location::geography,
                        l.location::geography
                    )::numeric) AS distance_m
                FROM pois p, listings l
                WHERE l.id = :listing_id
                  AND ST_DWithin(p.location::geography, l.location::geography, :radius)
                ORDER BY distance_m ASC
                LIMIT 50
            """),
            {"listing_id": str(uuid_obj), "radius": radius_meters},
        ).fetchall()

        # Group by type
        by_type: dict[str, list[dict]] = {}
        for row in rows:
            by_type.setdefault(row.type, []).append({
                "name": row.name,
                "distance_m": int(row.distance_m),
            })

        return {
            "area": ref.area_name,
            "radius_m": radius_meters,
            "pois": by_type,
        }
    finally:
        if db is not SessionLocal:
            db.close()


# ──────────────────────────────────────────────────────────────────────────
# Area Guide RAG Search
# ──────────────────────────────────────────────────────────────────────────

async def search_area_guides(
    query: str,
    area_name: str | None = None,
    top_k: int = 3,
) -> dict[str, Any]:
    """
    Search area guide chunks using semantic search.
    If area_name is provided, scopes results to that area.
    
    Returns:
      - results: list of {text, area_name, score} from Qdrant
      - query: the search query used
    """
    try:
        # Generate embedding for the query
        embedding = await _get_embedding(query)
        if not embedding:
            return {"error": "Failed to generate embedding for query"}
        
        qdrant = get_qdrant()
        
        # Search area guides (with optional area filtering)
        results = qdrant.search_area_guide(
            query_vector=embedding,
            area_name=area_name,
            top_k=top_k,
        )
        
        return {
            "query": query,
            "area_name": area_name,
            "results": results,
        }
    except Exception as e:
        logger.error(f"Area guide search error: {e}")
        return {"error": str(e)}


# ──────────────────────────────────────────────────────────────────────────
# Search More Listings
# ──────────────────────────────────────────────────────────────────────────

async def search_more_listings(
    query: str,
    area_name: str | None = None,
    top_k: int = 5,
) -> dict[str, Any]:
    """
    Semantic search for similar listings.
    
    Returns:
      - results: list of {listing_id, text, score}
      - query: search query used
    """
    try:
        embedding = await _get_embedding(query)
        if not embedding:
            return {"error": "Failed to generate embedding"}
        
        qdrant = get_qdrant()
        results = qdrant.search_listings(
            query_vector=embedding,
            area_name=area_name,
            top_k=top_k,
        )
        
        return {
            "query": query,
            "area_name": area_name,
            "results": results,
        }
    except Exception as e:
        logger.error(f"Listing search error: {e}")
        return {"error": str(e)}


# ──────────────────────────────────────────────────────────────────────────
# Google Places Live Search Tool
# ──────────────────────────────────────────────────────────────────────────

async def google_places_search(
    query: str,
    lat: float,
    lon: float,
    radius_meters: int = 15_000,
) -> dict[str, Any]:
    """
    Live Google Places Text Search for specific named places near a property.

    Use when the user asks about a specific restaurant, supermarket, or chain
    that may not be in the local POI database (e.g. 'Din Tai Fung', 'Lulu Hypermarket').

    Returns closest matches with distance in metres.
    """
    from app.tools.google_places import text_search

    results = await text_search(query, lat, lon, radius_meters)
    return {
        "query": query,
        "search_center": {"lat": lat, "lon": lon},
        "radius_m": radius_meters,
        "results": results,
    }


# ──────────────────────────────────────────────────────────────────────────
# Helper: Embedding Generation (Nomic API — no local model)
# ──────────────────────────────────────────────────────────────────────────

async def _get_embedding(text: str) -> list[float] | None:
    """
    Generate embedding via Nomic API — no local model needed.
    """
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api-atlas.nomic.ai/v1/embedding/text",
                headers={"Authorization": f"Bearer {settings.NOMIC_API_KEY}"},
                json={
                    "model": "nomic-embed-text-v1.5",
                    "texts": [text],
                    "task_type": "search_query",
                },
            )
            resp.raise_for_status()
            return resp.json()["embeddings"][0]
    except Exception as e:
        logger.error(f"Nomic embedding API failed: {e}")
        return None
