"""
BuyMe Store Scraper — Layer 1, Component 1
==========================================
Scrapes buyme.co.il partner stores via its internal JSON API.

BuyMe has 4 voucher types, each with its own brand listing endpoint:
    1. BUYME ALL     — /brands/13438757/options
    2. BUYME TOGETHER — /brands/17574075/options
    3. BUYME STYLE   — /brands/7565407/options
    4. BUYME MIX     — /brands/13438880/options

Each endpoint returns a JSON object with a ``brands`` array containing
the full list of partner stores for that voucher type (~1000–2000 stores).
No browser / Playwright required — pure async HTTP.

Each brand entry includes:
    id, title, logo, online_redeem, phone, googleMapAddr, siteWeb,
    siteLink, siteSlogan, supplier_regions (list of cities/areas),
    categories_on_brands (category name + icon), subcategories_on_brands

Usage (standalone):
    python -m scraper.buyme_store_scraper

Usage (as a module):
    from scraper.buyme_store_scraper import BuyMeStoreScraper
    scraper = BuyMeStoreScraper()
    stores = await scraper.run()
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# API endpoints — one per voucher type
# ---------------------------------------------------------------------------

BUYME_BASE_URL = "https://buyme.co.il"
BUYME_FILES_URL = "https://buyme.co.il/files"

# (internal_name, voucher_listing_id)
VOUCHER_TYPES: list[tuple[str, int]] = [
    ("BUYME_ALL",       13438757),
    ("BUYME_TOGETHER",  17574075),
    ("BUYME_STYLE",     7565407),
    ("BUYME_MIX",       13438880),
]

# ---------------------------------------------------------------------------
# Directories for raw snapshots and processed output
# ---------------------------------------------------------------------------

RAW_DATA_DIR = Path("data/raw/buyme_stores")
OUTPUT_JSON_DIR = Path("data/processed/buyme_stores")

# ---------------------------------------------------------------------------
# HTTP settings
# ---------------------------------------------------------------------------

_REQUEST_TIMEOUT = 20.0  # seconds
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8",
}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class RawStore:
    """
    A single BuyMe partner store as returned by the /brands/<id>/options API.

    Attributes:
        store_id:        Numeric BuyMe store ID.
        name_he:         Store name (Hebrew or mixed Hebrew/English).
        buyme_url:       Full URL of the store's BuyMe page.
        voucher_types:   Which BuyMe voucher types accept this store
                         (may contain multiple if the store appears in
                         more than one voucher-type listing).
        logo_url:        Full URL of the store logo image.
        online_redeem:   True if the voucher can be redeemed online.
        phone:           Contact phone number.
        address:         Physical address string (googleMapAddr field).
        regions:         List of region/city names where the store operates.
        categories:      List of BuyMe category names for this store.
        subcategories:   List of BuyMe subcategory names.
        site_url:        Store's own website URL.
        site_slogan:     Short Hebrew slogan from BuyMe.
        site_instagram:  Instagram profile URL (if available).
        site_facebook:   Facebook page URL (if available).
        search_terms:    Raw search terms string from BuyMe (for search index).
    """

    store_id: int
    name_he: str
    buyme_url: str
    voucher_types: list[str]
    logo_url: Optional[str] = None
    online_redeem: bool = False
    phone: Optional[str] = None
    address: Optional[str] = None
    regions: list[str] = None       # type: ignore[assignment]
    categories: list[str] = None    # type: ignore[assignment]
    subcategories: list[str] = None # type: ignore[assignment]
    site_url: Optional[str] = None
    site_slogan: Optional[str] = None
    site_instagram: Optional[str] = None
    site_facebook: Optional[str] = None
    search_terms: Optional[str] = None

    def __post_init__(self) -> None:
        """Ensure mutable defaults are properly initialised."""
        if self.regions is None:
            self.regions = []
        if self.categories is None:
            self.categories = []
        if self.subcategories is None:
            self.subcategories = []

    @property
    def is_online(self) -> bool:
        """True if this store can redeem vouchers online."""
        return bool(self.online_redeem)

    @property
    def buyme_category(self) -> str:
        """Map first BuyMe category to our internal primary enum value (legacy)."""
        cat = (self.categories[0] if self.categories else "").strip()
        _MAP = {
            "מסעדות וקולינריה": "restaurant",
            "ספא וימי כיף":     "spa",
            "מלונות ונופש":     "hotel",
            "חוויות":           "leisure",
            "סדנאות והעשרה":    "leisure",
            "לגוף ולנפש":       "spa",
            "תרבות ופנאי":      "leisure",
            "לבית":             "retail",
            "תינוקות וילדים":   "retail",
            "טיפוח ויופי":      "retail",
            "אופנה ושופינג":    "retail",
        }
        return _MAP.get(cat, "other")

    @property
    def redemption_details_url(self) -> Optional[str]:
        """Specific link for voucher redemption details."""
        return f"{BUYME_BASE_URL}/brands/{self.store_id}?showRedemption=true"

    def to_dict(self) -> dict:
        """Serialize to a plain dict including computed properties."""
        d = asdict(self)
        d["buyme_category"] = self.buyme_category
        d["redemption_details_url"] = self.redemption_details_url
        d["is_online"] = self.is_online
        return d


# ---------------------------------------------------------------------------
# Scraper
# ---------------------------------------------------------------------------

class BuyMeStoreScraper:
    """
    Scrapes all BuyMe partner stores from the 4 voucher-type API endpoints.

    Uses ``httpx.AsyncClient`` — no browser required.  All 4 voucher-type
    endpoints are fetched concurrently.  Stores that appear in multiple
    voucher types are merged into a single ``RawStore`` with a combined
    ``voucher_types`` list.

    Example::

        scraper = BuyMeStoreScraper()
        stores = await scraper.run()
        # → list[RawStore], typically ~1200-1500 unique stores
    """

    def __init__(
        self,
        save_raw: bool = True,
        raw_data_dir: Path = RAW_DATA_DIR,
        output_dir: Path = OUTPUT_JSON_DIR,
    ) -> None:
        """Initialise the scraper.

        Args:
            save_raw:     Write raw JSON snapshots to disk for auditing.
            raw_data_dir: Directory for raw JSON snapshots.
            output_dir:   Directory for the processed output file.
        """
        self.save_raw = save_raw
        self.raw_data_dir = raw_data_dir
        self.output_dir = output_dir

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def run(self) -> list[RawStore]:
        """
        Fetch all 4 voucher-type endpoints concurrently and merge results.

        Returns:
            De-duplicated list of ``RawStore`` objects.  Each store's
            ``voucher_types`` field lists every voucher type that accepts it.
        """
        async with httpx.AsyncClient(
            headers=_HEADERS,
            follow_redirects=True,
            timeout=_REQUEST_TIMEOUT,
        ) as client:
            tasks = [
                self._fetch_voucher_type(client, name, vid)
                for name, vid in VOUCHER_TYPES
            ]
            results: list[tuple[str, list[dict]]] = await asyncio.gather(*tasks)

        # Merge: store_id → RawStore (combining voucher_types)
        merged: dict[int, RawStore] = {}
        for voucher_name, brands in results:
            for brand in brands:
                store_id: int = brand["id"]
                if store_id in merged:
                    merged[store_id].voucher_types.append(voucher_name)
                else:
                    merged[store_id] = self._map_brand(brand, voucher_name)

        stores = list(merged.values())
        logger.info("Total unique stores: %d", len(stores))

        if self.save_raw:
            await self._save_results(stores)

        return stores

    # ------------------------------------------------------------------
    # HTTP fetch
    # ------------------------------------------------------------------

    async def _fetch_voucher_type(
        self, client: httpx.AsyncClient, voucher_name: str, voucher_id: int
    ) -> tuple[str, list[dict]]:
        """
        Fetch all brands for one voucher type from the BuyMe API.

        Args:
            client:       Shared async HTTP client.
            voucher_name: Internal name (e.g. ``"BUYME_ALL"``).
            voucher_id:   Numeric ID used in the URL path.

        Returns:
            A tuple of ``(voucher_name, brands_list)`` where ``brands_list``
            is the raw ``brands`` array from the API response.
        """
        url = f"{BUYME_BASE_URL}/brands/{voucher_id}/options"
        logger.info("Fetching %s → %s", voucher_name, url)

        try:
            response = await client.get(
                url,
                headers={**_HEADERS, "Referer": f"{BUYME_BASE_URL}/brands/{voucher_id}"},
            )
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            logger.error("Failed to fetch %s (%s): %s", voucher_name, url, exc)
            return voucher_name, []

        brands: list[dict] = data.get("brands", [])
        logger.info("  %s → %d stores", voucher_name, len(brands))

        if self.save_raw:
            await self._save_raw_json(data, f"voucher_{voucher_name}")

        return voucher_name, brands

    # ------------------------------------------------------------------
    # Data mapping
    # ------------------------------------------------------------------

    def _map_brand(self, brand: dict[str, Any], voucher_name: str) -> RawStore:
        """
        Map a raw API brand dict to a ``RawStore`` dataclass.

        Args:
            brand:        A single entry from the ``brands`` array.
            voucher_name: The voucher type this brand was found under.

        Returns:
            A populated ``RawStore``.
        """
        store_id: int = brand["id"]
        buyme_url = f"{BUYME_BASE_URL}/brands/{store_id}"

        # Logo URL
        logo_file: Optional[str] = brand.get("logo")
        logo_url = f"{BUYME_FILES_URL}/{logo_file}" if logo_file else None

        # Regions (cities/areas)
        regions: list[str] = [
            r["name"]
            for r in brand.get("supplier_regions", [])
            if r.get("name")
        ]

        # Categories
        categories: list[str] = [
            c["name"]
            for c in brand.get("categories_on_brands", [])
            if c.get("name")
        ]

        # Subcategories
        subcategories: list[str] = [
            s["name"]
            for s in brand.get("subcategories_on_brands", [])
            if s.get("name")
        ]

        # Website URL — prefer siteWeb, fall back to siteLink
        site_url: Optional[str] = (
            brand.get("siteWeb")
            or brand.get("siteLink")
            or None
        )

        return RawStore(
            store_id=store_id,
            name_he=brand.get("title", "").strip(),
            buyme_url=buyme_url,
            voucher_types=[voucher_name],
            logo_url=logo_url,
            online_redeem=bool(brand.get("online_redeem")),
            phone=brand.get("phone") or None,
            address=brand.get("googleMapAddr") or None,
            regions=regions,
            categories=categories,
            subcategories=subcategories,
            site_url=site_url,
            site_slogan=brand.get("siteSlogan") or None,
            site_instagram=brand.get("siteInstagram") or None,
            site_facebook=brand.get("siteFacebook") or None,
            search_terms=brand.get("searchTerms") or None,
        )

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    async def _save_raw_json(self, data: dict, label: str) -> None:
        """Write a raw API response to disk as JSON.

        Args:
            data:  Parsed JSON dict from the API.
            label: Short name used in the filename.
        """
        self.raw_data_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        path = self.raw_data_dir / f"{label}_{ts}.json"
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.debug("Saved raw JSON → %s", path)

    async def _save_results(self, stores: list[RawStore]) -> None:
        """Write the processed store list to a timestamped JSON file.

        Args:
            stores: List of ``RawStore`` objects to serialize.
        """
        self.output_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        path = self.output_dir / f"stores_{ts}.json"
        payload = {
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "count": len(stores),
            "stores": [s.to_dict() for s in stores],
        }
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info("Saved %d stores → %s", len(stores), path)


# ---------------------------------------------------------------------------
# DB upsert helper (optional — requires live SQLAlchemy session)
# ---------------------------------------------------------------------------

async def upsert_stores_to_db(stores: list[RawStore], session: object) -> int:
    """
    Upsert ``RawStore`` records into the ``stores`` PostgreSQL table.

    Conflict target is ``buyme_url`` (unique column).

    Args:
        stores:  List of ``RawStore`` objects to persist.
        session: Active ``sqlalchemy.ext.asyncio.AsyncSession``.

    Returns:
        Number of rows inserted or updated.
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from db.models import Store

    rows = [
        {
            "name_he":                s.name_he,
            "name_en":                None,
            "buyme_url":              s.buyme_url,
            "store_url":              s.site_url,
            "buyme_category":         s.buyme_category,
            "buyme_categories":       s.categories,
            "redemption_details_url": s.redemption_details_url,
            "is_online":              s.is_online,
            "address":                s.address,
            "city":                   s.regions[0] if s.regions else None,
            "lat":                    None,
            "lng":                    None,
            "scrape_status":          "success",
            "last_scraped_at":        datetime.now(timezone.utc),
        }
        for s in stores
    ]

    stmt = pg_insert(Store).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["buyme_url"],
        set_={
            "name_he":                stmt.excluded.name_he,
            "store_url":              stmt.excluded.store_url,
            "buyme_category":         stmt.excluded.buyme_category,
            "buyme_categories":       stmt.excluded.buyme_categories,
            "redemption_details_url": stmt.excluded.redemption_details_url,
            "is_online":              stmt.excluded.is_online,
            "address":                stmt.excluded.address,
            "city":                   stmt.excluded.city,
            "scrape_status":          stmt.excluded.scrape_status,
            "last_scraped_at":        stmt.excluded.last_scraped_at,
        },
    )
    result = await session.execute(stmt)
    await session.commit()
    return result.rowcount


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

