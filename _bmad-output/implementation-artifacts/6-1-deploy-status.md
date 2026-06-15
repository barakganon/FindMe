# Story 6.1 — Render Deploy Status (2026-06-15)

**Live URL:** https://findme-rau7.onrender.com — `/health` returns `200 {"status":"ok"}`.
The service auto-deploys on every push to `master`.

## ✅ Done (autonomous)

| Item | Detail |
|------|--------|
| Web service | `srv-d7r7s90sfn5c73c9r7og` (existed since 2026-05-02), Docker, **oregon**, free plan, live |
| Postgres | **created** `findme-db` (`dpg-d8o02qa8qa3s73fj5pu0-a`), PG16, oregon, **free** (expires 2026-07-15) |
| Key Value (Redis) | **created** `findme-kv` (`red-d8o031k8aovs739kspsg`), oregon, free, `allkeys_lru` |
| Non-secret env | APP_ENV=production, LOG_LEVEL, cost budgets, rate limits, body/message caps, cache TTLs |
| JWT_SECRET | generated + set |
| Code fix | `DATABASE_URL` scheme normalization (`postgresql://` → `postgresql+asyncpg://`) so a connected provider URL just works (commit b4004ed) |

## ⛔ Blocked — needs Barak (with reasons)

1. **DB + Redis wiring.** The Render MCP does **not** expose the DB password / connection
   string (security), so DATABASE_URL / REDIS_URL can't be set programmatically. Fix in
   ~2 dashboard clicks (service → Environment → connect `findme-db` and `findme-kv`), OR
   paste me the **External Database URL** + **KV connection URL** and I'll finish it.
2. **Secrets only you hold:** `GEMINI_API_KEY`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`.
   Paste into the service env (dashboard or to me). Without GEMINI the chat can't run.
3. **Schema migration** (`alembic upgrade head` against the Render PG, incl. `CREATE EXTENSION vector`).
   I can run this from your machine once I have the **External** DB URL.
4. **Catalog data** — the ~135,865 embedded rows live in your local Postgres. Options:
   (a) I `pg_dump` local → restore to Render (needs External DB URL + your local DB up), or
   (b) re-embed on Render (needs GEMINI_API_KEY + time + cost). **(a) is faster.**
5. **CORS_ORIGINS** — set once the frontend (6.2) is deployed; until then the API is
   reachable directly but no browser frontend points at it.

## ⚠ Watch

- **Free Postgres = 1 GB storage.** The 135k `vector(768)` rows + `ivfflat` index may
  approach/exceed 1 GB — if the data load fails on space, upgrade `findme-db` to `basic_1gb`+.
- **Region is oregon**, not Frankfurt. Co-located with the web service (right call for
  app↔DB latency); the only Israel-distance hop is user→app. Revisit only if user latency hurts.
- `/api/admin/cost-summary` reports `redis_available:true` even though Redis isn't wired
  yet — minor monitoring-accuracy nit (it doesn't do a live round-trip check). Follow-up.

## Fastest path to a working deploy
Paste me the **External Database URL** and **Key Value URL** (dashboard → each resource →
"Connect"), plus the 3 secrets — then I'll: set the env vars, run migrations, `pg_dump`
your local catalog → restore to Render, and smoke-test `/api/chat/v2/stream` end-to-end.
