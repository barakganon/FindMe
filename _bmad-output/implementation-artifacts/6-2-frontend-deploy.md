# Story 6.2 — Frontend Rebuild + Deploy

> Created 2026-07-11 (autonomous). The deferred W5 ChatInterface rebuild is **already
> done** — `frontend/src/components/ChatInterface.tsx` (910 lines) has the conversation
> view, cross-turn Tray (deduped by type/id, localStorage-persisted), SSE streaming state
> line (thinking → tool → composing), and memory chips. This story is the remaining
> **production-readiness** work, stopping short of the live deploy.

## Scope (in) — autonomous, no deploy

| # | Item | Status |
|---|------|--------|
| a | `cd frontend && npm ci && npm run build` completes green; fix any TS / build errors | — |
| b | API base URL is env-driven (`VITE_API_URL`, `api.ts:11`) — verify no hardcoded `localhost` leaks into the prod bundle | — |
| c | Add `frontend/.env.production` example pointing at the live API (`https://findme-rau7.onrender.com`) | — |
| d | Confirm relative-`/api/*` dev-proxy path still works (Vite proxy) so dev is unbroken | — |

## Scope (out) — needs Barak / launch

- Actual static-site deploy (Vercel / Render static). Outward-facing + account-bound.
- Setting `CORS_ORIGINS` on the API to the final frontend origin — do at launch once the
  frontend URL is known. API CORS is already env-driven (`api/main.py:86`).

## Kill gate (from epic plan, deferred to launch)

End 6.2: an anonymous browser visitor completes one search end-to-end on the deployed
site. Cannot run until deploy — validated at launch.
