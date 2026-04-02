"""
api/schemas.py — All Pydantic v2 request/response models for BuyMe Smart Search API.

These schemas define the contract between the API layer and its consumers.
Hebrew + English both supported in all text fields.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class LocationFilter(BaseModel):
    """Geographic filter for nearby store search."""

    lat: float = Field(..., description="Latitude of the user's location")
    lng: float = Field(..., description="Longitude of the user's location")
    radius_km: float = Field(10.0, ge=0.1, le=500.0, description="Search radius in kilometres")


class SearchFilters(BaseModel):
    """Optional filters applied to a product search."""

    online_only: bool = Field(False, description="Return only online stores")
    city: Optional[str] = Field(None, description="Filter results to a specific city (Hebrew or English)")
    location: Optional[LocationFilter] = Field(None, description="Geographic radius filter")
    max_price: Optional[float] = Field(None, ge=0.0, description="Maximum product price in ILS")
    min_match_score: float = Field(0.3, ge=0.0, le=1.0, description="Minimum similarity score (0.0–1.0)")
    brand: Optional[str] = Field(None, description="Filter by brand name (case-insensitive)")
    page: int = Field(1, ge=1, description="Page number (1-indexed)")
    page_size: int = Field(20, ge=1, le=100, description="Results per page")


class SearchRequest(BaseModel):
    """Search request payload — free text query or product URL."""

    query: str = Field(
        ...,
        description="Free text product search (e.g. 'אוזניות sony') or any product URL",
        examples=["אוזניות של sony", "https://www.ksp.co.il/web/cat/product/1234"],
    )
    filters: SearchFilters = Field(
        default_factory=SearchFilters,
        description="Optional search filters",
    )


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class StoreInfo(BaseModel):
    """Summary information about a BuyMe partner store."""

    id: str = Field(..., description="Store UUID")
    name_he: str = Field(..., description="Store name in Hebrew")
    name_en: Optional[str] = Field(None, description="Store name in English (when available)")
    buyme_url: Optional[str] = Field(None, description="BuyMe store page URL")
    is_online: bool = Field(..., description="True if the store operates online")
    city: Optional[str] = Field(None, description="City where the store is located")
    lat: Optional[float] = Field(None, description="Store latitude for map display")
    lng: Optional[float] = Field(None, description="Store longitude for map display")
    distance_km: Optional[float] = Field(
        None,
        description="Distance from user's location in km; null if location not provided",
    )


class ProductResult(BaseModel):
    """A single product found in a BuyMe partner store."""

    product_id: str = Field(..., description="Canonical product UUID")
    canonical_name: str = Field(..., description="Normalised product name")
    brand: Optional[str] = Field(None, description="Product brand / manufacturer")
    category_path: Optional[str] = Field(
        None,
        description="Hierarchical category path, e.g. 'Electronics > Headphones > Over-ear'",
    )
    store: StoreInfo = Field(..., description="Store carrying this product")
    price: Optional[float] = Field(None, description="Current price in the given currency")
    currency: str = Field("ILS", description="ISO 4217 currency code")
    availability: bool = Field(..., description="Whether the product is currently in stock")
    product_url: Optional[str] = Field(None, description="Direct link to this product at the store")
    match_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Similarity score between query product and this result (0.0–1.0)",
    )


class QueryProduct(BaseModel):
    """The product we extracted from the user's query (URL or free text)."""

    raw_query: str = Field(..., description="The original query submitted by the user")
    extracted_name: Optional[str] = Field(None, description="Product name extracted by Claude")
    brand: Optional[str] = Field(None, description="Brand extracted by Claude")
    estimated_price: Optional[float] = Field(None, description="Estimated price from the source page")
    extraction_success: bool = Field(
        ...,
        description="False if URL fetch or Claude extraction failed",
    )


class SearchResponse(BaseModel):
    """Full response returned by POST /search."""

    results: list[ProductResult] = Field(..., description="Matched products from BuyMe partner stores")
    query_product: QueryProduct = Field(..., description="Extracted product from the submitted URL")
    total: int = Field(..., ge=0, description="Number of results on this page")
    total_available: int = Field(..., ge=0, description="Total matching results across all pages")
    page: int = Field(..., ge=1, description="Current page number (1-indexed)")
    page_size: int = Field(..., ge=1, description="Results per page")
    exact_matches: int = Field(..., ge=0, description="Number of exact name matches")
    similar_matches: int = Field(..., ge=0, description="Number of partial / similar matches")
    search_time_ms: float = Field(..., ge=0.0, description="Total server-side search time in milliseconds")


# ---------------------------------------------------------------------------
# Store list
# ---------------------------------------------------------------------------