async def _main() -> None:
    """Run the scraper from the command line and print a summary."""
    import os
    from dotenv import load_dotenv
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

    load_dotenv()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )

    scraper = BuyMeStoreScraper(save_raw=True)
    stores = await scraper.run()

    db_url = os.getenv("DATABASE_URL", "postgresql+asyncpg://localhost/buyme_search")
    engine = create_async_engine(db_url.replace("postgresql://", "postgresql+asyncpg://"))
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as session:
        updated = await upsert_stores_to_db(stores, session)
        logger.info("Upserted %d stores to DB.", updated)

    await engine.dispose()

    print(f"\nDone. {len(stores)} unique stores scraped.\n")
    print(f"{'Name':<35} {'Voucher types':<45} {'Category':<20} {'Site URL'}")
    print("-" * 130)
    for s in stores[:25]:
        types = ", ".join(s.voucher_types)
        cat = s.categories[0] if s.categories else ""
        url = s.site_url or "(no url)"
        print(f"  {s.name_he:<33} {types:<45} {cat:<20} {url[:40]}")
    if len(stores) > 25:
        print(f"  ... and {len(stores) - 25} more")

    # Summary by voucher type
    print("\n=== Stores per voucher type ===")
    from collections import Counter
    counts: Counter = Counter()
    for s in stores:
        for vt in s.voucher_types:
            counts[vt] += 1
    for vt, count in counts.most_common():
        print(f"  {vt:<20} {count}")


if __name__ == "__main__":
    asyncio.run(_main())
