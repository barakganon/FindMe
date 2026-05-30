# Story 5.8: Test Rewrite Around Tools (W8)

Status: ready-for-dev

> **Source:** [findme-v2-sprint-plan.md](../planning-artifacts/findme-v2-sprint-plan.md) — Week 8.
> The v2 agentic refactor (W2–W7) built five tools (`search_products`, `search_stores`,
> `get_user_context`, `recall_history`, `clarify`), but only `search_products` is exercised
> end-to-end through `test_agent_loop.py`. The other four have **zero direct unit-test files**.
> Stream/SSE coverage is also thin (4 tests in `test_chat_v2_stream.py`). W8 fixes the gap and
> tightens CI so every PR runs the full suite green.
>
> **Gate question (W8):** Is the harness green on CI?
>
> **Definition of green:** every PR triggers `ci.yml`, the test job completes ≤ 5 min, the
> full pytest suite passes, frontend builds clean, and the eval-nightly workflow is either
> green or transparently opt-in (no false-failure noise).

## Scope

**In scope:**

- Direct unit-test files for all five agent tools (`tests/api/test_tool_*.py`)
- Expanded SSE coverage in `tests/api/test_chat_v2_stream.py`
- Consolidated mock fixtures in `tests/conftest.py` (and a new `tests/api/conftest.py`
  for API-scoped fixtures) so tool tests don't each rewrite mock setup
- Eval-nightly workflow refactored to skip cleanly when `EVAL_BASE_URL` is unset
  (currently fails noisily; the actual eval should be opt-in until we deploy)
- Test count target: **≥ 180 total** (was 141, so ≥ 39 new/rewritten)
- CI passes on every PR with the new tests

**Out of scope (defer):**

- Eval harness running against a docker-compose backend in CI — large infra change.
  W9 (cost + deploy hardening) is the natural place to wire a deployed staging URL into
  `EVAL_BASE_URL`. For W8, just stop the nightly failures.
- Frontend testing framework setup (Vitest, Playwright) — frontend has no test suite
  today and adding one is a separate story
- Property-based testing (Hypothesis) — overkill at this stage
- Mutation testing — overkill at this stage
- Recording Gemini cassettes (VCR.py) for replayable LLM tests — appealing but adds a
  large new dependency surface; defer

## Acceptance Criteria

### AC-1: `tests/api/test_tool_search_products.py`

New file. ≥ 8 tests covering `execute_search_products` directly:

- Hebrew query → returns shaped results (mock `_run_product_search` to return fixtures)
- English query → same path, with English filter values
- Brand re-rank applied: when `params.brand` set, brand-matching items sort first;
  non-matching items follow in original similarity order; `brand=None` items sort last
  (mirrors the W6 contract from `5-6-prompt-iteration.md`)
- `params.max_price` honored and passed through to `_run_product_search`
- `params.online_only=True` filters out non-online stores **BEFORE** the `limit` slice
- `params.location` (lat/lng) propagated to the search filter
- Empty results → `(items=[], summary="לא מצאתי…")` shape
- Embedding/SQL exception → returns `(items=[], summary="<error>")` not raised
- Result-count cap respected (the tool description says ≤ 6 items; verify slicing)

