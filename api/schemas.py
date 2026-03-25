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
    total: int = Field(..., ge=0, description="Total number of results returned")
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
