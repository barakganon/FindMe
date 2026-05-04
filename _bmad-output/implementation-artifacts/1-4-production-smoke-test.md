# Story 1.4: Production smoke test + deploy marker

Status: backlog

> **Spec source of truth:** [START_PROMPT.md](../../START_PROMPT.md) Phase 4.
> This is a thin BMad-shaped index — execute START_PROMPT.md directly.

## Story

As the deploy operator,
I want an end-to-end check of the live deployment and a permanent record of the launch state,
so that future regressions can be diagnosed against a known-good baseline.

## Acceptance Criteria

1. **Five canonical queries run against production** via the curl loop in START_PROMPT.md Task 4.1:
   - `אוזניות סוני בבת ים` → `intent=product_search`, ≥ 5 products
   - `תמצא מסעדות באילת` → `intent=store_search` (0 stores acceptable — known data gap)
   - `חנויות בגדים באזור שלי, מכנסיים לחתונה, תקציב 200 ש״ח` → `intent=clarify` (no GPS in curl)
   - `מה אפשר לקנות ב-BuyMe?` → `intent=help`, returns categories
   - `אני רוצה ל` (truncated) → `intent=clarify` with Hebrew clarifying question
2. **STATUS.md updated** with a "Session: 2026-05-XX — Production Deploy" section listing both URLs, Render service IDs, and a one-line summary per AC #1.
3. **Master commit pushed** with conventional message `docs(status): production deploy complete — live at <url>`.

## Tasks / Subtasks

- [ ] Task 1: Production query verification (AC: #1)
  - [ ] Execute the curl loop from START_PROMPT Task 4.1 against `<render-api-url>/api/chat`
  - [ ] Verify each query returns the expected intent and result counts
  - [ ] If any query returns wrong intent/zero results, debug before marking done
- [ ] Task 2: STATUS.md deploy marker (AC: #2)
  - [ ] Append a new `## Session: 2026-05-XX — Production Deploy` section
  - [ ] Include both URLs (Vercel + Render), service IDs, plan tier, region
  - [ ] One-line per canonical query result
- [ ] Task 3: Commit + push (AC: #3)
  - [ ] Conventional Commit: `docs(status): production deploy complete — live at <url>`
  - [ ] Push to master

## Dev Notes

- This story is pure verification + documentation. No code changes.
- Dependency: Story 1.3 must be `done` (Vercel live + CORS fixed).
- Estimated effort: ~15 min.
- After this story: Epic 1 closes, Epic 2 (post-launch hardening) becomes active.

### References

- [START_PROMPT.md](../../START_PROMPT.md) Phase 4
- [_bmad-output/planning-artifacts/epics.md](../planning-artifacts/epics.md#story-14--production-smoke-test--deploy-marker)

## Dev Agent Record

### Agent Model Used

(to be filled by dev agent)

### Debug Log References

(to be filled by dev agent)

### Completion Notes List

(to be filled by dev agent)

### File List

(STATUS.md only)

## Change Log

(to be filled by dev agent)