Each test mocks `_run_product_search` directly (it's the only external call) — no DB,
no Gemini. Reference: `api/agent/tools/search_products.py:149 execute_search_products`.

### AC-2: `tests/api/test_tool_search_stores.py`

New file. ≥ 6 tests covering `execute_search_stores`:

- `store_type='restaurant'` query with GPS → returns nearby stores with `distance_km`
- `store_type='retail'` query with city filter → returns stores in city
- Missing GPS + "lidi"-style location_hint → returns location-required clarification
  (`(items=[], summary="<location-needed>")`)
- Pagination: `params.page=2` retrieves the second page
- Empty store-list → graceful empty result
- DB error → graceful empty result, no raise

Reference: `api/agent/tools/search_stores.py:91 execute_search_stores`.

### AC-3: `tests/api/test_tool_get_user_context.py`

New file. ≥ 5 tests covering `execute_get_user_context`:

- Anonymous user (`current_user=None`) → `(items=[], summary="המשתמש לא מחובר")`
- Logged-in user with preferences only → summary contains preference values
- Logged-in user with high-confidence (≥ 0.5 per CLAUDE.md privacy contract) inferred
  attributes only → summary lists inferred attrs; low-confidence (< 0.5) attrs
  are EXCLUDED
- Logged-in user with both prefs + inferred → both appear in summary, prefs first
- DB error → graceful `(items=[], summary="מידע משתמש לא זמין")`

Reference: `api/agent/tools/get_user_context.py:55 execute_get_user_context`.

### AC-4: `tests/api/test_tool_recall_history.py`

New file. ≥ 5 tests covering `execute_recall_history`:

- Empty `session_state` → returns empty result with "no prior turns" summary
- `reference='הראשון'` / `'first one'` → returns the first item from `last_product_results`
- `reference='השני'` / `'second'` → returns the second item
- Name-based recall: `reference='Sony XM5'` → matches by `canonical_name` substring
- No match → empty result, no raise

Reference: `api/agent/tools/recall_history.py:55 execute_recall_history`.

### AC-5: `tests/api/test_tool_clarify.py`

New file. ≥ 3 tests covering `execute_clarify`:

- `kind='location'` → returns location-clarification summary in Hebrew
- `kind='ambiguous'` with `question` → returns the question verbatim
- Invalid `kind` → returns a generic clarification, never raises

Reference: `api/agent/tools/clarify.py:68 execute_clarify`.

### AC-6: Expanded `tests/api/test_chat_v2_stream.py`

Extend the existing 4 tests with ≥ 6 more:

- SSE parser: a single `read()` chunk containing two full frames produces two events
- SSE parser: a `read()` chunk that splits a frame at the `\n\n` boundary still
  produces one event after buffering across reads
- SSE parser: multi-byte UTF-8 split across two reads (Hebrew letter cut in half) is
  reassembled correctly — exercise this on the frontend OR document this is purely
  a `TextDecoder({stream: true})` guarantee (no Python-side test needed)
- Backend: `final` event payload includes the `chips` field (already covered, but
  add cases for: anon empty, anon with derived_facts, logged-in)
- Backend: `X-Session-ID` header is honored — passing a value derives the session id
  per `session_memory.derive_session_id`
- Backend: when `current_user` is set, session id uses `user:<id>` regardless of header

The multi-byte UTF-8 reassembly test belongs in the frontend if a frontend test
framework lands; if not, the backend already emits one frame per event so this is
implicitly safe — note this in test docstrings rather than skipping silently.

### AC-7: Consolidated mock fixtures

Refactor shared mock setup into:

- `tests/conftest.py` (existing) — keep `anyio_backend` and `ai_client` as-is; add
  a `redis_mock` fixture returning a configured `AsyncMock` with `.get`, `.setex`,
  `.delete` pre-bound (used by ~10 test files today)
- `tests/api/conftest.py` (new) — add API-scoped fixtures:
  - `tool_context()` — returns the dict passed to every `execute_*` tool (`db`, `api_key`,
    `location`, `current_user`, `session_state`) with sensible mocks
  - `mock_db()` — `AsyncMock` SQLAlchemy session with `.execute` returning a configurable
    chain (`.scalars()`, `.all()`, `.scalar_one_or_none()`)
  - `app_client()` — `httpx.AsyncClient` wired to `app` with deps already overridden
    (used by `test_chat_v2_stream.py`, `test_chat.py`, route tests)

Existing tests that duplicate this setup (notably `test_chat_v2_stream.py`,
`test_session_memory.py`, `test_chips.py`) should NOT be rewritten in this story —
just have the new fixtures available. Replace ad-hoc mocks in future stories naturally.

### AC-8: Eval-nightly workflow no longer false-fails

`.github/workflows/eval-nightly.yml` currently exits 1 when `EVAL_BASE_URL` is unset,
generating noise every night. Refactor:

- The `Resolve base URL` step writes `skip=true` (instead of `exit 1`) when no URL
- Subsequent steps gate on `if: steps.base.outputs.skip != 'true'`
- The workflow concludes successfully with a clear "skipped — set EVAL_BASE_URL
  repo variable to enable" message
- The cron schedule stays; manual `workflow_dispatch` still works the moment a URL
  is supplied

W9 will set `EVAL_BASE_URL` once a staging backend exists. Until then, no nightly
failure emails.

### AC-9: Test count + CI green

- After this story merges, `pytest tests/` reports **≥ 180 tests, all passing**
- The CI test job in `.github/workflows/ci.yml` completes ≤ 5 minutes
- No new dependencies added (everything mockable with `unittest.mock`)
- Document the new fixture surface in a top-of-file docstring in each new file
  AND in a one-paragraph "Testing patterns" section appended to `tests/eval/rubric.md`

### AC-10: Project context updated

Append a short rule to `_bmad-output/project-context.md` under the existing
**Testing Rules** section:

> - Every new tool in `api/agent/tools/` MUST have a matching
>   `tests/api/test_tool_<name>.py` file with at least: happy path, empty/no-result
>   path, error path, anonymous (when applicable), and per-parameter coverage for
>   each tool parameter that has documented behavior.

This codifies the W8 contract so future tools don't ship without coverage.

## Tasks / Subtasks

- [ ] **Task 1 (AC-7):** add `redis_mock` to `tests/conftest.py`; create `tests/api/conftest.py`
      with `tool_context`, `mock_db`, `app_client` fixtures. Test that fixtures resolve cleanly
      (no-op test file or use in Task 2).
- [ ] **Task 2 (AC-1):** create `tests/api/test_tool_search_products.py` with ≥ 8 tests covering
      Hebrew + English happy paths, brand re-rank, max_price, online_only ordering, location,
      empty, error, result cap.
- [ ] **Task 3 (AC-2):** create `tests/api/test_tool_search_stores.py` with ≥ 6 tests covering
      restaurant + retail paths, location-required clarification, pagination, empty, error.
- [ ] **Task 4 (AC-3):** create `tests/api/test_tool_get_user_context.py` with ≥ 5 tests.
- [ ] **Task 5 (AC-4):** create `tests/api/test_tool_recall_history.py` with ≥ 5 tests.
- [ ] **Task 6 (AC-5):** create `tests/api/test_tool_clarify.py` with ≥ 3 tests.
- [ ] **Task 7 (AC-6):** extend `tests/api/test_chat_v2_stream.py` with ≥ 6 SSE/session-id cases.
- [ ] **Task 8 (AC-8):** refactor `.github/workflows/eval-nightly.yml` to skip cleanly without
      `EVAL_BASE_URL` — no more nightly failure emails.
- [ ] **Task 9 (AC-9):** run `pytest tests/` locally; confirm ≥ 180 tests pass. Check CI on the PR.
- [ ] **Task 10 (AC-10):** append the new-tool-needs-tests rule to
      `_bmad-output/project-context.md` under Testing Rules.
- [ ] **Task 11:** Story → review, sprint-status updated, commits on
      `feature/w8-test-rewrite`, PR opened.

## Dev Notes

### Authoritative tool signatures (read before writing tests)

All five tools follow the same shape:

```python
async def execute_<name>(
    params: <Name>Params,        # Pydantic model — validated by the agent loop
    *,
    db: AsyncSession,
    api_key: str,                # Gemini key — most tools don't use it
    location: Optional[LocationFilter],   # GPS if provided
    current_user: Optional[Any],          # User or None for anon
    session_state: Optional[SessionState],
    **_unused: object,
) -> tuple[list, str]:
    """
    Returns (items, summary). `items` is the structured result list the agent
    loop accumulates onto ChatResponseV2.product_results or .store_results;
    `summary` is the JSON-encoded text the LLM sees in its tool-result message.
    """
```

The kwarg pattern is uniform — your `tool_context` fixture should just unpack into the
call. The `**_unused` swallow means extra keys in `tool_context` are fine.

### Per-tool quirks the tests must cover

**`search_products`:**
- Imports `_run_product_search` lazily from `api.routes.chat` (circular-dep band-aid;
  documented in `deferred-work.md`). Mock at `api.agent.tools.search_products._run_product_search`,
  not at the chat-route source.
- Has a 3-tier brand re-rank (W6): brand-match first, other-brand second, no-brand last.
  Tests must mock `_run_product_search` to return mixed `brand` fields and assert order.
- `online_only` filter is applied BEFORE the `limit` slice — this is a real W3 deferred-work
  item ("online_only filter applied before slicing to `limit`"). A test must exercise the
  ordering (return 10 results, 7 online + 3 offline, `online_only=True`, `limit=5` → 5 online).

**`search_stores`:**
- "Near me" without GPS triggers a clarification path (returns location-needed). Test for
  both: with GPS → search runs; without GPS → clarification summary.
- The store query builder is imported from `api.routes.stores` — mock it the same way.

**`get_user_context`:**
- Imports `UserPreference`, `UserInferredAttribute`, `UserVoucherCard`, `UserSearchHistory`
  locally (inside the function) to dodge module-load ordering. Don't try to patch them at
  the top of the test file — patch at use site inside the function call's lifetime, or
  use `monkeypatch.setattr` on the module's symbol table after first call.
- Confidence threshold for inferred attrs: per CLAUDE.md, ≥ 0.5 is "search-usable", < 0.5
  is "transparency-only". W7 tightened chips to `> 0.5`; this tool uses `>= 0.5`. The
  asymmetry is intentional — the chip strip is the most-visible surface, the tool result
  is internal LLM context. Don't change either threshold from this story.

**`recall_history`:**
- Reads `session_state.last_product_results` and `last_store_results` (W3). When both
  are empty, returns a "no prior turns" summary.
- Ordinal references ("first", "הראשון", "1") and name-substring references both supported.
  Coverage for each.

**`clarify`:**
- Smallest tool (~80 lines). Doesn't touch DB. Pure function over `params`.
- `kind` discriminator: `'location'`, `'ambiguous'`, plus a generic fallback. Test each.

### Fixture sketch (`tests/api/conftest.py`)

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from types import SimpleNamespace
from api.agent.session_memory import SessionState


@pytest.fixture
def mock_db() -> MagicMock:
    """AsyncMock SQLAlchemy session. `.execute()` is async; configure return
    via `db.execute.return_value = <result>` then chain `.scalars().all()`.
    """
    db = MagicMock()
    db.execute = AsyncMock()
    return db


@pytest.fixture
def tool_context(mock_db) -> dict:
    """The dict passed as **kwargs into every execute_* tool."""
    return {
        "db": mock_db,
        "api_key": "fake-key",
        "location": None,
        "current_user": None,
        "session_state": SessionState.empty(),
    }


def make_db_result(*scalars) -> MagicMock:
    """Build a mock result whose .scalars().all() returns the given items."""
    res = MagicMock()
    res.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=list(scalars))))
    return res


