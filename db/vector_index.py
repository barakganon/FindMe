"""
db/vector_index.py — Layer 3: pgvector setup for semantic product search.

Overview
--------
This module manages product embeddings for the FindMe / BuyMe Smart Search
platform.  It provides two main abstractions:

EmbeddingService
    Wraps the OpenAI Embeddings API to produce 1 536-dimensional vectors using
    the ``text-embedding-3-small`` model.  Each vector represents the semantic
    meaning of a product's canonical name, brand, and category.

VectorIndex
    Handles all database-side embedding operations: enabling the pgvector
    extension, persisting embeddings, and performing cosine-similarity search.

Embedding column
    ``products.embedding_vector`` is stored as TEXT in the initial schema.
    The value is a JSON-encoded ``list[float]`` of length 1 536.  An Alembic
    migration in ``db/migrations/`` will ALTER the column to ``vector(1536)``
    once pgvector is confirmed available; at that point the Python-side cosine
    fallback in ``search_similar`` can be replaced with a native ``<=>``
    operator query.

Embedding model
    ``text-embedding-3-small`` — 1 536 dimensions, low cost, strong multilingual
    quality (important for Hebrew + English mixed product names).
"""

from __future__ import annotations

import json
import logging
import math
from typing import Optional

import openai
from sqlalchemy import text, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db.models import Product

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EMBEDDING_DIM: int = 1536
"""Dimensionality of text-embedding-3-small vectors."""

_OPENAI_EMBEDDING_MODEL = "text-embedding-3-small"


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------


