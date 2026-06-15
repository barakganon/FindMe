# Story 6.3 — Anonymous `👦 ילד {age}` Chip: Decision Doc

> Drafted 2026-06-15 (autonomous). Resolves the possible-bug flagged by the 5.7
> verification pass: in Canonical Scenario 2 (Yael, anon user, *"מתנה לבן 3"*) the
> spec mock shows a `👦 ילד 3` memory chip, but the deployed behavior won't show it.
> **This is a product/design decision, not a clear bug — hence a doc, not a blind patch.**

## What actually happens today (grounded in code)

Memory chips come from two disjoint sources (`api/agent/chips.py`):

- **Logged-in users:** chips are built from the DB — `UserPreference` +
  `UserInferredAttribute`. The `👦 ילד {age}` chip exists here: `_inferred_to_chip`
  maps a `child_age_range` inferred-attribute row → `👦 ילד {value}`
  (`api/agent/chips.py:_inferred_to_chip`).
- **Anonymous users:** chips come *only* from `session_state.derived_facts`
  (`_anon_chips`), and `derived_facts` is populated *only* from this turn's
  tool-call args via `_DERIVED_FACT_RULES` (`api/agent/session_memory.py:145`):

  ```python
  _DERIVED_FACT_RULES = [
      ("search_products", "brand",     "brand"),
      ("search_products", "max_price", "max_price"),
      ("search_products", "city",      "city"),
      ("search_stores",   "city",      "city"),
  ]
  ```

So an anon chip can only ever reflect `brand`, `max_price`, or `city` — because
**those are the only tool arguments that exist.** No tool carries a recipient /
child-age field, so there is no path for `👦 ילד 3` to reach `derived_facts` for an
anonymous user. The chip is structurally impossible for anon today, regardless of
what the agent infers from the message.

(Secondary observation: `brand` *is* extracted into `derived_facts` but `_anon_chips`
does **not** render a brand chip — a real but separate inconsistency; see Option C.)

## Why it's not a simple fix

To show `👦 ילד 3` for an anon user you must get child-age from the free-text message
("מתנה לבן 3") into `derived_facts`. The current architecture only derives facts from
**structured tool args**, by deliberate design (chips reflect what the agent *acted on*,
not what it guessed). Surfacing child-age means one of:
- giving a tool a new `recipient_age` / `occasion` argument the agent fills, **or**
- adding a separate message→facts inference path for anon users (new code path,
  new prompt, new failure modes).

Both change the agent's contract. That's an Epic-6 design call, not a test-fix.

## Options

### Option A — Add a recipient/occasion arg to `search_products` (spec-faithful, larger)
- Add optional `recipient_age` (int) and/or `occasion` (str) args to the
  `search_products` tool spec; instruct the prompt to fill them when the user names a
  gift recipient ("לבן 3" → recipient_age=3).
- Add `("search_products", "recipient_age", "child_age")` to `_DERIVED_FACT_RULES`
  and a `👦 ילד {age}` branch in `_anon_chips`.
- **Pros:** matches the spec mock; anon + logged-in chips converge; the recipient
  signal could also *enrich* search (boost age-appropriate gifts) later.
- **Cons:** touches tool schema + `api/prompts.py` + eval expectations; the new arg
  must NOT *restrict* search (CLAUDE.md: inferred attrs boost, never filter); needs
  eval-harness golden updates so tool_call_match doesn't regress. Real work, real risk.

### Option B — Scope `👦 ילד` to logged-in only; correct the spec (honest, minimal)
- Accept that anon users don't get a child chip; the chip is a logged-in
  personalization feature (it already only works there).
- Update the 5.7 spec / Scenario 2 mock and the manual-validation checklist to show
  the child chip as a **logged-in** signal, not anon.
- **Pros:** zero risk, no schema/prompt churn, honest about current behavior. Anon users
  still get the chips that are actually derivable (city, price).
- **Cons:** the warm "we remember your kid" moment is lost for first-touch anon users —
  arguably the most delightful part of Scenario 2.

### Option C — Independent quick win: render the already-derived `brand` chip for anon
- `_anon_chips` ignores `derived_facts["brand"]` even though it's extracted. Adding a
  `🏷️ {brand}` (or similar) anon chip is a small, safe, self-consistent fix.
- **Caveat:** the spec screen-anatomy examples only show 👦/💰/📍 — adding a brand chip
  is a (minor) UI addition the designer should bless. **Recommend deferring until Sally
  confirms**, to avoid inventing UI. Listed here only so the inconsistency is on record.

## Recommendation

**Ship Option B now; schedule Option A as a proper 6.x story if user-testing shows the
anon child chip matters.** Rationale: B makes the product honest with zero risk and
unblocks 6.3; A is genuinely valuable but is a tool-schema + prompt + eval change that
deserves its own story and an eval-gate, not a quiet patch slipped into a "safe" task.
Decide A vs B against real 6.5 soft-launch feedback — if first-touch anon users light up
at the kid chip, A pays for itself; if not, B was right.

Option C: hold for designer sign-off.

## If Barak picks A later — concrete change list
1. `api/agent/tools/` — add `recipient_age` (and/or `occasion`) to the `search_products` tool spec.
2. `api/prompts.py` — extend the system prompt: fill `recipient_age` from gift-recipient phrasing; never use it to filter.
3. `api/agent/session_memory.py` — add `("search_products", "recipient_age", "child_age")` to `_DERIVED_FACT_RULES`.
4. `api/agent/chips.py:_anon_chips` — add the `👦 ילד {child_age}` branch.
5. `tests/eval/golden_queries.yaml` — add/adjust expectations so tool_call_match doesn't regress.
6. Tests: anon chip from `recipient_age`; confirm search results are **not** filtered by it (boost-only invariant).

## Action taken in this story
- This decision doc (no behavior change).
- Recommended: update the 5.7 manual-validation checklist Scenario-2 line to mark the
  child chip as logged-in-only pending the A/B decision. (Left to Barak to confirm B
  before editing the spec mock.)
