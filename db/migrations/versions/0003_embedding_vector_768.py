"""Resize embedding_vector from 1536 to 768 dims (Gemini text-embedding-004)

Revision ID: 0003
Revises: 0002
Create Date: 2026-03-25

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop old 1536-dim column and recreate as 768-dim for Gemini text-embedding-004
    op.execute("ALTER TABLE products DROP COLUMN IF EXISTS embedding_vector")
    op.execute("ALTER TABLE products ADD COLUMN embedding_vector vector(768)")
    # Index for cosine similarity search
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_products_embedding "
        "ON products USING ivfflat (embedding_vector vector_cosine_ops) "
        "WITH (lists = 100)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_products_embedding")
    op.execute("ALTER TABLE products DROP COLUMN IF EXISTS embedding_vector")
    op.execute("ALTER TABLE products ADD COLUMN embedding_vector vector(1536)")
