# Story 5.1: Eval Harness + Golden Queries + Baseline

Status: review

> **Source:** [findme-v2-sprint-plan.md](../planning-artifacts/findme-v2-sprint-plan.md) — Week 1 of the agentic conversation refactor.
> The eval harness is the *spine* of the entire 11-week sprint. Without it, every prompt iteration in W2-W6 is blind. This story produces the harness and establishes the baseline against the current (single-shot) chat pipeline so improvements are measurable.

## Story

As **the operator rebuilding FindMe's chat layer into an agentic conversation loop**,
I want **a golden-query eval harness with a reproducible baseline run against the current `api/routes/chat.py`**,
so that **every subsequent prompt change, tool addition, or LLM-provider swap can be measured against ground truth — and the W2 kill-gate (≥80% tool-call accuracy on Gemini-2.5-flash) can actually be checked**.

## Acceptance Criteria

### AC-1: `tests/eval/golden_queries.yaml` exists with ≥40 queries

- 30 Hebrew, 10 English queries minimum
- Each entry has: `id`, `query`, `expected_intent`, `expected_brand` (optional), `expected_city` (optional), `expected_max_price` (optional), `expected_needs_location` (bool), `expected_has_results` (bool), `expected_tool_calls` (list, for v2 use later), `notes`
- Coverage: brand+category (F-01), city normalization (F-11), single brand (F-09), needs_location synonyms (F-03), help, clarify, comparison turns, memory recall, edge cases (emoji, special chars, long), English queries
- Each canonical Sally scenario (Sarah, Yael, Avi, Rinat, Mind-Changer) has at least one corresponding query
- File is human-readable YAML, no schemas required to edit

### AC-2: `tests/eval/rubric.md` documents v1 + v2 scoring

- v1 scoring (current single-shot chat): how each ChatResponse field maps to a pass/fail per query
- v2 scoring (future tool-calling): how `expected_tool_calls` will be checked against the agent's tool invocations
- Pass/fail thresholds for the W2 kill-gate (≥80% tool-call accuracy) explicitly stated
- A worked example showing how one query is scored end-to-end

### AC-3: `tests/eval/runner.py` runs against a live `POST /api/chat`

- CLI: `python -m tests.eval.runner --base-url http://localhost:8000 [--limit N] [--output FILE]`
- Reads `golden_queries.yaml`, sends each query to `POST /api/chat`, scores response against expected fields per the rubric
- Outputs a per-query pass/fail table + summary (overall pass rate, breakdown by dimension)
- Handles errors gracefully (HTTP errors, malformed responses) — surfaces them in the output without aborting the run
- Supports `--limit N` to run a subset for fast iteration

### AC-4: Baseline run captured

- `tests/eval/baselines/2026-05-15-v1-baseline.md` exists with a snapshot of the baseline run
- Includes: command used, total queries, overall pass rate, per-dimension scores, ≥10 representative per-query failure modes (with the query, what was expected, what was returned)
- This baseline is the comparison point for every future eval run

### AC-5: No regressions to existing 29 tests

- `.venv/bin/pytest tests/ -q` reports 29 passed
- Eval files live in `tests/eval/` but are not auto-discovered by pytest (different shape — invoked via CLI, not pytest)

## Tasks / Subtasks

- [x] **Task 1 (AC-1): Author `tests/eval/golden_queries.yaml`**
  - [x] Create `tests/eval/` directory
  - [x] Author 30 Hebrew queries covering: brand+category, single brand, city by name + bucket synonym, needs_location synonyms, help, clarify ambiguous, comparison reference, memory recall pattern, emoji-only, very long message, SQL-injection-shaped, special chars (delivered 31)
  - [x] Author 10 English queries covering the same dimensions (delivered 11)
  - [x] Validate YAML parses correctly (`python -c 'import yaml; yaml.safe_load(open("tests/eval/golden_queries.yaml"))'`) — 42 queries total, all IDs unique

- [x] **Task 2 (AC-2): Write `tests/eval/rubric.md`**
  - [x] v1 scoring section: per-field mapping from `ChatResponse` → pass/fail
  - [x] v2 scoring section: tool-call name + args match (for W2 use)
  - [x] Worked example with one Hebrew query end-to-end (`headphones-sony-hebrew`)
  - [x] W2 kill-gate threshold (≥80% tool-call accuracy) clearly stated

