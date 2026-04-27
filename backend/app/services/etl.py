"""
ETL orchestrator — runs all scrapers, normalizes, upserts to Postgres,
marks stale listings, and indexes new descriptions in Qdrant.

Called by the scheduler every 6 hours, or manually:
    uv run python -m app.services.etl
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from geoalchemy2.elements import WKTElement
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

import httpx

from app.config import settings
from app.db.database import SessionLocal
from app.db.models import Listing, Platform, UserPreferences
from app.services.vector_store import get_qdrant
from app.tools.scrapers.normalizer import RawListing, dedup_across_platforms, description_hash
from app.tools.scrapers.property_finder import PropertyFinderScraper

logger = logging.getLogger(__name__)

STALE_AFTER_HOURS = 48   # mark listing unavailable if not seen in this window


async def run_etl() -> dict[str, Any]:
    """
    Full ETL run. Returns a summary dict for logging / observability.

    Steps:
        1. Load user preferences from DB
        2. Fetch listings from all platforms (incremental if not first run)
        3. Dedup cross-platform
        4. Upsert to Postgres
        5. Mark stale listings unavailable
        6. Index new/changed descriptions in Qdrant
    """
    get_qdrant().ensure_collections()

    # Run ETL pipeline
    db = SessionLocal()
    try:
        prefs = _load_preferences(db)

        # ── 1. Fetch ──────────────────────────────────────────────────
        raw_listings: list[RawListing] = []

        scrapers = [
            (PropertyFinderScraper, "property_finder"),
            # (BayutScraper,          "bayut"),         # blocked by CloudFront on datacenter IPs
            # (BhomesScraper,         "bhomes"),        # API pattern unknown
            # (BehomesScraper,        "behomes"),       # API pattern unknown
            # (HouzaScraper,          "houza"),         # domain doesn't exist
            # (JustPropertyScraper,   "justproperty"),  # domain doesn't exist
        ]

        for ScraperClass, platform_name in scrapers:
            since = _last_fetched(db, platform_name)
            run_type = "incremental" if since else "full"
            logger.info("[%s] starting %s load (since=%s)", platform_name, run_type, since)

            # Scrape platform
            async with ScraperClass() as scraper:
                results = await scraper.scrape(prefs, since=since)
            raw_listings.extend(results)

        # ── 2. Dedup ──────────────────────────────────────────────────
        # Deduplicate listings
        deduped = dedup_across_platforms(raw_listings)

        # ── 3. Upsert ─────────────────────────────────────────────────
        # Upsert to database
        upserted, to_embed = _upsert_listings(db, deduped)
        for _, platform_name in scrapers:
            _update_last_fetched(db, platform_name)
        db.commit()

        # ── 4. Mark stale ─────────────────────────────────────────────
        # Mark stale listings
        stale = _mark_stale(db)
        db.commit()

        # ── 5. Index in Qdrant ────────────────────────────────────────
        # Index in Qdrant
        indexed = await _index_listings(to_embed)

        summary = {
            "raw_fetched": len(raw_listings),
            "after_dedup": len(deduped),
            "upserted": upserted,
            "marked_stale": stale,
            "indexed_in_qdrant": indexed,
        }
        logger.info("ETL complete: %s", summary)
        return summary

    except Exception as exc:
        db.rollback()
        logger.error("ETL failed: %s", exc, exc_info=True)
        raise
    finally:
        db.close()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_preferences(db) -> dict[str, Any]:
    prefs = db.query(UserPreferences).first()
    if not prefs:
        raise RuntimeError("No user preferences found. Run the seeder first.")
    return {
        "min_price":      float(prefs.min_price) if prefs.min_price else None,
        "max_price":      float(prefs.max_price) if prefs.max_price else None,
        "min_beds":       prefs.min_beds,
        "bedrooms":       prefs.bedrooms or [],
        "min_bathrooms":  prefs.min_bathrooms,
        "max_bathrooms":  prefs.max_bathrooms,
        "furnished":      prefs.furnished,
        "is_rental":      prefs.is_rental,
        "areas":          prefs.areas or [],
    }


def _last_fetched(db, platform_name: str) -> datetime | None:
    platform = db.query(Platform).filter_by(name=platform_name).first()
    return platform.last_fetched_at if platform else None


def _update_last_fetched(db, platform_name: str) -> None:
    db.query(Platform).filter_by(name=platform_name).update(
        {"last_fetched_at": datetime.now(timezone.utc)}
    )
    db.commit()


def _upsert_listings(
    db, listings: list[RawListing]
) -> tuple[int, list[dict[str, Any]]]:
    """
    Upsert listings into Postgres.
    Returns (upserted_count, list_of_rows_needing_embedding).
    A row needs embedding when it's new OR its description changed.

    We pre-fetch existing description hashes in one bulk query so we can
    compare BEFORE the upsert overwrites them (post-upsert SELECT always
    returns the new hash, making change detection impossible).
    """
    platform_cache: dict[str, int] = {}
    to_embed: list[dict[str, Any]] = []
    upserted = 0

    # ── Build platform cache ──────────────────────────────────────────────────
    for raw in listings:
        name = raw.get("platform", "")
        if name and name not in platform_cache:
            p = db.query(Platform).filter_by(name=name).first()
            if p:
                platform_cache[name] = p.id
            else:
                logger.warning("Platform '%s' not in DB — skipping its listings", name)

    logger.info("Upsert: starting with %d listings, platforms in cache: %s", len(listings), list(platform_cache.keys()))

    # ── Pre-fetch existing hashes (platform_id, external_id) → hash ──────────
    existing_hashes: dict[tuple[int, str], str | None] = {}
    for raw in listings:
        pid = platform_cache.get(raw.get("platform", ""))
        if pid is None:
            continue
        eid = raw.get("external_id", "")
        row = db.execute(
            text("SELECT id, description_hash FROM listings WHERE platform_id=:p AND external_id=:e"),
            {"p": pid, "e": eid},
        ).fetchone()
        existing_hashes[(pid, eid)] = (str(row.id), row.description_hash) if row else None

    # ── Upsert each listing ───────────────────────────────────────────────────
    for raw in listings:
        platform_name = raw.get("platform", "")
        platform_id = platform_cache.get(platform_name)
        if platform_id is None:
            logger.warning("Platform '%s' not found in DB — run: alembic upgrade head", platform_name)
            continue

        external_id = raw.get("external_id", "")
        desc_hash = description_hash(raw.get("description"))
        prior = existing_hashes.get((platform_id, external_id))  # None = new row

        location = None
        lat, lon = raw.get("lat"), raw.get("lon")
        if lat is not None and lon is not None:
            location = WKTElement(f"POINT({lon} {lat})", srid=4326)

        values = {
            "platform_id":       platform_id,
            "external_id":       external_id,
            "url":               raw.get("url", ""),
            "title":             raw.get("title", ""),
            "description":       raw.get("description", ""),
            "price_aed":         raw.get("price_aed"),
            "is_rental":         raw.get("is_rental", True),
            "beds":              raw.get("beds"),
            "baths":             raw.get("baths"),
            "size_sqft":         raw.get("size_sqft"),
            "area_name":         raw.get("area_name"),
            "location":          location,
            "available":         True,
            "fetched_at":        datetime.now(timezone.utc),
            "description_hash":  desc_hash,
            "image_url":         raw.get("image_url"),
        }

        stmt = (
            pg_insert(Listing)
            .values(**values)
            .on_conflict_do_update(
                constraint="uq_listing_platform_external",
                set_={
                    "title":            values["title"],
                    "description":      values["description"],
                    "price_aed":        values["price_aed"],
                    "beds":             values["beds"],
                    "baths":            values["baths"],
                    "size_sqft":        values["size_sqft"],
                    "area_name":        values["area_name"],
                    "location":         values["location"],
                    "available":        True,
                    "fetched_at":       values["fetched_at"],
                    "description_hash": values["description_hash"],
                    # Only overwrite image_url if the new scrape actually got one
                    # (preserves backfilled og:image for listings that still have no RapidAPI photo)
                    "image_url": text(
                        "CASE WHEN EXCLUDED.image_url IS NOT NULL THEN EXCLUDED.image_url "
                        "ELSE listings.image_url END"
                    ),
                },
            )
            .returning(Listing.id, Listing.area_name, Listing.price_aed)
        )
        result = db.execute(stmt).fetchone()
        if not result:
            continue

        upserted += 1
        is_new = prior is None
        old_hash = prior[1] if prior else None

        if upserted % 100 == 0:
            logger.info("Upsert: %d/%d rows processed so far", upserted, len(listings))

        if is_new or old_hash != desc_hash:
            to_embed.append({
                "listing_id": str(result.id),
                "text":       raw.get("description") or raw.get("title", ""),
                "area_name":  raw.get("area_name", ""),
                "price_aed":  raw.get("price_aed"),
            })

    logger.info("Upsert complete: %d upserted, %d need embedding", upserted, len(to_embed))
    return upserted, to_embed


def _mark_stale(db) -> int:
    """Mark listings not seen in the last STALE_AFTER_HOURS as unavailable,
    and remove them from the Qdrant vector index."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=STALE_AFTER_HOURS)
    result = db.execute(
        text(
            "UPDATE listings SET available = FALSE "
            "WHERE available = TRUE AND fetched_at < :cutoff "
            "RETURNING id"
        ),
        {"cutoff": cutoff},
    )
    stale_ids = [str(row.id) for row in result.fetchall()]
    if stale_ids:
        from app.services.vector_store import get_qdrant, COLLECTION_LISTINGS, _str_to_uint
        qdrant = get_qdrant()
        qdrant._client.delete(
            collection_name=COLLECTION_LISTINGS,
            points_selector=[_str_to_uint(lid) for lid in stale_ids],
        )
        logger.info("Removed %d stale listings from Qdrant", len(stale_ids))
    return len(stale_ids)