class StoreListResponse(BaseModel):
    """Paginated list of BuyMe partner stores."""

    stores: list[StoreInfo] = Field(..., description="Page of store records")
    total: int = Field(..., ge=0, description="Total number of stores matching the query")
    page: int = Field(..., ge=1, description="Current page number (1-indexed)")
    page_size: int = Field(..., ge=1, description="Number of stores per page")


# ---------------------------------------------------------------------------
# Store search
# ---------------------------------------------------------------------------


class StoreSearchRequest(BaseModel):
    """Request payload for POST /stores/search."""

    query: Optional[str] = Field(None, description="Search store name (Hebrew or English)")
    store_type: Optional[str] = Field(
        None, description="'restaurant', 'retail', or None for all"
    )
    location: Optional[LocationFilter] = Field(
        None, description="Center point + radius_km for geo filter"
    )
    page: int = Field(1, ge=1)
    page_size: int = Field(40, ge=1, le=100)


class StoreResult(BaseModel):
    """A single store returned by POST /stores/search."""

    id: str
    name_he: str
    name_en: Optional[str]
    buyme_url: Optional[str]
    buyme_category: str
    address: Optional[str]
    city: Optional[str]
    lat: Optional[float]
    lng: Optional[float]
    distance_km: Optional[float]
    is_online: bool
    product_count: int


class StoreSearchResponse(BaseModel):
    """Response payload for POST /stores/search."""

    stores: list[StoreResult] = Field(..., description="Page of matching stores")
    total: int = Field(..., ge=0, description="Number of stores on this page")
    total_available: int = Field(..., ge=0, description="Total matching stores across all pages")
    page: int = Field(..., ge=1, description="Current page number (1-indexed)")
    page_size: int = Field(..., ge=1, description="Results per page")


# ---------------------------------------------------------------------------
# Conversational chat  (LLM-powered unified search)
# READ-ONLY after Phase 1 — all agents build against this contract
# ---------------------------------------------------------------------------


class ChatMessage(BaseModel):
    """A single turn in the conversation history."""

    role: str = Field(..., description="'user' or 'assistant'")
    content: str = Field(..., description="Message text (Hebrew or English)")


class SessionContext(BaseModel):
    """Client-side session state — location and voucher network.
    Never stored in DB; passed by the frontend with every request."""

    user_lat: Optional[float] = Field(None, description="GPS latitude if already acquired")
    user_lng: Optional[float] = Field(None, description="GPS longitude if already acquired")
    location_label: Optional[str] = Field(
        None, description="Human-readable location label, e.g. 'תל אביב מרכז'"
    )
    voucher_network: str = Field("buyme", description="Active voucher network")


class ParsedIntent(BaseModel):
    """Structured intent extracted from the user message by the intent parser LLM."""

    intent: str = Field(
        ...,
        description="'product_search' | 'store_search' | 'help' | 'clarify'",
    )
    product_query: Optional[str] = Field(None, description="Product name or keywords")
    brand: Optional[str] = Field(None, description="Brand / manufacturer name")
    max_price: Optional[float] = Field(None, description="Maximum price in ILS")
    city: Optional[str] = Field(None, description="City name in Hebrew")
    location_hint: Optional[str] = Field(
        None, description="Place name or address mentioned by user"
    )
    needs_user_location: bool = Field(
        False,
        description="True when user said 'לידי' / 'באזור שלי' but no GPS is available",
    )
    store_type: Optional[str] = Field(
        None, description="'restaurant' | 'retail' | None for all"
    )
    voucher_network: str = Field("buyme", description="Voucher network (default: buyme)")


class ChatRequest(BaseModel):
    """Request payload for POST /api/chat."""

    message: str = Field(..., description="User's free-text message (Hebrew or English)")
    history: list[ChatMessage] = Field(
        default_factory=list,
        description="Previous conversation turns for context",
    )
    session_context: Optional[SessionContext] = Field(
        None, description="Client-side session state (location, voucher network)"
    )
    voucher_network: str = Field("buyme", description="Active voucher network")


class ChatResponse(BaseModel):
    """Response payload for POST /api/chat."""

    message: str = Field(..., description="Hebrew natural-language answer")
    intent: str = Field(
        ..., description="'product_search' | 'store_search' | 'help' | 'clarify'"
    )
    product_results: Optional[list[ProductResult]] = Field(
        None, description="Matched products (when intent=product_search)"
    )
    store_results: Optional[list[StoreResult]] = Field(
        None, description="Matched stores (when intent=store_search)"
    )
    needs_location: bool = Field(
        False,
        description="True when GPS is required but unavailable — frontend should prompt",
    )
    location_prompt: Optional[str] = Field(
        None, description="Hebrew question to ask the user for their location"
    )
    voucher_network: str = Field("buyme", description="Voucher network used for this response")
    search_time_ms: float = Field(0.0, ge=0.0, description="Total server-side time in ms")
