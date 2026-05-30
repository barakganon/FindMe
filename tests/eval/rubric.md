# Eval Rubric — FindMe v2 Sprint

> Scoring rules for `tests/eval/runner.py`. Two scoring profiles:
> **v1** (single-shot `POST /api/chat`, scored against observable `ChatResponse` fields)
> **v2** (agentic `POST /api/chat/v2`, scored against tool-call traces; W2+ — not yet built)
>
> The same `golden_queries.yaml` file drives both profiles. v2 adds a `expected_tool_calls` check on top of every v1 check.

---

## v1 Scoring (current single-shot chat — for the W1 baseline)

Each query produces a per-dimension score. A query passes overall when **every applicable dimension passes**. Dimensions that aren't expected for a given query (e.g. `expected_brand` is absent) are skipped, not scored.

### Per-dimension rules

| Dimension | Applies when | Pass condition |
|---|---|---|
| **intent** | always | `response.intent == query.expected_intent` (exact string match) |
| **needs_location** | always | `response.needs_location == query.expected_needs_location` |
| **has_results** | always | `(len(response.product_results or []) + len(response.store_results or [])) > 0` matches `query.expected_has_results` |
| **brand_top_result** | `query.expected_brand` is set | The top product result's `brand` field contains `query.expected_brand` (case-insensitive substring). Skipped if no product results returned. |
| **brand_top_n** | `query.expected_brand` is set and `query.brand_in_top > 1` | At least one of the top N product results matches `expected_brand`. Default `brand_in_top=1` (same as brand_top_result). |
| **city_top_result** | `query.expected_city` is set | The top store result's `city` field contains `query.expected_city` (case-insensitive substring). Skipped for product results. |
| **price_filter_respected** | `query.expected_max_price` is set | All returned product results have `price` ≤ `expected_max_price * 1.05` (5% tolerance for promotional pricing rounding). Null prices are allowed (out-of-stock items). |
| **no_contradiction** | always | If results are non-empty, `response.message` must NOT contain any of: `לא מצאתי`, `לא מצאנו`, `לא נמצא`, `לא נמצאו`, `no results found`. This is the F-04 guard. |

### Aggregate score

- **Overall pass rate** = queries where every applicable dimension passed / total queries
- **Per-dimension pass rate** = dimension passes / queries where the dimension applies
- **Per-section pass rate** = pass rate within each `notes` tag (F-01, F-11, etc.)

### Worked example — `headphones-sony-hebrew`

Query:
```yaml
id: headphones-sony-hebrew
query: "אוזניות סוני"
expected_intent: product_search
expected_brand: sony
expected_needs_location: false
expected_has_results: true
```

Suppose the response is:
```json
{
  "intent": "product_search",
  "needs_location": false,
  "product_results": [
    {"canonical_name": "עגילי סאני", "brand": "Sani", "price": 140.0, ...},
    {"canonical_name": "אוזניות JBL Bluetooth", "brand": "JBL", "price": 250.0, ...}
  ],
  "store_results": null,
  "message": "מצאתי 2 תוצאות עבורך:"
}
```

Scoring:

| Dimension | Expected | Got | Pass? |
|---|---|---|---|
| intent | `product_search` | `product_search` | ✅ |
| needs_location | `false` | `false` | ✅ |
| has_results | `true` | `true` (2 results) | ✅ |
| brand_top_result | `sony` (substring of top result's brand) | top brand is `Sani` | ❌ |
| no_contradiction | reply doesn't say "didn't find" with results | reply: "מצאתי 2 תוצאות עבורך:" | ✅ |

**Overall: FAIL** — one dimension (brand_top_result) failed. This is the exact F-01 finding.

### Special handling

- **Multi-turn queries** (those with `history`): the runner sends `history` plus `message` to `POST /api/chat` exactly as a real client would. Scoring rules are identical — no special multi-turn dimensions in v1.
- **Edge cases tolerating empty results** (e.g. `eilat-restaurants`, `restaurants-near-me-lidi`): `expected_has_results: false` means "no results is correct here." The `brand_top_result` and `city_top_result` dimensions are auto-skipped when results are empty.
- **Errors** (HTTP 500, timeout, JSON parse fail): the query is recorded as a failure with `dimension: error` and the exception message in the per-query output. Errors do not abort the run.

### Thresholds (for the W1 baseline)

There is no pass/fail threshold for the W1 baseline — it's a measurement, not a gate. We expect the v1 baseline to be in the **50–70%** range (the QA findings predict ~10 known failures across F-01, F-09, F-11, F-13 alone, plus intermittent F-02 flakiness).

Track the baseline number; every subsequent eval run is compared against it.

---

## v2 Scoring (agentic — for the W2 kill-gate)

When `POST /api/chat/v2` exists (W2 deliverable), the runner can score against tool-call traces. Everything in v1 still applies; v2 adds:

### Additional dimensions

| Dimension | Applies when | Pass condition |
|---|---|---|
| **tool_call_match** | `query.expected_tool_calls` is non-empty | Every entry in `expected_tool_calls` has a matching call in the agent's trace. Match = `tool` name equal + `args` superset (agent may pass additional args beyond what's expected, but must include all expected args with matching values). |
| **no_extra_tool_calls** | `query.expected_tool_calls` is non-empty | Agent did not call any tools beyond what was expected (off by ≤1 is tolerated to allow for `clarify` follow-ups). |
| **empty_tool_calls** | `query.expected_tool_calls == []` | Agent made ZERO tool calls — used only conversation context (e.g. `sally-avi-comparison` should reuse tray, not re-search). |

