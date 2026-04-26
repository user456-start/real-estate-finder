"""
Normalizer — converts raw platform dicts into a unified RawListing schema,
and handles cross-platform deduplication before DB upsert.

RawListing is a plain TypedDict so it flows easily between scraper →
normalizer → ETL without ORM overhead.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any, TypedDict

logger = logging.getLogger(__name__)


class RawListing(TypedDict, total=False):
    """Unified listing schema produced by every scraper."""
    platform:       str           # 'bayut' | 'property_finder'
    external_id:    str           # platform's own ID
    url:            str
    title:          str
    description:    str
    price_aed:      float | None
    is_rental:      bool
    beds:           int | None
    baths:          int | None
    size_sqft:      float | None
    area_name:      str | None
    lat:            float | None
    lon:            float | None
    image_url:      str | None
    updated_at:     str | None    # ISO-8601


# ── Cross-platform deduplication ─────────────────────────────────────────────

def dedup_across_platforms(listings: list[RawListing]) -> list[RawListing]:
    """
    Remove listings that are almost certainly the same physical property
    appearing on multiple platforms.

    Only runs when listings come from 2+ platforms. Within a single platform,
    every listing has a unique external_id — the Postgres upsert handles that.
    """
    platforms = {l.get("platform") for l in listings}
    logger.info("Dedup: %d listings from %d platform(s): %s", len(listings), len(platforms), sorted(str(p) for p in platforms))
    if len(platforms) <= 1:
        # Single platform — no cross-platform duplicates possible
        logger.info("Dedup: single platform, skipping — all %d listings pass through", len(listings))
        return listings

    priority = {
        "property_finder": 0,
        "bayut":           1,
        "houza":           2,
        "bhomes":          3,
        "justproperty":    4,
        "behomes":         5,
    }

    # Group by fuzzy property identity
    groups: dict[tuple, list[RawListing]] = {}
    for listing in listings:
        key = _dedup_key(listing)
        groups.setdefault(key, []).append(listing)

    result: list[RawListing] = []
    for key, group in groups.items():
        # Separate by platform
        by_platform: dict[str, list[RawListing]] = {}
        for listing in group:
            by_platform.setdefault(listing.get("platform", ""), []).append(listing)

        if len(by_platform) == 1:
            # All from same platform — keep all
            result.extend(group)
        else:
            # Cross-platform collision — keep all listings from the best platform
            best = min(by_platform.keys(), key=lambda p: priority.get(p, 99))
            result.extend(by_platform[best])

    dropped = len(listings) - len(result)
    if dropped:
        logger.info("Dedup: dropped %d cross-platform duplicates", dropped)
    return result


def _dedup_key(listing: RawListing) -> tuple:
    price = listing.get("price_aed") or 0
    price_bucket = round(price / 1000)
    size = listing.get("size_sqft") or 0
    size_bucket = round(size / 50)
    return (
        (listing.get("area_name") or "").lower().strip(),
        listing.get("beds"),
        listing.get("baths"),
        price_bucket,
        size_bucket,
    )


# ── Description hash ──────────────────────────────────────────────────────────

def description_hash(text: str | None) -> str | None:
    if not text:
        return None
    return hashlib.md5(text.encode()).hexdigest()


# ── Field coercion helpers ─────────────────────────────────────────────────────

def to_float(val: Any) -> float | None:
    try:
        return float(val) if val not in (None, "", "N/A") else None
    except (TypeError, ValueError):
        return None


def to_int(val: Any) -> int | None:
    try:
        return int(float(val)) if val not in (None, "", "N/A") else None
    except (TypeError, ValueError):
        return None