def make_user(user_id: str = "user-abc") -> SimpleNamespace:
    return SimpleNamespace(id=user_id, email="t@e.st", display_name="T")
```

Tests then look like:

```python
async def test_anonymous_returns_empty(tool_context):
    from api.agent.tools.get_user_context import execute_get_user_context, GetUserContextParams
    items, summary = await execute_get_user_context(GetUserContextParams(), **tool_context)
    assert items == []
    assert "לא מחובר" in summary
```

### Eval-nightly skip pattern

The shell skip looks like:

```yaml
- name: Resolve base URL
  id: base
  run: |
    BASE="${{ inputs.base_url || vars.EVAL_BASE_URL }}"
    if [ -z "$BASE" ]; then
      echo "::notice::EVAL_BASE_URL is not set. Skipping eval run."
      echo "skip=true" >> "$GITHUB_OUTPUT"
    else
      echo "url=$BASE" >> "$GITHUB_OUTPUT"
      echo "skip=false" >> "$GITHUB_OUTPUT"
    fi

- name: Run eval harness
  if: steps.base.outputs.skip != 'true'
  run: ...

- name: Upload baseline artifact
  if: always() && steps.base.outputs.skip != 'true'
  uses: actions/upload-artifact@v4
  ...
```

The `::notice::` annotation surfaces in the Actions UI without marking the run failed.

### Anti-pattern prevention

- **Do not import or mock Gemini.** Tools that need an AI client (none of the five do
  directly; only `api/inference.py` does) are out of scope here.
- **Do not call `_run_product_search` for real.** Always mock it. It hits the DB +
  pgvector + Gemini embedding API.
- **Do not write tests that depend on test-order.** Each test must set up its own
  mocks; the `tool_context` fixture provides a fresh mock_db per test.
- **Do not add `redis_mock` to test files individually.** Use the conftest fixture.
- **Do not change tool signatures** to make them easier to test — the agent loop
  expects the current `(params, **kwargs) → tuple[list, str]` shape.
- **Do not introduce new dependencies** (no `pytest-mock`, no `vcrpy`, no `pytest-httpx`).
  `unittest.mock` + `httpx.AsyncClient` (already used) are sufficient.
- **Do not bypass the `from __future__ import annotations` rule.** Every new test
  file starts with that import (project rule).

### Previous-story intelligence (5-7 closeout)

- 5-7 added chip strip + memory + streaming UI. Code-review surfaced 18 patches, all
  applied (commit `2ea592f`). Notable W8-relevant artifacts:
  - `tests/api/test_chips.py` already validates the 6-cap, compound has_children chip,
    and `_clean_int_str` rounding. **Do not duplicate** in W8.
  - `test_session_memory.py` now covers `derived_facts` extraction and overwrite
    semantics. **Do not duplicate.**
  - The `getOrCreateSessionId` memoization for private-mode browsers is frontend-only
    and not testable here.
- The deferred-work entries from 5-7 review (test 6-cap weak, confidence-desc ordering
  untested, `MemoryChip.kind` not a Literal, `partial_content` unhandled) are also out
  of scope here — they belong to their own follow-up. Focus on the W8 spec.

### Files to read before writing tests

- `api/agent/tools/search_products.py` (esp. `_rerank_by_brand` logic and the lazy
  `_run_product_search` import)
- `api/agent/tools/search_stores.py`
- `api/agent/tools/get_user_context.py`
- `api/agent/tools/recall_history.py`
- `api/agent/tools/clarify.py`
- `api/agent/tools/__init__.py` (TOOL_SPECS, TOOLS registry — registry shape sanity)
- `tests/api/test_agent_loop.py` — pattern reference for how tools are exercised
  in integration; **but do not extend agent_loop tests** — your job is direct-unit.
- `tests/conftest.py` — fixture conventions to follow

### Testing standards (from project-context.md, restated)

- `@pytest.mark.anyio` on every async test; `anyio_backend` fixture lives in
  `tests/conftest.py` — do NOT redeclare per-file
- Never make real Gemini/DB calls — mock at dependency layer
- Test files live in `tests/api/` mirroring the route/tool they test
- File path convention: `tests/api/test_tool_<short_name>.py` (NEW convention from this
  story; matches the natural mapping `api/agent/tools/<name>.py → test_tool_<name>.py`)
- Run with venv pytest: `.venv/bin/python -m pytest tests/ -p no:cacheprovider`
  (the system Python's stale pytest_flask plugin breaks `pytest` directly — known trap
  from W7)

### Test count target math

Current: **141 collected** (`pytest tests/` head row). Target: **≥ 180**.

| File | New / target | Source |
|---|---|---|
| `test_tool_search_products.py` | ≥ 8 new | AC-1 |
| `test_tool_search_stores.py` | ≥ 6 new | AC-2 |
| `test_tool_get_user_context.py` | ≥ 5 new | AC-3 |
| `test_tool_recall_history.py` | ≥ 5 new | AC-4 |
| `test_tool_clarify.py` | ≥ 3 new | AC-5 |
| `test_chat_v2_stream.py` extension | ≥ 6 new | AC-6 |
| **Total new** | **≥ 33** | — |

That puts us at 141 + 33 = **174**. To hit 180, expect 6+ "free" tests as side effects
of the fixture work (e.g. fixture sanity checks, additional parameter coverage in
the per-tool files that come naturally). Target is `≥ 180`, not `==`.

### Git workflow

- Branch: `feature/w8-test-rewrite`
- Conventional commits, ≥ 8 commits across the story:
  1. `test(fixtures): add tool_context + mock_db conftest fixtures`
  2. `test(tools): cover execute_search_products direct paths`
  3. `test(tools): cover execute_search_stores direct paths`
  4. `test(tools): cover execute_get_user_context with prefs + inferred`
  5. `test(tools): cover execute_recall_history ordinal + name refs`
  6. `test(tools): cover execute_clarify dispatch + fallback`
  7. `test(stream): expand SSE coverage — buffering, session id, chips`
  8. `infra(ci): skip eval-nightly cleanly when EVAL_BASE_URL is unset`
  9. `docs(context): require test_tool_<name>.py for every new agent tool`
- PR title: `test(W8): 33+ new tool/stream tests + eval-nightly skip (Story 5.8)`
- Merge to master `--no-ff` after PR review.

### References

- [Source: _bmad-output/planning-artifacts/findme-v2-sprint-plan.md — Week 8]
- [Source: _bmad-output/implementation-artifacts/5-7-ui-polish-and-repair.md — review findings + deferred items]
- [Source: _bmad-output/implementation-artifacts/deferred-work.md — known gaps]
- [Source: _bmad-output/project-context.md — Testing Rules section]
- [Source: api/agent/tools/__init__.py — TOOL_SPECS + TOOLS registry]
- [Source: tests/eval/rubric.md — eval-harness scoring; not changed by this story]

## Dev Agent Record

### Agent Model Used

_To be filled by dev agent._

### Debug Log References

### Completion Notes List

### File List

## Change Log

| Date | Change |
|---|---|
| 2026-05-30 | Story created from v2 sprint plan W8 |
