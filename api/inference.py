"""
api/inference.py — Passive LLM attribute inference from user messages.

All failures are silently swallowed — never affects user response.
Call via asyncio.create_task() so it never blocks the main chat response.
"""
from __future__ import annotations

import json
import re
from uuid import UUID

from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

ATTRIBUTE_EXTRACTOR_SYSTEM = """
אתה מנתח שיחה ומחלץ מידע דמוגרפי ועדפות מהודעות המשתמש.
החזר JSON בלבד. אם אין מספיק מידע לשדה מסוים, החזר null.
אל תנחש — רק מה שמפורש או מרומז בבירור בהודעה.

פורמט הפלט:
{
  "age_range": "25-35" | "35-50" | "50+" | null,
  "has_children": true | false | null,
  "child_age_range": "0-3" | "3-10" | "10-18" | null,
  "gender": "female" | "male" | null,
  "lifestyle": ["sporty","fashionable","tech-enthusiast","homebody"],
  "price_sensitivity": "budget" | "mid-range" | "premium" | null,
  "occasions": ["birthday","holiday","work","wedding"],
  "interests": ["wine","art","cooking","gaming","fitness"],
  "confidence_notes": "<brief explanation>"
}

דוגמאות:
- "קניתי מתנה לבן 3 שלי" → has_children=true, child_age_range="0-3"
- "אני מחפשת שמלה לחתונה" → gender=female, occasions=["wedding"]
- "GPU חדש לגיימינג" → lifestyle=["tech-enthusiast"], interests=["gaming"]
- "יין טוב לא יקר מדי" → interests=["wine"], price_sensitivity="mid-range"
"""

_GEMINI_MODEL = "gemini-2.5-flash"


async def extract_and_update_attributes(
    user_id: UUID,
    message: str,
    db: AsyncSession,
    ai: AsyncOpenAI,
) -> None:
    """
    Run after every chat turn for logged-in users.
    Fire-and-forget via asyncio.create_task() — never blocks response.
    All errors silently swallowed.
    """
    try:
        response = await ai.chat.completions.create(
            model=_GEMINI_MODEL,
            max_tokens=300,
            messages=[
                {"role": "system", "content": ATTRIBUTE_EXTRACTOR_SYSTEM},
                {"role": "user", "content": message},
            ],
        )
        raw = response.choices[0].message.content.strip()

        # Robustly extract JSON object — handles ```json fences and extra prose
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if not match:
            return
        data = json.loads(match.group(0))

        scalar_attrs = {
            "age_range": data.get("age_range"),
            "has_children": (
                str(data.get("has_children"))
                if data.get("has_children") is not None
                else None
            ),
            "child_age_range": data.get("child_age_range"),
            "gender": data.get("gender"),
            "price_sensitivity": data.get("price_sensitivity"),
        }
        list_attrs = {
            "lifestyle": data.get("lifestyle", []),
            "occasions": data.get("occasions", []),
            "interests": data.get("interests", []),
        }

        from sqlalchemy import text

        for attr, value in scalar_attrs.items():
            if value:
                await db.execute(
                    text("""
                        INSERT INTO user_inferred_attributes
                            (id, user_id, attribute, value, confidence, source)
                        VALUES (gen_random_uuid(), :user_id, :attr, :value, 0.7, :source)
                        ON CONFLICT (user_id, attribute) DO UPDATE SET
                            value      = EXCLUDED.value,
                            confidence = EXCLUDED.confidence,
                            source     = EXCLUDED.source,
                            last_updated = now()
                    """),
                    {
                        "user_id": str(user_id),
                        "attr": attr,
                        "value": str(value),
                        "source": message[:200],
                    },
                )

        for attr, values in list_attrs.items():
            if values:
                await db.execute(
                    text("""
                        INSERT INTO user_inferred_attributes
                            (id, user_id, attribute, value, confidence, source)
                        VALUES (gen_random_uuid(), :user_id, :attr, :value, 0.65, :source)
                        ON CONFLICT (user_id, attribute) DO UPDATE SET
                            value      = EXCLUDED.value,
                            confidence = EXCLUDED.confidence,
                            source     = EXCLUDED.source,
                            last_updated = now()
                    """),
                    {
                        "user_id": str(user_id),
                        "attr": attr,
                        "value": json.dumps(values, ensure_ascii=False),
                        "source": message[:200],
                    },
                )

        await db.commit()

    except Exception:
        pass  # Inference failure NEVER affects user experience