### W2 kill-gate threshold

**End of W2: the agent loop on Gemini-2.5-flash must score ≥80% on `tool_call_match` across all v2-scorable queries (those with non-empty `expected_tool_calls`).**

Failure to clear this bar triggers a 1-day swap to Claude Sonnet 4.7 (per [findme-v2-sprint-plan.md](../../_bmad-output/planning-artifacts/findme-v2-sprint-plan.md) W2). If Claude doesn't clear it either, kill the agentic v1 thesis and revert to shipping transactional.

### Trace contract for v2 endpoint

For the runner to score tool calls, the `POST /api/chat/v2` response must include a `trace` field matching `AgentTrace` in `api/schemas.py`. **The tool-call entries use the `name` field for the tool name** (the runner also accepts `tool` as an alias for backward compatibility with older golden queries):

```json
{
  "message": "...",
  "intent": "...",
  "product_results": [...],
  "store_results": [...],
  "trace": {
    "tool_calls": [
      {"name": "search_products", "args": {"brand": "Sony", "max_price": 300}, "duration_ms": 432, "result_count": 10, "error": null}
    ],
    "iterations": 2,
    "total_latency_ms": 1450,
    "total_cost_usd": 0.0012,
    "terminated_by": "content"
  }
}
```

In `golden_queries.yaml`, `expected_tool_calls` entries may use either `tool:` or `name:` for the tool name — the runner's `score_response_v2` accepts both keys to make YAML authoring readable while keeping the schema-canonical `name` in the actual response.

If the v2 endpoint cannot include the trace inline (e.g. SSE streaming in W5), it MUST expose `GET /api/chat/v2/trace/{request_id}` for the runner to fetch post-hoc.

---

## Aggregating runs

Output of each run is appended to `tests/eval/baselines/`. File naming:

- `YYYY-MM-DD-v1-baseline.md` — v1 single-shot scoring
- `YYYY-MM-DD-v2-prompt-N.md` — v2 with prompt iteration N (W6+)
- `YYYY-MM-DD-v2-claude.md` — v2 after provider swap

Each file contains:

1. Run metadata (date, command, endpoint, total queries, model)
2. Summary row (overall pass rate, per-dimension breakdown)
3. Per-section breakdown (by `notes` tag — F-01, F-11, Sally, etc.)
4. Top 10 failures (query + expected + got + which dimension failed)
5. Comparison delta vs previous baseline (for runs after the first)

---

## Testing patterns (W8)

Direct unit tests for agent tools live in `tests/api/test_tool_<name>.py` (one file
per `api/agent/tools/<name>.py`). Each file mocks the tool's external dependencies
at the source — for `search_products` and `search_stores`, that means
`api.routes.chat._run_product_search` / `_run_store_search`. Shared mock setup
(AsyncMock SQLAlchemy session, the `tool_context` kwargs dict, an `httpx.AsyncClient`
wired to the FastAPI app with default overrides) lives in `tests/api/conftest.py`
and `tests/conftest.py`. Tests do not redefine those fixtures. The eval harness
above complements unit tests by exercising the full agent loop against a deployed
backend — never substitute one for the other.
