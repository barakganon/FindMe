# W7 UI Validation — TEMPLATE (manual)

> Story 5.7, AC-8. This is a TEMPLATE — when running the manual validation,
> copy this file to `tests/eval/baselines/{YYYY-MM-DD}-w7-ui-validation.md`
> (using the actual run date) and fill in the Result column + notes.

**Gate question:** Does the mind-changer scenario survive?

**Backend baseline going in:** W6 — overall 69.4%, brand_top_result 77.8%,
intent 91.8%. See `2026-05-17-v6-prompt-iteration.md`.

**Setup:**

```bash
# Backend
source .venv/bin/activate
redis-server &  # if not already running
uvicorn api.main:app --reload --port 8000

# Frontend
cd frontend && npm run dev  # → http://localhost:5173
```

Browser: Chrome desktop ≥768px AND Chrome mobile emulator <768px (test both layouts).

Clear `localStorage.findme_session_id`, `localStorage.findme_tray`,
`localStorage.findme_tray_open`, and `sessionStorage` between scenarios for a
clean baseline. Tray persistence across scenarios is intentional in real use
but pollutes scenario-isolation testing.

---

## Scenario 1 — Sarah (anonymous, ₪300, no plan)

**Input:** `יש לי 300 ש"ח, מה אפשר לעשות?`

**Expected:**
- Agent asks ONE warm clarifying question (no immediate search)
- After turn, chip strip shows `💰 ₪300`
- No tray items yet

**Result:** [ ] PASS  [ ] FAIL  
**Notes:** _fill in_

---

## Scenario 2 — Yael (anonymous, mom of 3yo)

**Input:** `מתנה לבן 3 שלי`

**Expected:**
- Agent calls `search_products` for kids items
- Chip strip after turn: a chip for the child age range surfaces (if inference fires)
- 1–6 product cards rendered below assistant bubble
- Tray accumulates the rendered items

**Result:** [ ] PASS  [ ] FAIL  
**Notes:** _fill in_

---

## Scenario 3 — Avi (anonymous, three headphones, then a comparison turn)

**Inputs (3 turns then 1):**
1. `אוזניות סוני`
2. `מה לגבי Bose?`
3. `JBL זה טוב?`
4. `איזה הכי שקט?`

**Expected:**
- Turns 1–3: tray accumulates Sony + Bose + JBL items without dropping earlier turns
- Turn 4: agent calls `recall_history` and NOT `search_products` (verify in trace
  shown in browser devtools network → /api/chat/v2/stream → SSE events)
- Chip strip after turn 4: `📍` and `💰` chips reflect any prices/cities mentioned

**Result:** [ ] PASS  [ ] FAIL  
**Notes:** _fill in_

---

## Scenario 4 — Rinat (logged-in, prior search history)

**Setup:** Log in as a test user (or create one) with at least one prior
`UserPreference(preferred_cities=["תל אביב"])` row.

**Input:** `מסעדות כמו פעם שעברה`

**Expected:**
- Chip strip BEFORE the turn already shows `📍 תל אביב` (from preference)
- Agent calls `recall_history` (visible in SSE trace)
- Returned stores all in/near Tel Aviv area

**Result:** [ ] PASS  [ ] FAIL  
**Notes:** _fill in_

---

## Scenario 5 — Mind-Changer (anonymous) — **GATE**

**Inputs (3 turns):**
1. `אופנה לחורף`
2. `בעצם, אוכל טוב באזור` (no GPS yet — should trigger clarify)
3. `מתנה לאמא עד 200`

**Expected:**
- Turn 1: fashion search runs, fashion items appear in tray
- Turn 2: agent does NOT search; calls `clarify` for location. UI shows GPS
  button inline. (Skip the GPS prompt — for this gate, we want to verify the
  clarify path itself.)
- Turn 3:
  - Assistant bubble shows the topic-change subtitle:
    `החלפת נושא? התוצאות הקודמות עדיין שמורות במגש.` (the turn's `intent`
    differs from turn 1's intent)
  - Tray now has fashion items from turn 1 + new gift items from turn 3
  - No 500 errors, no message lost, no in-flight bubble stuck
- Backend: no traceback in uvicorn output across all 3 turns

**Result:** [ ] PASS  [ ] FAIL  
**Notes:** _fill in_

---

## Layout checks (both viewports)

| Check | ≥768px (desktop) | <768px (mobile) |
|---|---|---|
| Tray visible on the RIGHT (RTL flex flip) | [ ] | n/a |
| Tray below chat, collapsed by default | n/a | [ ] |
| Tray toggle persists across reloads | n/a | [ ] |
| Chip strip horizontally scrollable when overflowing | [ ] | [ ] |
| Confirmed chips visually distinct (ring) | [ ] | [ ] |

## Notes / deltas vs W6 baseline

_e.g. "intent label parity holds, no eval regression observed"_

## Sign-off

- Run by: ___
- Date: ___
- Decision: [ ] gate cleared → proceed to Story 5.8  [ ] gate failed → see Notes
