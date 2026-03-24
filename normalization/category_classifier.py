"""
normalization/category_classifier.py — Layer 2: Product Category Classifier.

Uses the Claude API (via instructor) to classify Israeli retail products into a
unified, hierarchical taxonomy. The full taxonomy is injected into the system
prompt so Claude only picks from known categories (no hallucinated paths).

Supports Hebrew, English, and mixed-language product names.
"""

from __future__ import annotations

import logging

import instructor
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Claude model used for all classification tasks
_CLAUDE_MODEL = "claude-haiku-4-5-20251001"

# ---------------------------------------------------------------------------
# Full category taxonomy (at least 3 levels deep)
# ---------------------------------------------------------------------------

TAXONOMY: dict[str, dict[str, list[str]]] = {
    "Electronics": {
        "Audio": [
            "Headphones > Over-ear",
            "Headphones > In-ear",
            "Headphones > On-ear",
            "Speakers > Portable",
            "Speakers > Home",
            "Speakers > Soundbar",
            "Earbuds > True Wireless",
            "Microphones",
        ],
        "Phones & Tablets": [
            "Smartphones",
            "Tablets",
            "Smartwatches",
            "Phone Accessories > Cases",
            "Phone Accessories > Chargers",
            "Phone Accessories > Screen Protectors",
        ],
        "Computers": [
            "Laptops",
            "Desktop PCs",
            "Monitors",
            "Keyboards & Mice",
            "Storage > SSD",
            "Storage > HDD",
            "Storage > USB Drives",
            "Components > RAM",
            "Components > CPU",
            "Components > GPU",
        ],
        "TV & Video": [
            "Televisions > Smart TV",
            "Televisions > OLED",
            "Televisions > QLED",
            "Projectors",
            "Streaming Devices",
        ],
        "Cameras": [
            "DSLR Cameras",
            "Mirrorless Cameras",
            "Action Cameras",
            "Security Cameras",
            "Drones",
        ],
        "Gaming": [
            "Consoles",
            "Games > PlayStation",
            "Games > Xbox",
            "Games > Nintendo",
            "Gaming Accessories > Controllers",
            "Gaming Accessories > Headsets",
            "PC Gaming > Peripherals",
        ],
        "Home Appliances": [
            "Kitchen Appliances > Coffee Makers",
            "Kitchen Appliances > Blenders",
            "Kitchen Appliances > Microwaves",
            "Kitchen Appliances > Air Fryers",
            "Vacuum Cleaners > Robot",
            "Vacuum Cleaners > Upright",
            "Washing Machines",
            "Air Conditioners",
        ],
        "Power & Batteries": [
            "Power Banks",
            "Chargers > Wireless",
            "Chargers > Wired",
            "Batteries",
        ],
    },
    "Fashion": {
        "Men's Clothing": [
            "Tops > T-Shirts",
            "Tops > Shirts",
            "Tops > Hoodies",
            "Bottoms > Jeans",
            "Bottoms > Trousers",
            "Bottoms > Shorts",
            "Outerwear > Jackets",
            "Outerwear > Coats",
            "Suits & Formalwear",
        ],
        "Women's Clothing": [
            "Tops > Blouses",
            "Tops > T-Shirts",
            "Dresses > Casual",
            "Dresses > Evening",
            "Skirts",
            "Bottoms > Jeans",
            "Outerwear > Jackets",
            "Swimwear",
        ],
        "Footwear": [
            "Sneakers > Men",
            "Sneakers > Women",
            "Boots > Men",
            "Boots > Women",
            "Sandals",
            "Formal Shoes",
            "Sports Shoes",
        ],
        "Accessories": [
            "Bags > Handbags",
            "Bags > Backpacks",
            "Bags > Wallets",
            "Jewelry > Necklaces",
            "Jewelry > Rings",
            "Jewelry > Earrings",
            "Watches",
            "Sunglasses",
            "Belts",
            "Hats & Caps",
        ],
        "Kids' Clothing": [
            "Boys > Tops",
            "Boys > Bottoms",
            "Girls > Tops",
            "Girls > Dresses",
            "Baby Clothing",
        ],
    },
    "Home & Garden": {
        "Furniture": [
            "Living Room > Sofas",
            "Living Room > Coffee Tables",
            "Bedroom > Beds",
            "Bedroom > Wardrobes",
            "Dining > Tables",
            "Dining > Chairs",
            "Office > Desks",
            "Office > Chairs",
        ],
        "Home Décor": [
            "Lighting > Ceiling Lights",
            "Lighting > Table Lamps",
            "Rugs & Carpets",
            "Curtains & Blinds",
            "Wall Art",
            "Mirrors",
            "Candles & Aromatherapy",
        ],
        "Kitchen & Dining": [
            "Cookware > Pots",
            "Cookware > Pans",
            "Bakeware",
            "Tableware > Plates",
            "Tableware > Glasses",
            "Cutlery",
            "Storage & Organization",
        ],
        "Bedding & Bath": [
            "Bedding > Pillows",
            "Bedding > Duvets",
            "Bedding > Sheets",
            "Towels",
            "Bath Accessories",
        ],
        "Garden & Outdoor": [
            "Garden Tools",
            "Planters & Pots",
            "Outdoor Furniture",
            "BBQ & Grills",
            "Watering",
        ],
    },
    "Health & Beauty": {
        "Skincare": [
            "Moisturizers",
            "Serums",
            "Cleansers",
            "Sunscreen",
            "Anti-Aging",
            "Eye Cream",
        ],
        "Haircare": [
            "Shampoo",
            "Conditioner",
            "Hair Styling",
            "Hair Coloring",
            "Hair Tools > Straighteners",
            "Hair Tools > Dryers",
            "Hair Tools > Curlers",
        ],
        "Makeup": [
            "Foundation",
            "Lipstick",
            "Mascara",
            "Eyeshadow",
            "Blush & Bronzer",
            "Makeup Brushes",
        ],
        "Fragrances": [
            "Perfumes > Women",
            "Perfumes > Men",
            "Deodorants",
        ],
        "Personal Care": [
            "Oral Care > Toothbrushes",
            "Oral Care > Toothpaste",
            "Shaving > Razors",
            "Shaving > Cream",
            "Feminine Care",
        ],
        "Vitamins & Supplements": [
            "Vitamins",
            "Minerals",
            "Protein Supplements",
            "Herbal Supplements",
        ],
        "Medical Devices": [
            "Blood Pressure Monitors",
            "Thermometers",
            "Scales > Body",
            "Scales > Kitchen",
            "TENS Devices",
        ],
    },
    "Food & Beverage": {
        "Beverages": [
            "Coffee > Beans",
            "Coffee > Capsules",
            "Coffee > Instant",
            "Tea",
            "Juices",
            "Soft Drinks",
            "Water",
        ],
        "Snacks & Sweets": [
            "Chocolate",
            "Candy",
            "Chips & Crisps",
            "Nuts & Dried Fruits",
            "Cookies & Biscuits",
        ],
        "Pantry Staples": [
            "Oils & Vinegars",
            "Sauces & Condiments",
            "Pasta & Rice",
            "Canned Goods",
            "Spices & Seasonings",
        ],
        "Health Foods": [
            "Organic Products",
            "Gluten-Free",
            "Vegan Products",
            "Protein Bars",
        ],
        "Baby Food": [
            "Infant Formula",
            "Baby Snacks",
            "Baby Meals",
        ],
    },
    "Sports": {
        "Fitness Equipment": [
            "Cardio > Treadmills",
            "Cardio > Exercise Bikes",
            "Cardio > Ellipticals",
            "Strength > Dumbbells",
            "Strength > Barbells",
            "Strength > Resistance Bands",
            "Yoga & Pilates > Mats",
            "Yoga & Pilates > Blocks",
        ],
        "Outdoor Sports": [
            "Cycling > Bikes",
            "Cycling > Accessories",
            "Running > Shoes",
            "Running > Apparel",
            "Swimming > Swimwear",
            "Swimming > Goggles",
            "Hiking > Boots",
            "Hiking > Backpacks",
        ],
        "Ball Sports": [
            "Football",
            "Basketball",
            "Tennis",
            "Volleyball",
        ],
        "Water Sports": [
            "Surfing",
            "Diving",
            "Kayaking",
        ],
        "Sports Nutrition": [
            "Protein Powders",
            "Energy Drinks",
            "Recovery Supplements",
        ],
        "Team Sports": [
            "Football Gear",
            "Basketball Gear",
            "Baseball Gear",
        ],
    },
    "Toys & Games": {
        "Baby & Toddler": [
            "Baby Toys > 0-6 Months",
            "Baby Toys > 6-12 Months",
            "Baby Toys > 1-3 Years",
            "Baby Monitors",
            "Strollers",
            "Car Seats",
        ],
        "Educational Toys": [
            "STEM Kits",
            "Puzzles > Jigsaw",
            "Puzzles > 3D",
            "Board Games",
            "Building Sets > LEGO",
            "Building Sets > Magnetic",
        ],
        "Action & Adventure": [
            "Action Figures",
            "Toy Vehicles > Cars",
            "Toy Vehicles > Trains",
            "Dolls & Playsets",
            "Outdoor Play > Trampolines",
            "Outdoor Play > Playsets",
        ],
        "Video Games": [
            "PlayStation Games",
            "Xbox Games",
            "Nintendo Games",
            "PC Games",
        ],
        "Arts & Crafts": [
            "Drawing & Painting",
            "Modeling Clay",
            "Craft Kits",
        ],
    },
    "Books & Media": {
        "Books": [
            "Fiction > Novel",
            "Fiction > Fantasy",
            "Fiction > Thriller",
            "Non-Fiction > Biography",
            "Non-Fiction > Self-Help",
            "Non-Fiction > History",
            "Children's Books",
            "Textbooks & Academic",
            "Hebrew Books",
        ],
        "Music": [
            "CDs",
            "Vinyl Records",
            "Musical Instruments > Guitar",
            "Musical Instruments > Piano",
            "Musical Instruments > Drums",
            "Sheet Music",
        ],
        "Movies & TV": [
            "DVDs & Blu-ray",
            "Streaming Subscriptions",
        ],
        "Stationery": [
            "Pens & Pencils",
            "Notebooks",
            "Art Supplies",
        ],
    },
    "Other": {
        "Pet Supplies": [
            "Dog Food",
            "Cat Food",
            "Pet Toys",
            "Pet Care",
            "Aquarium & Fish",
        ],
        "Automotive": [
            "Car Accessories > GPS",
            "Car Accessories > Chargers",
            "Car Care",
            "Tires & Wheels",
        ],
        "Office Supplies": [
            "Printers & Ink",
            "Paper & Notebooks",
            "Office Furniture",
        ],
        "Travel": [
            "Luggage > Suitcases",
            "Luggage > Backpacks",
            "Travel Accessories",
        ],
        "Uncategorized": [
            "General Products",
        ],
    },
}


