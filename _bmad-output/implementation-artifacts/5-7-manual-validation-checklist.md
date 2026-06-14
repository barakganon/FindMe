# Story 5.7 — Manual Validation Checklist

> **Purpose:** The backend logic (chips, session memory, derived_facts, tray accumulation,
> repair invariants) is covered by automated tests. The items below are the irreducibly
> manual/browser-based checks that require a human running the live app in Hebrew.
>
> **Automated test coverage:** 23 new tests added in `test_session_memory.py`,
> `test_chat_v2_stream.py`, and `tests/api/test_repair.py`. Total suite: 164 tests.
>
> **Environment:** `uvicorn api.main:app --reload` + `cd frontend && npm run dev` + Redis running.
> Use an Incognito/Private window for anonymous-user scenarios.

---

## AC-1: SSE Client + Session-ID wiring

- [ ] **SSE frame boundary handling:** Send a long message that triggers multiple tool calls.
  Verify the streaming state line transitions correctly: `חושב…` → `מחפש בקטלוג…` → `מסנן…`
  → final result (no frozen "thinking" or doubled messages).
- [ ] **X-Session-ID persistence:** Clear `localStorage`, reload, send a message.
  Open DevTools → Network → the POST to `/api/chat/v2/stream` must include
  `X-Session-ID` header. Reload the page; confirm the same UUID is reused (not regenerated).
- [ ] **Auth header on JWT:** Log in, send a message. Confirm `Authorization: Bearer ...`
  header is present in the SSE request.
- [ ] **Cancel handle works:** Start a turn, immediately navigate away or close.
  Confirm no console errors about `setState` on an unmounted component.

## AC-2: Two-column layout + tray

- [ ] **Desktop (≥768px) layout:** Tray column always visible at 40% width alongside chat
  at 60%. Resize browser to 767px — tray collapses into a panel below chat.
- [ ] **Mobile tray default collapsed:** On ≤767px viewport, tray starts collapsed.
  Header shows `🛒 שמירה זמנית (N) ▾`. Tap — expands. Reload — collapse state is remembered
  (`localStorage.trayOpen`). Desktop ignores `localStorage.trayOpen` (always open).
- [ ] **Tray accumulates without dedup across turns:** Do 3 searches returning different
  products. Confirm tray grows to combined count (capped at 20). Refresh page — tray
  still present (from `localStorage.tray`).
- [ ] **Tray item display:** Each card shows image (if present), name (clamp-2),
  price or `מחיר לא זמין`, store name. Tap → opens `product_url` / `buyme_url` in new tab.
- [ ] **Tray empty state:** Clear localStorage, reload. Tray shows
  `אין עדיין מועדפים — חיפושים יישמרו כאן`.
- [ ] **🗑️ נקה button:** Tap — tray empties, `localStorage.tray` cleared.
  Messages in chat remain. Next search repopulates tray.
- [ ] **Dedup by item.id:** Send the same search query twice. Confirm tray doesn't
  accumulate duplicate cards for the same `item.id`.

## AC-3: Memory chip strip

- [ ] **Chip strip hidden when empty:** First load (no session). Confirm no horizontal
  strip / empty space above messages.
- [ ] **Anonymous chip appears after turn:** Send `יש לי 300 ש"ח` → search runs →
  confirm `💰 ₪300` chip appears in the strip above the next message input.
  (Validates the full save→load→build-chips→SSE-final pipeline end-to-end.)
- [ ] **City chip appears for anon:** Send a message triggering `search_stores` with
  `city=תל אביב`. Confirm `📍 תל אביב` chip appears.
- [ ] **Confirmed chip visual ring:** For a logged-in user with a `is_confirmed=true`
  inferred attribute, the chip renders with a stronger background ring vs. unconfirmed chips.
- [ ] **6-chip cap (visual):** Set up a user with >6 preferences/inferred attrs. Confirm
  only 6 chips render in the strip; the rest are silently dropped (no overflow or ellipsis).
