"""
db/embed_products.py — Generate Gemini embeddings for all products in the DB.

Usage:
    python -m db.embed_products                  # embed all unembedded products
    python -m db.embed_products --batch-size 50  # custom batch size
    python -m db.embed_products --limit 200      # only process first N products
"""
from __future__ import annotations

import asyncio
import logging
import os
from argparse import ArgumentParser

import asyncpg
import httpx
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Gemini native REST API for embeddings (OpenAI-compat endpoint doesn't support them)
_GEMINI_EMBED_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-embedding-001:batchEmbedContents"
)
_EMBED_DIMS = 768
_DEFAULT_BATCH = 100     # paid tier: up to 100 items per batchEmbedContents call
_BATCH_DELAY = 0.1       # paid tier: 1,500 RPM → ~0.04s min; 0.1s is safe
_MAX_RETRIES = 5


def _vec_literal(vec: list[float]) -> str:
    return "[" + ",".join(f"{v:.6f}" for v in vec) + "]"


async def _batch_embed(texts: list[str], api_key: str) -> list[list[float]] | None:
    """Call Gemini batchEmbedContents with exponential backoff on 429."""
    payload = {
        "requests": [
            {
                "model": "models/gemini-embedding-001",
                "content": {"parts": [{"text": t}]},
                "outputDimensionality": _EMBED_DIMS,
            }
            for t in texts
        ]
    }
    delay = 10.0
    for attempt in range(_MAX_RETRIES):
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.post(
                    _GEMINI_EMBED_URL,
                    json=payload,
                    params={"key": api_key},
                )
                if r.status_code == 429:
                    wait = delay * (2 ** attempt)
                    logger.warning("Rate limited (429) — waiting %.0fs before retry %d", wait, attempt + 1)
                    await asyncio.sleep(wait)
                    continue
                r.raise_for_status()
                data = r.json()
                return [item["values"] for item in data["embeddings"]]
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                wait = delay * (2 ** attempt)
                logger.warning("Rate limited — waiting %.0fs", wait)
                await asyncio.sleep(wait)
                continue
            logger.error("Gemini batch embed failed: %s", exc)
            return None
        except Exception as exc:
            logger.error("Gemini batch embed failed: %s", exc)
            return None
    logger.error("Gave up after %d retries", _MAX_RETRIES)
    return None


async def embed_products(
    batch_size: int = _DEFAULT_BATCH,
    limit: int | None = None,
    store_id: str | None = None,
) -> None:
    db_url = os.getenv("DATABASE_URL", "").replace("+asyncpg", "")
    gemini_key = os.getenv("GEMINI_API_KEY", "")

    if not gemini_key:
        raise SystemExit("GEMINI_API_KEY not set in .env")

    conn = await asyncpg.connect(db_url)

    try:
        if store_id:
            q = """
                SELECT DISTINCT p.id, p.canonical_name, p.brand
                FROM products p
                JOIN store_products sp ON p.id = sp.product_id
                WHERE p.embedding_vector IS NULL
                AND sp.store_id = $1::uuid
                ORDER BY p.id
            """
            if limit:
                q += f" LIMIT {limit}"
            rows = await conn.fetch(q, store_id)
        else:
            q = """
                SELECT p.id, p.canonical_name, p.brand
                FROM products p
                LEFT JOIN store_products sp ON p.id = sp.product_id
                WHERE p.embedding_vector IS NULL
                GROUP BY p.id, p.canonical_name, p.brand
                ORDER BY COUNT(sp.id) DESC
            """
            if limit:
                q += f" LIMIT {limit}"
            rows = await conn.fetch(q)
        total = len(rows)
        logger.info("Found %d products needing embeddings", total)

        if total == 0:
            logger.info("All products already embedded.")
            return

        embedded = 0
        failed = 0

        for i in range(0, total, batch_size):
            batch = rows[i : i + batch_size]

            texts = []
            for r in batch:
                t = r["canonical_name"]
                if r["brand"]:
                    t = f"{r['brand']} {t}"
                texts.append(t)

            vecs = await _batch_embed(texts, gemini_key)
            if vecs is None:
                failed += len(batch)
                continue

            updates = [
                (_vec_literal(vecs[j]), str(batch[j]["id"]))
                for j in range(len(batch))
            ]
            await conn.executemany(
                "UPDATE products SET embedding_vector = $1::vector WHERE id = $2::uuid",
                updates,
            )
            embedded += len(batch)
            logger.info("  Embedded %d / %d...", embedded, total)
            # Respect free-tier rate limits between batches
            await asyncio.sleep(_BATCH_DELAY)

        logger.info("Done. Embedded: %d, Failed: %d", embedded, failed)

    finally:
        await conn.close()


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument("--batch-size", type=int, default=_DEFAULT_BATCH)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--store-id", type=str, default=None, help="Only embed products for this store UUID")
    args = parser.parse_args()
    asyncio.run(embed_products(batch_size=args.batch_size, limit=args.limit, store_id=args.store_id))
