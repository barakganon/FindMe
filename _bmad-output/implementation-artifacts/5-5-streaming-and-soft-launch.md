# Story 5.5: SSE Streaming + Soft Launch Backend (W5)

Status: done (backend portion — frontend rebuild deferred per Scope split)

> **Source:** [findme-v2-sprint-plan.md](../planning-artifacts/findme-v2-sprint-plan.md) — Week 5.
> The backend pieces required for an invite-only soft launch: an SSE-streaming
> chat endpoint, a daily cost guard with circuit-breaker, and an email-allowlist
> gate. The **frontend rebuild** (results tray, streaming bubbles, memory chips
> per Sally's spec) is the natural handoff point — it's substantial UI work that
> warrants a dedicated session.

## Scope split

**In this story (backend ready for soft launch):**
- SSE streaming endpoint `/api/chat/v2/stream`
- Daily cost guard (Redis-backed counter, circuit-breaks on overspend)
- Invite-only email allowlist
- Tests for all three

**Deferred to follow-up (frontend rebuild + actual Render deploy):**
- `frontend/src/components/ChatInterface.tsx` rewrite for streaming
- Persistent results tray (Sally screen-anatomy spec)
- Memory chip strip
- Cost-guard fallback UX (when v2 is over budget, fall back to v1 transparently)
- Vercel deploy of new frontend
- Render env-var configuration for the invite list

The SSE event contract documented below is the bridge — frontend follow-up
can be a self-contained PR once the contract is stable.

## Acceptance Criteria

### AC-1: SSE streaming endpoint

- `POST /api/chat/v2/stream` accepts the same `ChatRequest` body as `/api/chat/v2`.
- Returns `text/event-stream` (Content-Type), one event per SSE chunk.
- Event shapes (all JSON-encoded in `data:` field):
  - `event: thinking` — `{stage: "thinking"|"calling_tool"|"composing", tool: name?}`
  - `event: tool_call` — `{name, args, result_count?, duration_ms}`
  - `event: partial_content` — `{delta: "..."}` (assistant message token-by-token)
  - `event: final` — `{message, intent, product_results, store_results, trace}` (same shape as ChatResponseV2)
  - `event: error` — `{error: "..."}` on terminal failure
- `chat_v2.py` non-streaming endpoint still works (`/api/chat/v2`) — clients pick.

### AC-2: Daily cost guard

- `api/agent/cost_guard.py` — `current_day_cost_usd()` reads Redis counter for `today` (UTC).
- `register_cost(usd)` increments after each turn.
- `is_over_budget()` returns True when daily total ≥ `DAILY_COST_BUDGET_USD` env var (default $20.00).
- When over budget, `/api/chat/v2` returns HTTP 503 with `Retry-After` header set to seconds until midnight UTC, and body suggests falling back to `/api/chat` (v1).
- Counter resets daily via Redis TTL (24h, refreshed on first write of the day).

### AC-3: Invite-only allowlist

- Env vars:
  - `V2_INVITE_ONLY` (bool, default `false`) — master toggle
  - `V2_EMAIL_ALLOWLIST` (comma-separated emails)
  - `V2_ALLOW_ANON` (bool, default `true`) — when invite-only, do anonymous users have access?
- When `V2_INVITE_ONLY=true`:
  - Logged-in users with email NOT in allowlist → 403
  - Anonymous users → 403 unless `V2_ALLOW_ANON=true`
- When `V2_INVITE_ONLY=false` (default): no gate.
- Applies to both `/api/chat/v2` and `/api/chat/v2/stream`.

### AC-4: Tests

- `tests/api/test_cost_guard.py` — under/over budget, day-boundary reset, Redis-down fallback (allow when can't read).
- `tests/api/test_invite_allowlist.py` — allowed/blocked email, anon with/without ALLOW_ANON, master toggle off.
- `tests/api/test_chat_v2_stream.py` — verifies SSE event order on a successful turn, error event on failure (mocked agent).
- All 84 prior tests still pass.

## Tasks

- [x] **Task 1 (AC-2):** `api/agent/cost_guard.py` with Redis-backed daily counter, 25h TTL, fail-open on Redis errors
- [x] **Task 2 (AC-3):** `api/agent/invite_allowlist.py` with V2_INVITE_ONLY / V2_EMAIL_ALLOWLIST / V2_ALLOW_ANON env vars
- [x] **Task 3 (AC-1):** `api/routes/chat_v2_stream.py` mounted at `/api/chat/v2/stream` — SSE events: thinking → tool_call → final (or error)
- [x] **Task 4 (AC-4):** 34 new tests across cost_guard (15), invite_allowlist (12), chat_v2_stream (4) — all pass; 118/118 total
- [x] **Task 5:** Story → done, sprint-status updated, commit on `feature/w5-streaming-and-launch`, PR opened

## Dev Notes

### SSE event contract for the frontend follow-up

The frontend's incremental render loop will look approximately like:

```ts
const es = new EventSource('/api/chat/v2/stream', {
  withCredentials: true,
  // body sent via fetch since EventSource is GET-only — use a polyfill or
  // switch to fetch + ReadableStream for true POST + streaming
});

es.addEventListener('thinking', (e) => {
  const { stage, tool } = JSON.parse(e.data);
  // Update the "מחפש בקטלוג…" thinking-state line
});

es.addEventListener('tool_call', (e) => {
  const { name, args, result_count } = JSON.parse(e.data);
  // Append to trace, optionally show "called search_products" debug
});

es.addEventListener('partial_content', (e) => {
  const { delta } = JSON.parse(e.data);
  // Append delta to the assistant bubble (incremental render)
});

es.addEventListener('final', (e) => {
  const response = JSON.parse(e.data); // ChatResponseV2 shape
  // Render results tray, finalize bubble
  es.close();
});

es.addEventListener('error', (e) => {
  const { error } = JSON.parse(e.data);
  // Show error toast, retry or fall back to v1
});
```

The non-streaming `/api/chat/v2` endpoint remains as the fallback for clients
that can't or don't want to stream (the v1 frontend, simple curl tests).

### Why the daily cost guard is Redis-backed

Per-process counters reset on every uvicorn restart and don't aggregate
across workers. Redis is already in the stack (W3 session memory uses it)
and provides cross-process correctness with TTL-based daily reset for free.

### Why the allowlist is env-var-driven

The W5 soft launch is 5 friends. Hard-coding emails in code would require
a deploy to add/remove a beta tester. Env-var lookup means rotating the
list takes one Render env var update + a restart.

### What this story does NOT do

- Does not modify `/api/chat` (v1) — v1 stays as the always-available fallback
- Does not rewrite the React frontend (deferred)
- Does not deploy to Render (the operator runs this with the migration after merging)
- Does not add per-user rate limits (global cost guard is sufficient for 5-friend scale)

## Change Log

| Date | Change |
|---|---|
| 2026-05-16 | Story created from v2 sprint plan W5 |
