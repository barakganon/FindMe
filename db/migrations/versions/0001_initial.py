"""Initial schema: stores, products, store_products, scrape_runs + pgvector

Revision ID: 0001
Revises:
Create Date: 2026-03-24
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # --- stores ---
    op.create_table(
        "stores",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("name_he", sa.String(255), nullable=False),
        sa.Column("name_en", sa.String(255), nullable=True),
        sa.Column("buyme_url", sa.String(1024), nullable=True),
        sa.Column("store_url", sa.String(1024), nullable=True),
        sa.Column("buyme_category", sa.String(50), nullable=False),
        sa.Column("is_online", sa.Boolean(), nullable=False),
        sa.Column("address", sa.String(512), nullable=True),
        sa.Column("city", sa.String(100), nullable=True),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("lng", sa.Float(), nullable=True),
        sa.Column("last_scraped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scrape_status", sa.String(50), nullable=False),
        sa.Column("scrape_error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("buyme_url", name="uq_stores_buyme_url"),
    )
    op.create_index("ix_stores_name_he", "stores", ["name_he"])
    op.create_index("ix_stores_buyme_url", "stores", ["buyme_url"])
    op.create_index("ix_stores_buyme_category", "stores", ["buyme_category"])
    op.create_index("ix_stores_city", "stores", ["city"])

    # --- products ---
    op.create_table(
        "products",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("canonical_name", sa.String(512), nullable=False),
        sa.Column("brand", sa.String(255), nullable=True),
        sa.Column("model", sa.String(255), nullable=True),
        sa.Column("category_path", sa.String(512), nullable=True),
        sa.Column("specs_json", postgresql.JSONB(), nullable=True),
        sa.Column("embedding_vector", sa.Text(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_products_canonical_name", "products", ["canonical_name"])
    op.create_index("ix_products_brand", "products", ["brand"])
    op.create_index("ix_products_category_path", "products", ["category_path"])

    # Convert embedding_vector to pgvector type (1536 dims = OpenAI text-embedding-3-small)
    op.execute("ALTER TABLE products ALTER COLUMN embedding_vector TYPE vector(1536) USING NULL")

    # --- store_products ---
    op.create_table(
        "store_products",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("price", sa.Float(), nullable=True),
        sa.Column("currency", sa.String(10), nullable=False),
        sa.Column("availability", sa.Boolean(), nullable=False),
        sa.Column("product_url", sa.String(1024), nullable=True),
        sa.Column("raw_name", sa.String(512), nullable=True),
        sa.Column("last_price_change_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("product_id", "store_id", "product_url", name="uq_store_product_url"),
    )
    op.create_index("ix_store_products_product_id", "store_products", ["product_id"])
    op.create_index("ix_store_products_store_id", "store_products", ["store_id"])

    # --- scrape_runs ---
    op.create_table(
        "scrape_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("run_type", sa.String(50), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("items_scraped", sa.Integer(), nullable=False),
        sa.Column("items_new", sa.Integer(), nullable=False),
        sa.Column("items_updated", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("raw_snapshot_path", sa.String(1024), nullable=True),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_scrape_runs_store_id", "scrape_runs", ["store_id"])
    op.create_index("ix_scrape_runs_run_type", "scrape_runs", ["run_type"])


def downgrade() -> None:
    op.drop_table("scrape_runs")
    op.drop_table("store_products")
    op.drop_table("products")
    op.drop_table("stores")
    op.execute("DROP EXTENSION IF EXISTS vector")
