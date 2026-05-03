# FindMe — Master Deploy Prompt (Render + Vercel via MCP)

> **Goal:** ship FindMe to a public URL today using the wired-up Render MCP server.
> **Outcome:** working frontend at `https://findme.vercel.app` (or custom domain), backend at `https://findme-api.onrender.com`, real users can search.
> **Time:** ~2-3 hours including the pre-deploy cleanup.

---

## Verified state (snapshot from end of 2026-05-03 session)

| Item | Status |
|---|---|
| Master commit | `bc69d50` — STATUS.md updated with all known issues |
| Tests | ✅ 29 passed |
| Docker build (linux/arm64 local) | ✅ Clean (Playwright `--with-deps` fix shipped) |
| API route prefix consistency | ✅ All routes under `/api/*` |
| Frontend production host config | ✅ Uses `VITE_API_URL` env |
| Render MCP (Claude Code, user scope) | ✅ Wired up, workspace "My Workspace" auto-selected |
| Local Postgres | ✅ pgvector 0.8.1, 1.26 GB on disk (~700 MB after restore) |
| Local data | 135,988 products / 134,963 embedded / 1,236 stores / 426 geocoded |
| Known **CRITICAL** bug | 🔴 Installment-price extraction at FOX/שילב/etc. (~13K affected products) — see Phase 0 |
| Known UI bug | 🟡 Out-of-stock visual treatment too subtle — see Phase 0 |
| Known infra issue | 🟡 venv shebangs point to old PycharmProjects path — see Phase 0 |

---

## Cost summary (recurring)

| Item | Cost |
|---|---|
| Render Postgres Starter (1 GB, pgvector) | $7 |
| Render Key Value Starter (25 MB Redis) | $7 |
| Render Web Service Starter (512 MB / 0.5 CPU) | $7 |
| Vercel Hobby (frontend) | $0 |
| Domain (.com, optional v1) | ~$1/mo amortized |
| Gemini API (paid tier, expected v1 traffic) | ~$5-15 |
| Google Maps Geocoding (one-time, 500 stores) | ~$2.50 |
| **Recurring monthly** | **~$22-32** |

Skipping Celery worker + beat services for v1 saves $14/mo. Trade-off: scrapers don't auto-run, you trigger weekly via Render Shell. Recommended for v1.

---

## Pre-flight (only-you tasks, ~30 min)

These cannot be done by Claude Code. Do them BEFORE pasting the prompt below.

1. **Vercel account** — sign up at https://vercel.com → connect GitHub. (No MCP exists for Vercel.)
2. **Google Maps Geocoding API key** — https://console.cloud.google.com → APIs & Services → Library → "Geocoding API" → Enable → Credentials → Create API key → restrict to Geocoding API only.
3. **Decide: domain or no domain for v1.**
   - **No domain (recommended for v1)**: ship at `findme.vercel.app` and `findme-api.onrender.com`. Move to a domain in week 2 once you've validated demand.
   - **With domain**: register at any registrar (~$10-15/year). Cloudflare for DNS is fine and free.
4. **Confirm Gemini paid tier** — https://aistudio.google.com → your project → billing enabled. Free tier limits get hit fast in production.

When all four are done, paste the prompt below into a fresh Claude Code session in `/Users/barakganon/personal_projects/FindMe`.

---

## ─────────────────────────────────────────────────────────────────
## PASTE EVERYTHING BELOW THIS LINE INTO CLAUDE CODE
## ─────────────────────────────────────────────────────────────────

You are the **Master Deploy Agent**. Read these files fully before doing anything:

- `STATUS.md` — full project history; the Session: 2026-05-03 block at the bottom is the most relevant
- `CLAUDE.md` — project conventions
- `ANALYTICS.md` — first-week post-launch SQL playbook (referenced in Phase 5)
- `Dockerfile`, `docker-compose.yml`, `requirements.txt`, `.env.example`
- `frontend/vite.config.ts`, `frontend/src/api.ts`

**You have the Render MCP available** at user scope. Use its tools (`list_services`, `create_postgres`, `create_keyvalue`, `create_web_service`, `update_environment_variables`, `list_logs`, `query_render_postgres`, etc.) instead of asking the user to click through dashboards. Tool results count as authoritative.

Execute in **6 phases**, sequentially. Each phase has an explicit checkpoint — confirm it passes before proceeding. **If a phase fails, stop and report.** Don't keep going on a broken foundation.

**Git discipline:** every change goes on a feature branch with conventional commit messages. Branch is pushed = task done. Never commit `.env*` or any secrets.