- [x] **Task 3 (AC-3): Implement `tests/eval/runner.py`**
  - [x] CLI with argparse: `--base-url`, `--limit`, `--output`, `--queries-file`, `--concurrency`, `--json`, `--endpoint`
  - [x] Load `golden_queries.yaml` via `pyyaml` (already in `requirements.txt`)
  - [x] Async loop using `httpx.AsyncClient` (already in `requirements.txt`) — concurrency cap to avoid hammering Gemini (default 3)
  - [x] Score each response per rubric, accumulate per-dimension scores
  - [x] Output: stdout summary table + optional markdown file via `--output`
  - [x] Error handling: HTTP errors, timeouts, malformed JSON — captured as failures, not crashes

- [x] **Task 4 (AC-4): Run baseline and capture results**
  - [x] Start local backend: `.venv/bin/python -m uvicorn api.main:app --port 8000` (uvicorn shebang stale, so invoke via `python -m`)
  - [x] Run: `.venv/bin/python -m tests.eval.runner --base-url http://127.0.0.1:8000 --concurrency 3 --output tests/eval/baselines/2026-05-15-v1-baseline.md`
  - [x] Manually review baseline output for sanity — **26/42 = 61.9%**, right in predicted 50-70% range, all known QA findings reproduced
  - [x] Baseline file committed at `tests/eval/baselines/2026-05-15-v1-baseline.md` with interpretation header

- [x] **Task 5 (AC-5): Verify no regressions**
  - [x] `.venv/bin/python -m pytest tests/ -q --ignore=tests/eval` reports **29 passed**
  - [x] Confirmed `tests/eval/` is not auto-collected by pytest (`pytest tests/eval --collect-only -q` → `no tests collected`)

## Dev Notes

### Why this is W1 and not W2

The kill-gate at end-of-W2 (≥80% tool-call accuracy on Gemini-2.5-flash for Hebrew) only works if we have a measurement tool. Building the agent loop first and then trying to measure it post-hoc means we'd be tuning prompts against vibes for a week before realizing the score-tracking infrastructure doesn't exist. Eval comes first.

### Why score against `ChatResponse` only (not internal `ParsedIntent`)

The current v1 chat pipeline doesn't expose `ParsedIntent` in the response — it's internal to `_parse_intent` in `chat.py:69`. Rather than modify the production schema for eval purposes, we score against observable `ChatResponse` fields:
- `intent` (matches expected)
- `needs_location` (matches expected)
- `len(product_results) > 0 or len(store_results) > 0` (has_results matches expected)
- Top result's `brand` (for F-01 brand-filter testing)
- Top result's `store.city` (for F-11 city-matching testing)
- Top result's `price <= expected_max_price` (for price filter testing)
- Reply text does NOT contradict result count (for F-04 contradiction guard)

This is a *strictly weaker* signal than scoring against `ParsedIntent` directly, but it has the advantage that the harness will work unchanged against v2's agentic responses (which also produce a `ChatResponse`).

### What the v2 extension looks like

When W2 introduces `POST /api/chat/v2` (agent loop with tool calls), the harness extends:
- New CLI flag: `--endpoint /api/chat/v2`
- New field in golden_queries: `expected_tool_calls: [{tool: "search_products", args: {brand: "Sony"}}]`
- New score dimension: tool-name match + args match (per the W2 kill-gate at 80%)
- v2 endpoint must include a `trace` field in its response (or a sibling `/api/chat/v2/trace/{request_id}` endpoint) so the runner can read what tools were called

The trace mechanism is W2 work, not this story. AC-2 documents the *expected shape* so W2 has a contract to build to.

### Files being created (new)

| File | Purpose |
|---|---|
| `tests/eval/__init__.py` | Make `tests.eval` importable as a module |
| `tests/eval/golden_queries.yaml` | 40+ golden queries with expected outcomes |
| `tests/eval/rubric.md` | Scoring rules for v1 and v2 |
| `tests/eval/runner.py` | Async eval CLI |
| `tests/eval/baselines/2026-05-15-v1-baseline.md` | First baseline against current chat.py |

### Files NOT touched

- `api/` (no production changes — this is pure eval scaffolding)
- `frontend/` (out of scope for W1)
- `db/` (no schema changes)
- Existing tests in `tests/api/` and `tests/scraper/` and `tests/normalization/` (no regressions)

### Critical safety rules

- The runner makes REAL API calls to `POST /api/chat`, which means REAL Gemini calls. Each run costs Gemini quota. Use `--limit N` for fast iteration; only run full 40-query baseline when you're ready to commit.
- The runner does NOT modify any data — it's read-only against the chat endpoint.
- Do not commit any output file containing user PII or API keys.

### Project Structure Notes

