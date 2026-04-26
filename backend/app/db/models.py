"""
SQLAlchemy ORM models for the Dubai real-estate finder.

Vector embeddings are stored in Qdrant (see app/services/vector_store.py),
NOT in Postgres. This file only contains relational + geospatial tables.

Extension required in Postgres (handled by docker-entrypoint-initdb.d/init.sql):
    CREATE EXTENSION postgis;
    CREATE EXTENSION "uuid-ossp";
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from geoalchemy2 import Geometry
from sqlalchemy import (
    ARRAY,
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


# ---------------------------------------------------------------------------
# Platforms
# ---------------------------------------------------------------------------

class Platform(Base):
    __tablename__ = "platforms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    last_fetched_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    listings: Mapped[list["Listing"]] = relationship(back_populates="platform")


# ---------------------------------------------------------------------------
# Listings
# ---------------------------------------------------------------------------

class Listing(Base):
    __tablename__ = "listings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    platform_id: Mapped[int] = mapped_column(ForeignKey("platforms.id"), nullable=False)
    external_id: Mapped[str] = mapped_column(String(256), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    price_aed: Mapped[Optional[float]] = mapped_column(Numeric(12, 2))
    is_rental: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    beds: Mapped[Optional[int]] = mapped_column(SmallInteger)
    baths: Mapped[Optional[int]] = mapped_column(SmallInteger)
    size_sqft: Mapped[Optional[float]] = mapped_column(Numeric(10, 2))
    area_name: Mapped[Optional[str]] = mapped_column(String(128))

    # PostGIS point — SRID 4326 (WGS84 lat/lon)
    location: Mapped[Optional[object]] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326), nullable=True
    )

    available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    fetched_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    image_url: Mapped[Optional[str]] = mapped_column(Text)

    # Hash of description — skip re-embedding in Qdrant if unchanged
    description_hash: Mapped[Optional[str]] = mapped_column(String(64))

    platform: Mapped["Platform"] = relationship(back_populates="listings")

    __table_args__ = (
        UniqueConstraint("platform_id", "external_id", name="uq_listing_platform_external"),
        Index("ix_listings_area_name", "area_name"),
        Index("ix_listings_available_fetched", "available", "fetched_at"),
        Index("ix_listings_location", "location", postgresql_using="gist"),
    )


# ---------------------------------------------------------------------------
# Points of Interest
# ---------------------------------------------------------------------------

class POI(Base):
    __tablename__ = "pois"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    location: Mapped[object] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326), nullable=False
    )
    description: Mapped[Optional[str]] = mapped_column(Text)
    rating: Mapped[Optional[float]] = mapped_column(Numeric(3, 1))
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="geoapify")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_pois_type", "type"),
        Index("ix_pois_location", "location", postgresql_using="gist"),
    )


# ---------------------------------------------------------------------------
# Area Guides
# ---------------------------------------------------------------------------

class AreaGuide(Base):
    __tablename__ = "area_guides"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    area_name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# ---------------------------------------------------------------------------
# User Preferences
# ---------------------------------------------------------------------------

class UserPreferences(Base):
    __tablename__ = "user_preferences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    min_price: Mapped[Optional[float]] = mapped_column(Numeric(12, 2))
    max_price: Mapped[Optional[float]] = mapped_column(Numeric(12, 2))
    min_beds: Mapped[Optional[int]] = mapped_column(SmallInteger)
    is_rental: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    areas: Mapped[Optional[list[str]]] = mapped_column(ARRAY(String))
    bedrooms: Mapped[Optional[list[int]]] = mapped_column(ARRAY(SmallInteger))
    min_bathrooms: Mapped[Optional[int]] = mapped_column(SmallInteger)
    max_bathrooms: Mapped[Optional[int]] = mapped_column(SmallInteger)
    furnished: Mapped[Optional[int]] = mapped_column(SmallInteger)  # 0=unfurnished, 1=furnished, null=no pref
    extra_criteria: Mapped[Optional[dict]] = mapped_column(JSON)
