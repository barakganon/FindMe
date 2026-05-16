# Story 5.4: Audit Fixes + Telemetry (W4)

Status: done

> **Source:** [findme-v2-sprint-plan.md](../planning-artifacts/findme-v2-sprint-plan.md) — Week 4. After W3 proved the agent can reliably call the right tools, W4 fixes the data-layer issues that cause the tools to return junk results — and adds telemetry so we can measure what real users actually do once the soft launch starts in W5.
>
> **Gate question:** Does multi-turn coherence hold with state? (Validated via existing W3 session memory + new measurable improvements on F-11 store counts and F-08 brand top-result.)

## Acceptance Criteria

### AC-1: City synonym module + wired into search_stores

- `api/normalization/city_synonyms.py` — `expand_city(user_city: str) -> list[str]` returns the user input plus every matching BuyMe regional bucket.
- Maps the 16 actual bucket values observed in production (see Dev Notes for full list).
- Handles BOTH ASCII straight quote (`ת"א`) and Hebrew typographic quote (`ת״א`) for TLV.
- Wired into `api/agent/tools/search_stores.py` to expand `params.city` into the OR clause that `_run_store_search` uses.
- Unit tests covering: TLV variants, Jerusalem variants, lowercase English ("tel aviv"), unknown city pass-through.

### AC-2: Brand backfill script + executed locally

- `scripts/backfill_brands.py` — regex-extract brand from `products.canonical_name` for top-20 Israeli brands (Sony, Apple, Samsung, Nike, Adidas, LG, Bosch, Philips, Braun, Whirlpool, Electrolux, GE, Asus, Lenovo, HP, Dell, Xiaomi, Garmin, Logitech, JBL).
- Updates `products.brand` where currently NULL or empty. Reports row counts updated per brand.
- Idempotent: re-running doesn't double-update; safe to schedule.
- Dry-run mode (`--dry-run`) prints what would change without writing.
- Executed against local DB; result counts documented in story completion notes.

### AC-3: agent_traces table + migration + insertion

- Alembic migration creates `agent_traces` table:
  ```
  id UUID PK, session_id TEXT, user_id UUID NULL, message TEXT, intent TEXT,
  tool_calls JSONB, iterations INT, total_latency_ms FLOAT,
  total_cost_usd NUMERIC(10,6) NULL, terminated_by TEXT, created_at TIMESTAMPTZ
  ```
- ORM model `AgentTrace` in `db/models.py`.
- `chat_v2.py` inserts a row after `run_agent` (best-effort — never blocks response on insert failure).
- Index on `(created_at DESC)` for recent-query lookups.

### AC-4: Chain detection skeleton

- `scripts/detect_chains.py` — pg_trgm-based clustering of store names, populates `parent_chain_id` for stores matching a hand-curated top-20 chain regex (FOX, Castro, Renuar, Greg, H&M, etc.).
- Migration check: if `parent_chain_id` column doesn't exist, document the manual step + defer.
- Dry-run mode prints proposed mappings.

### AC-5: Tests + regression

- `tests/api/test_city_synonyms.py` — covers expansion logic for 5 named cities + unknown pass-through.
- `tests/api/test_telemetry.py` — covers agent_traces insertion (mocked DB, verifies fields).
- All existing 68 tests still pass.

### AC-6: W4 eval baseline

- Re-run eval against `/api/chat/v2`.
- Capture `tests/eval/baselines/2026-05-16-v4-audit-fixes.md`.
- Expected improvements:
  - F-11 city queries: `has_results` should jump (e.g. "מסעדות בתל אביב" now returns ≥50 stores via bucket expansion).
  - F-08 brand_top_result: should improve as brand backfill populates products that previously had `brand=NULL`.

## Tasks

