"""
Property API routes for the frontend.

Endpoints:
  GET  /api/listings          — paginated listings with filters
  GET  /api/listings/shortlist — today's top-ranked listings
  GET  /api/listings/{id}     — single listing with nearby POIs
  GET  /api/listings/{id}/similar — semantically similar listings
  GET  /api/preferences       — current user preferences
  PUT  /api/preferences       — update user preferences
  GET  /api/pois              — all POIs (metro, malls)
"""

from __future__ import annotations

import math
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from geoalchemy2.functions import ST_DWithin, ST_X, ST_Y
from pydantic import BaseModel
from sqlalchemy import func, select, text

from app.db.database import SessionLocal
from app.db.models import AreaGuide, Listing, Platform, POI, UserPreferences

router = APIRouter(prefix="/api", tags=["properties"])


# ── Schemas ──────────────────────────────────────────────────────────────────

class ListingSummary(BaseModel):
    id: str
    title: str
    price_aed: float | None
    beds: int | None
    baths: int | None
    size_sqft: float | None
    area_name: str | None
    url: str
    lat: float | None
    lon: float | None
    platform_name: str | None
    fetched_at: str | None
    image_url: str | None = None

class ListingsResponse(BaseModel):
    listings: list[ListingSummary]
    total: int
    page: int
    limit: int

class POISummary(BaseModel):
    name: str
    type: str
    lat: float
    lon: float
    distance_min: float | None = None

class ListingDetail(BaseModel):
    id: str
    title: str
    description: str | None
    price_aed: float | None
    beds: int | None
    baths: int | None
    size_sqft: float | None
    area_name: str | None
    url: str
    lat: float | None
    lon: float | None
    platform_name: str | None
    fetched_at: str | None
    image_url: str | None = None
    area_blurb: str | None
    nearby_pois: list[POISummary]

class RankedListing(BaseModel):
    id: str
    title: str
    price_aed: float | None
    beds: int | None
    baths: int | None
    size_sqft: float | None
    area_name: str | None
    url: str
    lat: float | None
    lon: float | None
    platform_name: str | None
    image_url: str | None = None
    score: float
    score_value: int
    score_location: int
    metro_name: str
    metro_min: float
    mall_name: str
    mall_min: float

class PreferencesOut(BaseModel):
    min_price: float | None
    max_price: float | None
    min_beds: int | None
    bedrooms: list[int]
    min_bathrooms: int | None
    furnished: int | None
    is_rental: bool
    areas: list[str]
    extra_criteria: dict | None

class PreferencesIn(BaseModel):
    min_price: float | None = None
    max_price: float | None = None
    min_beds: int | None = None
    bedrooms: list[int] | None = None
    min_bathrooms: int | None = None
    furnished: int | None = None
    is_rental: bool = True
    areas: list[str] | None = None
    extra_criteria: dict | None = None


# ── Helpers ──────────────────────────────────────────────────────────────────

def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


# ── GET /api/listings ────────────────────────────────────────────────────────

@router.get("/listings", response_model=ListingsResponse)
def list_listings(
    area: Optional[str] = Query(None),
    min_price: Optional[float] = Query(None),
    max_price: Optional[float] = Query(None),
    beds: Optional[int] = Query(None),
    furnished: Optional[int] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
):
    db = SessionLocal()
    try:
        q = (
            select(
                Listing.id,
                Listing.title,
                Listing.price_aed,
                Listing.beds,
                Listing.baths,
                Listing.size_sqft,
                Listing.area_name,
                Listing.url,
                Listing.fetched_at,
                Listing.image_url,
                ST_Y(Listing.location).label("lat"),
                ST_X(Listing.location).label("lon"),
                Platform.name.label("platform_name"),
            )
            .join(Platform, Platform.id == Listing.platform_id, isouter=True)
            .where(Listing.available == True)
        )

        # Apply filters
        if area:
            areas = [a.strip() for a in area.split(",")]
            q = q.where(Listing.area_name.in_(areas))
        if min_price is not None:
            q = q.where(Listing.price_aed >= min_price)
        if max_price is not None:
            q = q.where(Listing.price_aed <= max_price)
        if beds is not None:
            q = q.where(Listing.beds == beds)

        # Count total
        count_q = select(func.count()).select_from(q.subquery())
        total = db.execute(count_q).scalar() or 0

        # Paginate
        q = q.order_by(Listing.fetched_at.desc()).offset((page - 1) * limit).limit(limit)
        rows = db.execute(q).all()

        listings = [
            ListingSummary(
                id=str(r.id),
                title=r.title,
                price_aed=float(r.price_aed) if r.price_aed else None,
                beds=r.beds,
                baths=r.baths,
                size_sqft=float(r.size_sqft) if r.size_sqft else None,
                area_name=r.area_name,
                url=r.url,
                lat=float(r.lat) if r.lat else None,
                lon=float(r.lon) if r.lon else None,
                platform_name=r.platform_name,
                fetched_at=r.fetched_at.isoformat() if r.fetched_at else None,
                image_url=r.image_url,
            )
            for r in rows
        ]

        return ListingsResponse(listings=listings, total=total, page=page, limit=limit)
    finally:
        db.close()


