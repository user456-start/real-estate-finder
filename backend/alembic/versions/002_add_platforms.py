"""Add houza, bhomes, and justproperty platforms.

Revision ID: 002
Revises: 001
Create Date: 2026-04-25
"""

from typing import Sequence, Union

from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO platforms (name, base_url) VALUES
            ('houza',        'https://www.houza.com'),
            ('bhomes',       'https://www.bhomes.com'),
            ('justproperty', 'https://www.justproperty.com')
        ON CONFLICT (name) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM platforms
        WHERE name IN ('houza', 'bhomes', 'justproperty')
        """
    )
