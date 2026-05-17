# Story 5.6: Prompt Iteration + Brand Re-Rank (W6)

Status: done

> **Source:** [findme-v2-sprint-plan.md](../planning-artifacts/findme-v2-sprint-plan.md) — Week 6.
> The W4 baseline left the agent at 63.6% overall, 94.3% tool_call_match. The
> ceiling on overall pass rate is dominated by **brand_top_result (28.6%)** and
> **empty_tool_calls (55.6%)**. W6 pushes both with two interventions:
>
> 1. **Brand re-rank** in `search_products` — soft post-search boost so brand-matching
>    items rise to the top. Targets brand_top_result 28.6% → 70%+.
> 2. **System prompt v2** with explicit Hebrew examples for the clarify-vs-search
>    edge cases. Targets empty_tool_calls 55.6% → 80%+.
>
> **Gate question:** Are we above 90% on the golden set?
> **Realistic goal:** ≥80% overall (data quality limits — F-08 0/2 still needs
> the SQL-layer brand filter that's deferred).

## Acceptance Criteria

### AC-1: Brand re-rank in `search_products`

- In `execute_search_products`, after `_run_product_search` returns and BEFORE
  the `online_only` filter + limit slice, when `params.brand` is set:
  apply a stable sort so items whose `brand` field contains `params.brand`
  (case-insensitive substring) come first.
- Items without a matching brand are NOT dropped — they appear after the
  brand-matching items in their original similarity order. This is a soft
  filter, not a hard filter.
- Items with `brand=None` always sort last when a brand filter is active.

### AC-2: System prompt v2

- Iterate `DEFAULT_SYSTEM_PROMPT` in `api/agent/loop.py` with:
  - Explicit "DO NOT call search on emoji-only / SQL-injection / single-word ambiguous queries → call clarify or return help text"
  - Explicit comparison-turn rule: "if user references prior results (הראשונה / כמו פעם שעברה / what about the second one), call `recall_history` FIRST, then compose — do not call search again"
  - Explicit help-vs-search rule: "if user asks 'how does this work' / 'what is BuyMe' / 'מה אפשר לקנות' (without describing a product) → return short help text, do not call any tool"
  - Single-brand reinforcement (already in W2 prompt, restate for emphasis): "single brand name alone (סמסונג, Apple, Sony) → call search_products with brand=<name>"

### AC-3: Tool description hardening

- `search_products` description: add "When NOT to call" subsection listing emoji-only queries, SQL injection patterns, "how does this work" questions, multi-result comparison references.
- `clarify` description: tighten the "When to call clarify" list with more explicit Hebrew triggers.
- `search_stores`: add reminder that "near me" without GPS triggers clarify, not search.

### AC-4: Probe queries added

- Extend `tests/eval/golden_queries.yaml` with 5-8 new queries targeting:
  - More clarify-vs-search edge cases ("מה?", "?", "abc")
  - Comparison references that should hit `recall_history` (not search) — e.g., "מה זה הראשון?" with prior history
  - Help variants ("איך זה עובד?", "מה זה BuyMe?", "explain this app")
- Each new query has expected_intent + expected_tool_calls set per the W3 contract.

### AC-5: CI eval workflow

- `.github/workflows/eval-nightly.yml` — schedules the eval harness to run
  nightly OR on-demand via `workflow_dispatch`.
- Posts results as an artifact (the markdown baseline).
- For now, runs against `http://localhost:8000` — assumes a deployed backend
  is reachable. **Note:** since we haven't deployed yet, this workflow will
  fail until W5 frontend + Render deploy land. Document as expected.

### AC-6: Tests + regression

- New test: brand re-rank logic in `search_products` (mocked `_run_product_search` returns mixed items, verify brand-matching ones sort first).
- All existing 118 tests still pass.

### AC-7: W6 eval baseline

- Capture at `tests/eval/baselines/2026-05-16-v6-prompt-iteration.md`.
- Compare against W4 baseline. Document any regressions explicitly.
- W6 gate: overall pass rate ≥ 80% (stretch: 90%). brand_top_result ≥ 70%. empty_tool_calls ≥ 80%.

## Tasks

- [x] **Task 1 (AC-1):** `_rerank_by_brand` in execute_search_products — 3-tier stable sort (brand match → other brand → no brand). **Result: brand_top_result 28.6% → 77.8% (+49pts)**.
- [x] **Task 2 (AC-2):** system prompt v2 with explicit routing rules. **Initial expanded version (80 lines) broke Gemini's tool-calling on multi-arg queries** — Gemini returned empty content + empty tool_calls on `מסעדות בתל אביב`, `מתנה לאמא עד 200`. Trimmed back to ~35 lines focused on routing rules + edge cases + reply style. Verified all 4 smoke queries pass.
- [x] **Task 3 (AC-3):** Tool description hardening — search_products got "When NOT to call" subsection (emoji, SQL inject, help-questions, comparison refs) + brand-handling-critical paragraph.
- [x] **Task 4 (AC-4):** 5 probe queries added (`?`, `מה?`, `abc`, `מה זה BuyMe?`, `explain this app`). 3 of 5 still fail (Gemini calls search on `?` / `מה?` / `abc`) — needs further iteration or code-level clarify heuristic.
- [x] **Task 5 (AC-5):** `.github/workflows/eval-nightly.yml` — schedules nightly + manual-trigger eval against a deployed backend. Wires repo variable EVAL_BASE_URL.
- [x] **Task 6 (AC-6):** 5 new tests for _rerank_by_brand. 123/123 passing.
- [x] **Task 7 (AC-7):** Baseline at `tests/eval/baselines/2026-05-17-v6-prompt-iteration.md` — full v1→W2→W3→W4→W6 comparison.
- [x] **Task 8:** Story → done, sprint-status updated, commit on `feature/w6-prompt-iteration`, PR opened.

## Change Log

| Date | Change |
|---|---|
| 2026-05-16 | Story created from v2 sprint plan W6 |
