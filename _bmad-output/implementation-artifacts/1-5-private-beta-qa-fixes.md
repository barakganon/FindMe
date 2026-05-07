# Story 1.5: Private-beta QA blocker fixes

Status: ready-for-dev

> **Note:** This is the first BMad story with full ceremony in this project — Stories 1.2-1.4
> are thin indexes that defer to START_PROMPT.md. Story 1.5 contains its own complete spec because
> the work is code-heavy across multiple files with non-trivial decisions baked in.

## Story

As **the operator running a private beta with friends and family**,
I want **the 5 BLOCK-tier issues found during the 2026-05-05/06 solo QA pass fixed** (plus the 4 fix-soon polish items),
so that **non-developer users get a working app on first impression rather than seeing earrings when they search for Sony headphones**.

## Acceptance Criteria

All ACs are direct mappings to findings from
[_bmad-output/qa-findings/2026-05-05-solo-qa.md](../qa-findings/2026-05-05-solo-qa.md).
Verify each AC by re-running the QA query that originally surfaced the bug.

### AC-1 (F-11) City matching expanded with synonym map  🔴

**Test:** `POST /api/chat {"message":"מסעדות בתל אביב"}` returns ≥ 50 store_results (currently returns 1).

**Detail:**
- The `stores.city` column uses BuyMe's own region buckets (e.g. `ת"א והסביבה`), not city names.
- Add a synonym map applied at chat-route entry (NOT at SQL level) that expands user-provided cities to the matching bucket(s):
  - `תל אביב` ↔ `ת"א` ↔ `ת״א` ↔ `תא` ↔ `יפו` ↔ `תל אביב-יפו` → all match `ת"א והסביבה`
  - `ירושלים` ↔ `י-ם` ↔ `ירושלים והסביבה`
  - `חיפה` ↔ `חיפה והסביבה`
  - `רמת גן` ↔ `מרכז` (verify in DB whether RG falls under TLV bucket or center)
  - At minimum cover the 5 BuyMe regions with recognizable city names from the [F-11 root-cause query result](../qa-findings/2026-05-05-solo-qa.md#f-11-).
- Implementation: replace `parsed.city` ILIKE in [api/routes/chat.py:367-369](../../api/routes/chat.py) (product) and [api/routes/chat.py:451-453](../../api/routes/chat.py) (store) with an OR-chain that tests against all bucket synonyms.
- Out of scope (deferred to Story 3.2): geo-radius fallback when synonym map yields 0 results.

### AC-2 (F-01 / F-08) Brand+category search relevance  🔴

**Test:**
- `POST /api/chat {"message":"אוזניות סוני"}` — top result has `brand ILIKE '%sony%'` (currently top is "עגילי סאני").
- `POST /api/chat {"message":"שעון אפל"}` — top result is a watch (not Lightning cable).
- `POST /api/chat {"message":"Sony WH-1000XM5"}` — top result has `brand ILIKE '%sony%'`.

**Detail:**
- **Approach: strict brand filter with empty-fallback to fuzzy** (decision baked in 2026-05-07).
- In [api/routes/chat.py `_run_product_search`](../../api/routes/chat.py#L250-L416), when `parsed.brand` is non-null:
  1. Apply `AND p.brand ILIKE '%<brand>%'` to BOTH the `_ILIKE_SQL` query (line 234-235) and the vector search SQL (line 295+).
  2. If filtered result count == 0, retry without the brand filter and prepend a clarifying note to the response message: e.g. "לא מצאתי תוצאות עבור <brand>, הנה תוצאות דומות:" (or similar).
- The currently-skipped brand filter at [chat.py:372 comment](../../api/routes/chat.py#L372) was an explicit design choice that turned out wrong. Replace it.
- Important: brand matching must be case-insensitive AND handle the most common brand-name variants. "Sony" should match `Sony`, `SONY`, `sony`, `סוני`. Either normalize at insertion (out of scope) or use `LOWER()` + a `brand_synonyms` dict for the top 20 brands.

### AC-3 (F-02) Intent parser determinism via temperature=0  🔴

**Test:** Run "מסעדות בתל אביב" and "כיסא ארגונומי לעבודה" 10 times each. Each query must return the same `intent` 10/10 times (currently ~80% / ~90% respectively).

**Detail:**
- In [api/routes/chat.py `_parse_intent` line 109-116](../../api/routes/chat.py#L109), add `temperature=0` parameter to the `client.chat.completions.create(...)` call.
- The Gemini OpenAI-compatible endpoint accepts `temperature`. Verify by inspecting response or running 10x manually.
- **Don't add temperature to `_compose_response`** (line 169) — response composition wants slight variety so users don't see the same phrasing every time.

### AC-4 (F-04) Reply text never contradicts results  🔴

**Test:** No response message containing `"לא מצאתי"`, `"לא מצאנו"`, `"לא נמצא"`, or `"לא נמצאו"` may be returned alongside `len(product_results) > 0` or `len(store_results) > 0`.

**Detail:**
- Code-level enforcement, not prompt-level. After `_compose_response` returns, check for the negative phrases; if found AND results are non-empty, replace with a deterministic positive opener like `"מצאתי עבורך:"`.
- Alternative: assert in tests, fail loudly in dev — but for now, the runtime guard is safer.

### AC-5 (F-09) Single brand name returns product_search  🔴

**Test:** `POST /api/chat {"message":"סמסונג"}` returns `intent=product_search` with ≥ 5 results, all where `brand ILIKE '%samsung%'` (currently returns clarify).

**Detail:**
- Update [api/prompts.py `INTENT_PARSER_SYSTEM`](../../api/prompts.py) to add an explicit example:
  - "אם המשתמש הזכיר רק שם מותג (סמסונג, אפל, סוני, נייקי וכו') — intent=product_search, brand=<name>, product_query=null"
- Verify with several brand-only queries: סמסונג, Apple, Sony, נייקי, אדידס.

### AC-6 (F-03) needs_location synonyms via regex post-processing  🔴

**Test:** `POST /api/chat {"message":"חנויות בגדים באזור שלי"}` returns `needs_location=True` (currently returns False with intent=clarify).

**Detail:**
- After `_parse_intent` returns, in the chat handler ([chat.py around line 600](../../api/routes/chat.py#L590-L600)), apply a deterministic post-processing step:

```python
LOCATION_SYNONYMS = re.compile(
    r"(?:לידי|באזור שלי|קרוב אלי|בקרבתי|פה בעיר|כאן|near me|by me|nearby)",
    re.IGNORECASE,
)
if LOCATION_SYNONYMS.search(body.message):
    parsed = parsed.model_copy(update={"needs_user_location": True})
```

- This is belt-and-suspenders: Gemini might say `needs_user_location=False` but regex catches it. Inverse (Gemini says True but no regex match) keeps Gemini's answer — this lets Gemini still detect novel phrasings.

### AC-7 (F-13) Query-time deduplication of search results  🔴

**Test:** `POST /api/chat {"message":"איפור"}` no longer returns the same Niveah Rose Care row 4 times (currently does — see B6.03 in QA report).

**Detail:**
- In `_run_product_search` after the `merged.sort(...)` line at [chat.py:358](../../api/routes/chat.py#L358), and BEFORE the result accumulation loop, deduplicate by `(canonical_name, normalized_price)` where:
  ```python
  normalized_price = round(row["price"], 0) if row["price"] is not None else 0
  ```
- Keep the first occurrence (highest similarity per the sort). Discard subsequent rows with the same key.
- Out of scope: rewriting the bulk `normalization/deduplication.py` algorithm. That's its own future story (the 6h-runtime bug from Story 1.1's QA).

### AC-8 (F-05/F-12) Frontend already handles non-retail product_count — verify only  🟡

**Test:** Open frontend at `http://localhost:5173`, query `"מסעדות בתל אביב"`, confirm restaurant cards do NOT show "0 מוצרים" line.

**Detail:**
- During architecture review, [StoreCard.tsx:60](../../frontend/src/components/StoreCard.tsx#L60) was found to already have `{result.product_count > 0 && …}` — meaning 0/null counts are already hidden.
- This AC is a **verification step only**, not a code change. Confirm in browser, then mark complete.
- If the verification reveals an actual UI issue (e.g. overlapping rendering), then add the explicit category-based hide as a sub-task.

### AC-9 (F-06) No English fragments in Hebrew response composer output  🟡

**Test:** `POST /api/chat {"message":"ספא בירושלים"}` reply text does not contain the words `spa`, `restaurant`, `store_type`, `product_query`. Verified across 5 manual queries spanning each store type.

**Detail:**
- In [api/routes/chat.py `_compose_response` line 163-167](../../api/routes/chat.py#L163), the user prompt currently injects `parsed.product_query or parsed.store_type or '(לא ידוע)'` directly. The composer LLM then sometimes echoes that English value back in Hebrew.
- Replace the injection with a Hebrew description:
  - `store_type=restaurant` → "מסעדות"
  - `store_type=spa` → "ספא"
  - `store_type=hotel` → "מלונות"
  - `store_type=leisure` → "אטרקציות וחוויות"
  - `store_type=retail` → "חנויות"
  - `product_query=<text>` → use as-is (already Hebrew or English from user)

### AC-10 No regressions

**Test:** `pytest tests/ -q` reports `29 passed` (currently the baseline). All existing tests for auth, cache, anonymous fallback, OOS sort, SQL safety must still pass.

**Detail:**
- New unit tests required for the changes. See **Testing Requirements** below.

## Tasks / Subtasks

Prioritized order — implement F-11 first (biggest user-visible impact), then F-01, then the small ones in parallel.

- [ ] **Task 1 (AC-1, F-11): City synonym map** ← **DO FIRST**, biggest unlock
  - [ ] Add `CITY_SYNONYMS: dict[str, list[str]]` constant to a new module `api/city_synonyms.py` or near the top of `api/routes/chat.py`
  - [ ] Verify exact spelling of BuyMe bucket names by querying DB: `SELECT DISTINCT city FROM stores ORDER BY 1`
  - [ ] Implement `expand_city(city: str) -> list[str]` that returns the user-provided city + all known synonyms
  - [ ] Replace `Store.city.ilike(f"%{parsed.city}%")` at [chat.py:453](../../api/routes/chat.py#L453) with `or_(Store.city.ilike(f"%{c}%") for c in expand_city(parsed.city))`
  - [ ] Replace the Python-side filter at [chat.py:367-369](../../api/routes/chat.py#L367) similarly
  - [ ] Verify with QA query: "מסעדות בתל אביב" → ≥ 50 stores
  - [ ] Add unit test in `tests/api/test_chat.py`: `test_city_synonyms_expand_tlv`

- [ ] **Task 2 (AC-2, F-01/F-08): Strict brand filter**
  - [ ] In [chat.py:212-240 `_ILIKE_SQL`](../../api/routes/chat.py#L212), wrap with optional brand-filter SQL fragment when `parsed.brand` is non-null
  - [ ] Same for vector search SQL at [chat.py:295](../../api/routes/chat.py#L295)
  - [ ] After result merge, if filtered result count == 0 AND `parsed.brand` was applied, retry without brand filter and set a flag for the response composer
  - [ ] Add brand-name normalization helper (top 20 brands → Hebrew↔English variants)
  - [ ] Verify: "אוזניות סוני" → top has Sony in `brand`; "Sony WH-1000XM5" → top has Sony; "שעון אפל" → top is a watch
  - [ ] Add unit tests: `test_brand_strict_filter_returns_brand_match_only`, `test_brand_filter_zero_results_falls_back_with_note`

- [ ] **Task 3 (AC-3, F-02): Temperature=0 on intent parser**
  - [ ] Add `temperature=0` to [chat.py:109-116](../../api/routes/chat.py#L109) `client.chat.completions.create(...)` call
  - [ ] Do NOT add to `_compose_response` at [chat.py:169](../../api/routes/chat.py#L169)
  - [ ] Verify: run "מסעדות בתל אביב" 10× via curl, count `intent=store_search` responses
  - [ ] Add unit test (mocked Gemini): `test_intent_parse_uses_temperature_zero` — mock checks the kwargs include `temperature=0`

- [ ] **Task 4 (AC-5, F-09): Single brand → product_search**
  - [ ] Update [api/prompts.py INTENT_PARSER_SYSTEM](../../api/prompts.py#L17-L49) — add the brand-only example rule
  - [ ] Verify: "סמסונג" → product_search with brand applied
  - [ ] Add unit test: `test_brand_only_query_routes_to_product_search`

- [ ] **Task 5 (AC-6, F-03): needs_location regex post-processing**
  - [ ] Add `LOCATION_SYNONYMS_RE` constant in `api/routes/chat.py`
  - [ ] After `_parse_intent` returns at [chat.py:600](../../api/routes/chat.py#L600), apply the regex check and override `parsed.needs_user_location` if matched
  - [ ] Verify: "חנויות בגדים באזור שלי" → `needs_location=True`
  - [ ] Add unit test: `test_location_synonyms_force_needs_location`

- [ ] **Task 6 (AC-7, F-13): Query-time deduplication**
  - [ ] In `_run_product_search` at [chat.py:358](../../api/routes/chat.py#L358), after the sort and before the filter loop, dedupe by `(canonical_name.lower(), round(price or 0, 0))`
  - [ ] Use a `set` of seen keys, drop duplicate rows
  - [ ] Verify: "איפור" returns ≤ 1 row per (name, price) combo
  - [ ] Add unit test: `test_query_time_dedup_removes_same_name_same_price`

- [ ] **Task 7 (AC-4, F-04): Reply contradiction guard**
  - [ ] After `_compose_response` returns in the route handler ([chat.py:690 / 701](../../api/routes/chat.py#L690)), check the message for negative phrases when results are non-empty
  - [ ] If contradicted, replace message with deterministic Hebrew opener (e.g. `f"מצאתי עבורך {len(results)} תוצאות:"`)
  - [ ] Verify: B1.09 reproduction (`Sony WH-1000XM5`) — message no longer says "לא מצאנו"
  - [ ] Add unit test: `test_response_composer_contradiction_replaced`

- [ ] **Task 8 (AC-9, F-06): Hebrew descriptions for parsed values in response composer**
  - [ ] In [chat.py:163-167 `_compose_response`](../../api/routes/chat.py#L163), build a Hebrew descriptor string from `parsed.store_type` and `parsed.product_query` instead of injecting raw values
  - [ ] Add `STORE_TYPE_HE: dict[str, str]` mapping
  - [ ] Verify: "ספא בירושלים" reply does not contain `spa`
  - [ ] Add unit test: `test_response_composer_no_english_fragments`

- [ ] **Task 9 (AC-8, F-05/F-12): Verify frontend handling**
  - [ ] Open `http://localhost:5173` in browser
  - [ ] Send "מסעדות בתל אביב" — verify restaurant cards do NOT display "0 מוצרים"
  - [ ] If verification passes, mark AC complete with a one-line note in the QA findings doc
  - [ ] If verification fails, add code change to `StoreCard.tsx` to explicitly hide product_count for category in `(restaurant, spa, hotel, leisure)`

- [ ] **Task 10 (AC-10): Regression check**
  - [ ] Run `.venv/bin/pytest tests/ -q` — must report 29 passed (or 29 + new tests added in Tasks 1-8)
  - [ ] If any pre-existing test fails, fix before continuing — do NOT skip or comment out

## Dev Notes

### Tech stack relevant to this story (from project-context.md)

- **Python**: All routes async/await; type hints required; `from __future__ import annotations` at top of every file
- **FastAPI**: All LLM prompts in `api/prompts.py` (NEVER inline); `get_optional_user` for endpoints anonymous can call
- **Gemini**: Model `gemini-2.5-flash`, max_tokens=256 for intent / 200 for response composer; OpenAI SDK 1.58.1
- **Pydantic v2**: All new schemas in `api/schemas.py`
- **Testing**: pytest + anyio; mock Gemini with MagicMock via `ai_client` fixture from `tests/conftest.py`; never make real LLM calls in tests

### Files being modified

| File | Lines | What changes |
|---|---|---|
| [api/routes/chat.py](../../api/routes/chat.py) | 109-150 | `_parse_intent`: add `temperature=0` |
| [api/routes/chat.py](../../api/routes/chat.py) | 153-180 | `_compose_response`: build Hebrew descriptor for parsed values |
| [api/routes/chat.py](../../api/routes/chat.py) | 212-240 | `_ILIKE_SQL`: add optional `AND p.brand ILIKE` clause |
| [api/routes/chat.py](../../api/routes/chat.py) | 250-416 | `_run_product_search`: brand filter w/ fallback, query-time dedup |
| [api/routes/chat.py](../../api/routes/chat.py) | 358 | After existing availability sort, dedupe by `(canonical_name, normalized_price)` |
| [api/routes/chat.py](../../api/routes/chat.py) | 367-369, 451-453 | Replace single-city ILIKE with synonym OR-chain |
| [api/routes/chat.py](../../api/routes/chat.py) | ~590-600 | Post-process `parsed` with `LOCATION_SYNONYMS_RE` |
| [api/routes/chat.py](../../api/routes/chat.py) | 690, 701 | After `_compose_response`, contradiction guard |
| [api/prompts.py](../../api/prompts.py) | 17-49 | Add brand-only-query rule to `INTENT_PARSER_SYSTEM` |
| **NEW**: `api/city_synonyms.py` (or top of chat.py) | n/a | `CITY_SYNONYMS: dict[str, list[str]]` + `expand_city(city)` helper |
| [tests/api/test_chat.py](../../tests/api/test_chat.py) | append | 8 new test cases (one per code-touching task) |
| (verify only) [frontend/src/components/StoreCard.tsx](../../frontend/src/components/StoreCard.tsx) | 60 | Already correct; verify in browser, no code change expected |

### Files NOT to touch (regression risk)

- `api/main.py` — router registration is fine; do not change rate limiter or CORS
- `api/auth.py` / `api/dependencies.py` — auth flow works; don't break it
- `api/cache.py` — Redis cache works (verified in QA Battery 4); the intent cache key is already `sha256(message)` so cache invalidation post-deploy is automatic
- `db/models.py` — no schema changes needed
- `scraper/*.py` — installment-price + dedup belong to Stories 3.1 separately
- Existing 29 tests — fix new test additions if they collide; do NOT modify existing tests

### Critical safety rules (from project-context.md)

- **Anonymous users must always work** — `POST /api/chat` uses `get_optional_user`. None of these fixes should require auth.
- **Always strip ` ```json ` fences before `json.loads()` on Gemini output** — already done in `_parse_intent`; keep it
- **Always `try/except` around Gemini JSON parsing; fallback to `intent=clarify`** — already in place; preserve
- **Pyramid of caching** — intent cache 2 min, search cache 5 min. After deploy, both auto-invalidate via TTL. No manual flush needed.
- **All user-facing text must be in Hebrew (RTL)**

### Previous story intelligence

**Story 1.1 (done)** taught us:
- Worktree's `.venv` lives in main checkout — invoke as `/Users/barakganon/personal_projects/FindMe/.venv/bin/python -m pytest`
- `frontend/node_modules` is per-checkout; needs `npm install` once per worktree
- Code edits flow: branch on worktree → push → merge from main checkout (worktree can't checkout master while main has it)
- The pre-deploy fixes (UI demotion + sort) shipped at commit `6792141` — that pattern of small focused commits with conventional-commit messages is what we want here

**QA findings doc** (the source for this story's ACs):
- Document is at [_bmad-output/qa-findings/2026-05-05-solo-qa.md](../qa-findings/2026-05-05-solo-qa.md)
- All AC tests are reproductions of QA queries; rerun them to verify
- The decision matrix at the bottom of the QA doc was answered by the user 2026-05-07: **strict filter** (F-01), **synonym map only** (F-11), **query-time dedup** (F-13)

### Testing requirements

- All new logic must have unit tests in `tests/api/test_chat.py` (or a new `tests/api/test_chat_qa_fixes.py` file if 1.5 grows organically)
- Mock Gemini for all tests via the `ai_client` fixture (see `tests/conftest.py`)
- Run baseline before committing each task: `.venv/bin/pytest tests/ -q` must always pass
- Manual QA queries from [_bmad-output/qa-findings/2026-05-05-solo-qa.md](../qa-findings/2026-05-05-solo-qa.md) should be re-run end-to-end against the local backend after Tasks 1-8 are complete

### Research notes

- **Gemini OpenAI-compatible endpoint** accepts `temperature` parameter. Spec at https://generativelanguage.googleapis.com/v1beta/openai/. No SDK upgrade needed (we're on `openai==1.58.1` which supports it).
- **PostgreSQL 16 + `or_`** in SQLAlchemy: `from sqlalchemy import or_`; multi-condition match is `where(or_(*conditions))`.
- **Hebrew normalization** — Python's `str.lower()` works for ASCII; for Hebrew we don't need lowercasing (no case in Hebrew), so simple substring match is fine. Just be aware that Hebrew tokenization varies (`ת"א` vs `ת״א` vs `תא`) — the synonym map handles this explicitly.

### Project Structure Notes

- Adheres to "all schemas in `api/schemas.py`" — no new schemas needed for this story
- City synonyms could go in `api/city_synonyms.py` (new file) OR at the top of `api/routes/chat.py` (~ 30 lines, manageable). I recommend the new file since it's tabular data that the test suite will want to import directly.
- No new dependencies — keep `requirements.txt` untouched.

### References

- [QA findings 2026-05-05/06](../qa-findings/2026-05-05-solo-qa.md) — single source of truth for AC interpretation
- [epics.md Story 1.5 entry](../planning-artifacts/epics.md#story-15--private-beta-qa-blocker-fixes) — the same content as ACs above
- [project-context.md](../../_bmad-output/project-context.md) — coding rules
- [START_PROMPT.md](../../START_PROMPT.md) — context for the future deploy (NOT relevant to this story; we're staying local)

## Dev Agent Record

### Agent Model Used

(to be filled by dev agent)

### Debug Log References

(to be filled by dev agent)

### Completion Notes List

(to be filled by dev agent)

### File List

(to be filled by dev agent — expected: 2-4 modified files, 1 new file, 1-2 modified test files)

## Change Log

(to be filled by dev agent)
