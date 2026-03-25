"""
normalization/pipeline.py — Layer 2: Normalization Pipeline.

Wires together NameNormalizer, CategoryClassifier, and SpecExtractor into a single
async pipeline that transforms a raw scraped product into a clean NormalizedProduct
ready for insertion into the products table.

Usage example:
    pipeline = NormalizationPipeline(gemini_api_key="AIza...")
    product = await pipeline.process_product(
        raw_name="Sony WH1000XM5 אוזניות אלחוטיות",
        raw_description="אוזניות over-ear עם ביטול רעשים אקטיבי, צבע שחור, 30 שעות סוללה",
    )
"""

from __future__ import annotations

import logging
from typing import Optional

import instructor
from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from normalization.category_classifier import CategoryClassifier, ClassifiedCategory
from normalization.name_normalizer import NameNormalizer, NormalizedName
from normalization.spec_extractor import ExtractedSpecs, SpecExtractor

logger = logging.getLogger(__name__)


_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


def get_instructor_client(api_key: str) -> instructor.AsyncInstructor:
    """Create an async instructor client using Gemini's OpenAI-compatible endpoint.

    This is the canonical factory function for creating the client used by all
    normalization components. Always use this instead of constructing the client
    manually.

    Args:
        api_key: The Gemini API key (from GEMINI_API_KEY env var).

    Returns:
        An instructor.AsyncInstructor configured for Gemini via OpenAI-compat mode.
    """
    raw_client = AsyncOpenAI(api_key=api_key, base_url=_GEMINI_BASE_URL)
    return instructor.from_openai(raw_client)


class NormalizedProduct(BaseModel):
    """Fully normalized product record combining name, category, and spec data.

    This model is the output of the NormalizationPipeline and maps directly to
    the columns of the `products` table in db/models.py.

    Attributes:
        canonical_name: Clean product name with brand stripped (from NameNormalizer).
        brand: Brand / manufacturer name (from NameNormalizer or SpecExtractor).
        model: Model identifier code (from NameNormalizer or SpecExtractor).
        language_detected: Detected language of the raw name — "he", "en", or "mixed".
        name_confidence: Confidence score for the name normalization (0.0–1.0).
        category_path: Full hierarchical category path (from CategoryClassifier).
        top_level_category: Top-level category segment (from CategoryClassifier).
        category_confidence: Confidence score for the category classification (0.0–1.0).
        category_reasoning: Brief explanation of the category choice (for debugging).
        color: Product color (from SpecExtractor).
        size: Product size — clothing, screen, etc. (from SpecExtractor).
        weight: Weight with units (from SpecExtractor).
        storage_gb: Storage in GB for electronics (from SpecExtractor).
        material: Material for fashion/furniture (from SpecExtractor).
        additional_specs: Catch-all dict of extra specs (from SpecExtractor).
    """

    # --- From NameNormalizer ---
    canonical_name: str = Field(..., description="Clean product name, brand stripped out")
    brand: Optional[str] = Field(default=None, description="Brand / manufacturer name")
    model: Optional[str] = Field(default=None, description="Model identifier code")
    language_detected: str = Field(
        default="en", description="'he', 'en', or 'mixed'"
    )
    name_confidence: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Name normalization confidence"
    )

    # --- From CategoryClassifier ---
    category_path: Optional[str] = Field(
        default=None, description="e.g. 'Electronics > Audio > Headphones > Over-ear'"
    )
    top_level_category: Optional[str] = Field(
        default=None, description="e.g. 'Electronics'"
    )
    category_confidence: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Category classification confidence"
    )
    category_reasoning: str = Field(
        default="", description="Brief explanation of the category choice"
    )

    # --- From SpecExtractor ---
    color: Optional[str] = Field(default=None, description="Product color")
    size: Optional[str] = Field(default=None, description="Size (clothing, screen, etc.)")
    weight: Optional[str] = Field(default=None, description="Weight with units")
    storage_gb: Optional[int] = Field(
        default=None, description="Storage in GB (electronics)"
    )
    material: Optional[str] = Field(
        default=None, description="Material (fashion/furniture)"
    )
    additional_specs: dict[str, str] = Field(
        default_factory=dict,
        description="Catch-all extra specs",
    )


