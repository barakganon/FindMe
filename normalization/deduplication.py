"""
normalization/deduplication.py — Layer 2: Deduplication Engine.

Detects when two different store listings refer to the same physical product by
computing semantic similarity between their embeddings. Uses OpenAI
text-embedding-3-small to produce dense vector representations of product
names and brands, then applies cosine similarity to identify near-duplicate
entries.

When a candidate product's similarity to an existing master product record
exceeds the configured threshold (default 0.92), it is classified as a
duplicate and linked to that master record rather than creating a new one.
This ensures the products table contains one canonical entry per product,
while store_products holds the per-store pricing and availability rows.

Usage example:
    client = EmbeddingClient(api_key="sk-...")
    engine = DeduplicationEngine(embedding_client=client, similarity_threshold=0.92)

    existing = [
        {"id": "uuid-1", "canonical_name": "WH-1000XM5 אוזניות", "brand": "Sony"},
    ]
    result = await engine.find_duplicate(
        candidate_name="WH1000XM5 Headphones",
        candidate_brand="Sony",
        existing_products=existing,
    )
    # result.is_duplicate -> True if similarity >= 0.92
"""

from __future__ import annotations

import asyncio
import logging
import math
from typing import Optional

import openai
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_EMBEDDING_MODEL = "text-embedding-3-small"
_BATCH_CONCURRENCY = 20  # max concurrent embedding API calls


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two embedding vectors.

    Uses a pure-Python implementation so NumPy is not required. Returns a
    value in the range [0.0, 1.0]. For well-formed unit-normalised embeddings
    from the OpenAI API the result will naturally fall in this range.

    Args:
        a: First embedding vector (list of floats).
        b: Second embedding vector (list of floats, same length as ``a``).

    Returns:
        Cosine similarity as a float between 0.0 and 1.0. Returns 0.0 when
        either vector is the zero vector to avoid division-by-zero.
    """
    if len(a) != len(b):
        raise ValueError(
            f"Vector length mismatch: len(a)={len(a)}, len(b)={len(b)}"
        )

    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))

    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0

    # Clamp to [0, 1] to handle minor floating-point drift
    raw = dot / (norm_a * norm_b)
    return max(0.0, min(1.0, raw))


# ---------------------------------------------------------------------------
# DeduplicationResult
# ---------------------------------------------------------------------------


class DeduplicationResult(BaseModel):
    """Result of a single deduplication check against the master product index.

    Attributes:
        is_duplicate: True when the candidate is considered the same product as
            an existing master record (i.e. similarity >= threshold).
        similarity_score: Cosine similarity between the candidate and the best
            matching existing product. Range [0.0, 1.0].
        master_product_id: UUID string of the existing master product when
            ``is_duplicate`` is True; None otherwise.
        reason: Human-readable explanation of the decision, useful for
            debugging and audit logging.
    """

    is_duplicate: bool
    similarity_score: float = Field(ge=0.0, le=1.0)
    master_product_id: Optional[str] = None
    reason: str


# ---------------------------------------------------------------------------
# EmbeddingClient
# ---------------------------------------------------------------------------


class EmbeddingClient:
    """Async wrapper around the OpenAI Embeddings API.

    Uses the ``text-embedding-3-small`` model which offers a strong
    cost/quality trade-off for Hebrew+English product text.

    Args:
        api_key: OpenAI API key. Typically read from the OPENAI_API_KEY
            environment variable by the caller.
    """

    def __init__(self, api_key: str) -> None:
        """Initialise the async OpenAI client.

        Args:
            api_key: OpenAI API key.
        """
        self._client = openai.AsyncOpenAI(api_key=api_key)

    async def embed(self, text: str) -> list[float]:
        """Embed a single text string and return its vector.

        Args:
            text: The text to embed. May be Hebrew, English, or mixed.

        Returns:
            A list of floats representing the embedding vector. On API
            failure, logs the error and returns an empty list; callers
            must handle this gracefully.

        Raises:
            openai.OpenAIError: Propagates only unexpected / non-retriable
                errors after logging.
        """
        try:
            response = await self._client.embeddings.create(
                input=text,
                model=_EMBEDDING_MODEL,
            )
            return response.data[0].embedding
        except openai.OpenAIError as exc:
            logger.error(
                "EmbeddingClient.embed failed for text=%r: %s", text[:80], exc
            )
            return []

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts concurrently, respecting a concurrency cap.

        Uses an ``asyncio.Semaphore`` to limit simultaneous API requests to
        ``_BATCH_CONCURRENCY`` (20) at a time, preventing rate-limit errors on
        large batches.

        Args:
            texts: List of strings to embed. Order is preserved in the output.

        Returns:
            List of embedding vectors in the same order as ``texts``. Any
            individual failure returns an empty list at that position.
        """
        semaphore = asyncio.Semaphore(_BATCH_CONCURRENCY)

        async def _embed_with_limit(text: str) -> list[float]:
            async with semaphore:
                return await self.embed(text)

        return list(
            await asyncio.gather(*(_embed_with_limit(t) for t in texts))
        )