def _build_taxonomy_text(taxonomy: dict[str, dict[str, list[str]]]) -> str:
    """Serialize the TAXONOMY dict into a readable text block for the system prompt.

    Args:
        taxonomy: The full nested category taxonomy dict.

    Returns:
        A multi-line string listing every category path.
    """
    lines: list[str] = []
    for top_level, sub_dict in taxonomy.items():
        for sub_category, leaf_list in sub_dict.items():
            for leaf in leaf_list:
                lines.append(f"  {top_level} > {sub_category} > {leaf}")
    return "\n".join(lines)


_TAXONOMY_TEXT = _build_taxonomy_text(TAXONOMY)

_SYSTEM_PROMPT = f"""\
You are a product category classification expert for an Israeli retail catalog.

Your job is to classify products into the correct category from the taxonomy below.
Product names and descriptions may be in Hebrew, English, or a mix of both — this
is very common in Israeli retail.

IMPORTANT: You MUST only select a category_path that exists in the taxonomy below.
Do NOT invent or hallucinate new category paths.

TAXONOMY (format: Top Level > Sub Category > Leaf Category):
{_TAXONOMY_TEXT}

Instructions:
1. Choose the most specific matching category_path from the taxonomy.
2. Set top_level to the first segment of the path (e.g. "Electronics").
3. Set confidence (0.0–1.0) based on how clearly the product fits.
4. Provide a brief reasoning (1–2 sentences) explaining your choice (for debugging).

Always return valid JSON matching the schema.
"""