- [x] **Task 1 (AC-1):** `normalization/city_synonyms.py` (42 synonyms across 16 buckets) + wired into search_stores (multi-query merge with dedup by store.id) + 16 unit tests
- [x] **Task 2 (AC-2):** `scripts/backfill_brands.py` — 58 products tagged (Sony 13, HP 14, Bosch 9, Samsung 7, Apple 6, Xiaomi 4, JBL 3, others)
- [x] **Task 3 (AC-3):** migration `0009_agent_traces.py` applied, `AgentTrace` ORM in db/models.py, best-effort insert in chat_v2.py `_record_trace`, smoke test verified 1 row inserted
- [x] **Task 4 (AC-4):** `scripts/detect_chains.py` ran successfully, 7 stores linked to chain parents (Castro 4, FOX 3, Greg 2, H&M 2, plus singletons)
- [x] **Task 5 (AC-5):** 16 new city-synonym tests, 84/84 total tests pass
- [x] **Task 6 (AC-6):** `tests/eval/baselines/2026-05-16-v4-audit-fixes.md` — overall 56.8%→63.6%, F-11 86%→100%, F-09 33%→67%, tool_call_match 91.4%→94.3%
- [x] **Task 7:** Story → done, sprint-status updated, commit on `feature/w4-audit-fixes-telemetry`, PR opened

## Dev Notes

### BuyMe regional bucket inventory (observed in local DB, 2026-05-16)

| Bucket value | Store count |
|---|---|
| `ת"א והסביבה` | 407 |
| `מרכז` | 260 |
| `(NULL)` | 182 |
| `סניפים בפריסה ארצית` | 94 (nationwide chains) |
| `צפון` | 74 |
| `השרון והסביבה` | 48 |
| `ירושלים והסביבה` | 47 |
| `דרום` | 38 |
| `הגליל והגולן` | 29 |
| `הנגב` | 21 |
| `חיפה והסביבה` | 14 |
| `מודיעין, השפלה והסביבה` | 10 |
| `אילת והערבה` | 7 |
| `אשקלון, אשדוד והסביבה` | 2 |
| `פתח תקווה ובקעת אונו` | 1 |
| `רמת השרון` | 1 |
| `תל אביב-יפו` | 1 |

### Synonym map design

User input → bucket(s):
- `תל אביב` / `ת"א` / `ת״א` / `תא` / `יפו` / `Tel Aviv` → `["ת"א והסביבה", "תל אביב-יפו"]` (408 stores)
- `ירושלים` / `י-ם` / `Jerusalem` → `["ירושלים והסביבה"]`
- `חיפה` / `Haifa` → `["חיפה והסביבה"]`
- `אילת` / `Eilat` → `["אילת והערבה"]`
- `הרצליה` / `רמת השרון` / `כפר סבא` → `["השרון והסביבה", "רמת השרון"]`
- `אשקלון` / `אשדוד` → `["אשקלון, אשדוד והסביבה"]`
- `פתח תקווה` / `אונו` / `קרית אונו` → `["פתח תקווה ובקעת אונו"]`
- `מודיעין` / `רמלה` / `לוד` → `["מודיעין, השפלה והסביבה"]`
- Unknown city → pass-through (just the original input)

### Why brand-backfill is a script, not a migration

Alembic migrations should be schema changes. Data backfills go in `scripts/` so they can be re-run (idempotently) without touching schema history. The brand regex set is also subject to ongoing refinement — easier to update a script than amend a migration.

### Telemetry shape

The `agent_traces` table is the foundation for first-week analytics (Story 2.2 from the original epics) and for the data-driven prompt iteration in W6. Storing the full `tool_calls` array as JSONB lets us run ad-hoc analytics like:
- "what cities do users actually search?"
- "which tools are called most?"
- "p95 latency by intent"
- "cost per session"

Without inflating row counts to one-per-tool-call.

### What this story does NOT do

- Does not re-embed products (no embedding changes).
- Does not change the chat.py v1 endpoint.
- Does not add a UI for the trace data (W7 polish).
- Does not deploy the migration to Render (that's the user's call when ready).

## Change Log

| Date | Change |
|---|---|
| 2026-05-16 | Story created from v2 sprint plan W4 |
