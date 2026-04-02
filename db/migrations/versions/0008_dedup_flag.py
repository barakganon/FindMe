"""Add is_duplicate and canonical_product_id columns to products table

Revision ID: 0008
Revises: 0007
Create Date: 2026-04-02

Supports the bulk deduplication pass in normalization/deduplication.py.
After running deduplication, duplicate products are flagged so they can be
excluded from search results and UIs.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS is_duplicate BOOLEAN DEFAULT false NOT NULL"
    )
    op.execute(
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS canonical_product_id UUID REFERENCES products(id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_products_is_duplicate ON products(is_duplicate) WHERE is_duplicate = true"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_products_canonical_product_id ON products(canonical_product_id) WHERE canonical_product_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_products_canonical_product_id")
    op.execute("DROP INDEX IF EXISTS idx_products_is_duplicate")
    op.execute("ALTER TABLE products DROP COLUMN IF EXISTS canonical_product_id")
    op.execute("ALTER TABLE products DROP COLUMN IF EXISTS is_duplicate")
