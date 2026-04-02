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
from datetime import date, datetime
from decimal import Decimal
from enum import Enum as PyEnum
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
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

    # Product image URL scraped from the store page
    image_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    image_url_updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    product: Mapped["Product"] = relationship("Product", back_populates="store_products")
    store: Mapped["Store"] = relationship("Store", back_populates="store_products")
    price_changes: Mapped[list["PriceChange"]] = relationship(
        "PriceChange", back_populates="store_product", cascade="all, delete-orphan"
    )

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


# ---------------------------------------------------------------------------
# PriceChange  (history of price / availability changes per StoreProduct)
# ---------------------------------------------------------------------------

class PriceChange(Base):
    """
    Records every price or availability change detected for a StoreProduct.

    Written by the scheduler's detect_price_changes task after each scrape.
    Enables "price dropped since last week" features and scrape freshness monitoring.
    """

    __tablename__ = "price_changes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    store_product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("store_products.id", ondelete="CASCADE"),
        nullable=False,
    )
    old_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    new_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    old_availability: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    new_availability: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationship
    store_product: Mapped["StoreProduct"] = relationship(
        "StoreProduct", back_populates="price_changes"
    )

    def __repr__(self) -> str:
        return (
            f"<PriceChange store_product={self.store_product_id} "
            f"old={self.old_price} new={self.new_price}>"
        )


# ---------------------------------------------------------------------------
# User  (registered user account — anonymous users are never stored)
# ---------------------------------------------------------------------------

class User(Base):
    """
    A registered FindMe user.

    Anonymous users are never stored in the DB — they use session state only.
    Registration is optional; the app works fully without an account.
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    display_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    password_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    google_id: Mapped[Optional[str]] = mapped_column(String(255), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_login_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Relationships
    locations: Mapped[list["UserLocation"]] = relationship(
        "UserLocation", back_populates="user", cascade="all, delete-orphan"
    )
    voucher_cards: Mapped[list["UserVoucherCard"]] = relationship(
        "UserVoucherCard", back_populates="user", cascade="all, delete-orphan"
    )
    preferences: Mapped[list["UserPreference"]] = relationship(
        "UserPreference", back_populates="user", cascade="all, delete-orphan"
    )
    implicit_signals: Mapped[list["UserImplicitSignal"]] = relationship(
        "UserImplicitSignal", back_populates="user", cascade="all, delete-orphan"
    )
    inferred_attributes: Mapped[list["UserInferredAttribute"]] = relationship(
        "UserInferredAttribute", back_populates="user", cascade="all, delete-orphan"
    )
    search_history: Mapped[list["UserSearchHistory"]] = relationship(
        "UserSearchHistory", back_populates="user", cascade="all, delete-orphan"
    )
    favorites: Mapped[list["UserFavoriteStore"]] = relationship(
        "UserFavoriteStore", back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<User {self.email!r} active={self.is_active}>"


# ---------------------------------------------------------------------------
# UserLocation  (saved named locations per user)
# ---------------------------------------------------------------------------

class UserLocation(Base):
    """A saved named location for a user (e.g. "בית", "עבודה")."""

    __tablename__ = "user_locations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lng: Mapped[float] = mapped_column(Float, nullable=False)
    address: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationship
    user: Mapped["User"] = relationship("User", back_populates="locations")

    def __repr__(self) -> str:
        return f"<UserLocation {self.label!r} user={self.user_id}>"


# ---------------------------------------------------------------------------
# UserVoucherCard  (voucher cards held by a user)
# ---------------------------------------------------------------------------

class UserVoucherCard(Base):
    """A voucher card (BuyMe, תו הזהב, etc.) held by a registered user."""

    __tablename__ = "user_voucher_cards"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    voucher_network: Mapped[str] = mapped_column(String(50), nullable=False)
    nickname: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    balance: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    expiry_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationship
    user: Mapped["User"] = relationship("User", back_populates="voucher_cards")

    def __repr__(self) -> str:
        return f"<UserVoucherCard {self.voucher_network!r} user={self.user_id}>"


# ---------------------------------------------------------------------------
# UserPreference  (explicit user preferences — key/value pairs)
# ---------------------------------------------------------------------------

class UserPreference(Base):
    """
    Explicit user preference stored as a key/value pair.

    Supported keys: default_max_price, preferred_cities, preferred_categories,
    show_online_only, default_radius_km, language.
    """

    __tablename__ = "user_preferences"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    key: Mapped[str] = mapped_column(String(100), primary_key=True, nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationship
    user: Mapped["User"] = relationship("User", back_populates="preferences")

    def __repr__(self) -> str:
        return f"<UserPreference {self.key!r}={self.value!r} user={self.user_id}>"


# ---------------------------------------------------------------------------
# UserImplicitSignal  (behavioral signals learned from usage)
# ---------------------------------------------------------------------------

class UserImplicitSignal(Base):
    """
    Implicit behavioral signal learned from the user's search behavior.

    Signal types: city_search, category_click, store_visit, price_range.
    Weight increases with repetition; used to personalize search results.
    """

    __tablename__ = "user_implicit_signals"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    signal_type: Mapped[str] = mapped_column(String(50), nullable=False)
    signal_value: Mapped[str] = mapped_column(String(255), nullable=False)
    weight: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # Relationship
    user: Mapped["User"] = relationship("User", back_populates="implicit_signals")

    def __repr__(self) -> str:
        return (
            f"<UserImplicitSignal {self.signal_type!r}={self.signal_value!r} "
            f"weight={self.weight} user={self.user_id}>"
        )


# ---------------------------------------------------------------------------
# UserInferredAttribute  (LLM-inferred user attributes — transparent + deletable)
# ---------------------------------------------------------------------------

class UserInferredAttribute(Base):
    """
    An attribute inferred by the LLM from the user's conversation and behavior.

    PRIVACY: Users can view all inferred attributes and delete any of them.
    Attributes with confidence < 0.5 are stored but never used for search.
    Only boosts relevance — never restricts results.
    """

    __tablename__ = "user_inferred_attributes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    attribute: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[str] = mapped_column(String(255), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    source: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    inferred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_updated: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    is_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Relationship
    user: Mapped["User"] = relationship("User", back_populates="inferred_attributes")

    def __repr__(self) -> str:
        return (
            f"<UserInferredAttribute {self.attribute!r}={self.value!r} "
            f"confidence={self.confidence} user={self.user_id}>"
        )


# ---------------------------------------------------------------------------
# UserSearchHistory  (full search history per user)
# ---------------------------------------------------------------------------

class UserSearchHistory(Base):
    """
    A record of every search performed by a registered user.

    Used by the LLM to reference past searches in conversation context.
    Users can view and clear their search history.
    """

    __tablename__ = "user_search_history"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    intent: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    resolved_query: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    city_used: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    result_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    top_result_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    voucher_network: Mapped[str] = mapped_column(
        String(50), default="buyme", nullable=False
    )
    searched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationship
    user: Mapped["User"] = relationship("User", back_populates="search_history")

    def __repr__(self) -> str:
        return f"<UserSearchHistory message={self.message[:40]!r} user={self.user_id}>"


# ---------------------------------------------------------------------------
# UserFavoriteStore  (saved favorite stores per user)
# ---------------------------------------------------------------------------

class UserFavoriteStore(Base):
    """A store saved as a favorite by a registered user."""

    __tablename__ = "user_favorite_stores"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("stores.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    saved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    note: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="favorites")
    store: Mapped["Store"] = relationship("Store")

    def __repr__(self) -> str:
        return f"<UserFavoriteStore user={self.user_id} store={self.store_id}>"