def _merge(
    name: NormalizedName,
    category: ClassifiedCategory,
    specs: ExtractedSpecs,
) -> NormalizedProduct:
    """Merge the three component outputs into a single NormalizedProduct.

    Brand and model from NameNormalizer take precedence; SpecExtractor values
    are used as fallbacks when the name normalizer returned empty strings.

    Args:
        name: Output from NameNormalizer.normalize().
        category: Output from CategoryClassifier.classify().
        specs: Output from SpecExtractor.extract().

    Returns:
        A fully populated NormalizedProduct.
    """
    resolved_brand: Optional[str] = name.brand or specs.brand or None
    resolved_model: Optional[str] = name.model or specs.model or None

    return NormalizedProduct(
        canonical_name=name.canonical_name,
        brand=resolved_brand,
        model=resolved_model,
        language_detected=name.language_detected,
        name_confidence=name.confidence,
        category_path=category.category_path,
        top_level_category=category.top_level,
        category_confidence=category.confidence,
        category_reasoning=category.reasoning,
        color=specs.color,
        size=specs.size,
        weight=specs.weight,
        storage_gb=specs.storage_gb,
        material=specs.material,
        additional_specs=specs.additional_specs,
    )


class NormalizationPipeline:
    """End-to-end normalization pipeline for raw scraped product data.

    Wires together NameNormalizer, CategoryClassifier, and SpecExtractor.
    All three Gemini calls are run concurrently (via asyncio.gather) to minimize
    latency. The results are merged into a single NormalizedProduct.

    Args:
        gemini_api_key: The Gemini API key. Typically read from the
            GEMINI_API_KEY environment variable by the caller.
    """

    def __init__(self, gemini_api_key: str) -> None:
        """Initialize the pipeline and all component normalizers.

        Args:
            gemini_api_key: Gemini API key for creating the instructor client.
        """
        self._client: instructor.AsyncInstructor = get_instructor_client(
            gemini_api_key
        )
        self._name_normalizer = NameNormalizer(self._client)
        self._category_classifier = CategoryClassifier(self._client)
        self._spec_extractor = SpecExtractor(self._client)

    async def process_product(
        self, raw_name: str, raw_description: str = ""
    ) -> NormalizedProduct:
        """Normalize a raw scraped product into a structured NormalizedProduct.

        Runs all three normalization steps (name, category, specs) concurrently
        using asyncio.gather to minimize total latency. The three results are
        then merged into a single flat NormalizedProduct.

        Product names and descriptions may be in Hebrew, English, or a mix of
        both — all normalizers are designed to handle this.

        Args:
            raw_name: Raw product name from the store scrape (Hebrew/English/mixed).
            raw_description: Optional raw product description for richer context.

        Returns:
            A NormalizedProduct combining name normalization, category
            classification, and spec extraction results.
        """
        import asyncio

        raw_text_for_specs = raw_name
        if raw_description:
            raw_text_for_specs = f"{raw_name}\n{raw_description}"

        try:
            name_result, category_result, specs_result = await asyncio.gather(
                self._name_normalizer.normalize(raw_name),
                self._category_classifier.classify(raw_name, raw_description),
                self._spec_extractor.extract(raw_text_for_specs),
            )
        except Exception as exc:
            logger.error(
                "NormalizationPipeline.process_product failed for raw_name=%r: %s",
                raw_name,
                exc,
            )
            return NormalizedProduct(
                canonical_name=raw_name,
                name_confidence=0.0,
                category_path="Other > Uncategorized > General Products",
                top_level_category="Other",
                category_confidence=0.0,
            )

        return _merge(name_result, category_result, specs_result)
