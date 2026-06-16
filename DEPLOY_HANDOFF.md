# FindMe — Deploy Handoff (what I need from you)

Live backend: **https://findme-rau7.onrender.com** (`/health` is green).
Infra is provisioned (Postgres `findme-db`, Redis `findme-kv`, all config + JWT set).
It just needs the 3 things below to actually serve search/chat. Should take you ~5 min.

---

## What I need from you (4 items)

### 1. External Database URL
Render Dashboard → **findme-db** → "Connect" → copy the **External Database URL**
(looks like `postgresql://findme_db_u04q_user:****@dpg-...oregon-postgres.render.com/findme_db_u04q`).

### 2. Key Value (Redis) URL
Dashboard → **findme-kv** → "Connect" → copy the **Internal** Key Value URL
(`redis://...`). Internal is fine — the web service shares its region.

### 3. The three secrets
- `GEMINI_API_KEY`
- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`

### 4. Confirm your local DB is running
So I can copy the ~135,865 embedded products into the Render DB.
Quick check: `! pg_isready` (or just tell me it's up).

---

## How to give them to me

Paste each in the chat using the `!` prefix so the value lands in our session, e.g.:

```
! echo "DB=$DATABASE_URL"          # your LOCAL database url (for the data copy)
```

…and just paste the 4 Render items above as plain text in a message. (They're
secrets — only do this if you're comfortable; alternatively set items 1–3 yourself
in the Render dashboard → service → Environment, and I'll verify + load the data.)

---

## What I'll do once I have them
1. Set `DATABASE_URL`, `DATABASE_URL_SYNC`, `REDIS_URL`, and the 3 secrets on the service.
2. Run `alembic upgrade head` (creates the schema + `CREATE EXTENSION vector`).
3. `pg_dump` your local catalog → restore into Render (or flag if it exceeds free-tier space).
4. Smoke-test `/api/chat/v2/stream` end-to-end and report back.

---

## Costs

Everything is on **free tiers right now = $0/month**, but free has real limits
(web service sleeps after ~15 min idle → slow first request; **free Postgres is
deleted after 30 days**, on **2026-07-15**; 1 GB storage). For an actual soft-launch
you'll want to upgrade. Figures are **approximate (mid-2026) — verify on
render.com/pricing before committing**:

| Resource | Free (now) | Soft-launch recommended | Why upgrade |
|----------|-----------|-------------------------|-------------|
| Web service | $0 (sleeps, cold starts) | **Starter ~$7/mo** (always-on, 512 MB) | no cold-start lag for first users |
| Postgres `findme-db` | $0 (1 GB, **expires 2026-07-15**) | **Basic-1GB ~$19/mo** (or higher) | 135k `vector(768)` rows + ivfflat index may exceed 1 GB; won't expire |
| Redis `findme-kv` | $0 (25 MB) | **Starter ~$10/mo** | session memory + cost-guard + cache headroom |
| **Total** | **$0/mo** | **~$36/mo** | — |

Notes:
- The **1 GB free Postgres may not fit the data** — if the load runs out of space I'll
  stop and tell you; upgrading is one click and keeps the data.
- You can soft-launch on free tiers to validate, then upgrade — nothing is lost on upgrade.
- A managed pgvector elsewhere (Supabase/Neon free tiers) is an alternative; see
  `_bmad-output/planning-artifacts/6-1-pgvector-provider-comparison.md`. Recommendation
  stands: Render native is simplest now that it supports pgvector.

---

*Frontend (6.2) is separate — the API is reachable directly, but there's no browser UI
pointing at it yet, and `CORS_ORIGINS` stays open until the frontend URL exists.*
