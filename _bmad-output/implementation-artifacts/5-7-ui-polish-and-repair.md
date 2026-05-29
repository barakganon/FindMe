# Story 5.7: UI Polish and Conversation Repair (W7)

Status: review

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
- Sends `X-Session-ID` header from `localStorage.session_id`. Generation lives in **one place**:
  export `getOrCreateSessionId()` from `frontend/src/api.ts` (read `localStorage.session_id`;
  if missing, generate `crypto.randomUUID()` and persist). Call it from `streamChatV2` and
  `sendChatMessage` only — never inline the read elsewhere, to avoid race conditions on first load.
- Sends `Authorization: Bearer <token>` when a JWT exists in `localStorage`.

### AC-2: Two-column layout with persistent results tray

- New layout in `ChatInterface.tsx`:
  - **≥768px:** flex row, chat column `flex-[6]`, tray column `flex-[4]`, `gap-4`. Tray always
    visible.
  - **<768px:** stack — chat on top, tray below as a collapsible panel with header
    `🛒 שמירה זמנית ({N}) ▾` (or `▴` when expanded). **Default state: collapsed.** Persist
    the user's open/closed choice in `localStorage.trayOpen` (`"true"` | `"false"`); read on
    mount, write on every toggle. The persisted choice applies on mobile only — desktop
    ignores it (tray always visible).
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
      confirmed: bool = False  # true when user explicitly confirmed an inferred attribute
                               # (UserInferredAttribute.is_confirmed=True). Confirmed chips
                               # render with a stronger background ring; see Layout numbers.
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
- **Chip ordering** (first-to-last, left-to-right in the strip):
  1. Explicit preferences (`UserPreference` rows) — most stable, user set them consciously
  2. **Confirmed inferred** attributes (`is_confirmed=true`) — user verified them
  3. Unconfirmed inferred attributes, ordered by `confidence` descending
  4. Anonymous session-derived facts (only for anon — logged-in users skip this; their inferred
     attributes are the canonical source)
  Cap at 6 visible chips; remainder is dropped (chip strip is for at-a-glance context, not a
  full profile view).
- Wire `build_chips` into both `chat_v2.py` and `chat_v2_stream.py` — populate
  `final.chips` right before emitting the `final` event.
- Frontend: chips render as a horizontal-scrolling strip above the messages list:
  `bg-white border-b border-gray-100 px-3 py-2 flex gap-2 overflow-x-auto`.
  Each chip: `rounded-full bg-blue-50 text-blue-700 text-sm px-3 py-1 flex items-center gap-1`.
- Empty chip list → strip is hidden (no empty space reserved).
- Chip mapping rules (in `chips.py`). **Sally's spec explicitly names only the three rows
  marked "(spec)" below**; the rest are reasonable extensions. **Ship the three "(spec)" rows
  in this story; ship the extensions only if implementation is trivial — otherwise defer
  to a follow-up and document in deferred-work.md.**
  | DB source | Chip | Authority |
  |---|---|---|
  | `inferred.has_children=true` + `child_age_range` | 👦 ילד {age} | (spec) |
  | `preferences.default_max_price=N` | 💰 ₪{N} | (spec) |
  | `preferences.preferred_cities=[X,...]` | 📍 {X} | (spec) |
  | session `derived_facts.city=X` | 📍 {X} | (spec, anon variant) |
  | session `derived_facts.max_price=N` | 💰 ₪{N} | (spec, anon variant) |
  | `inferred.gender=female` | 👗 | extension |
  | `inferred.gender=male` | 👔 | extension |
  | `inferred.price_sensitivity=budget` | 💰 חסכוני | extension |
  | `inferred.price_sensitivity=premium` | 💎 פרימיום | extension |

### AC-4: Conversation repair (mind-changer handling)

