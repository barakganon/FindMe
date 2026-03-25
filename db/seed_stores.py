"""
db/seed_stores.py — Load scraped BuyMe stores into the database.

Usage:
    python -m db.seed_stores
"""
from __future__ import annotations

import asyncio
import glob
import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

load_dotenv()

from db.models import Store, ScrapeStatus

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://localhost/buyme_search")
PROCESSED_DIR = Path("scraper/data/processed/buyme_stores")


def _latest_file() -> Path | None:
    files = sorted(PROCESSED_DIR.glob("stores_*.json"))
    return files[-1] if files else None


def _map_category(voucher_types: list[str]) -> str:
    if not voucher_types:
        return "other"
    if "BUYME_STYLE" in voucher_types:
        return "retail"
    if "BUYME_TOGETHER" in voucher_types:
        return "restaurant"
    return "retail"


async def seed(path: Path) -> None:
    logger.info("Loading stores from %s", path)
    data = json.loads(path.read_text())
    stores = data["stores"]
    logger.info("Found %d stores in file", len(stores))

    engine = create_async_engine(DATABASE_URL, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    inserted = 0
    skipped = 0

    async with factory() as session:
        for s in stores:
            buyme_url = s.get("buyme_url")

            # Check if already exists
            existing = await session.scalar(
                select(Store).where(Store.buyme_url == buyme_url)
            )
            if existing:
                skipped += 1
                continue

            store = Store(
                name_he=s.get("name_he") or s.get("name", "Unknown"),
                name_en=None,
                buyme_url=buyme_url,
                store_url=s.get("store_url"),
                buyme_category=_map_category(s.get("voucher_types", [])),
                is_online=bool(s.get("online_redeem", False)),
                address=s.get("address"),
                city=None,
                lat=None,
                lng=None,
                scrape_status=ScrapeStatus.PENDING,
            )
            session.add(store)
            inserted += 1

            # Commit in batches of 100
            if inserted % 100 == 0:
                await session.commit()
                logger.info("  %d inserted so far...", inserted)

        await session.commit()

    await engine.dispose()
    logger.info("Done. Inserted: %d, Skipped (already existed): %d", inserted, skipped)


if __name__ == "__main__":
    path = _latest_file()
    if not path:
        logger.error("No processed stores file found in %s", PROCESSED_DIR)
        raise SystemExit(1)
    asyncio.run(seed(path))
