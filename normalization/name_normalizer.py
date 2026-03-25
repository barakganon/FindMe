"""
normalization/name_normalizer.py — Layer 2: Product Name Normalizer.

Uses the Claude API (via instructor) to canonicalize Israeli retail product names
in Hebrew, English, or a mix of both. Extracts brand, model, and produces a clean
canonical name that can be used for deduplication and display.

Example:
    'Sony WH1000XM5 אוזניות' → canonical_name='Headphones WH-1000XM5', brand='Sony', model='WH-1000XM5'
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import instructor
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Gemini model used for all normalization tasks (fast + free tier available)
_GEMINI_MODEL = "gemini-2.0-flash"

_SYSTEM_PROMPT = """\
You are a product name normalization expert for an Israeli retail catalog.

Your job is to parse raw product names and extract structured information from them.
Product names may be in Hebrew, English, or a mix of both — this is very common in
Israeli retail (e.g. 'Sony WH1000XM5 אוזניות', 'נעלי ספורט Nike Air Max 270').

For each product name:
1. Extract the BRAND (manufacturer name, e.g. "Sony", "Apple", "Nike", "פיליפס").
   If no brand is identifiable, return an empty string.
2. Extract the MODEL identifier (alphanumeric code, e.g. "WH-1000XM5", "iPhone 15 Pro", "Air Max 270").
   If no model is identifiable, return an empty string.
3. Produce a CANONICAL NAME — a clean, human-readable product name with the brand
   stripped out (e.g. "Wireless Noise-Cancelling Headphones WH-1000XM5").
   The canonical name should be in the dominant language of the input.
4. Detect the LANGUAGE: "he" for Hebrew, "en" for English, "mixed" for a mix.
5. Rate your CONFIDENCE from 0.0 to 1.0 based on how clearly you could parse the name.

Always return valid JSON matching the schema.
"""


class NormalizedName(BaseModel):
    """Structured result of normalizing a raw product name.

    Attributes:
        canonical_name: Clean product name with the brand stripped out.
        brand: Brand / manufacturer name (e.g. "Sony", "Apple"). Empty string if unknown.
        model: Model identifier (e.g. "WH-1000XM5"). Empty string if unknown.
        language_detected: Dominant language — "he", "en", or "mixed".
        confidence: Confidence score for the extraction, between 0.0 and 1.0.
    """

    canonical_name: str = Field(..., description="Clean product name, brand stripped out")
    brand: str = Field(default="", description="Brand name, e.g. 'Sony', 'Apple'")
    model: str = Field(default="", description="Model identifier, e.g. 'WH-1000XM5'")
    language_detected: str = Field(
        default="en",
        description="Dominant language of the raw name: 'he', 'en', or 'mixed'",
    )
    confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Confidence score for the extraction (0.0–1.0)",
    )


class NameNormalizer:
    """Normalizes raw Israeli retail product names using Claude via instructor.

    Uses Claude to extract structured name data (brand, model, canonical name)
    from raw product titles that may be in Hebrew, English, or a mix of both.

    Args:
        client: An async instructor client wrapping an Anthropic AsyncAnthropic instance.
    """

    def __init__(self, client: instructor.AsyncInstructor) -> None:
        """Initialize the normalizer with an instructor async client.

        Args:
            client: instructor.AsyncInstructor wrapping an AsyncOpenAI Gemini client.
        """
        self._client = client

    async def normalize(self, raw_name: str) -> NormalizedName:
        """Normalize a single raw product name using Claude.

        Calls Claude with a structured system prompt and uses instructor to extract
        a NormalizedName object. If the API call fails, logs the error and returns
        a safe default model.

        Args:
            raw_name: The raw product name from a store scrape (Hebrew/English/mixed).

        Returns:
            A NormalizedName with canonical_name, brand, model, language_detected,
            and confidence populated.
        """
        try:
            result: NormalizedName = await self._client.create(
                response_model=NormalizedName,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": f"Normalize this product name: {raw_name}",
                    },
                ],
                model=_GEMINI_MODEL,
                max_tokens=512,
            )
            return result
        except Exception as exc:
            logger.error(
                "NameNormalizer.normalize failed for raw_name=%r: %s", raw_name, exc
            )
            return NormalizedName(
                canonical_name=raw_name,
                brand="",
                model="",
                language_detected="en",
                confidence=0.0,
            )

    async def normalize_batch(self, raw_names: list[str]) -> list[NormalizedName]:
        """Normalize a batch of raw product names concurrently.

        Uses asyncio.gather to run all normalization calls in parallel, significantly
        reducing total latency for large batches.

        Args:
            raw_names: List of raw product names to normalize.

        Returns:
            List of NormalizedName objects in the same order as raw_names.
        """
        tasks = [self.normalize(name) for name in raw_names]
        results: list[NormalizedName] = await asyncio.gather(*tasks)
        return results