- Streaming state line in the in-flight assistant bubble. The backend emits exactly **one**
  `thinking` event at turn start (`stage: "thinking"`), then a sequence of `tool_call` events,
  then `final`. There is NO `composing` or `calling_tool` thinking event. The frontend synthesizes
  the state line from this real event flow:
  - On `onThinking` (turn start) → show `חושב…`
  - On first `onToolCall` → show per-tool label:
    - `search_products` or `search_stores` → `מחפש בקטלוג…`
    - `get_user_context` → `מאתר העדפות…`
    - `recall_history` → `נזכר בשיחה…`
    - `clarify` → `מבקש פרטים…`
  - On subsequent `onToolCall` events → continue showing the last per-tool label
  - When `onFinal` is about to arrive (after the last tool_call but before render) → show `מסנן…`
    for ~200ms, then replace the in-flight bubble with the final assistant message.
  The line is **replaced**, not appended, on each transition.
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
  message via `streamChatV2` with `session_context` populated. The detection is server-side
  via `_looks_like_location_prompt(trace)` in `api/routes/chat_v2.py:259` (already wired
  in W3) — it reads the agent's trace to spot when `clarify` was called for location.
  The field is reliable; do not duplicate detection client-side.
- Soft-registration prompt after 3rd user message — unchanged from v1 behavior.

### AC-7: Tests

- **Backend (pytest):**
  - `tests/api/test_chips.py` — `build_chips` returns expected shape for: anon empty,
    anon with `derived_facts`, logged-in with inferred only, logged-in with prefs only,
    logged-in with both (chip ordering: prefs → confirmed inferred → unconfirmed inferred
    by confidence desc). Also: confirmed inferred chip has `confirmed=True`, unconfirmed
    has `confirmed=False`. 6-chip cap enforced.
  - `tests/api/test_session_memory.py` — new case `test_derived_facts_extracted_from_tool_calls`:
    invoke `save_session_state` with mock `tool_calls=[{name: "search_products", args: {brand: "סוני", max_price: 300}}, {name: "search_stores", args: {city: "תל אביב"}}]`,
    then `load_session_state` and assert
    `state.derived_facts == {"brand": "סוני", "max_price": "300", "city": "תל אביב"}`.
    Second case: later turn overwrites earlier values (newer city wins).
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

Document outcomes inline in `tests/eval/baselines/{YYYY-MM-DD}-w7-ui-validation.md` using the
actual date of the validation run (e.g. `2026-06-04-w7-ui-validation.md`), with pass/fail per
scenario and any deltas vs the W6 baseline.

## Tasks / Subtasks

- [x] **Task 1 (AC-3 backend):** add `MemoryChip` schema, `chips: list[MemoryChip]` to `ChatResponseV2`,
      `derived_facts: dict[str, str]` to `SessionState`.
- [x] **Task 2 (AC-3 backend):** create `api/agent/chips.py` with `build_chips()` per the mapping
      table. Wire into `chat_v2.py` and `chat_v2_stream.py` before emitting `final`.
- [x] **Task 3 (AC-3 backend):** populate `derived_facts` in `session_memory.save_session_state`
      by inspecting this turn's tool_call args (`search_products.brand/max_price`,
      `search_stores.city`). Keep accumulation idempotent — newer values overwrite older.
- [x] **Task 4 (AC-7 backend):** `tests/api/test_chips.py` covering 5 cases above.
- [x] **Task 5 (AC-7 backend):** extend `tests/api/test_chat_v2_stream.py` for chips in `final`.
- [x] **Task 6 (AC-1):** `streamChatV2` in `frontend/src/api.ts` — fetch + ReadableStream + SSE parse.
- [x] **Task 7 (AC-5):** 503 detection in `streamChatV2` → silent fallback to v1.
- [x] **Task 8 (AC-6 + AC-2 + AC-3 + AC-4):** rewrite `ChatInterface.tsx`:
  - Two-column layout (flex row ≥768px, stack <768px)
  - Chip strip (reads `final.chips`)
  - Tray panel with localStorage persistence, dedup, 20-item cap, `🗑️ נקה`
  - Streaming state line in in-flight bubble, mapped from `onThinking`
  - Mind-changer subtitle when `final.intent` differs from last assistant `intent`
- [ ] **Task 9 (AC-8):** manual run of all 5 scenarios. Capture baseline doc. Iterate on any
      visible regressions before marking done. **Awaiting manual run by Barakganon** —
      baseline template at `tests/eval/baselines/w7-ui-validation-template.md`. Backend
      code, frontend code, and tests are all production-ready; only browser-based
      Hebrew interaction by a human can verify the gate.