# ── GET /api/listings/shortlist ──────────────────────────────────────────────

@router.get("/listings/shortlist", response_model=list[RankedListing])
def get_shortlist():
    """Return today's top-ranked listings using the digest scoring algorithm."""
    db = SessionLocal()
    try:
        prefs = db.query(UserPreferences).first()
        if not prefs:
            return []

        # Fetch POIs
        poi_rows = db.execute(
            text("""
                SELECT name, type,
                       ST_Y(location::geometry) AS lat,
                       ST_X(location::geometry) AS lon
                FROM pois WHERE type IN ('metro', 'mall')
            """)
        ).fetchall()
        metro_pois = [{"name": r.name, "lat": r.lat, "lon": r.lon} for r in poi_rows if r.type == "metro"]
        mall_pois = [{"name": r.name, "lat": r.lat, "lon": r.lon} for r in poi_rows if r.type == "mall"]

        # Build filters
        filters = ["l.available = TRUE"]
        params: dict[str, Any] = {}

        min_p = float(prefs.min_price) if prefs.min_price else None
        max_p = float(prefs.max_price) if prefs.max_price else None

        if min_p:
            filters.append("l.price_aed >= :min_price")
            params["min_price"] = min_p
        if max_p:
            filters.append("l.price_aed <= :max_price")
            params["max_price"] = max_p

        bedrooms = list(prefs.bedrooms) if prefs.bedrooms else []
        if bedrooms:
            placeholders = ",".join(str(int(b)) for b in bedrooms)
            filters.append(f"l.beds IN ({placeholders})")

        if prefs.min_bathrooms:
            filters.append("l.baths >= :min_bathrooms")
            params["min_bathrooms"] = prefs.min_bathrooms

        areas = list(prefs.areas) if prefs.areas else []
        if areas:
            escaped = [a.replace("'", "''") for a in areas]
            area_list = ",".join(f"'{a}'" for a in escaped)
            filters.append(f"l.area_name IN ({area_list})")

        sql = text(f"""
            SELECT l.id::text, l.title, l.price_aed, l.beds, l.baths, l.size_sqft,
                   l.area_name, l.url, l.image_url,
                   ST_Y(l.location::geometry) AS lat,
                   ST_X(l.location::geometry) AS lon,
                   p.name AS platform_name
            FROM listings l
            LEFT JOIN platforms p ON p.id = l.platform_id
            WHERE {" AND ".join(filters)}
            ORDER BY l.fetched_at DESC
        """)

        rows = db.execute(sql, params).fetchall()
        listings = [dict(r._mapping) for r in rows]

        # Filter out incomplete
        required = ("price_aed", "beds", "baths", "size_sqft", "area_name", "url", "title")
        listings = [l for l in listings if all(l.get(f) for f in required)]

        # Score
        min_price = min_p or 0
        max_price = max_p or 999_999
        price_range = max(max_price - min_price, 1)

        def _nearest(pois, lat, lon):
            if lat is None or lon is None or not pois:
                return 999.0, ""
            best_km, best_name = min(
                (_haversine_km(lat, lon, p["lat"], p["lon"]), p["name"])
                for p in pois
            )
            return (best_km * 1000) / 80, best_name  # walk minutes

        scored = []
        for l in listings:
            price = float(l["price_aed"] or 0)
            lat, lon = l.get("lat"), l.get("lon")

            price_score = max(0.0, 40 * (1 - (price - min_price) / price_range))
            metro_min, metro_name = _nearest(metro_pois, lat, lon)
            metro_score = max(0.0, 35 * (1 - metro_min / 15))
            mall_min, mall_name = _nearest(mall_pois, lat, lon)
            mall_score = max(0.0, 25 * (1 - mall_min / 20))
            overall = price_score + metro_score + mall_score

            scored.append({
                **l,
                "score": round(overall, 1),
                "score_value": round(price_score / 40 * 100),
                "score_location": round((metro_score + mall_score) / 60 * 100),
                "metro_name": metro_name,
                "metro_min": round(metro_min, 1),
                "mall_name": mall_name,
                "mall_min": round(mall_min, 1),
            })

        # Top 3 per area, top 15 overall
        by_area: dict[str, list] = {}
        for l in scored:
            by_area.setdefault(l.get("area_name") or "Other", []).append(l)

        top: list[dict] = []
        for area_list in by_area.values():
            area_list.sort(key=lambda x: x["score"], reverse=True)
            top.extend(area_list[:3])

        top.sort(key=lambda x: x["score"], reverse=True)
        top = top[:15]

        return [
            RankedListing(
                id=l["id"],
                title=l["title"],
                price_aed=float(l["price_aed"]) if l["price_aed"] else None,
                beds=l["beds"],
                baths=l["baths"],
                size_sqft=float(l["size_sqft"]) if l["size_sqft"] else None,
                area_name=l["area_name"],
                url=l["url"],
                lat=float(l["lat"]) if l.get("lat") else None,
                lon=float(l["lon"]) if l.get("lon") else None,
                platform_name=l.get("platform_name"),
                image_url=l.get("image_url"),
                score=l["score"],
                score_value=l["score_value"],
                score_location=l["score_location"],
                metro_name=l["metro_name"],
                metro_min=l["metro_min"],
                mall_name=l["mall_name"],
                mall_min=l["mall_min"],
            )
            for l in top
        ]
    finally:
        db.close()