---

### PHASE 0 — Pre-deploy local cleanup (~45 min)

#### Task 0.1 — Branch off
```bash
cd /Users/barakganon/personal_projects/FindMe
git checkout master && git pull origin master
git checkout -b deploy/pre-launch-cleanup
```

#### Task 0.2 — Resolve the installment-price bug

The user's Phase 0 decision: ask them to confirm Option 1 (null bad prices). If they confirm:

```bash
PGBIN=/Applications/Postgres.app/Contents/Versions/18/bin

# Show the impact first — DON'T commit this UPDATE blindly
$PGBIN/psql -d buyme_search -c "
SELECT s.name_he, count(*) AS will_be_nulled, min(sp.price), max(sp.price)
FROM store_products sp JOIN stores s ON s.id = sp.store_id
WHERE s.name_he IN ('FOX','Fox Home','שילב','רשת Bגוד','Babystar','SOHO','אהבה קטנה','SWEETWEET','Femina')
  AND sp.price IS NOT NULL AND sp.price < 40
GROUP BY s.name_he ORDER BY will_be_nulled DESC;"
```

Show the user the count breakdown. If they approve:

```bash
$PGBIN/psql -d buyme_search -c "
UPDATE store_products
SET price = NULL
WHERE store_id IN (
  SELECT id FROM stores
  WHERE name_he IN ('FOX','Fox Home','שילב','רשת Bגוד','Babystar','SOHO','אהבה קטנה','SWEETWEET','Femina')
)
AND price IS NOT NULL AND price < 40;"
```

Document the fix in STATUS.md as a new entry under Session 2026-05-03, with the count of rows nulled.

```bash
git add STATUS.md
git commit -m "fix(data): null installment-extracted prices at fashion/baby stores

Set price=NULL for ~10K products at FOX, שילב, רשת Bגוד, Babystar,
SOHO, אהבה קטנה, SWEETWEET, Femina, Fox Home where price < ₪40.

These were installment prices captured by scrapers as the lump-sum
price. Frontend already shows 'מחיר לא זמין' for null prices, so this
prevents misleading users while we plan a proper scraper fix in week 1
post-launch."
```

#### Task 0.3 — Fix out-of-stock visual treatment

Edit `frontend/src/components/ResultCard.tsx`:

- Wrap the entire card in a className that adds `opacity-60 bg-gray-50` when `!result.availability`
- Replace the tiny `● אזל` line with a prominent badge: `<span className="text-red-600 font-semibold text-xs">אזל המלאי</span>` when sold out
- Disable the "לרכישה ←" link entirely OR change it to "לפרטים ←" (text gray, lower-emphasis) when sold out — choice is yours

Also update `chat.py` `_run_product_search`: after merging results, sort `availability=true` first, `availability=false` last. This keeps in-stock items at the top of result grids.

```bash
cd /Users/barakganon/personal_projects/FindMe
# Verify build still passes
cd frontend && npm run build && cd ..
git add frontend/src/components/ResultCard.tsx api/routes/chat.py
git commit -m "fix(ui): visually demote out-of-stock products in result cards

- Greyed background + reduced opacity for sold-out items
- Replace tiny gray 'אזל' text with prominent red 'אזל המלאי' badge
- Sort in-stock products first in chat product_search results
- Disable purchase link styling on sold-out cards"
```

#### Task 0.4 — Recreate the venv

The current `.venv/bin/*` script wrappers have shebangs hardcoded to the old PycharmProjects path. Workarounds (`.venv/bin/python -m uvicorn`) work but the wrappers are brittle. Fix it now:

```bash
cd /Users/barakganon/personal_projects/FindMe
# Stop any running uvicorn first
pkill -f "uvicorn api.main" || true
deactivate 2>/dev/null || true
rm -rf .venv
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
# Verify all binaries now have correct shebangs
head -1 .venv/bin/uvicorn .venv/bin/alembic .venv/bin/celery .venv/bin/pytest
# All should show: #!/Users/barakganon/personal_projects/FindMe/.venv/bin/python
```

If pip install fails on any package (e.g., `playwright`), report to user — `.venv/bin/playwright install chromium` may be needed.

#### Task 0.5 — Run tests on the fresh venv
```bash
.venv/bin/pytest tests/ -q
# Expect: 29 passed
```

#### Task 0.6 — Optional: Google Maps geocoding

