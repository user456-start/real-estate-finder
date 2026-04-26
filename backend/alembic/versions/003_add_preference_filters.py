"""Add bathroom, bedroom array, and furnished preference filters.

Revision ID: 003
Revises: 002
Create Date: 2026-04-25
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add new columns to user_preferences
    op.add_column(
        "user_preferences",
        sa.Column("bedrooms", postgresql.ARRAY(sa.SmallInteger()), nullable=True),
    )
    op.add_column(
        "user_preferences",
        sa.Column("min_bathrooms", sa.SmallInteger(), nullable=True),
    )
    op.add_column(
        "user_preferences",
        sa.Column("max_bathrooms", sa.SmallInteger(), nullable=True),
    )
    op.add_column(
        "user_preferences",
        sa.Column("furnished", sa.SmallInteger(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_preferences", "furnished")
    op.drop_column("user_preferences", "max_bathrooms")
    op.drop_column("user_preferences", "min_bathrooms")
    op.drop_column("user_preferences", "bedrooms")
