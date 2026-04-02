"""
tests/api/test_chat.py — Tests for POST /api/chat endpoint.

All Gemini/LLM calls are mocked. The DB dependency is overridden with an
AsyncMock so no live database is required.

Uses the same anyio-based async pattern as other tests in this suite.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, MagicMock, patch

from api.main import app
from api.dependencies import get_db, get_ai_client
from api.schemas import ParsedIntent, ProductResult, StoreInfo, StoreResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FIXED_COMPOSE_RESPONSE = "מצאתי תוצאות מתאימות."


def _make_mock_db():
    """Return an AsyncMock that satisfies the get_db dependency."""
    mock_session = AsyncMock()
    mappings_mock = MagicMock()
    mappings_mock.all.return_value = []
    execute_result = MagicMock()
    execute_result.mappings.return_value = mappings_mock
    execute_result.all.return_value = []
    mock_session.execute = AsyncMock(return_value=execute_result)
    return mock_session


async def _mock_db_generator():
    """Async generator that yields a mock DB session."""
    yield _make_mock_db()


def _override_db():
    """FastAPI dependency override for get_db — returns a mock session."""
    return _mock_db_generator()


def _make_product_result() -> ProductResult:
    """Build a minimal ProductResult for assertions."""
    store_info = StoreInfo(
        id="store-001",
        name_he="חנות לדוגמה",
        name_en="Sample Store",
        buyme_url="https://buyme.co.il/store/sample",
        is_online=True,
        city="תל אביב",
        lat=32.08,
        lng=34.78,
        distance_km=None,
    )
    return ProductResult(
        product_id="prod-001",
        canonical_name="אוזניות סוני WH-1000XM5",
        brand="Sony",
        category_path="Electronics > Headphones",
        store=store_info,
        price=1299.0,
        currency="ILS",
        availability=True,
        product_url="https://example.com/product/1",
        match_score=0.92,
    )


def _make_store_result() -> StoreResult:
    """Build a minimal StoreResult for assertions."""
    return StoreResult(
        id="store-002",
        name_he="מסעדת הים",
        name_en="Sea Restaurant",
        buyme_url="https://buyme.co.il/store/sea",
        buyme_category="restaurant",
        address="רחוב הים 1",
        city="אילת",
        lat=29.55,
        lng=34.95,
        distance_km=None,
        is_online=False,
        product_count=0,
    )


def _make_mock_ai_client(clarify_message: str = "לא הבנתי — מה אתה מחפש בדיוק?") -> AsyncMock:
    """Return a mock AsyncOpenAI client with a canned clarify response."""
    mock_choice = MagicMock()
    mock_choice.message.content = clarify_message
    mock_completion = MagicMock()
    mock_completion.choices = [mock_choice]

    mock_ai = AsyncMock()
    mock_ai.chat.completions.create = AsyncMock(return_value=mock_completion)
    return mock_ai


# ---------------------------------------------------------------------------
# Test 1: Product search intent
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_product_search_intent() -> None:
    """POST /api/chat with product_search intent returns matching product results."""
    parsed = ParsedIntent(
        intent="product_search",
        product_query="אוזניות סוני",
        brand="Sony",
        voucher_network="buyme",
    )
    product_results = [_make_product_result()]

    app.dependency_overrides[get_db] = _override_db
    try:
        with patch("api.routes.chat._parse_intent", new=AsyncMock(return_value=parsed)), \
             patch("api.routes.chat._run_product_search", new=AsyncMock(return_value=product_results)), \
             patch("api.routes.chat._compose_response", new=AsyncMock(return_value=_FIXED_COMPOSE_RESPONSE)):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://testserver"
            ) as client:
                r = await client.post(
                    "/api/chat",
                    json={
                        "message": "אוזניות של סוני",
                        "history": [],
                        "voucher_network": "buyme",
                    },
                )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert r.status_code == 200
    data = r.json()
    assert data["intent"] == "product_search"
    assert data["product_results"] is not None
    assert len(data["product_results"]) == 1
    assert data["product_results"][0]["brand"] == "Sony"


# ---------------------------------------------------------------------------
# Test 2: Store search intent — city filter
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_store_search_city_filter() -> None:
    """POST /api/chat with store_search intent and city returns store results."""
    parsed = ParsedIntent(
        intent="store_search",
        store_type="restaurant",
        city="אילת",
        voucher_network="buyme",
    )
    store_results = [_make_store_result()]

    app.dependency_overrides[get_db] = _override_db
    try:
        with patch("api.routes.chat._parse_intent", new=AsyncMock(return_value=parsed)), \
             patch("api.routes.chat._run_store_search", new=AsyncMock(return_value=store_results)), \
             patch("api.routes.chat._compose_response", new=AsyncMock(return_value=_FIXED_COMPOSE_RESPONSE)):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://testserver"
            ) as client:
                r = await client.post(
                    "/api/chat",
                    json={"message": "מסעדות באילת"},
                )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert r.status_code == 200
    data = r.json()
    assert data["intent"] == "store_search"
    assert data["store_results"] is not None
    assert len(data["store_results"]) == 1
    assert data["store_results"][0]["city"] == "אילת"


# ---------------------------------------------------------------------------
# Test 3: needs_location — no GPS in session_context
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_needs_location_no_gps() -> None:
    """When intent needs GPS but none is provided, endpoint returns needs_location=True."""
    parsed = ParsedIntent(
        intent="store_search",
        store_type="restaurant",
        needs_user_location=True,
        voucher_network="buyme",
    )

    app.dependency_overrides[get_db] = _override_db
    try:
        with patch("api.routes.chat._parse_intent", new=AsyncMock(return_value=parsed)):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://testserver"
            ) as client:
                r = await client.post(
                    "/api/chat",
                    json={"message": "מסעדות לידי"},
                )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert r.status_code == 200
    data = r.json()
    assert data["needs_location"] is True
    assert data["intent"] == "clarify"
    assert data["location_prompt"] is not None
    assert len(data["location_prompt"]) > 0


# ---------------------------------------------------------------------------
# Test 4: needs_location resolved by session_context GPS
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_needs_location_resolved_by_gps() -> None:
    """When intent needs GPS and session_context provides it, search runs normally."""
    parsed = ParsedIntent(
        intent="store_search",
        store_type="restaurant",
        needs_user_location=True,
        voucher_network="buyme",
    )
    store_results = [_make_store_result()]

    app.dependency_overrides[get_db] = _override_db
    try:
        with patch("api.routes.chat._parse_intent", new=AsyncMock(return_value=parsed)), \
             patch("api.routes.chat._run_store_search", new=AsyncMock(return_value=store_results)), \
             patch("api.routes.chat._compose_response", new=AsyncMock(return_value=_FIXED_COMPOSE_RESPONSE)):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://testserver"
            ) as client:
                r = await client.post(
                    "/api/chat",
                    json={
                        "message": "מסעדות לידי",
                        "session_context": {
                            "user_lat": 32.08,
                            "user_lng": 34.78,
                            "location_label": "תל אביב",
                            "voucher_network": "buyme",
                        },
                    },
                )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert r.status_code == 200
    data = r.json()
    assert data["needs_location"] is False
    assert data["store_results"] is not None
    assert len(data["store_results"]) >= 1


# ---------------------------------------------------------------------------
# Test 5: Help intent
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_help_intent() -> None:
    """When intent is 'help', endpoint returns HELP_RESPONSE without product results."""
    parsed = ParsedIntent(intent="help", voucher_network="buyme")

    app.dependency_overrides[get_db] = _override_db
    try:
        with patch("api.routes.chat._parse_intent", new=AsyncMock(return_value=parsed)):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://testserver"
            ) as client:
                r = await client.post(
                    "/api/chat",
                    json={"message": "מה אפשר לקנות ב-BuyMe?"},
                )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert r.status_code == 200
    data = r.json()
    assert data["intent"] == "help"
    assert len(data["message"]) > 50
    assert data["product_results"] is None


# ---------------------------------------------------------------------------
# Test 6: Clarify fallback — internal Gemini JSON parse fails
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_clarify_fallback_on_internal_parse_failure() -> None:
    """When the Gemini LLM call inside _parse_intent raises, it returns intent='clarify'.

    The route then enters the clarify branch and calls ai.chat.completions.create
    to ask a clarifying question. That call is also mocked here.
    """
    # Mock the AI client: its chat.completions.create raises during _parse_intent
    # (first call), so _parse_intent falls back to clarify.
    # Then the route's clarify branch calls create again — mock that to succeed.

    call_count = 0

    async def _flaky_create(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # First call is inside _parse_intent — simulate JSON parse error
            raise ValueError("Simulated Gemini JSON parse failure")
        # Subsequent calls (clarify branch) return a valid response
        mock_choice = MagicMock()
        mock_choice.message.content = "לא הבנתי — מה אתה מחפש בדיוק?"
        mock_completion = MagicMock()
        mock_completion.choices = [mock_choice]
        return mock_completion

    mock_ai = AsyncMock()
    mock_ai.chat.completions.create = _flaky_create

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_ai_client] = lambda: mock_ai
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            r = await client.post(
                "/api/chat",
                json={"message": "blah blah"},
            )
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_ai_client, None)

    assert r.status_code == 200
    data = r.json()
    # _parse_intent caught the exception and returned intent='clarify'
    assert data["intent"] == "clarify"
    # The clarify branch produced a non-empty Hebrew message
    assert isinstance(data["message"], str)
    assert len(data["message"]) > 0
