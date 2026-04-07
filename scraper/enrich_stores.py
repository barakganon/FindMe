
import asyncio
import json
import logging
import os
import uuid
from typing import Any, Optional

from dotenv import load_dotenv
from openai import AsyncOpenAI
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

load_dotenv()

from db.models import Store
from api.dependencies import get_ai_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://localhost/buyme_search")

ENRICHMENT_PROMPT = """
You are a retail and travel expert in Israel. Given a store's name, its categories from BuyMe, and search terms, provide structured metadata.

Input:
Name: {name}
Categories: {categories}

Tasks:
1. Chain Detection: Is this store part of a well-known chain in Israel? (e.g., Isrotel, Fox, Castro, Greg Cafe). 
   - Provide the 'canonical_chain_name' (in Hebrew).
2. Store Description: A short 1-sentence description of what they sell/offer.
3. Target Audience: Who is this for? (e.g., families, couples, tech-enthusiasts).
4. Keywords: 5-10 descriptive keywords in Hebrew.

Return JSON only:
{{
  "canonical_chain_name": "string or null",
  "description": "string",
  "target_audience": "string",
  "keywords": ["word1", "word2", ...]
}}
"""

async def enrich_stores(limit: int = 50):
    engine = create_async_engine(DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://"), echo=False)
    async_session = async_sessionmaker(engine, expire_on_commit=False)
    
    ai_client = AsyncOpenAI(api_key=os.getenv("GEMINI_API_KEY"), base_url="https://generativelanguage.googleapis.com/v1beta/openai/")

    async with async_session() as session:
        # Find stores that haven't been enriched yet (metadata_json is empty default '{}')
        stmt = select(Store).where(Store.metadata_json == {}).limit(limit)
        result = await session.execute(stmt)
        stores = result.scalars().all()
        
        logger.info(f"Found {len(stores)} stores to enrich")
        
        for store in stores:
            try:
                prompt = ENRICHMENT_PROMPT.format(
                    name=store.name_he,
                    categories=", ".join(store.buyme_categories or [])
                )
                
                response = await ai_client.chat.completions.create(
                    model="gemini-2.5-flash",
                    messages=[{"role": "user", "content": prompt}],
                    response_format={"type": "json_object"}
                )
                
                meta = json.loads(response.choices[0].message.content)
                logger.info(f"Enriched {store.name_he}: {meta.get('canonical_chain_name')}")
                
                # Update metadata
                store.metadata_json = meta
                
                # Chain Logic: Link to parent chain
                chain_name = meta.get("canonical_chain_name")
                if chain_name:
                    # Look for existing parent record
                    parent_stmt = select(Store).where(Store.name_he == chain_name)
                    parent_result = await session.execute(parent_stmt)
                    parent = parent_result.scalar_one_or_none()
                    
                    if not parent:
                        # Create a "Virtual Parent" record if it doesn't exist
                        # This record represents the chain as a whole
                        parent = Store(
                            name_he=chain_name,
                            buyme_category=store.buyme_category,
                            buyme_categories=store.buyme_categories,
                            is_online=False, # The parent is virtual
                            scrape_status="success",
                            voucher_network=store.voucher_network
                        )
                        session.add(parent)
                        await session.flush() # Get the new ID
                        logger.info(f"Created virtual parent chain: {chain_name}")
                    
                    store.parent_chain_id = parent.id
                
                session.add(store)
                await session.commit()
                
            except Exception as e:
                logger.error(f"Failed to enrich {store.name_he}: {e}")
                await session.rollback()

    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(enrich_stores(limit=20))