class ClassifiedCategory(BaseModel):
    """Structured classification result for a product.

    Attributes:
        category_path: Full hierarchical path, e.g. "Electronics > Audio > Headphones > Over-ear".
        top_level: First segment of the path, e.g. "Electronics".
        confidence: Confidence score between 0.0 and 1.0.
        reasoning: Brief explanation of the classification choice (for debugging).
    """

    category_path: str = Field(
        ..., description="Full path, e.g. 'Electronics > Audio > Headphones > Over-ear'"
    )
    top_level: str = Field(..., description="Top-level category, e.g. 'Electronics'")
    confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Confidence score (0.0–1.0)",
    )
    reasoning: str = Field(
        default="",
        description="Brief explanation of why this category was chosen",
    )


class CategoryClassifier:
    """Classifies products into a unified taxonomy using Claude via instructor.

    Injects the full TAXONOMY into the system prompt to prevent hallucinated
    category paths. Supports Hebrew, English, and mixed-language product data.

    Args:
        client: An async instructor client wrapping an Anthropic AsyncAnthropic instance.
    """

    def __init__(self, client: instructor.AsyncInstructor) -> None:
        """Initialize the classifier with an instructor async client.

        Args:
            client: instructor.AsyncInstructor wrapping anthropic.AsyncAnthropic.
        """
        self._client = client

    async def classify(
        self, product_name: str, description: str = ""
    ) -> ClassifiedCategory:
        """Classify a product into the taxonomy using Claude.

        Sends the product name and optional description to Claude and returns
        a structured ClassifiedCategory. If the call fails, returns a safe
        default pointing to "Other > Uncategorized > General Products".

        Args:
            product_name: The product name (Hebrew/English/mixed).
            description: Optional product description for richer context.

        Returns:
            A ClassifiedCategory with category_path, top_level, confidence,
            and reasoning populated.
        """
        user_content = f"Product name: {product_name}"
        if description:
            user_content += f"\nProduct description: {description}"

        try:
            result: ClassifiedCategory = await self._client.create(
                response_model=ClassifiedCategory,
                messages=[{"role": "user", "content": user_content}],
                model=_CLAUDE_MODEL,
                max_tokens=512,
                system=_SYSTEM_PROMPT,
            )
            return result
        except Exception as exc:
            logger.error(
                "CategoryClassifier.classify failed for product_name=%r: %s",
                product_name,
                exc,
            )
            return ClassifiedCategory(
                category_path="Other > Uncategorized > General Products",
                top_level="Other",
                confidence=0.0,
                reasoning="Classification failed — returned default.",
            )
