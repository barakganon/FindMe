# Story 1.3: Frontend on Vercel + CORS wiring

Status: backlog

> **Spec source of truth:** [START_PROMPT.md](../../START_PROMPT.md) Phase 3.
> This is a thin BMad-shaped index — execute START_PROMPT.md directly.

## Story

As the deploy operator,
I want the frontend live on Vercel and the API CORS allowlist updated to match,
so that real users can hit the chat from a real URL with no console errors.

## Acceptance Criteria

1. **Vercel project created** — `barakganon/FindMe` repo, root `frontend`, framework Vite, `VITE_API_URL=<Render API URL>`. (User does this manually; no Vercel MCP exists.)
2. **First Vercel deploy succeeds** and serves the chat at the assigned `*.vercel.app` URL.
3. **`CORS_ORIGINS` env var on Render updated via MCP** to include the actual Vercel hostname; redeploy of `findme-api` triggered automatically and finishes cleanly.
4. **Browser smoke test** — open Vercel URL, send "אוזניות סוני" → 10 products render with proper RTL; click "הירשם" → register a test account → confirm logged-in state; send "מסעדות לידי" → GPS prompt appears.
5. **No CORS errors** in browser DevTools Network/Console panels for the test session.

## Tasks / Subtasks

- [ ] Task 1: Vercel deploy (AC: #1, #2)
  - [ ] User connects barakganon/FindMe to Vercel (manual; no MCP)
  - [ ] Configure: framework=Vite, root=frontend, env `VITE_API_URL=<Render URL from Story 1.2>`
  - [ ] Trigger deploy, wait ~90 sec, capture the assigned `*.vercel.app` URL
- [ ] Task 2: CORS update on Render (AC: #3)
  - [ ] Use Render MCP `update_environment_variables` to set `CORS_ORIGINS=https://<vercel-host>,https://www.<vercel-host>`
  - [ ] Wait for redeploy (~60 sec) via MCP `list_logs`
- [ ] Task 3: Browser smoke test (AC: #4, #5)
  - [ ] Send each of the 4 test queries from START_PROMPT Task 3.3
  - [ ] Verify register flow works
  - [ ] Verify no CORS errors in DevTools

## Dev Notes

- **No Vercel MCP exists.** User must do Task 1 manually. Give them clear instructions, wait for the URL.
- **Common failure modes** (from START_PROMPT Task 3.3 troubleshooting):
  - Browser CORS errors → CORS_ORIGINS still wrong
  - Network 404s → VITE_API_URL wrong or routes path mismatch
  - 500s → backend bug; check Render logs via MCP
- Dependency: Story 1.2 must be `done` (Render API live).
- Estimated effort: ~20 min total.

### References

- [START_PROMPT.md](../../START_PROMPT.md) Phase 3
- [_bmad-output/planning-artifacts/epics.md](../planning-artifacts/epics.md#story-13--frontend-on-vercel--cors-wiring)

## Dev Agent Record

### Agent Model Used

(to be filled by dev agent)

### Debug Log References

(to be filled by dev agent)

### Completion Notes List

(to be filled by dev agent)

### File List

(none expected)

## Change Log

(to be filled by dev agent)
