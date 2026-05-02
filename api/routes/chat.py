"""
api/routes/chat.py — POST /api/chat endpoint for BuyMe Smart Search conversational interface.

Flow:
    1. Parse intent from user message using Gemini (INTENT_PARSER_SYSTEM prompt).
    2. If needs_user_location and no GPS in session_context → return location prompt.
    3. Execute search based on intent:
       - product_search → reuse _embed, _vec_literal, SQL from search.py
       - store_search   → reuse store query builder from stores.py
       - help           → return HELP_RESPONSE directly
       - clarify        → ask Gemini for a clarifying question
    4. Compose Hebrew response using Gemini (RESPONSE_COMPOSER_SYSTEM prompt).
    5. Return ChatResponse.
"""

from __future__ import annotations

import json
import re
import logging
import math
import time
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends
from openai import AsyncOpenAI
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from starlette.requests import Request

from api.dependencies import limiter

from api.auth import get_optional_user
from api.cache import get_intent_cache, set_intent_cache
from api.chat_utils import apply_inferred_attributes, build_user_context_block, merge_preferences_into_search
from api.dependencies import get_ai_client, get_db, get_redis, get_settings
from api.inference import extract_and_update_attributes
from api.prompts import HELP_RESPONSE, INTENT_PARSER_SYSTEM, RESPONSE_COMPOSER_SYSTEM
from api.routes.search import _embed, _vec_literal, _distance_km
from api.routes.stores import _haversine_km
from api.schemas import (
    ChatRequest,
    ChatResponse,
    ChatMessage,
    LocationFilter,
    ParsedIntent,
    ProductResult,
    SessionContext,
    StoreInfo,
    StoreResult,
    StoreSearchRequest,
)
from db.models import Store, StoreProduct

logger = logging.getLogger(__name__)

router = APIRouter()

_GEMINI_MODEL = "gemini-2.5-flash"
_CHAT_PAGE_SIZE = 10  # smaller page size for chat mode
_MAX_CANDIDATES = 200


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _parse_intent(
    message: str,
    history: list[ChatMessage],
    session_context: Optional[SessionContext],
    client: AsyncOpenAI,
    redis: Optional[Redis] = None,
    user_context: str = "",
) -> ParsedIntent:
    """
    Call Gemini with INTENT_PARSER_SYSTEM to extract structured intent from the
    user's message and conversation history.

    Returns a ParsedIntent; falls back to intent='clarify' on any parse failure.
    Intent results are cached in Redis for 2 minutes to avoid repeat LLM calls.
    Optional user_context (for logged-in users) is appended to the system prompt.
    """
    # Check intent cache (message only — history may vary, but message is the primary key)
    if redis is not None:
        cached = await get_intent_cache(redis, message)
        if cached is not None:
            return ParsedIntent(**cached)

    # Build a history string so Gemini has context
    history_lines: list[str] = []
    for turn in history[-6:]:  # last 6 turns is enough context
        role_label = "משתמש" if turn.role == "user" else "עוזר"
        history_lines.append(f"{role_label}: {turn.content}")

    history_str = "\n".join(history_lines)
    user_content = (
        f"{history_str}\nמשתמש: {message}" if history_str else f"משתמש: {message}"
    )

    # Enrich system prompt with user context for logged-in users
    if user_context:
        system_prompt = INTENT_PARSER_SYSTEM + "\n\n" + user_context
    else:
        system_prompt = INTENT_PARSER_SYSTEM

    try:
        response = await client.chat.completions.create(
            model=_GEMINI_MODEL,
            max_tokens=512,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
        )
        raw = response.choices[0].message.content.strip()

        # Extract JSON object robustly — handles ```json fences and extra prose
        json_match = re.search(r'\{.*?\}', raw, re.DOTALL)
        if not json_match:
            raise ValueError(f"No JSON object found in: {raw[:100]}")
        data = json.loads(json_match.group())

        intent = data.get("intent", "clarify")
        valid_intents = {"product_search", "store_search", "help", "clarify"}
        if intent not in valid_intents:
            intent = "clarify"

        parsed_intent = ParsedIntent(
            intent=intent,
            product_query=data.get("product_query"),
            brand=data.get("brand"),
            max_price=data.get("max_price"),
            city=data.get("city"),
            location_hint=data.get("location_hint"),
            needs_user_location=bool(data.get("needs_user_location", False)),
            store_type=data.get("store_type"),
            voucher_network=data.get("voucher_network", "buyme"),
        )

        # Store parsed intent in cache before returning
        if redis is not None:
            await set_intent_cache(redis, message, parsed_intent.model_dump())

        return parsed_intent

    except Exception as exc:
        logger.warning("Intent parse failed: %s", exc)
        return ParsedIntent(intent="clarify", voucher_network="buyme")


