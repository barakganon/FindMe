"""
normalization/spec_extractor.py — Layer 2: Product Spec Extractor.

Uses the Claude API (via instructor) to extract structured product specifications
from raw product text (names and descriptions). Handles mixed Hebrew/English input
as commonly found in Israeli retail catalogs.

Extracted specs feed into the deduplication engine and the products.specs_json column.
"""

from __future__ import annotations

import logging
from typing import Optional

import instructor
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Gemini model used for all spec extraction tasks
_GEMINI_MODEL = "gemini-2.0-flash"

_SYSTEM_PROMPT = """\
You are a product specification extraction expert for an Israeli retail catalog.

Your job is to read raw product text and extract structured specifications from it.
Product names and descriptions may be in Hebrew, English, or a mix of both — this
is very common in Israeli retail. Extract specs even when they are embedded in Hebrew
text (e.g. 'צבע: שחור' means 'color: black', 'גודל: XL' means 'size: XL').

Common Hebrew spec keywords to look for:
  - מותג / מותגים = brand
  - דגם = model
  - צבע = color
  - גודל / מידה = size
  - משקל = weight
  - אחסון / נפח = storage
  - חומר = material
  - זיכרון = memory/RAM
  - מסך = screen
  - סוללה = battery

Instructions:
1. Extract any brand name you find (manufacturer, not retailer).
2. Extract the model identifier/code (alphanumeric, e.g. "WH-1000XM5", "Galaxy S24").
3. Extract color if mentioned (in either language).
4. Extract size (clothing size like S/M/L/XL, or screen size like "65 inch", etc.).
5. Extract weight with units if mentioned.
6. Extract storage in GB as an integer if it's an electronic device (e.g. 256 from "256GB").
7. Extract material if it's fashion or furniture (e.g. "cotton", "כותנה", "leather").
8. Put any other specs that don't fit the above fields into additional_specs as key-value pairs.
   Keys should be in English even if the source was Hebrew (translate the key).
9. Use null for fields you cannot determine from the text.

Always return valid JSON matching the schema.
"""


class ExtractedSpecs(BaseModel):
    """Structured product specifications extracted from raw text.

    Attributes:
        brand: Brand / manufacturer name. None if not found.
        model: Model identifier code. None if not found.
        color: Color of the product (any language). None if not found.
        size: Size descriptor (clothing size, screen size, etc.). None if not found.
        weight: Weight with units (e.g. "1.5 kg"). None if not found.
        storage_gb: Storage capacity in GB as an integer (for electronics). None if not applicable.
        material: Material (for fashion, furniture, etc.). None if not applicable.
        additional_specs: Catch-all dict for any other specs not covered above.
    """

    brand: Optional[str] = Field(default=None, description="Brand / manufacturer name")
    model: Optional[str] = Field(default=None, description="Model identifier code")
    color: Optional[str] = Field(default=None, description="Product color")
    size: Optional[str] = Field(
        default=None,
        description="Size: clothing (S/M/L/XL), screen (65 inch), etc.",
    )
    weight: Optional[str] = Field(
        default=None, description="Weight with units, e.g. '1.5 kg'"
    )
    storage_gb: Optional[int] = Field(
        default=None, description="Storage capacity in GB (electronics only)"
    )
    material: Optional[str] = Field(
        default=None, description="Material, e.g. 'cotton', 'leather' (fashion/furniture)"
    )
    additional_specs: dict[str, str] = Field(
        default_factory=dict,
        description="Catch-all for any other specs not covered by dedicated fields",
    )


class SpecExtractor:
    """Extracts product specifications from raw text using Claude via instructor.

    Handles mixed Hebrew/English input. The system prompt teaches Claude the
    common Hebrew spec keywords found in Israeli retail product descriptions.

    Args:
        client: An async instructor client wrapping an Anthropic AsyncAnthropic instance.
    """

    def __init__(self, client: instructor.AsyncInstructor) -> None:
        """Initialize the extractor with an instructor async client.

        Args:
            client: instructor.AsyncInstructor wrapping an AsyncOpenAI Gemini client.
        """
        self._client = client

    async def extract(self, raw_text: str) -> ExtractedSpecs:
        """Extract structured specs from raw product text.

        Calls Claude with a structured system prompt and uses instructor to
        extract an ExtractedSpecs object. If the call fails, logs the error
        and returns an empty ExtractedSpecs with all fields set to None/empty.

        Args:
            raw_text: Raw product text (name + description) in Hebrew/English/mixed.

        Returns:
            An ExtractedSpecs with all identifiable specs populated; unknown
            fields will be None.
        """
        try:
            result: ExtractedSpecs = await self._client.create(
                response_model=ExtractedSpecs,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": f"Extract specifications from this product text:\n\n{raw_text}",
                    },
                ],
                model=_GEMINI_MODEL,
                max_tokens=1024,
            )
            return result
        except Exception as exc:
            logger.error(
                "SpecExtractor.extract failed for raw_text=%r: %s", raw_text[:80], exc
            )
            return ExtractedSpecs()