def cosine_similarity_vectors(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two equal-length float vectors.

    Pure-Python implementation used as a fallback when the pgvector native
    operator is not yet available (i.e. while the column is still TEXT).

    Args:
        a: First embedding vector.
        b: Second embedding vector.

    Returns:
        Cosine similarity in the range [-1.0, 1.0].  Returns 0.0 if either
        vector has zero magnitude (avoids division by zero).
    """
    if len(a) != len(b):
        raise ValueError(
            f"Vector length mismatch: {len(a)} vs {len(b)}"
        )

    dot_product: float = sum(x * y for x, y in zip(a, b))
    magnitude_a: float = math.sqrt(sum(x * x for x in a))
    magnitude_b: float = math.sqrt(sum(x * x for x in b))

    if magnitude_a == 0.0 or magnitude_b == 0.0:
        return 0.0

    return dot_product / (magnitude_a * magnitude_b)


# ---------------------------------------------------------------------------
# EmbeddingService
# ---------------------------------------------------------------------------


class EmbeddingService:
    """Wraps the OpenAI Embeddings API for product text vectorisation.

    Uses the ``text-embedding-3-small`` model (1 536 dims) which offers strong
    multilingual quality — important for Hebrew/English mixed product names
    common in Israeli retail.

    Args:
        api_key: OpenAI API key.  Should be read from the ``OPENAI_API_KEY``
                 environment variable by the caller.
    """

    def __init__(self, api_key: str) -> None:
        """Initialise an async OpenAI client.

        Args:
            api_key: OpenAI API key.
        """
        self._client = openai.AsyncOpenAI(api_key=api_key)

    async def embed_text(self, text_input: str) -> list[float]:
        """Embed a single text string using text-embedding-3-small.

        Args:
            text_input: The text to embed.  May be Hebrew, English, or mixed.

        Returns:
            A list of 1 536 floats representing the semantic vector.

        Raises:
            openai.OpenAIError: On API failure (network, quota, etc.).
        """
        logger.debug(
            "embed_text: requesting embedding for %d chars", len(text_input)
        )
        response = await self._client.embeddings.create(
            input=text_input,
            model=_OPENAI_EMBEDDING_MODEL,
        )
        vector: list[float] = response.data[0].embedding
        logger.debug("embed_text: received vector of dim %d", len(vector))
        return vector

    async def embed_product(
        self,
        canonical_name: str,
        brand: Optional[str] = None,
        category_path: Optional[str] = None,
    ) -> list[float]:
        """Build a product text string and embed it.

        Concatenates the available product fields into a single descriptive
        string and delegates to :meth:`embed_text`.  Fields are joined with
        spaces; ``None`` values are silently omitted.

        Example concatenation::

            "Sony Wireless Noise-Cancelling Headphones WH-1000XM5 Electronics > Headphones > Over-ear"

        Args:
            canonical_name: Normalised product name (required).
            brand:          Brand / manufacturer name (optional).
            category_path:  Hierarchical category string (optional).

        Returns:
            A list of 1 536 floats representing the product embedding.
        """
        parts: list[str] = []
        if brand:
            parts.append(brand)
        parts.append(canonical_name)
        if category_path:
            parts.append(category_path)

        combined_text = " ".join(parts)
        logger.debug(
            "embed_product: combined text = %r (%d chars)",
            combined_text[:80],
            len(combined_text),
        )
        return await self.embed_text(combined_text)


# ---------------------------------------------------------------------------
# VectorIndex
# ---------------------------------------------------------------------------


class VectorIndex:
    """Database-side embedding storage and similarity search.

    Manages the lifecycle of product embeddings in PostgreSQL:

    * Enabling the pgvector extension.
    * Persisting embeddings to ``products.embedding_vector``.
    * Searching for semantically similar products via cosine similarity.
    * Bulk re-indexing of products that have no embedding yet.

    Note on column type
    -------------------
    ``products.embedding_vector`` is currently typed as ``TEXT`` and stores a
    JSON-encoded ``list[float]``.  Once the Alembic migration converts it to
    ``vector(1536)``, the Python-side cosine fallback in
    :meth:`search_similar` can be replaced with a native pgvector ``<=>``
    query for significantly better performance at scale.

    Args:
        session_factory: An :class:`async_sessionmaker` bound to the async
                         PostgreSQL engine.
    """

    def __init__(self, session_factory: async_sessionmaker) -> None:
        """Store the async session factory.

        Args:
            session_factory: Async SQLAlchemy session factory.
        """
        self._session_factory = session_factory

    async def enable_pgvector_extension(self) -> None:
        """Enable the pgvector PostgreSQL extension if not already present.

        Executes ``CREATE EXTENSION IF NOT EXISTS vector`` in a dedicated
        transaction.  This is idempotent and safe to call on every startup.

        Raises:
            sqlalchemy.exc.SQLAlchemyError: If the statement fails (e.g. the
                extension is not installed on the server).
        """
        async with self._session_factory() as session:
            async with session.begin():
                await session.execute(
                    text("CREATE EXTENSION IF NOT EXISTS vector")
                )
        logger.info("pgvector extension enabled (or already present)")

    async def upsert_product_embedding(
        self, product_id: str, embedding: list[float]
    ) -> None:
        """Persist an embedding vector for a product.

        Serialises the embedding as a JSON string and writes it to the
        ``products.embedding_vector`` column.  Uses a SQLAlchemy UPDATE so
        the row must already exist (products are created by the normalisation
        pipeline before embeddings are generated).

        Args:
            product_id: The UUID string of the product to update.
            embedding:  The 1 536-float embedding vector.

        Raises:
            sqlalchemy.exc.SQLAlchemyError: On database write failure.
        """
        embedding_json: str = json.dumps(embedding)
        async with self._session_factory() as session:
            async with session.begin():
                await session.execute(
                    update(Product)
                    .where(Product.id == product_id)
                    .values(embedding_vector=embedding_json)
                )
        logger.debug("upsert_product_embedding: updated product %s", product_id)

    async def search_similar(
        self,
        query_embedding: list[float],
        limit: int = 10,
        min_similarity: float = 0.7,
    ) -> list[dict]:
        """Find products whose embedding is most similar to the query vector.

        Because ``products.embedding_vector`` is currently typed as TEXT
        (not the native ``vector(1536)``), this method implements a
        Python-side cosine similarity fallback:

        1. Fetch all products with a non-null ``embedding_vector``.
        2. Parse each stored JSON string into a ``list[float]``.
        3. Compute cosine similarity against the query vector.
        4. Filter by ``min_similarity``, sort descending, return top ``limit``.

        Once the column is migrated to the ``vector(1536)`` type, replace
        this implementation with a native ``<=>`` (cosine distance) query
        using an IVFFlat or HNSW index for O(log n) lookup.

        Args:
            query_embedding:  1 536-float query vector.
            limit:            Maximum number of results to return (default 10).
            min_similarity:   Minimum cosine similarity threshold (default 0.7).

        Returns:
            List of dicts, each with keys:
            ``product_id``, ``canonical_name``, ``brand``,
            ``category_path``, ``similarity_score``.
            Sorted by ``similarity_score`` descending.
        """
        async with self._session_factory() as session:
            stmt = select(Product).where(Product.embedding_vector.isnot(None))
            result = await session.execute(stmt)
            products: list[Product] = list(result.scalars().all())

        logger.debug(
            "search_similar: scoring %d products with stored embeddings",
            len(products),
        )

        scored: list[tuple[float, Product]] = []
        for product in products:
            try:
                stored_vector: list[float] = json.loads(product.embedding_vector)  # type: ignore[arg-type]
                similarity = cosine_similarity_vectors(query_embedding, stored_vector)
                if similarity >= min_similarity:
                    scored.append((similarity, product))
            except (json.JSONDecodeError, ValueError, TypeError) as exc:
                logger.warning(
                    "search_similar: could not parse embedding for product %s — %s",
                    product.id,
                    exc,
                )

        # Sort by similarity descending, truncate to limit
        scored.sort(key=lambda t: t[0], reverse=True)
        top = scored[:limit]

        results: list[dict] = [
            {
                "product_id": str(product.id),
                "canonical_name": product.canonical_name,
                "brand": product.brand,
                "category_path": product.category_path,
                "similarity_score": round(score, 6),
            }
            for score, product in top
        ]

        logger.info(
            "search_similar: returning %d results (min_similarity=%.2f)",
            len(results),
            min_similarity,
        )
        return results

    async def reindex_all_products(
        self, embedding_service: EmbeddingService
    ) -> int:
        """Embed all products that currently have no embedding vector.

        Fetches every ``Product`` row where ``embedding_vector IS NULL``,
        calls :meth:`EmbeddingService.embed_product` for each one, and
        persists the result via :meth:`upsert_product_embedding`.

        Args:
            embedding_service: A ready :class:`EmbeddingService` instance.

        Returns:
            The number of products that were successfully indexed in this run.
        """
        async with self._session_factory() as session:
            stmt = select(Product).where(Product.embedding_vector.is_(None))
            result = await session.execute(stmt)
            products_to_index: list[Product] = list(result.scalars().all())

        logger.info(
            "reindex_all_products: %d products need embedding", len(products_to_index)
        )

        indexed_count = 0
        for product in products_to_index:
            try:
                embedding = await embedding_service.embed_product(
                    canonical_name=product.canonical_name,
                    brand=product.brand,
                    category_path=product.category_path,
                )
                await self.upsert_product_embedding(
                    product_id=str(product.id), embedding=embedding
                )
                indexed_count += 1
                logger.debug(
                    "reindex_all_products: indexed product %s (%r)",
                    product.id,
                    product.canonical_name,
                )
            except Exception as exc:
                logger.error(
                    "reindex_all_products: failed to embed product %s (%r): %s",
                    product.id,
                    product.canonical_name,
                    exc,
                )

        logger.info(
            "reindex_all_products: done — %d / %d products indexed",
            indexed_count,
            len(products_to_index),
        )
        return indexed_count