- [ ] **Chip strip scrolls horizontally** on small screens when 4+ chips present.

## AC-4: Conversation repair / Mind-Changer (GATE)

This is the gating scenario from the story definition.

- [ ] **Scenario 5 — Mind-Changer (GATE):**
  1. Anonymous, fresh session (Incognito).
  2. Turn 1: type `אופנה לחורף`. Agent searches fashion, returns results. Tray shows items.
  3. Turn 2: type `בעצם, אוכל טוב באזור`. No GPS yet — agent asks clarifying question.
     Tray items from turn 1 still present (not cleared). Assistant bubble shows
     `המשך השיחה ↑` badge. Intent changed → subtitle
     `החלפת נושא? התוצאות הקודמות עדיין שמורות במגש.` appears.
  4. Turn 3: type `מתנה לאמא עד 200`. Agent searches gifts. Tray accumulates (turns 1+3).
     `💰 ₪200` chip appears (overwrites ₪400 from turn 1 — backend merge).
  5. **PASS criteria:** No 500 errors, no lost messages, tray non-empty throughout,
     subtitle appeared on turns 2 and 3, no `חושב…` stuck state.
- [ ] **`המשך השיחה ↑` badge:** Appears on the in-flight assistant bubble when
  `messages.length > 2` and tray is non-empty at turn start.
- [ ] **Intent-change subtitle:** `החלפת נושא? התוצאות הקודמות עדיין שמורות במגש.`
  appears as a small subtitle under the assistant bubble when
  `final.intent` differs from the previous assistant turn's `intent`.
- [ ] **No restart button exists:** Confirm there is NO "restart" or "clear history" button
  in the chat UI. Only `🗑️ נקה` exists on the tray header.

## AC-4b: Streaming state line transitions

- [ ] `onThinking` → shows `חושב…` in the in-flight bubble immediately.
- [ ] First `onToolCall` with `search_products` or `search_stores` → shows `מחפש בקטלוג…`.
- [ ] First `onToolCall` with `get_user_context` → shows `מאתר העדפות…`.
- [ ] First `onToolCall` with `recall_history` → shows `נזכר בשיחה…`.
- [ ] First `onToolCall` with `clarify` → shows `מבקש פרטים…`.
- [ ] Multiple `onToolCall` events: text stays at last-tool label (not appended).
- [ ] After last tool_call, before final: shows `מסנן…` for ~200ms.
- [ ] In-flight bubble is **replaced** (not appended) when final arrives.

## AC-5: Cost-guard fallback to v1

- [ ] Simulate 503: temporarily set `DAILY_COST_BUDGET_USD=0.000001` and send a message.
  Confirm the frontend silently falls back to v1 `/api/chat`. No error toast.
  One-time note `מצב מבוסס במקום סוכן (מגבלת עלות יומית)` appears in `text-xs text-gray-500 italic`.
  Subsequent turns in the same browser session do NOT show the note again.

## AC-6: ChatInterface contract preservation

- [ ] Welcome message + suggestion chips visible on fresh load; hidden after first message.
- [ ] `ProfileDrawer` still opens from the avatar button.
- [ ] GPS flow: trigger a `needs_location=true` response, confirm GPS prompt fires,
  user allows location, the SAME message is automatically re-sent with coordinates.
- [ ] Soft-registration prompt after the 3rd user message (anonymous user).

## AC-8: All 5 canonical scenarios

Document results in `tests/eval/baselines/<YYYY-MM-DD>-w7-ui-validation.md`.

- [ ] **Scenario 1 (Sarah):** Anon `יש לי 300 ש"ח, מה אפשר לעשות?` → agent asks ONE clarifying
  question → `💰 ₪300` chip appears after turn.
