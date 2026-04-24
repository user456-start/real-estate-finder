"""Initial schema — relational + PostGIS tables.
Vector embeddings live in Qdrant, not Postgres.

Revision ID: 001
Revises:
Create Date: 2026-04-24
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geometry
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')

    # ── platforms ──────────────────────────────────────────────────────────
    op.create_table(
        "platforms",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column("last_fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    # ── listings ───────────────────────────────────────────────────────────
    op.create_table(
        "listings",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            nullable=False,
        ),
        sa.Column("platform_id", sa.Integer(), sa.ForeignKey("platforms.id"), nullable=False),
        sa.Column("external_id", sa.String(256), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("price_aed", sa.Numeric(12, 2), nullable=True),
        sa.Column("is_rental", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("beds", sa.SmallInteger(), nullable=True),
        sa.Column("baths", sa.SmallInteger(), nullable=True),
        sa.Column("size_sqft", sa.Numeric(10, 2), nullable=True),
        sa.Column("area_name", sa.String(128), nullable=True),
        sa.Column("location", Geometry("POINT", srid=4326), nullable=True),
        sa.Column("available", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("description_hash", sa.String(64), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("platform_id", "external_id", name="uq_listing_platform_external"),
    )
    op.create_index("ix_listings_area_name", "listings", ["area_name"])
    op.create_index("ix_listings_available_fetched", "listings", ["available", "fetched_at"])
    op.create_index("ix_listings_location", "listings", ["location"], postgresql_using="gist")

    # ── pois ───────────────────────────────────────────────────────────────
    op.create_table(
        "pois",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("type", sa.String(64), nullable=False),
        sa.Column("location", Geometry("POINT", srid=4326), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("rating", sa.Numeric(3, 1), nullable=True),
        sa.Column("source", sa.String(64), nullable=False, server_default="geoapify"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pois_type", "pois", ["type"])
    op.create_index("ix_pois_location", "pois", ["location"], postgresql_using="gist")

    # ── area_guides ────────────────────────────────────────────────────────
    op.create_table(
        "area_guides",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            nullable=False,
        ),
        sa.Column("area_name", sa.String(128), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("area_name"),
    )

    # ── user_preferences ───────────────────────────────────────────────────
    op.create_table(
        "user_preferences",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("min_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("max_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("min_beds", sa.SmallInteger(), nullable=True),
        sa.Column("is_rental", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("areas", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("extra_criteria", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── seed platforms ─────────────────────────────────────────────────────
    op.execute(
        """
        INSERT INTO platforms (name, base_url) VALUES
            ('bayut',            'https://www.bayut.com'),
            ('property_finder',  'https://www.propertyfinder.ae'),
            ('behomes',          'https://behomes.tech')
        ON CONFLICT (name) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_table("user_preferences")
    op.drop_table("area_guides")
    op.drop_index("ix_pois_location", table_name="pois")
    op.drop_index("ix_pois_type", table_name="pois")
    op.drop_table("pois")
    op.drop_index("ix_listings_location", table_name="listings")
    op.drop_index("ix_listings_available_fetched", table_name="listings")
    op.drop_index("ix_listings_area_name", table_name="listings")
    op.drop_table("listings")
    op.drop_table("platforms")
