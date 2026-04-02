"""Add price_changes table for tracking product price history

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-02

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "price_changes",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "store_product_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("old_price", sa.Numeric(10, 2), nullable=True),
        sa.Column("new_price", sa.Numeric(10, 2), nullable=True),
        sa.Column("old_availability", sa.Boolean(), nullable=True),
        sa.Column("new_availability", sa.Boolean(), nullable=True),
        sa.Column(
            "detected_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["store_product_id"],
            ["store_products.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_price_changes_store_product",
        "price_changes",
        ["store_product_id", sa.text("detected_at DESC")],
    )
    op.create_index(
        "idx_price_changes_detected",
        "price_changes",
        [sa.text("detected_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("idx_price_changes_detected", table_name="price_changes")
    op.drop_index("idx_price_changes_store_product", table_name="price_changes")
    op.drop_table("price_changes")