# ── GET /api/listings/{id} ───────────────────────────────────────────────────

@router.get("/listings/{listing_id}", response_model=ListingDetail)
def get_listing(listing_id: str):
    db = SessionLocal()
    try:
        uid = UUID(listing_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid listing ID")

    try:
        row = db.execute(
            select(
                Listing.id,
                Listing.title,
                Listing.description,
                Listing.price_aed,
                Listing.beds,
                Listing.baths,
                Listing.size_sqft,
                Listing.area_name,
                Listing.url,
                Listing.fetched_at,
                Listing.image_url,
                ST_Y(Listing.location).label("lat"),
                ST_X(Listing.location).label("lon"),
                Platform.name.label("platform_name"),
            )
            .join(Platform, Platform.id == Listing.platform_id, isouter=True)
            .where(Listing.id == uid)
        ).first()

        if not row:
            raise HTTPException(status_code=404, detail="Listing not found")

        # Area guide blurb
        area_blurb = None
        if row.area_name:
            guide = db.query(AreaGuide).filter(AreaGuide.area_name == row.area_name).first()
            if guide:
                area_blurb = guide.content

        # Nearby POIs (within ~2km)
        nearby_pois: list[POISummary] = []
        if row.lat and row.lon:
            poi_rows = db.execute(
                text("""
                    SELECT name, type,
                           ST_Y(location::geometry) AS lat,
                           ST_X(location::geometry) AS lon
                    FROM pois
                    ORDER BY location <-> ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)
                    LIMIT 10
                """),
                {"lat": row.lat, "lon": row.lon},
            ).fetchall()

            for p in poi_rows:
                dist_km = _haversine_km(row.lat, row.lon, p.lat, p.lon)
                walk_min = (dist_km * 1000) / 80
                nearby_pois.append(POISummary(
                    name=p.name,
                    type=p.type,
                    lat=p.lat,
                    lon=p.lon,
                    distance_min=round(walk_min, 1),
                ))

        return ListingDetail(
            id=str(row.id),
            title=row.title,
            description=None,  # skip for now, can be large
            price_aed=float(row.price_aed) if row.price_aed else None,
            beds=row.beds,
            baths=row.baths,
            size_sqft=float(row.size_sqft) if row.size_sqft else None,
            area_name=row.area_name,
            url=row.url,
            lat=float(row.lat) if row.lat else None,
            lon=float(row.lon) if row.lon else None,
            platform_name=row.platform_name,
            fetched_at=row.fetched_at.isoformat() if row.fetched_at else None,
            image_url=row.image_url,
            area_blurb=area_blurb,
            nearby_pois=nearby_pois,
        )
    finally:
        db.close()


# ── GET /api/listings/{id}/similar ───────────────────────────────────────────

@router.get("/listings/{listing_id}/similar", response_model=list[ListingSummary])
def get_similar(listing_id: str, limit: int = Query(6, ge=1, le=20)):
    """Find similar listings by area + price range."""
    db = SessionLocal()
    try:
        uid = UUID(listing_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid listing ID")

    try:
        ref = db.execute(select(Listing).where(Listing.id == uid)).scalar()
        if not ref:
            raise HTTPException(status_code=404, detail="Listing not found")

        # Find in same area, similar price range
        price = float(ref.price_aed) if ref.price_aed else 0
        margin = price * 0.3  # +/- 30%

        q = (
            select(
                Listing.id,
                Listing.title,
                Listing.price_aed,
                Listing.beds,
                Listing.baths,
                Listing.size_sqft,
                Listing.area_name,
                Listing.url,
                Listing.fetched_at,
                Listing.image_url,
                ST_Y(Listing.location).label("lat"),
                ST_X(Listing.location).label("lon"),
                Platform.name.label("platform_name"),
            )
            .join(Platform, Platform.id == Listing.platform_id, isouter=True)
            .where(
                Listing.available == True,
                Listing.id != uid,
                Listing.area_name == ref.area_name,
                Listing.price_aed.between(price - margin, price + margin),
            )
            .order_by(func.abs(Listing.price_aed - price))
            .limit(limit)
        )

        rows = db.execute(q).all()
        return [
            ListingSummary(
                id=str(r.id),
                title=r.title,
                price_aed=float(r.price_aed) if r.price_aed else None,
                beds=r.beds,
                baths=r.baths,
                size_sqft=float(r.size_sqft) if r.size_sqft else None,
                area_name=r.area_name,
                url=r.url,
                lat=float(r.lat) if r.lat else None,
                lon=float(r.lon) if r.lon else None,
                platform_name=r.platform_name,
                fetched_at=r.fetched_at.isoformat() if r.fetched_at else None,
                image_url=r.image_url,
            )
            for r in rows
        ]
    finally:
        db.close()


# ── GET /api/preferences ────────────────────────────────────────────────────

@router.get("/preferences", response_model=PreferencesOut)
def get_preferences():
    db = SessionLocal()
    try:
        prefs = db.query(UserPreferences).first()
        if not prefs:
            raise HTTPException(status_code=404, detail="No preferences set")
        return PreferencesOut(
            min_price=float(prefs.min_price) if prefs.min_price else None,
            max_price=float(prefs.max_price) if prefs.max_price else None,
            min_beds=prefs.min_beds,
            bedrooms=list(prefs.bedrooms) if prefs.bedrooms else [],
            min_bathrooms=prefs.min_bathrooms,
            furnished=prefs.furnished,
            is_rental=prefs.is_rental,
            areas=list(prefs.areas) if prefs.areas else [],
            extra_criteria=prefs.extra_criteria,
        )
    finally:
        db.close()


# ── PUT /api/preferences ────────────────────────────────────────────────────

@router.put("/preferences", response_model=PreferencesOut)
def update_preferences(data: PreferencesIn):
    db = SessionLocal()
    try:
        prefs = db.query(UserPreferences).first()
        if not prefs:
            prefs = UserPreferences()
            db.add(prefs)

        if data.min_price is not None:
            prefs.min_price = data.min_price
        if data.max_price is not None:
            prefs.max_price = data.max_price
        if data.min_beds is not None:
            prefs.min_beds = data.min_beds
        if data.bedrooms is not None:
            prefs.bedrooms = data.bedrooms
        if data.min_bathrooms is not None:
            prefs.min_bathrooms = data.min_bathrooms
        if data.furnished is not None:
            prefs.furnished = data.furnished
        if data.areas is not None:
            prefs.areas = data.areas
        if data.extra_criteria is not None:
            prefs.extra_criteria = data.extra_criteria
        prefs.is_rental = data.is_rental

        db.commit()
        db.refresh(prefs)

        return PreferencesOut(
            min_price=float(prefs.min_price) if prefs.min_price else None,
            max_price=float(prefs.max_price) if prefs.max_price else None,
            min_beds=prefs.min_beds,
            bedrooms=list(prefs.bedrooms) if prefs.bedrooms else [],
            min_bathrooms=prefs.min_bathrooms,
            furnished=prefs.furnished,
            is_rental=prefs.is_rental,
            areas=list(prefs.areas) if prefs.areas else [],
            extra_criteria=prefs.extra_criteria,
        )
    finally:
        db.close()


# ── GET /api/pois ────────────────────────────────────────────────────────────

@router.get("/pois")
def get_pois(type: Optional[str] = Query(None)):
    db = SessionLocal()
    try:
        rows = db.execute(
            text("""
                SELECT name, type,
                       ST_Y(location::geometry) AS lat,
                       ST_X(location::geometry) AS lon
                FROM pois
                ORDER BY type, name
            """)
        ).fetchall()

        pois = [
            {"name": r.name, "type": r.type, "lat": r.lat, "lon": r.lon}
            for r in rows
            if type is None or r.type == type
        ]
        return pois
    finally:
        db.close()
