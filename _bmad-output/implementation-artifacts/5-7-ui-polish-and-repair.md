# Story 5.7: UI Polish and Conversation Repair (W7)

Status: ready-for-dev

> **Source:** [findme-v2-sprint-plan.md](../planning-artifacts/findme-v2-sprint-plan.md) — Week 7.
> The agentic backend has been live since W5: `POST /api/chat/v2/stream` emits SSE events
> (`thinking` → `tool_call` → `final`), session memory persists 2h in Redis, cost guard +
> invite allowlist gate access. The frontend (`ChatInterface.tsx`) still talks to v1 `/api/chat` —
> single column, no streaming, no tray, no chips. W7 ships the new UI per Sally's screen-anatomy
> spec and verifies the **Mind-Changer** canonical scenario.
>
> **Gate question (W7):** Does the mind-changer scenario survive?
>
> **Definition of survival:** A user types `אופנה → אוכל → מתנה לאמא` across three turns.
> The agent does not lose memory, the tray accumulates without contradiction, and the active
> topic stays clear. Manual run against Scenario 5 in the v2 sprint plan passes.

## Scope

**In scope:**
- Rewrite `ChatInterface.tsx` to consume `/api/chat/v2/stream` via `fetch` + `ReadableStream`
- Persistent results tray (60/40 chat/tray on ≥768px; stacks on mobile)
- Memory chip strip above the chat column
- Conversation repair UX (mind-changer scenario)
- Backend: add `chips: list[Chip]` to `ChatResponseV2` + extend `SessionState` with derived facts
- Cost-guard fallback: on `503` from `/v2/stream`, transparently call `/api/chat` (v1)
- Manual validation against all 5 canonical scenarios

