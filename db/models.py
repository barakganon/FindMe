"""
db/models.py — SQLAlchemy async ORM models for BuyMe Smart Search.

Tables:
    stores          — BuyMe partner stores (retail, restaurant, online)
    products        — Canonical / deduplicated master product records
    store_products  — Join table: one product linked to many stores
    scrape_runs     — Audit log for every scrape job
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum as PyEnum
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


# ---------------------------------------------------------------------------
# Base + shared mixin
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    """Declarative base for all ORM models."""
    pass


class BaseMixin:
    """
    Shared primary-key and timestamp fields inherited by every model.

    Fields:
        id          — UUID primary key, server-generated
        created_at  — row creation timestamp (UTC, set once)
        updated_at  — last update timestamp (UTC, updated on every write)
    """

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class BuyMeCategory(str, PyEnum):
    """Category of a BuyMe partner store as shown on buyme.co.il."""
    RESTAURANT = "restaurant"
    RETAIL = "retail"
    ONLINE = "online"
    OTHER = "other"


class ScrapeStatus(str, PyEnum):
    """Status of the most recent scrape attempt for a store."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class ScrapeRunType(str, PyEnum):
    """What a ScrapeRun was scraping."""
    STORE_LIST = "store_list"       # Full BuyMe partner list scrape
    STORE_PRODUCTS = "store_products"  # Product catalog for one store


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

class Store(BaseMixin, Base):
    """
    A BuyMe partner store.

    Populated by scraper/buyme_store_scraper.py.
    One store can carry many products via the store_products join table.
    """

    __tablename__ = "stores"

    # Names — Hebrew is canonical; English populated when available
    name_he: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    name_en: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # BuyMe-provided store page URL (unique — used as upsert key)
    buyme_url: Mapped[Optional[str]] = mapped_column(
        String(1024), nullable=True, unique=True, index=True
    )
    # The store's own external website
    store_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)

    buyme_category: Mapped[str] = mapped_column(
        String(50), default=BuyMeCategory.OTHER, nullable=False, index=True
    )
    is_online: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Physical location — NULL for online-only stores
    address: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    lat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    lng: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Scraping state
    last_scraped_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    scrape_status: Mapped[str] = mapped_column(
        String(50), default=ScrapeStatus.PENDING, nullable=False
    )
    scrape_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    store_products: Mapped[list["StoreProduct"]] = relationship(
        "StoreProduct", back_populates="store", cascade="all, delete-orphan"
    )
    scrape_runs: Mapped[list["ScrapeRun"]] = relationship(
        "ScrapeRun", back_populates="store", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Store {self.name_he!r} category={self.buyme_category}>"


# ---------------------------------------------------------------------------
# Product  (canonical / deduplicated master record)
# ---------------------------------------------------------------------------

class Product(BaseMixin, Base):
    """
    A canonical, deduplicated product record.

    Multiple store listings (StoreProduct rows) map to a single Product.
    The embedding_vector column is written as TEXT here; the Alembic migration
    in db/migrations/ will ALTER it to vector(1536) after enabling pgvector.
    """

    __tablename__ = "products"

    # Canonical display name after AI normalization (Hebrew or English)
    canonical_name: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    brand: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    model: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Hierarchical taxonomy path, e.g. "Electronics > Headphones > Over-ear"
    category_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True, index=True)

    # Extracted specs: {color, size, weight, storage_gb, ...}
    specs_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    # pgvector — stored as TEXT placeholder; migration converts to vector(1536)
    # See db/vector_index.py for index creation
    embedding_vector: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    store_products: Mapped[list["StoreProduct"]] = relationship(
        "StoreProduct", back_populates="product", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Product {self.canonical_name!r} brand={self.brand}>"


# ---------------------------------------------------------------------------
# StoreProduct  (join: one product → many store listings)
# ---------------------------------------------------------------------------

class StoreProduct(BaseMixin, Base):
    """
    Links a canonical Product to a specific Store, with price and availability.

    A product available in three BuyMe stores → three StoreProduct rows,
    all pointing to the same Product master record.
    """

    __tablename__ = "store_products"
    __table_args__ = (
        UniqueConstraint(
            "product_id", "store_id", "product_url",
            name="uq_store_product_url",
        ),
    )

    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("stores.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    currency: Mapped[str] = mapped_column(String(10), default="ILS", nullable=False)
    availability: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # The store's own product page URL
    product_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)

    # Pre-normalization store-side name (for debugging / re-normalization)
    raw_name: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    last_price_change_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    product: Mapped["Product"] = relationship("Product", back_populates="store_products")
    store: Mapped["Store"] = relationship("Store", back_populates="store_products")

    def __repr__(self) -> str:
        return f"<StoreProduct product={self.product_id} store={self.store_id} price={self.price}>"


# ---------------------------------------------------------------------------
# ScrapeRun  (audit log for every scrape job)
# ---------------------------------------------------------------------------

class ScrapeRun(BaseMixin, Base):
    """
    Audit record for a single scrape execution.

    Created at the start of every scrape; updated when it finishes.
    Enables the Admin Dashboard to show scrape health per store.
    """

    __tablename__ = "scrape_runs"

    # NULL for STORE_LIST runs (not tied to a specific store)
    store_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("stores.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    run_type: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )  # ScrapeRunType value

    status: Mapped[str] = mapped_column(
        String(50), default=ScrapeStatus.IN_PROGRESS, nullable=False
    )

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # How many items were processed in this run
    items_scraped: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    items_new: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    items_updated: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Raw snapshot file path (for auditing / re-processing)
    raw_snapshot_path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)

    # Relationship
    store: Mapped[Optional["Store"]] = relationship("Store", back_populates="scrape_runs")

    def __repr__(self) -> str:
        return f"<ScrapeRun type={self.run_type} status={self.status} items={self.items_scraped}>"