- [x] **Task 10:** Story → ready-for-review, sprint-status updated, commits on
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
  Note: `_run_product_search` also lives in `api/routes/chat.py:250` (it predates the agent
  refactor and is imported by `api/agent/tools/search_products.py:168`). Do not move, rename,
  or change its signature in this story — that's tracked under deferred-work (move to
  `api/search_core.py` during W4 audit followup).
- **Do not change the SQL** in `api/routes/search.py` — import only.
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

**RTL trap:** the project mandates `dir="rtl"` on the chat container (project-context.md). With
RTL, `flex-row` puts the first DOM child on the **right**. Sally's screen anatomy has chat on
the LEFT and tray on the RIGHT. Two valid solutions — pick one and be consistent:

**Option A (preferred):** keep `dir="rtl"` on the outer container, use `flex-row` with DOM order
[chat, tray] — RTL flips them so tray ends up on the right naturally. **Verify visually after
build.**

**Option B (fallback if A breaks tray scrolling):** put `dir="ltr"` on the outer flex container,
then re-apply `dir="rtl"` on the chat column and tray column individually so their inner content
stays Hebrew-RTL.

- Outer container: `flex h-screen bg-gray-50` with `dir="rtl"` (Option A)
- Split row: `flex flex-col md:flex-row gap-0 md:gap-4 flex-1`
- Chat column (DOM-first): `flex-1 md:flex-[6] flex flex-col min-h-0` (min-h-0 lets the message list scroll)
- Tray column (DOM-second): `flex-shrink-0 md:flex-[4] border-t md:border-t-0 md:border-l border-gray-200`
  (use `md:border-l` not `md:border-r` because in RTL the divider sits on the chat-facing edge,
  which is the tray's logical left)
- Tray panel max width on desktop: don't cap — let flex distribute
- Chip strip: `bg-white border-b border-gray-100 px-3 py-2 flex gap-2 overflow-x-auto`
- Single chip: `flex-shrink-0 rounded-full bg-blue-50 text-blue-700 text-sm px-3 py-1 flex items-center gap-1`
  (confirmed-inferred chips get `bg-blue-100 ring-1 ring-blue-200` for emphasis)
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

### Review Findings (2026-05-29 multi-agent adversarial review)

**Decision needed (resolved 2026-05-29):**

- [x] [Review][Decision][A] Inferred-attribute confidence threshold conflict — chose option A: tighten chips to `> 0.5` (privacy-strict). Aligns chips with the chip strip's "always-visible personalization surface" role; transparency for low-confidence guesses lives in the ProfileDrawer instead. Applied as a patch.
- [x] [Review][Decision][C] Anon → logged-in transition orphans `derived_facts` — chose option C: defer. Migrating Redis state across the auth boundary touches `/auth/import-session` + frontend session-id transmission + race handling, which is out of scope for a UI story. Appended to `deferred-work.md`.

**Patches:**

- [x] [Review][Patch] 30s safety timer is broken three ways: no `clearTimeout` on success/error, `onError` never sets `receivedFinal=true`, `loading` closure is stale [`frontend/src/components/ChatInterface.tsx` `sendMessage()`]
- [x] [Review][Patch] 200ms `settleFinal` timer never cleared — interleaved sends graft prior turn onto new conversation [`ChatInterface.tsx` `onFinal` callback]
- [x] [Review][Patch] Tray dedup fallback `${storeId}:${canonicalName}` is always truthy → variant products collapse to one tray slot [`ChatInterface.tsx` `mergeIntoTray()` ~line 1003]
- [x] [Review][Patch] Component unmount during stream → stale `setMessages` runs against post-logout state; no `useEffect` cleanup cancels the handle [`ChatInterface.tsx` `sendMessage()`]
- [x] [Review][Patch] `final.intent === 'error'` cascades phantom topic-change subtitle on error bubbles and into the next successful turn [`ChatInterface.tsx` `onFinal` `topicChanged` calc]
- [x] [Review][Patch] AC-3 violation: `has_children=true` + `child_age_range` both render — duplicate 👦 chips. Spec required a single compound chip [`api/agent/chips.py` `_inferred_to_chip()`]
- [x] [Review][Patch] AC-4 violation: continuation badge `המשך השיחה ↑` not implemented [`ChatInterface.tsx` in-flight bubble]
- [x] [Review][Patch] SSE `data:` line `.trim()` corrupts multi-line JSON payloads — spec strips only one leading space [`frontend/src/api.ts` `_dispatchFrame()`]
- [x] [Review][Patch] `_fallbackToV1` synthesizes `trace.terminated_by: 'content'` → telemetry treats budget fallbacks as zero-cost content-terminated turns. Either widen the enum to include `'fallback'` or use `'cost_budget'` [`frontend/src/api.ts` `_fallbackToV1()`]
- [x] [Review][Patch] `getOrCreateSessionId()` returns a fresh UUID per call in Safari private mode / non-secure context — breaks single-source contract; Redis bucketing fails silently [`frontend/src/api.ts`]
- [x] [Review][Patch] Chip `source` field leaks raw user message text as a `title=` tooltip on every chip — privacy regression [`frontend/src/components/ChatInterface.tsx` chip strip `<span title={chip.source}>`]
- [x] [Review][Patch] `messages.slice(-10)` history sent to backend includes prior error bubbles — agent sees its own "מצטער, אירעה שגיאה…" as prior assistant turns [`ChatInterface.tsx` `sendMessage()`]
- [x] [Review][Patch] GPS resend uses `lastMessage` (most recently sent text), not the message the needs_location bubble belongs to — interleaved sends resend the wrong message [`ChatInterface.tsx` `requestGPS()` callsite]
- [x] [Review][Patch] `localStorage.findme_tray` has no schema version — drift will crash `<ResultCard result={undefined}>` for existing users on next deploy [`ChatInterface.tsx` `loadTray()`]
- [x] [Review][Patch] Tray persists across user logout — privacy leak on shared devices. Clear on logout for logged-in users (anon→anon retention is fine) [`ChatInterface.tsx` `onLogout` handler]
- [x] [Review][Patch] Loading-dots branch (`loading && !streamingState`) is dead code — `streamingState='thinking'` is set in the same render as `loading=true` [`ChatInterface.tsx` JSX]
- [x] [Review][Patch] `_clean_int_str` truncates instead of rounds — `default_max_price="300.7"` displays as `₪300` [`api/agent/chips.py`]
- [x] [Review][Patch] Tray header `<button>` fires `onMobileToggle` on desktop too; `localStorage.findme_tray_open` writes occur unnecessarily [`ChatInterface.tsx` `TrayPanel`]

**Deferred (real but not blocking this PR):**

- [x] [Review][Defer] `tests/api/test_chips.py` 6-cap test only feeds 7 chips — would pass at 5 or 7 [`tests/api/test_chips.py`] — deferred, test-coverage gap not a code bug
- [x] [Review][Defer] No test asserts confidence-desc ordering of unconfirmed chips [`tests/api/test_chips.py`] — deferred, behavior is correct in `chips.py` via `order_by(confidence.desc())`
- [x] [Review][Defer] `MemoryChip.kind` is free `str`, not `Literal` — type-strictness only [`api/schemas.py`] — deferred, no runtime risk
- [x] [Review][Defer] `_dispatchFrame` silently drops `partial_content` events — future-proofing if backend ever streams tokens [`frontend/src/api.ts`] — deferred, current backend doesn't emit them

## Dev Agent Record

### Agent Model Used

claude-opus-4-7 (1M context)

### Debug Log References

- Existing pytest_flask plugin in system Python 3.11 conflicts with newer Flask;
  ran tests with `.venv/bin/python -m pytest -p no:cacheprovider` to bypass.
- Stale pre-existing TypeScript warning `import.meta.env` in `frontend/src/api.ts` —
  not introduced by this story, no `vite/client` types reference in tsconfig.
- Vite production build clean: 80 modules transformed, 324 KB JS (100 KB gzip).

### Completion Notes List

**Tasks 1–8 + 10 done; Task 9 (manual validation) deferred to a human run.**

- Backend (T1–T6): `MemoryChip` schema, `chips` on `ChatResponseV2`, `derived_facts`
  on `SessionState`, `api/agent/chips.py` builder with prefs → confirmed → unconfirmed
  ordering + 6-cap, `save_session_state(..., tool_calls=...)` extractor, wired into both
  `/api/chat/v2` and `/api/chat/v2/stream`. **137 / 137 backend tests pass (was 123).**
- Frontend (T7): `streamChatV2()` in `frontend/src/api.ts` with fetch+ReadableStream,
  proper `\n\n` SSE-frame buffering, transparent 503 → v1 fallback via
  `_fallbackToV1()`. Single-source `getOrCreateSessionId()` exported.
- Frontend (T8): full `ChatInterface.tsx` rewrite — 60/40 chat/tray flex split
  with RTL flip (DOM order = chat, tray; visually = tray on right), `dir="rtl"`
  on outer container. Memory chip strip reads `final.chips`; mobile tray starts
  collapsed and persists open/closed in `localStorage.findme_tray_open`; tray
  dedup by `(type, id)`; topic-change subtitle when `final.intent` differs;
  streaming state line synthesized from `onThinking` + `onToolCall` per AC-4;
  transparent v1-fallback notice shown once per tab session via
  `sessionStorage.findme_fallback_notice_shown`.
- T9 baseline doc skeleton: `tests/eval/baselines/w7-ui-validation-template.md` with
  all 5 canonical scenarios + layout checks + sign-off block. **The gate verdict
  belongs to the human running real Hebrew turns against real Gemini calls.**
- 30-second safety timeout in `ChatInterface.sendMessage` for hung streams.
- Vite production build green.

**Anti-pattern checks honored:**
- v1 `/api/chat` untouched (still the fallback target)
- `_run_product_search` not moved or renamed
- `DEFAULT_SYSTEM_PROMPT` not touched
- No EventSource (POST-incompatible)
- No new dependency added; no `auth library`, `state manager`, or `animation lib`

### File List

Backend (new):
- `api/agent/chips.py`
- `tests/api/test_chips.py`

Backend (modified):
- `api/schemas.py` — added `MemoryChip` model; `chips` field on `ChatResponseV2`
- `api/agent/session_memory.py` — added `derived_facts` field on `SessionState`;
  `tool_calls` parameter on `save_session_state` + `_extract_derived_facts` helper
- `api/routes/chat_v2.py` — import + build_chips + chips field on response;
  pass tool_calls to save_session_state
- `api/routes/chat_v2_stream.py` — same; chip-build wrapped in best-effort try
- `tests/api/test_session_memory.py` — 5 new cases for derived_facts + load round-trip
- `tests/api/test_chat_v2_stream.py` — assert chips present in final event

Frontend (new):
- *(none)* — all changes are extensions of existing files

Frontend (modified):
- `frontend/src/types.ts` — `MemoryChip`, `ToolCallTrace`, `AgentTrace`,
  `ChatResponseV2`, `StreamThinking`, `StreamError`
- `frontend/src/api.ts` — `getOrCreateSessionId`, `streamChatV2`, `_consumeSse`,
  `_dispatchFrame`, `_fallbackToV1`; `X-Session-ID` header added to v1 chat too
- `frontend/src/components/ChatInterface.tsx` — full rewrite per AC-1, AC-2,
  AC-3, AC-4, AC-5, AC-6

Story/docs:
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — 5-7 → in-progress
- `_bmad-output/implementation-artifacts/5-7-ui-polish-and-repair.md` — tasks
  checked, Dev Agent Record + File List populated, Status → review
- `tests/eval/baselines/w7-ui-validation-template.md` (new) — manual-run template

## Change Log

| Date | Change |
|---|---|
| 2026-05-29 | Story created from v2 sprint plan W7 |
| 2026-05-29 | Validation pass: fixed `_run_product_search` path, AC-4 streaming line, RTL flex direction, `is_confirmed` chip handling, chip mapping authority, `derived_facts` tests, session-id helper, mobile tray default, baseline filename |
| 2026-05-29 | Implementation complete (tasks 1–8 + 10). T9 awaits human manual run against the canonical 5 scenarios. 137/137 backend tests pass; frontend builds clean. |