async def _compose_response(
    intent: str,
    results_summary: str,
    parsed: ParsedIntent,
    client: AsyncOpenAI,
) -> str:
    """
    Call Gemini with RESPONSE_COMPOSER_SYSTEM to generate a short Hebrew answer
    referencing the top results.
    """
    user_prompt = (
        f"כוונת המשתמש: {intent}\n"
        f"חיפוש: {parsed.product_query or parsed.store_type or '(לא ידוע)'}\n"
        f"תוצאות:\n{results_summary}"
    )
    try:
        response = await client.chat.completions.create(
            model=_GEMINI_MODEL,
            max_tokens=200,
            messages=[
                {"role": "system", "content": RESPONSE_COMPOSER_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
        )
        return response.choices[0].message.content.strip()
    except Exception as exc:
        logger.warning("Response composer failed: %s", exc)
        return "מצאתי כמה תוצאות רלוונטיות עבורך."


def _build_results_summary(
    product_results: Optional[list[ProductResult]],
    store_results: Optional[list[StoreResult]],
) -> str:
    """Build a short text summary of top 3 results for the response composer."""
    lines: list[str] = []

    if product_results:
        for r in product_results[:3]:
            price_str = f"₪{r.price:.0f}" if r.price else "מחיר לא זמין"
            lines.append(f"- {r.canonical_name} | {r.store.name_he} | {price_str}")

    if store_results:
        for s in store_results[:3]:
            dist_str = (
                f" ({s.distance_km:.1f} ק\"מ)" if s.distance_km is not None else ""
            )
            lines.append(f"- {s.name_he}{dist_str} | {s.product_count} מוצרים")

    if not lines:
        return "לא נמצאו תוצאות."

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Product search (reuses search.py helpers)
# ---------------------------------------------------------------------------

_ILIKE_SQL = text("""
    SELECT DISTINCT ON (sp.product_id, sp.store_id)
        sp.id            AS sp_id,
        sp.price,
        sp.currency,
        sp.availability,
        sp.product_url,
        p.id             AS product_id,
        p.canonical_name,
        p.brand          AS product_brand,
        p.category_path,
        s.id             AS store_id,
        s.name_he,
        s.name_en,
        s.buyme_url,
        s.is_online,
        s.city,
        s.lat,
        s.lng
    FROM store_products sp
    JOIN products p ON sp.product_id = p.id
    JOIN stores s ON sp.store_id = s.id
    WHERE p.canonical_name ILIKE :term
       OR p.brand ILIKE :term
       OR p.canonical_name ILIKE :word1
       OR p.canonical_name ILIKE :word2
    ORDER BY sp.product_id, sp.store_id
    LIMIT :limit
""")


def _word_overlap_similarity(search_words: set[str], row: Any) -> float:
    name_words = set((row["canonical_name"] or "").lower().split())
    brand_words = set((row["product_brand"] or "").lower().split())
    overlap = len(search_words & (name_words | brand_words))
    return min(0.9, 0.4 + (overlap / max(len(search_words), 1)) * 0.5)


async def _run_product_search(
    search_text: str,
    parsed: ParsedIntent,
    location: Optional[LocationFilter],
    db: AsyncSession,
    api_key: str,
) -> list[ProductResult]:
    """
    Execute a hybrid ILIKE + pgvector product search, applying chat-mode filters.
    Returns up to _CHAT_PAGE_SIZE results.
    """
    # Embed the search text
    embedding = await _embed(search_text, api_key)

    # ILIKE search
    query_words_list = [w for w in search_text.split() if len(w) > 1]
    word1 = f"%{query_words_list[0]}%" if query_words_list else f"%{search_text}%"
    word2 = f"%{query_words_list[1]}%" if len(query_words_list) > 1 else word1
    query_words_set = set(search_text.lower().split())

    ilike_result = await db.execute(
        _ILIKE_SQL,
        {
            "term": f"%{search_text}%",
            "word1": word1,
            "word2": word2,
            "limit": _MAX_CANDIDATES * 2,
        },
    )
    ilike_raw = ilike_result.mappings().all()
    ilike_seen: set[str] = set()
    ilike_rows: list[dict] = []
    for r in ilike_raw:
        key = f"{r['product_id']}:{r['store_id']}"
        if key in ilike_seen:
            continue
        ilike_seen.add(key)
        sim = _word_overlap_similarity(query_words_set, r)
        ilike_rows.append({**r, "similarity": sim})
    ilike_rows.sort(key=lambda x: x["similarity"], reverse=True)

    # Vector search
    vector_rows: list = []
    if embedding:
        vec_str = _vec_literal(embedding)
        vec_sql = text("""
            SELECT * FROM (
                SELECT DISTINCT ON (sp.product_id, sp.store_id)
                    sp.id            AS sp_id,
                    sp.price,
                    sp.currency,
                    sp.availability,
                    sp.product_url,
                    p.id             AS product_id,
                    p.canonical_name,
                    p.brand          AS product_brand,
                    p.category_path,
                    s.id             AS store_id,
                    s.name_he,
                    s.name_en,
                    s.buyme_url,
                    s.is_online,
                    s.city,
                    s.lat,
                    s.lng,
                    1 - (p.embedding_vector <=> CAST(:vec AS vector)) AS similarity
                FROM store_products sp
                JOIN products p ON sp.product_id = p.id
                JOIN stores s ON sp.store_id = s.id
                WHERE p.embedding_vector IS NOT NULL
                ORDER BY sp.product_id, sp.store_id, p.embedding_vector <=> CAST(:vec AS vector)
            ) deduped
            ORDER BY similarity DESC
            LIMIT :limit
        """)
        vec_result = await db.execute(
            vec_sql, {"vec": vec_str, "limit": _MAX_CANDIDATES * 2}
        )
        vector_rows = list(vec_result.mappings().all())

    # Merge results (mirrors search.py merge logic)
    seen_merged: set[str] = set()
    merged: list[dict] = []

    for r in ilike_rows:
        if float(r["similarity"]) > 0.4:
            key = f"{r['product_id']}:{r['store_id']}"
            seen_merged.add(key)
            merged.append(r)

    for r in vector_rows:
        key = f"{r['product_id']}:{r['store_id']}"
        if key not in seen_merged and float(r["similarity"]) > 0.5:
            seen_merged.add(key)
            merged.append(dict(r))

    for r in ilike_rows:
        key = f"{r['product_id']}:{r['store_id']}"
        if key not in seen_merged:
            seen_merged.add(key)
            merged.append(r)

    for r in vector_rows:
        key = f"{r['product_id']}:{r['store_id']}"
        if key not in seen_merged:
            seen_merged.add(key)
            merged.append(dict(r))

    merged.sort(key=lambda x: float(x["similarity"]), reverse=True)

    # Apply filters and collect results
    results: list[ProductResult] = []
    for row in merged:
        if len(results) >= _CHAT_PAGE_SIZE:
            break

        # city filter (from parsed intent)
        if parsed.city:
            city_val = row["city"] or ""
            if parsed.city.lower() not in city_val.lower():
                continue

        # brand filter skipped in chat mode — brand is already in search_text for semantic matching

        # max_price filter
        if parsed.max_price is not None and row["price"] is not None:
            if row["price"] > parsed.max_price:
                continue

        # location radius filter
        distance_km: Optional[float] = None
        if location is not None and row["lat"] is not None:
            distance_km = round(
                _distance_km(location.lat, location.lng, row["lat"], row["lng"]), 2
            )
            if distance_km > location.radius_km:
                continue

        similarity = float(row["similarity"])

        store_info = StoreInfo(
            id=str(row["store_id"]),
            name_he=row["name_he"],
            name_en=row["name_en"],
            buyme_url=row["buyme_url"],
            is_online=row["is_online"],
            city=row["city"],
            lat=row["lat"],
            lng=row["lng"],
            distance_km=distance_km,
        )
        results.append(
            ProductResult(
                product_id=str(row["product_id"]),
                canonical_name=row["canonical_name"],
                brand=row["product_brand"],
                category_path=row["category_path"],
                store=store_info,
                price=row["price"],
                currency=row["currency"],
                availability=row["availability"],
                product_url=row["product_url"],
                match_score=round(similarity, 3),
            )
        )

    return results


# ---------------------------------------------------------------------------
# Store search (reuses stores.py query logic)
# ---------------------------------------------------------------------------


async def _run_store_search(
    parsed: ParsedIntent,
    location: Optional[LocationFilter],
    db: AsyncSession,
) -> list[StoreResult]:
    """
    Execute a store search using the same query builder as stores.py.
    Returns up to _CHAT_PAGE_SIZE results.
    """
    product_count_subq = (
        select(
            StoreProduct.store_id,
            func.count(StoreProduct.id).label("product_count"),
        )
        .group_by(StoreProduct.store_id)
        .subquery("product_counts")
    )

    base_stmt = select(
        Store,
        func.coalesce(product_count_subq.c.product_count, 0).label("product_count"),
    ).outerjoin(product_count_subq, Store.id == product_count_subq.c.store_id)

    # store_type filter
    if parsed.store_type is not None:
        base_stmt = base_stmt.where(Store.buyme_category.ilike(parsed.store_type))

    # city filter
    if parsed.city:
        base_stmt = base_stmt.where(Store.city.ilike(f"%{parsed.city}%"))
    elif parsed.location_hint:
        base_stmt = base_stmt.where(
            Store.name_he.ilike(f"%{parsed.location_hint}%")
            | Store.name_en.ilike(f"%{parsed.location_hint}%")
            | Store.city.ilike(f"%{parsed.location_hint}%")
        )

    # location filter — only include stores with coords
    if location is not None:
        base_stmt = base_stmt.where(
            Store.lat.is_not(None),
            Store.lng.is_not(None),
        )

    rows_result = await db.execute(base_stmt)
    all_rows: list[tuple[Store, int]] = list(rows_result.all())

    # Geo filter + distance annotation (mirrors stores.py logic)
    annotated: list[tuple[Store, int, Optional[float]]] = []

    if location is not None:
        for store, product_count in all_rows:
            if store.lat is None or store.lng is None:
                continue
            dist = _haversine_km(location.lat, location.lng, store.lat, store.lng)
            if dist <= location.radius_km:
                annotated.append((store, product_count, round(dist, 2)))
    else:
        for store, product_count in all_rows:
            annotated.append((store, product_count, None))

    # Sort: distance ASC when location provided, else product_count DESC
    if location is not None:
        annotated.sort(key=lambda t: t[2] if t[2] is not None else float("inf"))
    else:
        annotated.sort(key=lambda t: t[1], reverse=True)

    # Return up to _CHAT_PAGE_SIZE results
    page_rows = annotated[:_CHAT_PAGE_SIZE]

    return [
        StoreResult(
            id=str(store.id),
            name_he=store.name_he,
            name_en=store.name_en,
            buyme_url=store.buyme_url,
            buyme_category=store.buyme_category,
            address=store.address,
            city=store.city,
            lat=store.lat,
            lng=store.lng,
            distance_km=distance_km,
            is_online=store.is_online,
            product_count=product_count,
        )
        for store, product_count, distance_km in page_rows
    ]


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: Request,
    body: ChatRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    ai: Annotated[AsyncOpenAI, Depends(get_ai_client)],
    redis: Annotated[Redis, Depends(get_redis)],
    current_user=Depends(get_optional_user),
) -> ChatResponse:
    """
    Conversational search endpoint.

    Accepts a free-text message in Hebrew or English, conversation history,
    and optional session context (GPS, voucher network). Parses intent, runs
    the appropriate search, and returns a Hebrew natural-language response
    together with structured product or store results.

    Works for both anonymous users (no JWT) and logged-in users (with JWT).
    Logged-in users get personalized results based on preferences and history.
    """
    start_time = time.time()

    session_context: Optional[SessionContext] = body.session_context
    voucher_network = (
        session_context.voucher_network
        if session_context and session_context.voucher_network
        else body.voucher_network
    )

    # ------------------------------------------------------------------
    # Step 1a — Load personalization context for logged-in users
    # ------------------------------------------------------------------
    user_context = ""
    prefs: dict = {}
    implicit: list = []

    if current_user:
        try:
            from sqlalchemy import select as sa_select
            from db.models import UserPreference, UserImplicitSignal, UserSearchHistory

            prefs_rows = await db.execute(
                sa_select(UserPreference).where(UserPreference.user_id == current_user.id)
            )
            prefs = {p.key: p.value for p in prefs_rows.scalars().all()}

            signals_rows = await db.execute(
                sa_select(UserImplicitSignal)
                .where(UserImplicitSignal.user_id == current_user.id)
                .order_by(UserImplicitSignal.last_seen.desc())
                .limit(10)
            )
            implicit = [
                {"signal_type": s.signal_type, "signal_value": s.signal_value}
                for s in signals_rows.scalars().all()
            ]

            history_rows = await db.execute(
                sa_select(UserSearchHistory)
                .where(UserSearchHistory.user_id == current_user.id)
                .order_by(UserSearchHistory.searched_at.desc())
                .limit(3)
            )
            user_history = [
                {"message": h.message, "searched_at": str(h.searched_at)}
                for h in history_rows.scalars().all()
            ]

            user_context = build_user_context_block(prefs, implicit, user_history)
        except Exception:
            pass  # Never block the request

    # ------------------------------------------------------------------
    # Step 1 — Parse intent
    # ------------------------------------------------------------------
    parsed = await _parse_intent(
        message=body.message,
        history=body.history,
        session_context=session_context,
        client=ai,
        redis=redis,
        user_context=user_context,
    )

    # ------------------------------------------------------------------
    # Step 1b — Merge preferences and inferred attributes
    # ------------------------------------------------------------------
    if current_user and prefs:
        try:
            parsed = merge_preferences_into_search(parsed, prefs, implicit)

            from sqlalchemy import select as sa_select
            from db.models import UserInferredAttribute

            inferred_rows = await db.execute(
                sa_select(UserInferredAttribute).where(
                    UserInferredAttribute.user_id == current_user.id
                )
            )
            inferred = [
                {"attribute": a.attribute, "value": a.value, "confidence": a.confidence}
                for a in inferred_rows.scalars().all()
            ]
            parsed = apply_inferred_attributes(parsed, inferred)
        except Exception:
            pass  # Never block the request

    # ------------------------------------------------------------------
    # Step 2 — Handle needs_location
    # ------------------------------------------------------------------
    has_location = (
        session_context is not None
        and session_context.user_lat is not None
        and session_context.user_lng is not None
    )

    if parsed.needs_user_location and not has_location:
        return ChatResponse(
            message="כדי למצוא לך את הקרוב ביותר, אני צריך לדעת איפה אתה נמצא.",
            intent="clarify",
            product_results=None,
            store_results=None,
            needs_location=True,
            location_prompt="באיזה אזור אתה נמצא? אפשר לשתף מיקום GPS או לכתוב עיר.",
            voucher_network=voucher_network,
            search_time_ms=round((time.time() - start_time) * 1000, 2),
        )

    # Build LocationFilter from session context if available
    location: Optional[LocationFilter] = None
    if has_location and session_context is not None:
        location = LocationFilter(
            lat=session_context.user_lat,  # type: ignore[arg-type]
            lng=session_context.user_lng,  # type: ignore[arg-type]
            radius_km=10.0,
        )

    settings = get_settings()
    api_key = settings.gemini_api_key

    product_results: Optional[list[ProductResult]] = None
    store_results: Optional[list[StoreResult]] = None
    message: str = ""

    # ------------------------------------------------------------------
    # Step 3 — Execute search based on intent
    # ------------------------------------------------------------------

    if parsed.intent == "product_search":
        parts = [p for p in [parsed.product_query, parsed.brand] if p]
        search_text = " ".join(parts) if parts else body.message
        product_results = await _run_product_search(
            search_text=search_text,
            parsed=parsed,
            location=location,
            db=db,
            api_key=api_key,
        )
        # City-filter fallback: if city filter yielded 0 results, retry without city
        if not product_results and parsed.city:
            logger.info("City filter '%s' yielded 0 results — retrying without city filter", parsed.city)
            fallback_parsed = parsed.model_copy(update={"city": None})
            product_results = await _run_product_search(
                search_text=search_text,
                parsed=fallback_parsed,
                location=location,
                db=db,
                api_key=api_key,
            )

        # Step 4 — Compose response
        summary = _build_results_summary(product_results, None)
        message = await _compose_response(parsed.intent, summary, parsed, ai)

    elif parsed.intent == "store_search":
        store_results = await _run_store_search(
            parsed=parsed,
            location=location,
            db=db,
        )

        # Step 4 — Compose response
        summary = _build_results_summary(None, store_results)
        message = await _compose_response(parsed.intent, summary, parsed, ai)

    elif parsed.intent == "help":
        # No DB query, no LLM call — return the static help response directly
        message = HELP_RESPONSE

    else:
        # intent == "clarify" — ask Gemini for a clarifying question
        try:
            clarify_response = await ai.chat.completions.create(
                model=_GEMINI_MODEL,
                max_tokens=200,
                messages=[
                    {"role": "system", "content": RESPONSE_COMPOSER_SYSTEM},
                    {
                        "role": "user",
                        "content": (
                            f"המשתמש אמר: {body.message}\n"
                            "אין לי מספיק מידע כדי לחפש. שאל שאלת הבהרה קצרה בעברית."
                        ),
                    },
                ],
            )
            message = clarify_response.choices[0].message.content.strip()
        except Exception as exc:
            logger.warning("Clarify LLM call failed: %s", exc)
            message = "לא הבנתי את הבקשה. האם תוכל לפרט יותר מה אתה מחפש?"

    # ------------------------------------------------------------------
    # Step 4b — Save history + fire inference (logged-in users only)
    # ------------------------------------------------------------------
    if current_user:
        try:
            import asyncio
            from sqlalchemy import text as sa_text
            from db.models import UserSearchHistory

            results_list = product_results or store_results or []
            top_result_name: Optional[str] = None
            if product_results:
                top_result_name = product_results[0].canonical_name if product_results else None
            elif store_results:
                top_result_name = store_results[0].name_he if store_results else None

            history_entry = UserSearchHistory(
                user_id=current_user.id,
                message=body.message,
                intent=parsed.intent,
                resolved_query=parsed.product_query or parsed.city,
                city_used=parsed.city,
                result_count=len(results_list),
                top_result_name=top_result_name,
                voucher_network=voucher_network,
            )
            db.add(history_entry)

            # Update city implicit signal
            if parsed.city:
                await db.execute(
                    sa_text("""
                        INSERT INTO user_implicit_signals
                            (id, user_id, signal_type, signal_value, weight, last_seen, count)
                        VALUES (gen_random_uuid(), :uid, 'city_search', :val, 1.0, now(), 1)
                        ON CONFLICT (user_id, signal_type, signal_value)
                        DO UPDATE SET
                            weight   = user_implicit_signals.weight + 0.1,
                            count    = user_implicit_signals.count + 1,
                            last_seen = now()
                    """),
                    {"uid": str(current_user.id), "val": parsed.city},
                )

            await db.commit()

            # Fire-and-forget inference extraction (never blocks response)
            asyncio.create_task(
                extract_and_update_attributes(current_user.id, body.message, db, ai)
            )
        except Exception:
            pass  # Never block the response

    # ------------------------------------------------------------------
    # Step 5 — Return ChatResponse
    # ------------------------------------------------------------------
    return ChatResponse(
        message=message,
        intent=parsed.intent,
        product_results=product_results if product_results else None,
        store_results=store_results if store_results else None,
        needs_location=False,
        location_prompt=None,
        voucher_network=voucher_network,
        search_time_ms=round((time.time() - start_time) * 1000, 2),
    )