- `tests/eval/` is a new subdirectory peer to `tests/api/`, `tests/scraper/`, `tests/normalization/`
- It is invoked via CLI (`python -m tests.eval.runner`), NOT auto-collected by pytest (the runner is not a test file in the pytest sense — it's an evaluation script)
- No new dependencies needed: `pyyaml`, `httpx`, `argparse` (stdlib) all already available

### References

- [findme-v2-sprint-plan.md](../planning-artifacts/findme-v2-sprint-plan.md) — the 11-week parent plan
- [qa-findings/2026-05-05-solo-qa.md](../qa-findings/2026-05-05-solo-qa.md) — the failures the baseline should reproduce
- [project-context.md](../project-context.md) — coding rules (async, type hints, etc.)

## Dev Agent Record

### Agent Model Used

claude-opus-4-7 (1M context)

### Debug Log References

- `.venv/bin/uvicorn` shebang points at stale `/Users/barakganon/PycharmProjects/PythonProject/FindMe/.venv/bin/python` path. Worked around by invoking `python -m uvicorn` directly. Recreating the venv is in Story 1.1's deferred list — not blocking here. Same issue affects all `.venv/bin/*` console scripts.
- Smoke test against 3 queries (head of golden set) reproduced F-01 (Sony→Sani earrings), F-08 (Apple watch→Lightning earphones), and F-04 (reply contradicts results) on the first run — confirming both the runner and the rubric work as designed before the full baseline.

### Completion Notes List

1. **W1 deliverable complete.** Eval harness is the spine of the v2 sprint. Every subsequent prompt change, tool addition, or LLM-provider swap can now be measured against ground truth. No more "tuning prompts blind."
2. **42 golden queries** — 31 Hebrew, 11 English, 3 multi-turn. Each tagged with a section identifier (F-01, F-11, Sally, Edge, Help, Clarify, English, Other) so runner output breaks down per-dimension. All BLOCK-tier QA findings from 2026-05-05 are covered as explicit queries.
3. **6 v1 scoring dimensions** in the rubric — `intent`, `needs_location`, `has_results`, `brand_top_result`, `city_top_result` (auto-skipped when not applicable), `price_filter_respected`, `no_contradiction`. v2 will add `tool_call_match`, `no_extra_tool_calls`, `empty_tool_calls` against the trace contract documented in rubric.md.
4. **Baseline: 26/42 = 61.9%.** Right in the 50-70% range Winston/Mary predicted in round 4. Per-dimension breakdown:
   - intent 81% · needs_location 100% · has_results 88% · brand_top_result **22%** · no_contradiction 98% · price_filter 100%
   - F-01 brand filter: 1/3, F-08 brand+model: 0/2, F-09 single brand: 1/3, F-03 needs_location: **0/4** (prompt drift since QA), F-11 city: 6/7 (better than expected), F-13 dedup: 1/1
   - Sally scenarios 2/5 — comparison/ambiguous-open can't pass on single-shot intent parser. The v2 thesis in evidence.
5. **Latency:** p50 3.4s, p95 5.6s, max 37s (one cold-start outlier). v2 agentic loop will 2-3× this; cost-guard at W5 is non-negotiable.
6. **Runner extensibility for v2:** `--endpoint` flag swaps `/api/chat` → `/api/chat/v2` when that route exists in W2. Rubric documents the `trace` field contract the v2 endpoint must include.
7. **Sprint-status updated.** Epic 1 stories 1.2-1.5 marked `superseded` (deploy path abandoned). Epic 5 added with 5-1 through 5-9 for the 11-week refactor.

### File List

**New:**
- `_bmad-output/implementation-artifacts/5-1-eval-harness.md` (this file)
- `tests/eval/__init__.py` (empty, for module importability)
- `tests/eval/golden_queries.yaml` (42 queries, 19 KB)
- `tests/eval/rubric.md` (scoring rules + worked example + W2 kill-gate, 7.4 KB)
- `tests/eval/runner.py` (async eval CLI, 21 KB)
- `tests/eval/baselines/2026-05-15-v1-baseline.md` (first baseline + interpretation, 8.6 KB)

**Modified:**
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — added pivot note, superseded Epic 1 stories 1.2-1.5, added Epic 5 + stories 5-1 through 5-9
- `_bmad-output/planning-artifacts/findme-v2-sprint-plan.md` was *created* in the party-mode session preceding this story; not modified here

**No production code (`api/`, `frontend/`, `db/`) was touched** — this story is pure eval scaffolding by design.

## Change Log

| Date | Change |
|---|---|
| 2026-05-15 | Story created from v2 sprint plan W1 |
| 2026-05-15 | Implementation complete: 42 golden queries, rubric, runner, baseline (26/42=61.9%), 29 regression tests still passing. Status → review. |
