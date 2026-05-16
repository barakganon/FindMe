"""api/agent/tools/clarify.py — Explicit clarification tool for the v2 agent (W3).

The agent calls this tool when it needs the user to answer a specific question
BEFORE it can perform a useful search. The tool itself does nothing — it just
captures the question into the trace so:
  - `_infer_intent` can map `clarify`-called → `intent="clarify"`
  - The eval rubric scores the call correctly
  - The user sees a focused single question rather than a wall of options

This separates "I need info" from "I searched and found nothing." Without it,
the LLM tends to either guess (wrong results) or generate generic clarifying
prose that's hard to evaluate.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ClarifyParams(BaseModel):
    """The Hebrew question the agent wants to ask."""

    question: str = Field(
        ...,
        description=(
            "The exact Hebrew question the agent should put to the user. "
            "Keep it to ONE question. Examples: 'מהיכן אתה?', 'מה התקציב שלך?', "
            "'אילו עוצמת בס מעניינת אותך?'."
        ),
        min_length=1,
        max_length=300,
    )


_PARAMS_SCHEMA = ClarifyParams.model_json_schema()


_TOOL_DESCRIPTION = (
    "Ask the user ONE specific question. Use this when you cannot produce a "
    "useful answer without more information from the user.\n\n"
    "When to call clarify:\n"
    "  - User said 'near me' / 'לידי' / 'באזור שלי' / 'קרוב אלי' and no GPS is "
    "available → clarify('מהיכן אתה? תוכל לציין עיר?')\n"
    "  - User asked for a recommendation with no constraints at all (no category, "
    "no brand, no budget) → clarify('מתנה לעצמך או למישהו? במה אתה מתעניין?')\n"
    "  - User's request is contradictory or impossible to parse → clarify with a "
    "specific narrowing question.\n\n"
    "When NOT to call clarify:\n"
    "  - The user gave one constraint (a brand, a budget, a category) — search "
    "first, narrow later if results are too broad.\n"
    "  - A single-brand query like 'סמסונג' or 'Apple' — call search_products "
    "with brand=<name>; do not ask 'what kind of Samsung?'.\n\n"
    "After this tool returns, write a short Hebrew reply containing the question, "
    "then stop. Do not call other tools in the same turn."
)


CLARIFY_SPEC: dict = {
    "type": "function",
    "function": {
        "name": "clarify",
        "description": _TOOL_DESCRIPTION,
        "parameters": _PARAMS_SCHEMA,
    },
}


async def execute_clarify(
    params: ClarifyParams,
    **_unused: object,
) -> tuple[list, str]:
    """
    Capture the clarifying question. The loop's downstream `_infer_intent`
    sees `clarify` was called → maps response intent to "clarify".

    Returns no items — just echoes the question back as the summary so the
    agent's final reply includes it verbatim.
    """
    return [], params.question
