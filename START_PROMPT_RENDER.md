# Production Deploy Sprint — Render + Vercel (lighter alternative)

> Use this instead of `START_PROMPT.md` if you'd rather pay ~$22/month and skip all
> the AWS infrastructure work. Trade-off: you bypass the existing GitHub Actions
> deploy workflows (they target S3+EC2). Migration to AWS later is straightforward.

---

## Cost (monthly)

| Item | Cost |
|------|------|
| Render Web Service (Starter, 512MB, 0.5 CPU) | $7 |
| Render Postgres (Starter, 1GB storage, pgvector) | $7 |
| Render Key Value / Redis (Starter, 25MB) | $7 |
| Vercel Hobby (frontend) | $0 |
| Cloudflare DNS + domain | ~$15/year |
| Gemini paid tier | ~$10–30 |
| Google Maps Geocoding (one-time) | ~$2.50 |
| **Total** | **~$22–32/mo** |

Time to deploy: ~90 min if everything goes smoothly.

---

## PRE-FLIGHT — human steps (~30 min)

1. **Render account** — sign up at https://render.com, connect your GitHub.
2. **Vercel account** — sign up at https://vercel.com, connect your GitHub.
3. **Domain** — register at your preferred registrar. Cloudflare ($9/yr for .com) or .il registrar.
4. **Cloudflare account** (optional but recommended for DNS) — free at https://cloudflare.com.

---

## ─────────────────────────────────────────────────────────────────
## PASTE EVERYTHING BELOW INTO CLAUDE CODE
## ─────────────────────────────────────────────────────────────────

Read these files fully before doing anything:
- `CLAUDE.md`, `STATUS.md`
- `Dockerfile` (will be used by Render directly)
- `requirements.txt`
- `.env.example`

You are the **Render Deploy Agent**. Execute sequentially. Stop on failure.
The user will be active in chat to provide values from Render/Vercel dashboards.

---

### PHASE 0 — verify the test-fix is on master

The `fix/chat-route-rate-limiter-regression` branch should already be merged to master
(see `START_PROMPT.md` Phase 0 for context — the bug fix removed a rate-limiter decorator
that was breaking 8 tests). Verify:

```bash
cd /Users/barakganon/personal_projects/FindMe
git checkout master && git pull origin master
source .venv/bin/activate && python -m pytest tests/ -q   # must show 29 passed
git checkout -b infra/render-vercel-deploy
```

**Checkpoint 0:** 29 tests pass on master.

---

### PHASE 1 — provision Render infrastructure (human in dashboard)

Tell the human:

```
On https://dashboard.render.com:

1. New → PostgreSQL
   • Name: findme-db
   • Database: buyme_search
   • User: findme
   • Region: Frankfurt (closest to Israel; Render doesn't offer Israel/Middle East)
   • Plan: Starter ($7/mo)
   • Postgres version: 16
   • Click Create.
   When deployed: copy the "Internal Database URL" — give it to me.

2. New → Key Value (Render's Redis-compatible service)
   • Name: findme-cache
   • Region: Frankfurt
   • Plan: Starter ($7/mo)
   • Maxmemory policy: allkeys-lru
   When deployed: copy the "Internal Connection URL" — give it to me.

3. New → Web Service
   • Connect repository: barakganon/FindMe
   • Branch: master
   • Region: Frankfurt
   • Plan: Starter ($7/mo)
   • Runtime: Docker
   • Dockerfile path: Dockerfile (default)
   • Auto-deploy: Yes (deploys on every master push)

   Click "Advanced" and add these env vars:
     APP_ENV=production
     APP_HOST=0.0.0.0
     APP_PORT=8000
     LOG_LEVEL=INFO
     CORS_ORIGINS=<we'll fill once Vercel domain is known>
     DATABASE_URL=<paste the Internal Database URL, prefix with postgresql+asyncpg://>
     DATABASE_URL_SYNC=<same as DATABASE_URL but prefix with postgresql+psycopg2://>
     REDIS_URL=<paste Key Value Internal URL>
     CELERY_BROKER_URL=<same as REDIS_URL with /0>
     CELERY_RESULT_BACKEND=<same as REDIS_URL with /1>
     GEMINI_API_KEY=<copy from local .env>
     JWT_SECRET=<I'll generate a strong one>
     SEARCH_CACHE_TTL=300
     INTENT_CACHE_TTL=120
     EMBED_BATCH_SIZE=100

   DON'T click Create yet — I need to give you the JWT_SECRET first.
```

Generate a strong JWT secret and give it to the human:
```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

Wait for the human to give you back the Postgres URL and Redis URL.

**Checkpoint 1:** Postgres + Key Value provisioned. Web Service exists with all env vars
except CORS_ORIGINS (set in Phase 3).

---

### PHASE 2 — apply migrations to Render Postgres

Render Web Service can shell in via dashboard. Tell the human:

```
On the Render Web Service for findme:
  → "Shell" tab → wait for shell to start.
  Once you see a prompt, type:
    cd /app
    python -m alembic upgrade head

  You should see all 8 migrations apply (0001 through 0008).
  Tell me when done.
```

WAIT for confirmation.

**Checkpoint 2:** `alembic current` reports `0008 (head)`.

---

### PHASE 3 — deploy frontend to Vercel

Tell the human:

```
On https://vercel.com:
  1. Add New → Project
  2. Import barakganon/FindMe
  3. Framework Preset: Vite
  4. Root Directory: frontend
  5. Build Command: npm run build (default)
  6. Output Directory: dist (default)
  7. Environment Variables:
       VITE_API_URL = https://findme-api.onrender.com
         (or whatever URL Render assigned — see your Render Web Service)
  8. Deploy.

