
import asyncio
import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

load_dotenv()

# Import models after loading env
from db.models import Store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://localhost/buyme_search")
LATEST_JSON = Path("data/processed/buyme_stores/stores_20260407T005055.json")

async def update_categories():
    if not LATEST_JSON.exists():
        logger.error(f"File not found: {LATEST_JSON}")
        return

    logger.info(f"Loading latest store data from {LATEST_JSON}")
    with open(LATEST_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    scraped_stores = data.get("stores", [])
    logger.info(f"Processing {len(scraped_stores)} stores from JSON")

    engine = create_async_engine(DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://"), echo=False)
    async_session = async_sessionmaker(engine, expire_on_commit=False)

    updated_count = 0
    
    async with async_session() as session:
        for s in scraped_stores:
            buyme_url = s.get("buyme_url")
            new_cat = s.get("buyme_category")
            
            if not buyme_url or not new_cat:
                continue
                
            # Perform update
            stmt = (
                update(Store)
                .where(Store.buyme_url == buyme_url)
                .where(Store.buyme_category != new_cat)
                .values(buyme_category=new_cat)
            )
            result = await session.execute(stmt)
            if result.rowcount > 0:
                updated_count += 1
                if updated_count % 100 == 0:
                    logger.info(f"  Updated {updated_count} stores...")
        
        await session.commit()
    
    await engine.dispose()
    logger.info(f"Finished. Total stores updated: {updated_count}")

if __name__ == "__main__":
    asyncio.run(update_categories())