If the user provided `GOOGLE_MAPS_API_KEY`, add to `.env` and run:
```bash
echo "GOOGLE_MAPS_API_KEY=<key>" >> .env
.venv/bin/python -m db.run_geocoding
# Expect: ~500 additional stores geocoded, $2.50 cost on Google Maps
```

If they didn't provide one, skip — tell them they can run this from Render Shell post-deploy.

#### Task 0.7 — Optional: bulk deduplication

```bash
# Dry-run first to see the count
.venv/bin/python -m normalization.deduplication --threshold 0.95
# If the count looks reasonable (<2K merges), apply:
.venv/bin/python -m normalization.deduplication --threshold 0.95 --apply
```

#### Task 0.8 — Push the cleanup branch and merge

```bash
git push origin deploy/pre-launch-cleanup
git checkout master
git merge --no-ff deploy/pre-launch-cleanup -m "Merge: pre-deploy cleanup (price fix, UI, venv, geocoding, dedup)"
git push origin master
git branch -d deploy/pre-launch-cleanup
```

#### Checkpoint 0
- [ ] Tests pass (29/29)
- [ ] Backend chat returns sensible results for the 5 canonical queries
- [ ] Frontend `npm run build` succeeds
- [ ] Branch merged to master, pushed to origin

If anything fails, **stop and report**.

---

### PHASE 1 — Provision Render infrastructure via MCP (~15 min)

This phase uses the Render MCP. **Do not tell the user to click through dashboards.** Use the MCP tools.

#### Task 1.1 — Generate the production JWT secret
```bash
.venv/bin/python -c "import secrets; print(secrets.token_urlsafe(64))"
```
Save this value as `JWT_SECRET_PROD`. You'll inject it into the Render Web Service env vars in Task 1.4.

#### Task 1.2 — Create Postgres via MCP

Ask the MCP to create a Postgres database. Use these parameters exactly:

- name: `findme-db`
- plan: `starter` ($7/mo, 1 GB — fits the catalog)
- region: `frankfurt` (closest to Israel; Render has no Middle East region)
- postgres version: `16`
- extensions: `vector` (pgvector — required for embedding search)

The MCP tool returns the database ID. **Save the internal DATABASE_URL and external DATABASE_URL** from the response — you'll need both.

#### Task 1.3 — Create Key Value via MCP

- name: `findme-cache`
- plan: `starter` ($7/mo, 25 MB)
- region: `frankfurt`
- maxmemory policy: `allkeys-lru`

Save the internal Redis URL.

#### Task 1.4 — Create the Web Service via MCP

- name: `findme-api`
- runtime: `docker`
- repo: `https://github.com/barakganon/FindMe`
- branch: `master`
- region: `frankfurt`
- plan: `starter`
- auto-deploy: yes

Set environment variables on the service via the MCP. You need the Postgres URL from Task 1.2 (use the **internal** URL since the service and DB are in the same region):

```
APP_ENV=production
APP_HOST=0.0.0.0
APP_PORT=8000
LOG_LEVEL=INFO
DATABASE_URL=<internal postgres URL with prefix postgresql+asyncpg://>
DATABASE_URL_SYNC=<same URL but with prefix postgresql+psycopg2://>
REDIS_URL=<internal redis URL>
CELERY_BROKER_URL=<same redis URL>/0
CELERY_RESULT_BACKEND=<same redis URL>/1
GEMINI_API_KEY=<copy from local .env>
JWT_SECRET=<value from Task 1.1>
SEARCH_CACHE_TTL=300
INTENT_CACHE_TTL=120
EMBED_BATCH_SIZE=100
CORS_ORIGINS=https://findme.vercel.app
   # placeholder — we'll update with the real Vercel URL in Phase 3
```

If the user provided `GOOGLE_MAPS_API_KEY`, also set it.

#### Task 1.5 — Wait for the Web Service to deploy