When deployed, Vercel gives you a URL like findme-xyz.vercel.app.
Tell me that URL.
```

WAIT for the Vercel URL.

Now update the Render Web Service's `CORS_ORIGINS`:
```
CORS_ORIGINS=https://findme-xyz.vercel.app,https://www.findme-xyz.vercel.app
```

This requires the human to edit the env var on the Render dashboard — tell them, then
wait for confirmation that the service redeployed.

**Checkpoint 3:** Open the Vercel URL in a browser. The chat UI loads. Sending a message
reaches Render and returns Hebrew text.

---

### PHASE 4 — custom domain (optional but recommended)

Tell the human:
```
1. On your domain registrar / Cloudflare:
   - For api.<domain>: CNAME → findme-api.onrender.com
   - For <domain>: CNAME → cname.vercel-dns.com (Vercel will tell you the exact target on the project's Domains page)
   - For www.<domain>: CNAME → cname.vercel-dns.com

2. On Render Web Service → Settings → Custom Domains → Add: api.<domain>
3. On Vercel project → Settings → Domains → Add: <domain> AND www.<domain>

Both will auto-issue SSL certs (~5-10 min).

Update the Render env var:
   CORS_ORIGINS=https://<domain>,https://www.<domain>

Update the Vercel env var:
   VITE_API_URL=https://api.<domain>

Then trigger a Vercel redeploy (Deployments → ⋮ → Redeploy).
```

WAIT for both SSL certs to be issued.

**Checkpoint 4:** `https://<domain>` shows the chat. `https://api.<domain>/health` returns
`{"status":"ok"}`.

---

### PHASE 5 — verification + parallel productivity

Run the same smoke tests as `START_PROMPT.md` Phase 6 — `curl` against `/api/admin/health`,
register a test user, send a chat query.

While waiting on DNS / SSL, do these in parallel:

**Google Maps geocoding** — same as `START_PROMPT.md`:
```bash
# Add GOOGLE_MAPS_API_KEY to local .env
source .venv/bin/activate
python -m db.run_geocoding
```

After local geocoding completes, push the geocoded coordinates to the Render DB. Two options:

**Option A — re-run on Render Shell** (slower, but no data sync):
```
Render Shell:
  cd /app
  python -m db.run_geocoding
```
Add `GOOGLE_MAPS_API_KEY` env var first via the dashboard.

**Option B — pg_dump + restore** (faster):
```bash
pg_dump $DATABASE_URL_SYNC -t stores -a > stores_geocoded.sql
psql <render-postgres-external-url> -f stores_geocoded.sql
```

**Bulk deduplication** — same as before, but on Render Shell:
```
Render Shell:
  cd /app
  python -m normalization.deduplication --threshold 0.95 --apply
```

---

### PHASE 6 — celery worker + beat (the missing piece)

The Render Web Service runs the API. It does NOT run Celery workers or beat — those
are separate services.

Tell the human:
```
On Render dashboard:

1. New → Background Worker
   • Connect repo: barakganon/FindMe
   • Region: Frankfurt
   • Plan: Starter ($7/mo)
   • Runtime: Docker
   • Dockerfile path: Dockerfile
   • Docker command: celery -A scraper.scheduler worker --loglevel=info -Q scraper --concurrency=2
   • Env vars: copy ALL env vars from the Web Service (Render has a "Copy from another service" option)

2. New → Background Worker (for Beat)
   • Same setup as above, but Docker command:
     celery -A scraper.scheduler beat --loglevel=info

This adds $14/mo (2 workers) — bringing total to ~$36/mo.
```

If you want to save money in v1, you can SKIP the worker + beat. The site works without
them. Trade-off: scrapers don't run automatically, so the catalog goes stale over time.
You can manually trigger via Render Shell:
```
celery -A scraper.scheduler call scraper.scheduler.scrape_buyme_store_list
```

**Recommendation for v1:** skip workers, run scrapers manually once a week from Render
Shell. Add the worker services later if traffic justifies it.

**Checkpoint 6:** all smoke tests from `START_PROMPT.md` Phase 6 pass.

---

### PHASE 7 — set up uptime monitoring

Free at https://uptimerobot.com:
- Monitor 1: `https://api.<domain>/health` — every 5 min
- Monitor 2: `https://<domain>` — every 5 min
- Alert: email/SMS

---

### Final orchestrator step

```bash
# Update CLAUDE.md "Current State" — ✅ Production live at https://<domain> via Render+Vercel
# Update STATUS.md with deploy notes
git add CLAUDE.md STATUS.md
git commit -m "docs: production deploy complete via Render + Vercel — live at https://<domain>"
git push origin master
```

---

## Trade-offs versus the AWS path

| Aspect | Render+Vercel | AWS |
|--------|---------------|-----|
| Monthly cost | ~$22–36 | ~$50 |
| Setup time | ~90 min | ~3–5 hours |
| Existing tooling reuse | None (GitHub Actions ignored) | Full (Dockerfile, Compose, workflows) |
| Scalability | Limited (vertical only on Starter) | High |
| Control over infra | Low | High |
| Migration cost later (to AWS) | Medium — env vars + DB dump | n/a |
| Debugging access | Render Shell, log streaming, no SSH | Full SSH |
| Free tier headroom | Vercel free tier covers frontend | None |

If you grow to >1000 daily users or need custom networking, migrate to AWS. Until then,
Render is fine and significantly less work.

## ─────────────────────────────────────────────────────────────────
## END
## ─────────────────────────────────────────────────────────────────