**Out of scope (defer):**
- Token-level partial LLM streaming (backend doesn't yet emit `partial_content` events — keep `thinking` → `tool_call` → `final` contract). See [deferred-work.md].
- Render/Vercel deploy of the rebuilt frontend (W9 deploy hardening).
- `@reference` autocomplete in the input — UI hook only, full reference resolution defers.
- Drag-to-reorder, swipe-to-remove on tray items — tap-to-open + manual clear only.
- Theme switching, animations longer than 200ms, onboarding tour, settings page.

## Acceptance Criteria

### AC-1: SSE client wired to `/api/chat/v2/stream`

- `frontend/src/api.ts` gets a new exported function `streamChatV2(body, callbacks)` using
  `fetch` + `body.getReader()` (NOT `EventSource` — it's GET-only and we POST).
- Callbacks: `onThinking({stage, tool?})`, `onToolCall({name, args, result_count, duration_ms})`,
  `onFinal(ChatResponseV2)`, `onError(error)`. The function returns a `cancel()` handle.
- Parses SSE frames: split on `\n\n`, extract `event:` and `data:` lines, JSON-decode `data`.
- Sends `X-Session-ID` header from `localStorage.session_id` (generate UUID on first load,
  persist forever) so the backend can derive session memory for anonymous users.
- Sends `Authorization: Bearer <token>` when a JWT exists in `localStorage`.

### AC-2: Two-column layout with persistent results tray

- New layout in `ChatInterface.tsx`:
  - **≥768px:** flex row, chat column `flex-[6]`, tray column `flex-[4]`, `gap-4`.
  - **<768px:** stack — chat on top, tray below (collapsible header `🛒 שמירה זמנית (N)`).
- Tray data model: `trayItems: Array<{type: 'product'|'store', addedAt: number, item: ProductResult | StoreResult}>`.
- Tray accumulation rule: on every `onFinal`, merge `final.product_results` and `final.store_results`
  into `trayItems`, deduping by `item.id`. Cap at 20 items total — drop oldest when over.
- Tray persists in `localStorage.tray` (JSON, capped at 20). Cleared via tray header `🗑️ נקה`.
- Each tray item shows: image (if `image_url`), name (line-clamp-2), price or "מחיר לא זמין",
  store name, tap-to-open external link (`product_url` or `buyme_url`).
- Empty state: `אין עדיין מועדפים — חיפושים יישמרו כאן`.

### AC-3: Memory chip strip

- Backend: add to `api/schemas.py`:
  ```python
  class MemoryChip(BaseModel):
      icon: str           # emoji, e.g. "👦", "💰", "📍"
      label: str          # Hebrew, e.g. "ילד 3", "₪300", "תל אביב"
      kind: str           # "inferred" | "preference" | "session"
      source: Optional[str] = None  # the message/value that triggered it
  ```
- Add `chips: list[MemoryChip] = Field(default_factory=list)` to `ChatResponseV2`.
- Add `derived_facts: dict[str, str] = field(default_factory=dict)` to
  `api/agent/session_memory.SessionState` — keys: `city`, `max_price`, `child_age_range`, etc.
- New helper `api/agent/chips.py` with `build_chips(current_user, session_state, db) -> list[MemoryChip]`:
  - For logged-in users: query `user_inferred_attributes` where `confidence >= 0.5`, plus
    `user_preferences` for `default_max_price`, `preferred_cities`. Map each to a chip.
  - For anonymous users: read `session_state.derived_facts` (synthesized in the chat route
    from this turn's `tool_calls[*].args` — e.g. `search_products.brand`, `search_products.max_price`,
    `search_stores.city`).
- Wire `build_chips` into both `chat_v2.py` and `chat_v2_stream.py` — populate
  `final.chips` right before emitting the `final` event.
- Frontend: chips render as a horizontal-scrolling strip above the messages list:
  `bg-white border-b border-gray-100 px-3 py-2 flex gap-2 overflow-x-auto`.
  Each chip: `rounded-full bg-blue-50 text-blue-700 text-sm px-3 py-1 flex items-center gap-1`.
- Empty chip list → strip is hidden (no empty space reserved).
- Chip mapping rules (in `chips.py`):
  | DB source | Chip |
  |---|---|
  | `inferred.has_children=true` + `child_age_range` | 👦 ילד {age} |
  | `inferred.gender=female` | 👗 |
  | `inferred.gender=male` | 👔 |
  | `inferred.price_sensitivity=budget` | 💰 חסכוני |
  | `preferences.default_max_price=N` | 💰 ₪{N} |
  | `preferences.preferred_cities=[X,...]` | 📍 {X} |
  | session `derived_facts.city=X` | 📍 {X} |
  | session `derived_facts.max_price=N` | 💰 ₪{N} |

### AC-4: Conversation repair (mind-changer handling)

- Streaming state line in the in-flight assistant bubble:
  `חושב…` → `מחפש בקטלוג…` → `מסנן…` → final content.
  Maps from `onThinking({stage, tool})` events. The line is replaced (not appended) on each event.
- When the user sends a new message **while** the previous turn's results are still in the tray
  (i.e., tray is non-empty and `messages.length > 2`):
  - The new in-flight assistant bubble shows a thin badge above it: `המשך השיחה ↑`.
  - Tray items from prior turns are NOT cleared — accumulation only.
  - On `onFinal`, if `final.intent` differs from the last assistant entry's `intent`, the new
    assistant bubble gets a small subtitle: `החלפת נושא? התוצאות הקודמות עדיין שמורות במגש.`
- No "restart conversation" button — repair is implicit. The escape hatch is `🗑️ נקה`
  on the tray header (clears tray + `localStorage.tray`; messages stay).

### AC-5: Cost-guard fallback to v1

- `streamChatV2` detects HTTP 503 with body `{error: "...", fallback: "/api/chat"}`. On detection
  it does NOT throw — it transparently re-issues the same logical message via the existing
  `sendChatMessage` (v1 `/api/chat`), then synthesizes a fake `onFinal(v1Response)` so the
  rest of the UI loop is unchanged. v1 lacks SSE, so `onThinking` and `onToolCall` are skipped.
- A subtle inline note appears once per session: `מצב מבוסס במקום סוכן (מגבלת עלות יומית)`,
  styled as `text-xs text-gray-500 italic`, no toast / no modal.

### AC-6: ChatInterface refactor — keep contract, replace internals

- Delete the v1-specific code paths from `ChatInterface.tsx` that won't survive the rewrite:
  inline `sendChatMessage` calls become the **fallback only** (AC-5).
- Keep the props contract (`sessionContext`, `onLocationUpdate`) — `App.tsx` is not touched.
- Keep the welcome message + suggestion chips for the first load (hidden after first message).
- Keep `ProfileDrawer` and the avatar header button.
- Keep `requestGPS` flow — `onFinal.needs_location=true` re-triggers GPS, then resends the
  message via `streamChatV2` with `session_context` populated.
- Soft-registration prompt after 3rd user message — unchanged from v1 behavior.

### AC-7: Tests

- **Backend (pytest):**
  - `tests/api/test_chips.py` — `build_chips` returns expected shape for: anon empty,
    anon with `derived_facts`, logged-in with inferred only, logged-in with prefs only,
    logged-in with both (chip ordering: prefs first, then inferred high→low confidence).
  - `tests/api/test_chat_v2_stream.py` — extend existing tests to assert `final` event
    payload includes a `chips` key (empty for anon-no-tools, populated when `derived_facts`
    are set via tool_calls).
  - All prior 123 tests still pass.
- **Frontend:** no test framework is installed. Manual validation only — see AC-8.

### AC-8: Manual validation against the 5 canonical scenarios

Run all five from the v2 sprint plan against the rebuilt UI. **Scenario 5 (Mind-Changer) is the gate.**

1. **Sarah** — anon, types `יש לי 300 ש"ח, מה אפשר לעשות?`. Agent asks ONE clarifying question.
   Chip `💰 ₪300` lights up after the turn.
2. **Yael** — anon, types `מתנה לבן 3 שלי`. Agent calls `search_products` (kids). Chip
   `👦 ילד 3` appears after turn.
3. **Avi** — anon, three turns adding Sony, Bose, JBL headphones. Tray accumulates 3 items.
   Fourth turn `איזה הכי שקט?` triggers `recall_history`, no new search.
4. **Rinat** — logged in (test user with prior `city_search=תל אביב` history). Types
   `מסעדות כמו פעם שעברה`. Chip `📍 תל אביב` is present pre-turn. Agent calls `recall_history`.
5. **Mind-Changer** (**GATE**) — anon: `אופנה לחורף` → `בעצם, אוכל טוב באזור` (no GPS yet,
   triggers clarify) → `מתנה לאמא עד 200`. Tray accumulates without dropping items; final
   bubble shows the subtitle `החלפת נושא? התוצאות הקודמות עדיין שמורות במגש.` on turn 2 and 3.
   No 500 errors, no message lost.

Document outcomes inline in `tests/eval/baselines/2026-XX-XX-w7-ui-validation.md` (date of
validation), with pass/fail per scenario and any deltas vs the W6 baseline.

## Tasks / Subtasks

- [ ] **Task 1 (AC-3 backend):** add `MemoryChip` schema, `chips: list[MemoryChip]` to `ChatResponseV2`,
      `derived_facts: dict[str, str]` to `SessionState`.
- [ ] **Task 2 (AC-3 backend):** create `api/agent/chips.py` with `build_chips()` per the mapping
      table. Wire into `chat_v2.py` and `chat_v2_stream.py` before emitting `final`.
- [ ] **Task 3 (AC-3 backend):** populate `derived_facts` in `session_memory.save_session_state`
      by inspecting this turn's tool_call args (`search_products.brand/max_price`,
      `search_stores.city`). Keep accumulation idempotent — newer values overwrite older.
- [ ] **Task 4 (AC-7 backend):** `tests/api/test_chips.py` covering 5 cases above.
- [ ] **Task 5 (AC-7 backend):** extend `tests/api/test_chat_v2_stream.py` for chips in `final`.
- [ ] **Task 6 (AC-1):** `streamChatV2` in `frontend/src/api.ts` — fetch + ReadableStream + SSE parse.
- [ ] **Task 7 (AC-5):** 503 detection in `streamChatV2` → silent fallback to v1.
- [ ] **Task 8 (AC-6 + AC-2 + AC-3 + AC-4):** rewrite `ChatInterface.tsx`:
  - Two-column layout (flex row ≥768px, stack <768px)
  - Chip strip (reads `final.chips`)
  - Tray panel with localStorage persistence, dedup, 20-item cap, `🗑️ נקה`
  - Streaming state line in in-flight bubble, mapped from `onThinking`
  - Mind-changer subtitle when `final.intent` differs from last assistant `intent`
- [ ] **Task 9 (AC-8):** manual run of all 5 scenarios. Capture baseline doc. Iterate on any
      visible regressions before marking done.
- [ ] **Task 10:** Story → done, sprint-status updated, commit on
      `feature/w7-ui-polish-and-repair`, PR opened.

## Dev Notes

### Backend contract already in place — DO NOT re-derive

- **SSE event shapes** (from W5 — already implemented in `chat_v2_stream.py`):
  - `event: thinking` — `{stage: "thinking"|"calling_tool"|"composing", tool: name?}`
  - `event: tool_call` — `{name, args, duration_ms, error, result_count}`
  - `event: final` — full `ChatResponseV2` JSON (will gain a `chips` key in this story)
  - `event: error` — `{error: "..."}` on terminal failure
  - **No `partial_content` events yet** — backend awaits the full run_agent call before emitting `final`.
- **Session ID derivation** (from W3 — already implemented in `session_memory.derive_session_id`):
  - Logged-in: `user:{user.id}` (overrides X-Session-ID)
  - Anonymous: `anon:{X-Session-ID header}` — frontend must generate + persist a UUID
  - No header on anon: memory disabled for that turn (degraded but functional)
- **Cost guard** (W5): 503 with `Retry-After` header on overspend. Body has `{error, fallback: "/api/chat"}`.
- **Invite gate** (W5): 403 with reason text when `V2_INVITE_ONLY=true` and user/anon not allowed.
  Frontend behavior on 403: show the assistant error bubble with the returned reason. Do not retry.

### Files to read before touching

- `api/routes/chat_v2_stream.py` — the SSE producer (you're adding `chips` to its `final` event)
- `api/agent/session_memory.py` — `SessionState`, load/save (you're extending with `derived_facts`)
- `api/agent/tools/get_user_context.py` — inferred + prefs query patterns to mirror in `chips.py`
- `api/schemas.py` lines 279–330 — `ToolCallTrace`, `AgentTrace`, `ChatResponseV2` shape
- `frontend/src/components/ChatInterface.tsx` — current welcome + chips + GPS flow to preserve
- `frontend/src/api.ts` — existing `sendChatMessage` (v1 fallback)
- `frontend/src/types.ts` — extend with new `MemoryChip`, `ChatResponseV2`, `ToolCallTrace`, `AgentTrace`
- `frontend/src/components/ResultCard.tsx`, `StoreCard.tsx` — reuse in tray, do NOT clone

### Previous-story intelligence (from 5-6)

- **System prompt is fragile** — Gemini-2.5-flash broke tool-calling when the system prompt
  expanded to ~80 lines in W6. Trimmed back to ~35 lines. **Don't touch `DEFAULT_SYSTEM_PROMPT`
  in this story.** This story is UI-only on the backend side (chips + derived facts).
- Probe queries `?`, `מה?`, `abc` still call `search` instead of `clarify` — not a regression
  this story introduces. Tracked under W6 follow-up.
- Brand re-rank in `search_products` is a stable 3-tier sort. Tray dedup by `item.id` will
  preserve the agent's ranking decisions — do not re-sort tray items by anything else.

### Anti-pattern prevention

- **Do not rewrite `App.tsx`.** Props contract (`sessionContext`, `onLocationUpdate`) is unchanged.
- **Do not add `EventSource`.** It's GET-only. Use `fetch` with `body.getReader()`.
- **Do not cache chat history in Redis.** Conversation history lives in React state.
  Session memory is for tray (`last_product_results` / `last_store_results`) + derived facts only.
- **Do not modify `api/routes/chat.py` (v1).** It stays as the always-available fallback.
- **Do not change `_run_product_search` or the SQL** in `api/routes/search.py` — import only.
- **Do not add a tab switcher, modal, or page route.** Single screen, two columns, tray collapses on mobile.
- **Do not add an auth library, state manager, or animation lib.** React state + `localStorage` only.
- **Do not block the SSE stream awaiting cost / save operations** — `chat_v2_stream.py` already
  wraps them in try/except. Mirror that pattern when adding chip-building.

### LLM token budget — do not raise

- Backend system prompt stays at ~35 lines (W6 baseline). Adding chips data to the response
  does NOT change the agent loop's LLM prompt. Chips are post-loop, route-layer synthesis.
- `get_user_context` `max_tokens` budget is unchanged. We're not calling it more often.

### Trap: `derived_facts` and chip flicker

When `build_chips()` runs **after** `save_session_state` (which writes `derived_facts`), the
chip strip will accurately reflect this turn's facts. If you build chips **before** save,
the strip will lag by one turn. **Build chips AFTER save_session_state**, before yielding
the `final` SSE event.

### Trap: SSE parse boundaries

A single `fetch` chunk may contain multiple SSE events or split one across two chunks. The
`streamChatV2` parser MUST buffer the incoming bytes and only consume up to the last `\n\n`
boundary on each read. Don't assume one `read()` = one event.

```ts
let buffer = ''
while (true) {
  const { done, value } = await reader.read()
  if (done) break
  buffer += decoder.decode(value, { stream: true })
  let idx
  while ((idx = buffer.indexOf('\n\n')) !== -1) {
    const frame = buffer.slice(0, idx)
    buffer = buffer.slice(idx + 2)
    handleFrame(frame)
  }
}
```

### Trap: tray dedup keys

`ProductResult.id` is the `store_products.id` UUID — stable across turns. `StoreResult.id`
is `stores.id` UUID — also stable. Dedup by `(type, id)` tuple so a product and a store with
the same UUID don't collide (different tables, but assume nothing).

### Reuse over rebuild

- `ResultCard` for products in tray (pass `compact` prop if needed — extend ResultCard with
  one prop, do not clone)
- `StoreCard` for stores in tray
- `ProfileDrawer` unchanged — opens from the header avatar
- `getSavedToken`, `saveAuth`, `clearAuth`, `isRegistrationDismissed`, `dismissRegistration`
  from `frontend/src/store/auth.ts` — unchanged

### Hebrew copy reference (for visible text)

| Where | Copy |
|---|---|
| Tray header (items) | `🛒 שמירה זמנית ({N})` |
| Tray header (empty) | `🛒 שמירה זמנית` |
| Tray clear button | `🗑️ נקה` |
| Tray empty state | `אין עדיין מועדפים — חיפושים יישמרו כאן` |
| In-flight states | `חושב…` → `מחפש בקטלוג…` → `מסנן…` |
| Topic-change subtitle | `החלפת נושא? התוצאות הקודמות עדיין שמורות במגש.` |
| Continuation badge | `המשך השיחה ↑` |
| v1 fallback notice | `מצב מבוסס במקום סוכן (מגבלת עלות יומית)` |
| Mobile tray collapsed header | `🛒 שמירה זמנית ({N}) ▾` |

Banned phrases (Sally's voice rules): `אשמח לעזור`, generic call-center politeness. Tone is
"brisk Tel Aviv friend who knows every store and has opinions" — but **this is style for the
agent's `compose`d message, not new copy you write**. The static UI copy above stays neutral.

### Layout numbers (Tailwind)

- Container: `flex h-screen bg-gray-50` (outer), `flex flex-col md:flex-row gap-0 md:gap-4 flex-1`
- Chat column: `flex-1 md:flex-[6] flex flex-col min-h-0` (min-h-0 lets the message list scroll)
- Tray column: `flex-shrink-0 md:flex-[4] border-t md:border-t-0 md:border-r border-gray-200`
- Tray panel max width on desktop: don't cap — let flex distribute
- Chip strip: `bg-white border-b border-gray-100 px-3 py-2 flex gap-2 overflow-x-auto`
- Single chip: `flex-shrink-0 rounded-full bg-blue-50 text-blue-700 text-sm px-3 py-1 flex items-center gap-1`
- Streaming state line: `text-xs text-gray-400 italic mb-1` inside the in-flight assistant bubble

### Testing standards (project-context.md)

- `@pytest.mark.anyio` for async tests; `anyio_backend` fixture is in `tests/conftest.py`
- Never make real Gemini or DB calls — mock at dependency layer using fixtures from `conftest.py`
- Run `pytest tests/` to verify the full suite. Baseline going into this story: **123/123 passing**.
- Each new route or helper needs: happy path, empty path, error path
- For `build_chips`: anon empty, anon with derived_facts, logged-in inferred-only, logged-in prefs-only, logged-in both (ordering)

### Git workflow

- Branch: `feature/w7-ui-polish-and-repair`
- Conventional commits, ≥8 commits across the story (backend chip schema, chip builder, session
  derived_facts, tests for chips, SSE parser, layout shell, tray, chip strip, streaming line,
  fallback path, manual baseline doc).
- PR title: `feat(ui): W7 — UI polish, memory chips, conversation repair (Story 5.7)`
- Merge to master `--no-ff` after PR review.

### References

- [Source: _bmad-output/planning-artifacts/findme-v2-sprint-plan.md — Week 7]
- [Source: _bmad-output/implementation-artifacts/5-5-streaming-and-soft-launch.md — SSE event contract]
- [Source: _bmad-output/implementation-artifacts/5-3-tools-and-memory.md — session memory]
- [Source: _bmad-output/implementation-artifacts/5-6-prompt-iteration.md — prompt fragility]
- [Source: _bmad-output/implementation-artifacts/deferred-work.md — known deferrals]
- [Source: _bmad-output/project-context.md — frontend + backend rules]

## Dev Agent Record

### Agent Model Used

_To be filled by dev agent._

### Debug Log References

### Completion Notes List

### File List

## Change Log

| Date | Change |
|---|---|
| 2026-05-29 | Story created from v2 sprint plan W7 |