The first deploy will fail because the database is empty (Alembic migrations haven't run yet, no data). That's expected. Use the MCP to stream the logs and confirm:
- Build succeeded (Docker image built clean)
- App startup probably fails on `alembic upgrade head` because it can't find tables — that's fine

#### Checkpoint 1
- [ ] Postgres `findme-db` exists, pgvector enabled
- [ ] Key Value `findme-cache` exists
- [ ] Web Service `findme-api` exists with correct env vars
- [ ] First deploy went through Build phase OK (Runtime errors expected, that's the next phase)

---

### PHASE 2 — Migrate data from local to Render (~30 min)

#### Task 2.1 — Dump local DB

```bash
PGBIN=/Applications/Postgres.app/Contents/Versions/18/bin
$PGBIN/pg_dump -d buyme_search \
  --format=custom \
  --no-owner \
  --no-acl \
  --compress=9 \
  --exclude-extension=plpgsql \
  -f /tmp/findme-local.dump
ls -lh /tmp/findme-local.dump
# Expect ~120 MB
```

`--exclude-extension=plpgsql` skips the default Postgres extension (Render has it built-in). We're letting pgvector come through naturally because we explicitly enabled it on Render in Task 1.2.

#### Task 2.2 — Apply Alembic migrations on Render Postgres FIRST

Do NOT pg_restore directly into an empty DB. The alembic migration system needs to run first to create the schema with the right migration version tracking. Run migrations via the MCP:

Use the MCP tool to invoke a Render Web Service shell and run:
```
cd /app
python -m alembic upgrade head
```

Expect output: 8 migrations applied (0001 through 0008).

If the MCP can't shell into the service, fall back to: SSH-style approach via Render Dashboard (the user opens a Shell tab on the service) and run the alembic command there.

#### Task 2.3 — Restore data only (not schema)

```bash
RENDER_DB_URL="<external postgres URL from Task 1.2 — uses postgresql:// prefix>"

PGBIN=/Applications/Postgres.app/Contents/Versions/18/bin
$PGBIN/pg_restore \
  --dbname="$RENDER_DB_URL" \
  --data-only \
  --disable-triggers \
  --no-owner \
  --no-acl \
  --jobs=4 \
  --verbose \
  /tmp/findme-local.dump 2>&1 | tee /tmp/restore.log
```

`--data-only` because the schema already exists (created by alembic in Task 2.2). `--disable-triggers` to avoid foreign-key issues during restore. `--jobs=4` parallelizes the load (~3-5 min for ~120 MB).

You may see warnings about `alembic_version` already populated — those are expected and harmless.

#### Task 2.4 — Verify counts via MCP

Use `query_render_postgres` MCP tool to run:
```sql
SELECT
  (SELECT count(*) FROM stores) AS stores,
  (SELECT count(*) FROM products) AS products,
  (SELECT count(*) FROM products WHERE embedding_vector IS NOT NULL) AS embedded,
  (SELECT count(*) FROM store_products) AS store_products;
```

Expected (give or take a few from any local edits):
- stores ≈ 1,236
- products ≈ 135,988
- embedded ≈ 134,963
- store_products ≈ 181,517

If counts are way off, **stop and investigate** — restore probably partial.

#### Task 2.5 — Rebuild the HNSW index (if needed)

Vector indexes don't always restore cleanly via `pg_restore --data-only`. Verify:
```sql
SELECT indexname FROM pg_indexes WHERE tablename='products' AND indexname LIKE '%embedding%';
```

If the embedding index is missing, recreate it (this takes ~5-10 min for 134K vectors):
```sql
CREATE INDEX ix_products_embedding
  ON products USING hnsw (embedding_vector vector_cosine_ops);
```

#### Task 2.6 — Trigger a fresh deploy of `findme-api`

Now that the DB has data, the service should start cleanly. Use the MCP `update_environment_variables` (touching any env var triggers a redeploy) or have the user push an empty commit to master:
```bash
git commit --allow-empty -m "chore: trigger deploy after DB migration"
git push origin master
```

Stream logs via MCP `list_logs`. Expect:
- Migrations: "alembic_version is at 0008"
- Uvicorn started on 0.0.0.0:8000
- Health probe passes

#### Task 2.7 — Test backend endpoints

```bash
# Get the live URL via MCP `get_service` for findme-api → it returns serviceDetails.url
RENDER_API_URL="https://findme-api.onrender.com"

curl -s "$RENDER_API_URL/health"
# {"status":"ok","version":"0.1.0"}

curl -s "$RENDER_API_URL/api/admin/health" | head -c 400
# Should report ~135K products embedded, DB+Redis up
```

#### Checkpoint 2
- [ ] DB counts match local (within rounding)
- [ ] HNSW index exists
- [ ] `findme-api` deploys cleanly
- [ ] `/health` and `/api/admin/health` return 200

---

### PHASE 3 — Frontend on Vercel (~20 min)

Vercel doesn't have an MCP (yet). User needs to do dashboard interaction here. Instruct them clearly.

#### Task 3.1 — User connects the repo to Vercel

Tell the user (in chat):

```
Open https://vercel.com → Add New → Project → Import barakganon/FindMe.

Configure:
- Framework Preset: Vite
- Root Directory: frontend
- Build Command: npm run build (default)
- Output Directory: dist (default)
- Environment Variables:
    VITE_API_URL = https://findme-api.onrender.com
    (or the actual Render URL from Phase 2)

Click Deploy. It takes ~90 sec.

When done, give me the Vercel URL (something like findme-xyz.vercel.app).
```

WAIT for the URL.

#### Task 3.2 — Update CORS_ORIGINS on Render via MCP

Once you have the Vercel URL, use the MCP `update_environment_variables` to set:
```
CORS_ORIGINS=https://<vercel-url>,https://www.<vercel-url>
```

This triggers a redeploy of the API service. Wait for it (~60 sec via `list_logs`).

#### Task 3.3 — Smoke-test the live frontend

Tell the user to open the Vercel URL in a browser and:
1. Send "אוזניות סוני" — confirm 10 products render with proper RTL
2. Click "הירשם" → register a test account → confirm logged in
3. Send a few more queries → open profile drawer → see if anything's there
4. Try "מסעדות לידי" — confirm GPS prompt appears

If anything is broken, debug:
- Check browser console for CORS errors → CORS_ORIGINS still wrong
- Check Network tab for 404s → VITE_API_URL wrong or routes path issue
- Check Render logs via MCP for 500s → backend bug

#### Checkpoint 3
- [ ] Vercel URL serves the chat
- [ ] At least one query returns real Hebrew results
- [ ] Registration works
- [ ] No CORS errors in browser console

---

### PHASE 4 — Final smoke test + production verification (~15 min)

#### Task 4.1 — Run all 5 canonical queries against production

```bash
RENDER_API_URL="https://findme-api.onrender.com"  # or actual

for q in \
  "אוזניות סוני בבת ים" \
  "תמצא מסעדות באילת" \
  "חנויות בגדים באזור שלי, מכנסיים לחתונה, תקציב 200 ש״ח" \
  "מה אפשר לקנות ב-BuyMe?" \
  "אני רוצה ל"
do
  echo "=== $q ==="
  curl -s -X POST "$RENDER_API_URL/api/chat" \
    -H "Content-Type: application/json" \
    -d "{\"message\":\"$q\",\"history\":[],\"session_context\":null}" \
    | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(f'  intent: {d[\"intent\"]}')
print(f'  msg:    {(d[\"message\"] or \"\")[:80]}')
print(f'  prods:  {len(d.get(\"product_results\") or [])}')
print(f'  stores: {len(d.get(\"store_results\") or [])}')
print(f'  ms:     {d.get(\"search_time_ms\")}')
"
  echo ""
done
```

Expected:
- 1: product_search, 10 products
- 2: store_search, 0 stores (data gap, not a bug)
- 3: clarify (because GPS not provided in curl)
- 4: help, returns categories
- 5: clarify

#### Task 4.2 — Update STATUS.md with deploy marker

Append a new section to STATUS.md:
```markdown
---

## Session: 2026-05-XX — Production Deploy

| Service | URL |
|---|---|
| Frontend | https://<vercel>.vercel.app |
| Backend | https://findme-api.onrender.com |
| Postgres | findme-db (Render Frankfurt, Starter) |
| Redis | findme-cache (Render Frankfurt, Starter) |

### Verified post-deploy
- All 5 canonical queries return expected intent and result counts
- /api/admin/health reports 99.2% embedding coverage on Render Postgres
- Registration + login work end-to-end
- Logs stream cleanly via Render MCP
```

#### Task 4.3 — Commit and push

```bash
git add STATUS.md
git commit -m "docs(status): production deploy complete — live at https://<vercel-url>"
git push origin master
```

#### Checkpoint 4
- [ ] All 5 production queries return expected results
- [ ] STATUS.md updated and pushed
- [ ] Frontend shareable URL exists

---

### PHASE 5 — Optional polish (post-deploy, no time pressure)

These are not blockers for "is FindMe live?" — do them after you've shared the URL with humans and gotten initial feedback.

#### Task 5.1 — UptimeRobot monitoring (free, 5 min)

Tell the user:
```
Sign up free at https://uptimerobot.com.
Add 2 HTTP monitors, 5-min interval, email alert:
1. https://findme-api.onrender.com/health
2. https://<vercel>.vercel.app/
```

#### Task 5.2 — Custom domain (optional)

If the user registered a domain in pre-flight:
- Render dashboard: add custom domain `api.<domain>` to findme-api Web Service. Render gives DNS instructions.
- Vercel dashboard: add `<domain>` and `www.<domain>` to project. Vercel gives DNS instructions.
- DNS provider: add records as instructed by both Render and Vercel.
- After SSL provisions: update Vercel `VITE_API_URL` to `https://api.<domain>` and Render `CORS_ORIGINS` to `https://<domain>,https://www.<domain>`.

#### Task 5.3 — Background workers for scheduled scrapers (optional, $14/mo)

If user wants automatic scraping (Shopify weekly, sitemap bi-weekly):
- Use MCP to create Render Background Worker for `celery -A scraper.scheduler worker -Q scraper`
- Use MCP to create Render Background Worker for `celery -A scraper.scheduler beat`
- Same env vars as findme-api

For v1, **skip this**. Run scrapers manually weekly via Render Shell:
```
celery -A scraper.scheduler call scraper.scheduler.scrape_buyme_store_list
```

#### Task 5.4 — Open ANALYTICS.md and run Tier 1 queries

After you've told some real humans about the URL and waited 24 hours, open `ANALYTICS.md` and run the Tier 1 queries via MCP `query_render_postgres`. The decision rules at the bottom of ANALYTICS.md tell you what to do next based on what you see.

---

## ROLLBACK plan

If production breaks badly mid-deploy or in the first 24 hours:

**Frontend rollback (instant):**
- Vercel dashboard → Deployments → previous successful → "Promote to Production"

**Backend rollback (~2 min):**
- Render dashboard → findme-api → Manual Deploy → pick a previous successful commit
- OR via MCP: tell Claude to deploy the previous commit SHA

**Data rollback (drastic, ~30 min):**
- pg_restore from `/tmp/findme-local.dump` (kept locally) into Render Postgres again
- Note: any user data created in production (registrations, search history) is lost

---

## HARD RULES

- Never commit `.env*` or any production secrets
- Never paste API keys directly into chat — use the no-echo zsh pattern: `read -rs "X?Render API key: "`
- Branch pushed AND CI green AND smoke tests pass = task done. Anything less = not done.
- If a checkpoint fails, **stop and report** — do not "try the next thing"
- If the Render MCP returns an error, retry once. If it fails again, fall back to dashboard interaction (tell user clearly what to click) rather than escalating
- All user-facing text must be in Hebrew

## ─────────────────────────────────────────────────────────────────
## END — copy everything above into Claude Code
## ─────────────────────────────────────────────────────────────────

---

## Appendix — File-level changelog of pre-deploy fixes

The pre-deploy cleanup phase touches these files. If something breaks during Phase 0, this is your map:

| File | Change | Why |
|---|---|---|
| `frontend/src/components/ResultCard.tsx` | Out-of-stock visual treatment | Users were misled by identical styling for sold-out items |
| `api/routes/chat.py` | Sort in-stock first in search results | Out-of-stock items shouldn't dominate top results |
| Database (no schema change) | UPDATE store_products SET price=NULL ... | Installment-extracted prices removed from ~10K products at fashion stores |
| `.venv/` | Recreated from scratch | Old shebangs pointed to non-existent PycharmProjects path |
| `.env` | Added GOOGLE_MAPS_API_KEY (if user provided) | Enables geocoding for 500 remaining physical stores |

---

## Appendix — What was deliberately deferred

These are valid concerns that we are NOT solving in this deploy:

| Item | Why deferred |
|---|---|
| Permanent fix for installment-price scraper | Larger refactor; nulling bad prices ships honest data faster |
| Adding Tav HaZahav voucher network | Requires multi-voucher schema; not pre-launch critical |
| Bulk deduplication beyond initial 0.99 threshold | Marginal quality win; do in week 2 with real usage data |
| Background worker / Celery beat | Saves $14/mo; manual scrapes weekly are fine for v1 |
| Custom domain | Vercel/Render subdomains work; add domain in week 2 if desired |
| Mobile-specific UI fixes | Test on mobile after launch; fix what real users complain about |

---

## Appendix — Why this prompt supersedes the older ones

Old `START_PROMPT.md` (now `START_PROMPT_AWS.md`): the AWS-on-EC2 path. Still valid, but more work (~3-5 hours setup vs. ~2 hours here) and ~$50/mo vs. ~$22/mo. Kept for reference if you ever want to migrate FROM Render TO AWS for scale or compliance reasons.

Old `START_PROMPT_RENDER.md`: deleted. Predated the Render MCP — its Phase 1 walked the user through 30 minutes of dashboard clicking. The MCP collapses that to ~5 minutes of natural-language commands to Claude Code.