- [ ] **Scenario 2 (Yael):** Anon `מתנה לבן 3 שלי` → `search_products` runs → `👦 ילד 3` chip
  appears.  _(Note: `child_age_range` must be extracted via tool args for anon — verify chip
  appears, as this path requires the derived_facts to include a child-age key. **See potential
  bug note below.**)_
- [ ] **Scenario 3 (Avi):** 3 turns adding Sony/Bose/JBL headphones. Tray has 3 items.
  Turn 4 `איזה הכי שקט?` → `recall_history` fires, no new search, tray unchanged.
- [ ] **Scenario 4 (Rinat):** Logged-in test user with prior `city_search=תל אביב`. `📍 תל אביב`
  chip is pre-populated before turn (from DB preferences). `recall_history` is called.
- [ ] **Scenario 5 (Mind-Changer):** See AC-4 gate above.

---

## ⚠ Possible Bug — Scenario 2 Anon Child Chip

**Observed during automated test authoring (not verified in the running app):**

The `_anon_chips()` function in `api/agent/chips.py` only maps `city` and `max_price` from
`derived_facts`. It does NOT handle `child_age_range` as a derived fact.

For Scenario 2 (Yael — `מתנה לבן 3 שלי`), the `👦 ילד 3` chip is expected by the story spec.
However, for an **anonymous** user:
- The logged-in path queries `UserInferredAttribute` rows — which would have `child_age_range`.
- The anonymous path reads `session_state.derived_facts` — which only gets `city`, `max_price`,
  and `brand` from the `_DERIVED_FACT_RULES` list in `session_memory.py`.

There is no rule that extracts `child_age_range` from `search_products.args` (e.g. an arg like
`age_range` or `for_child_age`). The `👦 ילד 3` chip will therefore **NOT appear for anonymous
users** even if the agent internally handles child-gift searches correctly.

**Impact:** Scenario 2 may show no chip, but product search may still work. The chip strip
for anon users is limited to city + price only — the spec row `👦 ילד {age}` for anon is
listed under "logged-in inferred" in the mapping table (not as an anon session-derived fact).

**Action needed:**
- [ ] Manually verify whether Scenario 2 with an **anonymous** user produces `👦 ילד 3` or no chip.
- If no chip appears: confirm with Barak whether AC-3 chip mapping for anon child-age is
  intentionally limited to logged-in users (and update spec), or if a new `_DERIVED_FACT_RULES`
  entry + `_anon_chips` mapping is needed.
- Do NOT fix without spec confirmation — this is a spec ambiguity, not a clear code bug.

---

## Items Confirmed Covered by Automated Tests (no manual check needed)

The following 5.7 backend behaviors are fully covered by the new automated tests and do NOT
need manual validation:

- `build_chips` shape + ordering for all 4 user/session combinations (test_chips.py — 13 tests)
- `derived_facts` extraction from tool_call args, dict form, merge semantics (test_session_memory.py)
- `clear_session_state` correctness + graceful degradation (test_session_memory.py)
- 20-item tray cap enforced in `save_session_state` (test_session_memory.py)
- `SessionState.is_empty()` honours both product and store results (test_session_memory.py)
- Forward-compatibility: unknown Redis fields don't break `load_session_state` (test_session_memory.py)
- SSE event contract: `thinking` → `tool_call` (×N, one per tool) → `final` (test_chat_v2_stream.py)
- `final` SSE event includes `chips` key (test_chat_v2_stream.py)
- `chips` populated end-to-end from tool_call args when session has derived_facts (test_chat_v2_stream.py)
- Each `tool_call` SSE event includes `name`, `args`, `duration_ms`, `result_count` (test_chat_v2_stream.py)
- `voucher_network` echoed correctly in `final` (test_chat_v2_stream.py)
- Mind-changer 3-turn scenario: derived_facts merge, city overwrite, clarify turn doesn't erase facts (test_repair.py)
- Explicit `clear_session_state` + fresh accumulation (test_repair.py)
- Non-search turn (recall_history) preserves prior derived_facts (test_repair.py)