# ---------------------------------------------------------------------------
# DeduplicationEngine
# ---------------------------------------------------------------------------


def _build_product_text(name: str, brand: Optional[str]) -> str:
    """Combine brand and name into a single string for embedding.

    Putting the brand first improves embedding quality because the model
    sees brand context before the product name.

    Args:
        name: Canonical product name (Hebrew/English/mixed).
        brand: Optional brand/manufacturer name.

    Returns:
        A single string: ``"<brand> <name>"`` when brand is present,
        otherwise just ``"<name>"``.
    """
    if brand:
        return f"{brand} {name}"
    return name


class DeduplicationEngine:
    """Identifies duplicate product listings using embedding-based similarity.

    Embeds candidate product names/brands with OpenAI and compares them
    against a list of existing master product records. A candidate is
    classified as a duplicate when its cosine similarity to the best-matching
    master exceeds ``similarity_threshold``.

    Args:
        embedding_client: Pre-configured :class:`EmbeddingClient` instance.
        similarity_threshold: Minimum cosine similarity to declare a
            duplicate. Default 0.92 — high enough to catch variant spellings
            (e.g. "WH-1000XM5" vs "WH1000XM5") while avoiding false positives
            across distinct models.
    """

    def __init__(
        self,
        embedding_client: EmbeddingClient,
        similarity_threshold: float = 0.92,
    ) -> None:
        """Initialise the engine.

        Args:
            embedding_client: Async embedding client to use.
            similarity_threshold: Cosine similarity threshold for duplicate
                detection (0.0–1.0). Defaults to 0.92.
        """
        self._embedder = embedding_client
        self._threshold = similarity_threshold

    async def find_duplicate(
        self,
        candidate_name: str,
        candidate_brand: Optional[str],
        existing_products: list[dict],
    ) -> DeduplicationResult:
        """Check whether a candidate product already exists in the master index.

        Embeds the candidate (``"<brand> <name>"``) and all existing products,
        then finds the highest cosine similarity. If it meets the threshold the
        candidate is declared a duplicate and linked to that master record.

        Args:
            candidate_name: Canonical name of the incoming product
                (Hebrew/English/mixed).
            candidate_brand: Optional brand name of the incoming product.
            existing_products: List of dicts from the ``products`` table, each
                with keys:
                - ``"id"`` (str): UUID of the master product.
                - ``"canonical_name"`` (str): Stored canonical name.
                - ``"brand"`` (Optional[str]): Stored brand name.

        Returns:
            A :class:`DeduplicationResult` describing whether the candidate
            is a duplicate and, if so, which master product it matches.
        """
        if not existing_products:
            return DeduplicationResult(
                is_duplicate=False,
                similarity_score=0.0,
                master_product_id=None,
                reason="No existing products to compare against.",
            )

        candidate_text = _build_product_text(candidate_name, candidate_brand)

        # Embed candidate
        candidate_vector = await self._embedder.embed(candidate_text)
        if not candidate_vector:
            logger.warning(
                "find_duplicate: embedding failed for candidate %r", candidate_text
            )
            return DeduplicationResult(
                is_duplicate=False,
                similarity_score=0.0,
                master_product_id=None,
                reason="embedding failed",
            )

        # Embed all existing products
        existing_texts = [
            _build_product_text(p["canonical_name"], p.get("brand"))
            for p in existing_products
        ]
        existing_vectors = await self._embedder.embed_batch(existing_texts)

        best_score = 0.0
        best_id: Optional[str] = None
        best_name: Optional[str] = None

        for product, vector in zip(existing_products, existing_vectors):
            if not vector:
                # Skip products whose embedding failed
                continue
            score = cosine_similarity(candidate_vector, vector)
            if score > best_score:
                best_score = score
                best_id = product["id"]
                best_name = product["canonical_name"]

        if best_score >= self._threshold:
            return DeduplicationResult(
                is_duplicate=True,
                similarity_score=best_score,
                master_product_id=best_id,
                reason=(
                    f"Candidate '{candidate_text}' matches existing master product "
                    f"'{best_name}' (id={best_id}) with similarity "
                    f"{best_score:.4f} >= threshold {self._threshold}."
                ),
            )

        return DeduplicationResult(
            is_duplicate=False,
            similarity_score=best_score,
            master_product_id=None,
            reason=(
                f"Best match was '{best_name}' with similarity "
                f"{best_score:.4f}, below threshold {self._threshold}. "
                "Candidate will create a new master product record."
            ),
        )

    async def find_duplicate_batch(
        self,
        candidates: list[dict],
        existing_products: list[dict],
    ) -> list[DeduplicationResult]:
        """Batch deduplication for multiple candidate products at once.

        More efficient than calling :meth:`find_duplicate` in a loop because
        all embeddings (candidates + existing products) are computed in a
        single batched call via :meth:`EmbeddingClient.embed_batch`.

        Args:
            candidates: List of dicts, each with keys:
                - ``"canonical_name"`` (str): Product name.
                - ``"brand"`` (Optional[str]): Brand name.
            existing_products: List of dicts from the ``products`` table, each
                with keys ``"id"``, ``"canonical_name"``, and ``"brand"``.

        Returns:
            List of :class:`DeduplicationResult` in the same order as
            ``candidates``. Any candidate whose embedding fails gets a
            ``is_duplicate=False`` result with ``reason="embedding failed"``.
        """
        if not candidates:
            return []

        candidate_texts = [
            _build_product_text(c["canonical_name"], c.get("brand"))
            for c in candidates
        ]
        existing_texts = [
            _build_product_text(p["canonical_name"], p.get("brand"))
            for p in existing_products
        ]

        # Single batched embedding call for all texts
        all_texts = candidate_texts + existing_texts
        all_vectors = await self._embedder.embed_batch(all_texts)

        n_candidates = len(candidates)
        candidate_vectors = all_vectors[:n_candidates]
        existing_vectors = all_vectors[n_candidates:]

        results: list[DeduplicationResult] = []

        for idx, (candidate_text, candidate_vector) in enumerate(
            zip(candidate_texts, candidate_vectors)
        ):
            if not candidate_vector:
                logger.warning(
                    "find_duplicate_batch: embedding failed for candidate[%d]=%r",
                    idx,
                    candidate_text,
                )
                results.append(
                    DeduplicationResult(
                        is_duplicate=False,
                        similarity_score=0.0,
                        master_product_id=None,
                        reason="embedding failed",
                    )
                )
                continue

            if not existing_products:
                results.append(
                    DeduplicationResult(
                        is_duplicate=False,
                        similarity_score=0.0,
                        master_product_id=None,
                        reason="No existing products to compare against.",
                    )
                )
                continue

            best_score = 0.0
            best_id: Optional[str] = None
            best_name: Optional[str] = None

            for product, vector in zip(existing_products, existing_vectors):
                if not vector:
                    continue
                score = cosine_similarity(candidate_vector, vector)
                if score > best_score:
                    best_score = score
                    best_id = product["id"]
                    best_name = product["canonical_name"]

            if best_score >= self._threshold:
                results.append(
                    DeduplicationResult(
                        is_duplicate=True,
                        similarity_score=best_score,
                        master_product_id=best_id,
                        reason=(
                            f"Candidate '{candidate_text}' matches existing master "
                            f"product '{best_name}' (id={best_id}) with similarity "
                            f"{best_score:.4f} >= threshold {self._threshold}."
                        ),
                    )
                )
            else:
                results.append(
                    DeduplicationResult(
                        is_duplicate=False,
                        similarity_score=best_score,
                        master_product_id=None,
                        reason=(
                            f"Best match was '{best_name}' with similarity "
                            f"{best_score:.4f}, below threshold {self._threshold}. "
                            "Candidate will create a new master product record."
                        ),
                    )
                )

        return results