async def _embed(text: str) -> list[float] | None:
    """Generate embedding via Nomic API."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api-nomic.ai/v1/embedding/text",
                headers={"Authorization": f"Bearer {settings.NOMIC_API_KEY}"},
                json={"model": "nomic-embed-text-v1.5", "texts": [text], "task_type": "search_document"},
            )
            resp.raise_for_status()
            return resp.json()["embeddings"][0]
    except Exception as exc:
        logger.error("Nomic embed failed: %s", exc)
        return None


async def _index_listings(to_embed: list[dict[str, Any]]) -> int:
    """Embed listing descriptions and upsert into Qdrant."""
    qdrant = get_qdrant()
    indexed = 0
    for item in to_embed:
        try:
            vector = await _embed(item["text"])
            if not vector:
                continue
            qdrant.upsert_listing(
                listing_id=item["listing_id"],
                text=item["text"],
                embedding=vector,
                area_name=item.get("area_name", ""),
                price_aed=item.get("price_aed"),
            )
            indexed += 1
        except Exception as exc:
            logger.error("Failed to embed listing %s: %s", item["listing_id"], exc)
    return indexed


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import asyncio
    logging.basicConfig(level=logging.INFO)

    # Ensure Qdrant collections exist (FastAPI lifespan doesn't run from CLI)
    get_qdrant().ensure_collections()

    asyncio.run(run_etl())
