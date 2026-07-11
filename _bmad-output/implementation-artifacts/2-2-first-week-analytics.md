# Story 2.2 — First-Week Analytics Pass

> Drafted 2026-07-11 (autonomous, pre-launch). This is the analysis story referenced
> as "Epic 2.2" throughout the Epic 6 plan and sprint-status (6.5 depends on it).
> It cannot run until Story 6.5 (soft-launch) has produced at least a week of real
> `agent_traces` rows. This doc specs the queries so they're ready to execute the
> day traffic exists, instead of designing them under time pressure.

## Data source (verified against code)

All v2 chat turns are recorded in the `agent_traces` table (migration
`db/migrations/versions/0009_agent_traces.py`), written best-effort from
`_record_trace()` in `api/routes/chat_v2.py:236`. **This is the only telemetry
store** — there is no separate events/analytics table. Columns actually available:

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `session_id` | TEXT | groups turns within a Redis session (2h TTL) |
| `user_id` | UUID NULL | null for anonymous users |
| `message` | TEXT | raw user message (Hebrew/English free text) |
| `intent` | TEXT | from the agent loop's intent field |
| `tool_calls` | JSONB | array of `{name, args, duration_ms, error, result_count}` |
| `iterations` | INT | agent loop iteration count for the turn |
| `total_latency_ms` | FLOAT | full turn latency |
| `total_cost_usd` | NUMERIC(10,6) | per-turn LLM cost |
| `terminated_by` | TEXT | e.g. cost budget fallback vs normal completion |
| `voucher_network` | TEXT | default `'buyme'` |
| `created_at` | TIMESTAMPTZ | indexed DESC |

Indexes: `created_at DESC`, `(user_id, created_at DESC)` partial, `intent`. No index
on `session_id` — queries grouping by session should filter by `created_at` range
first to keep scans bounded.

**Caveat that must be stated up front, not discovered mid-analysis:** insertion is
best-effort and swallows failures (`except Exception: logger.warning(...)`, see
`chat_v2.py:276`). Any metric derived from `agent_traces` is a **lower bound** on
real traffic, not a ground truth — if Redis/DB hiccups happened, some turns are
silently missing. Note this caveat in the actual analytics writeup.

There is **no click-tracking table**. "Conversations-to-link-tap" is not directly
observable from `agent_traces` alone — see that metric's section below for what's
actually derivable vs what would need new instrumentation.

## Metrics and their queries

### 1. Intent distribution

```sql
SELECT intent, COUNT(*) AS turns, COUNT(*) * 100.0 / SUM(COUNT(*)) OVER () AS pct
FROM agent_traces
WHERE created_at >= now() - interval '7 days'
GROUP BY intent
ORDER BY turns DESC;
```

### 2. Tool-call success rate

`tool_calls` is a JSONB array of objects with an `error` field (null/absent on
success). Unnest and count:

```sql
SELECT
  tc->>'name' AS tool_name,
  COUNT(*) AS calls,
  COUNT(*) FILTER (WHERE tc->>'error' IS NULL) AS successes,
  ROUND(100.0 * COUNT(*) FILTER (WHERE tc->>'error' IS NULL) / COUNT(*), 1) AS success_pct
FROM agent_traces, jsonb_array_elements(tool_calls) AS tc
WHERE created_at >= now() - interval '7 days'
GROUP BY tc->>'name'
ORDER BY calls DESC;
```

### 3. Latency p95

```sql
SELECT
  percentile_cont(0.95) WITHIN GROUP (ORDER BY total_latency_ms) AS p95_latency_ms,
  percentile_cont(0.50) WITHIN GROUP (ORDER BY total_latency_ms) AS p50_latency_ms,
  COUNT(*) AS n
FROM agent_traces
WHERE created_at >= now() - interval '7 days';
```

Break out by `intent` too (same query, `GROUP BY intent`) — the eval harness already
distinguishes intents, worth checking whether e.g. `search_products` turns are
slower than `clarify` turns.

### 4. Conversations-to-link-tap

**Not directly measurable today.** `agent_traces` records what the agent *did*
(tool calls, results returned) but not what the *user clicked* in the frontend —
there is no click/impression event pipeline. What's derivable as a **proxy**:

```sql
-- Proxy: sessions whose last recorded turn included non-empty product/store
-- tool results (i.e. the agent surfaced a link-bearing result), as a fraction
-- of all sessions. This measures "got to a result", not "tapped a link".
WITH session_last_turn AS (
  SELECT DISTINCT ON (session_id) session_id, tool_calls, created_at
  FROM agent_traces
  WHERE created_at >= now() - interval '7 days'
  ORDER BY session_id, created_at DESC
)
SELECT
  COUNT(*) AS sessions,
  COUNT(*) FILTER (
    WHERE EXISTS (
      SELECT 1 FROM jsonb_array_elements(tool_calls) tc
      WHERE (tc->>'name') IN ('search_products', 'search_stores')
        AND COALESCE((tc->>'result_count')::int, 0) > 0
    )
  ) AS sessions_with_results
FROM session_last_turn;
```

True conversations-to-link-tap requires a frontend click event (e.g. `POST
/api/events/link-tap` or a query-param-tagged outbound link) that doesn't exist
yet. **Flag this as a finding, not a blocker**: ship the proxy metric for the
first-week pass, and open a fast-follow story if the soft-launch kill gate
(`≥4 of 5 friends tap a result link`, per `epic-6-deploy-launch-plan.md`) needs
harder data than manual observation during the 6.5 soft-launch itself provides.

## Scope (in)

- Run the four queries above against prod `agent_traces` after ≥7 days of 6.5
  soft-launch traffic.
- Write up findings (a markdown doc, not code) with the lower-bound caveat stated.
- Feed findings into ordering Epic 3 (data-quality phase 2) per the epic-6 plan's
  explicit instruction: "order it by what the 6.5 analytics actually surface, not
  by guess."

## Scope (out)

- Building a click-tracking pipeline for true link-tap measurement — note as a
  fast-follow, don't build it inside this story.
- Any dashboarding/BI tool — raw SQL + a written summary is sufficient for a
  5–10-user soft launch.

## Dependencies

- Hard block: Story 6.5 (soft-launch) must have run and accumulated ≥1 week of data.
- Soft dependency: Story 6.4's monitoring should confirm `agent_traces` inserts
  aren't silently failing at a high rate before trusting the numbers.
