"""Add image_url and image_url_updated_at columns to store_products

Revision ID: 0007
Revises: 0006
Create Date: 2026-04-02

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "store_products",
        sa.Column("image_url", sa.Text(), nullable=True),
    )
    op.add_column(
        "store_products",
        sa.Column(
            "image_url_updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("store_products", "image_url_updated_at")
    op.drop_column("store_products", "image_url")
