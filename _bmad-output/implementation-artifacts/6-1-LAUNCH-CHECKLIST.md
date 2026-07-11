# Story 6.1 — Launch Checklist (Barak-gated steps, in order)

> Consolidates the "Blocked — needs Barak" items from `6-1-deploy-status.md`
> into one ordered runbook. Every step marked **[SECRET]** needs a value
> only Barak holds; everything else can be run/verified without new secrets.
> None of these steps have been executed by this prep task — this is a plan.

Live service: https://findme-rau7.onrender.com
Existing resources: Postgres `findme-db`, Key Value `findme-kv` (created, not wired).

---

## Step 0 — Reconcile region/plan decision (optional, before or after launch)

`render.yaml` now declares the intended target (frankfurt, standard plan). The
running `findme-api` service is oregon/free. Decide whether to:
  a) leave the running service as-is (oregon/free) for soft launch, or
  b) recreate/migrate it to match `render.yaml` (frankfurt/standard).
This is a cost + latency call — not required to unblock the steps below.

---

## Step 1 — Wire DATABASE_URL / REDIS_URL

**Dashboard action:** Render → `findme-api` → Environment → "Add from database"
→ connect `findme-db` (as `DATABASE_URL` / `DATABASE_URL_SYNC`) and `findme-kv`
(as `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`).

Alternative: copy the **External Database URL** for `findme-db` and the
connection URL for `findme-kv` from their respective dashboard pages and paste
them into `findme-api`'s env vars manually.

**Verify:** `findme-api` → Environment tab shows non-empty values (masked) for
all four keys; service redeploys automatically after an env var change.

---

## Step 2 — [SECRET] Paste GEMINI_API_KEY / GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET

**Dashboard action:** Render → `findme-api` → Environment → add:
- `GEMINI_API_KEY` (required — chat cannot run without it)
- `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` (required for Google OAuth login;
  anonymous chat still works without these, but skip only if OAuth is out of
  scope for soft launch)

**Verify:** redeploy completes; `GET /api/admin/health/detailed` no longer
reports a missing-Gemini-key error (check response body / logs).

---

## Step 3 — Run schema migrations + enable pgvector on the Render DB

Get the **External Database URL** for `findme-db` from its Render dashboard
page ("Connect" → External).

```bash
# Enable pgvector (idempotent)
psql "$RENDER_DB_EXTERNAL_URL" -c "CREATE EXTENSION IF NOT EXISTS vector;"

# Run Alembic migrations against the Render DB
DATABASE_URL_SYNC="$RENDER_DB_EXTERNAL_URL" python -m alembic upgrade head
```

**Verify:**
```bash
psql "$RENDER_DB_EXTERNAL_URL" -c "SELECT extversion FROM pg_extension WHERE extname='vector';"
python -m alembic -x sqlalchemy.url="$RENDER_DB_EXTERNAL_URL" current  # should show 0008 (head)
```

---

## Step 4 — Load the catalog (135,865 products, 99.3% embedded)

Use `scripts/migrate_catalog.sh` (created in this prep task). Dry-run first,
then re-run with `--confirm`:

```bash
# Dry run — prints commands, changes nothing
scripts/migrate_catalog.sh \
  --source "$LOCAL_DB_URL" \
  --target "$RENDER_DB_EXTERNAL_URL"

# Live run
scripts/migrate_catalog.sh \
  --source "$LOCAL_DB_URL" \
  --target "$RENDER_DB_EXTERNAL_URL" \
  --confirm
```

Requires local Postgres running and reachable (`docker-compose up` locally).

**Verify:**
```bash
psql "$RENDER_DB_EXTERNAL_URL" -c "SELECT count(*) FROM products;"                              # ~135865
psql "$RENDER_DB_EXTERNAL_URL" -c "SELECT count(*) FROM products WHERE embedding_vector IS NOT NULL;"  # ~134800 (99.3%)
```

**Watch:** free/standard tier storage cap — if `pg_restore` fails on space,
upgrade the `findme-db` plan before retrying (storage is non-shrinkable once
allocated, so size correctly rather than over-provisioning speculatively).

---

## Step 5 — Set CORS_ORIGINS after frontend deploy (Story 6.2, separate)

Once the frontend is deployed (e.g. to Vercel/Render static site), set:

**Dashboard action:** Render → `findme-api` → Environment → `CORS_ORIGINS` =
`https://<frontend-domain>` (comma-separate multiple origins if needed).

**Verify:** browser console on the deployed frontend shows no CORS errors on
`POST /api/chat/v2/stream`.

---

## Step 6 — Smoke test the agentic chat endpoint end-to-end

```bash
curl -N https://findme-rau7.onrender.com/api/chat/v2/stream \
  -H "Content-Type: application/json" \
  -d '{"message": "יש לי כרטיס BuyMe, מה אפשר לקנות בזול בתל אביב?", "history": []}'
```

**Verify:**
- SSE stream returns `thinking` → `tool_call` → `final` events (not `error`).
- `final` event's `message` field is coherent Hebrew text referencing real
  products/stores (confirms DB + embeddings + Gemini all wired correctly).
- `GET https://findme-rau7.onrender.com/api/admin/health/detailed` reports
  `redis_available: true` with an actual round-trip (not just presence of
  `REDIS_URL`) and `database: ok`.

---

## Quick reference — what's [SECRET] vs. dashboard-only

| Step | Needs a secret only Barak holds? |
|------|-----------------------------------|
| 0. Region/plan decision | No — judgment call |
| 1. Wire DATABASE_URL/REDIS_URL | No — dashboard connect action |
| 2. Paste GEMINI/GOOGLE secrets | **Yes** |
| 3. Migrations + CREATE EXTENSION | No, but needs the External DB URL (semi-sensitive, treat as secret) |
| 4. Load catalog | No, but needs External DB URL + local DB running |
| 5. Set CORS_ORIGINS | No — needs frontend URL, not a secret |
| 6. Smoke test | No |
