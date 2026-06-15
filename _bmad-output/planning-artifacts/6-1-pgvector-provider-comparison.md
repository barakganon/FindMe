# pgvector Provider Comparison — FindMe 6.1

> Decision one-pager for Story 6.1 (Render backend deploy).
> Written: 2026-06-15. Author: autonomous research agent.
> Supersedes informal notes in `5-9-cost-and-deploy-hardening.md`.

---

## TL;DR Recommendation

**Use Render's own managed Postgres** (created fresh, post-2026).

Render added native pgvector support for all Postgres databases created after
5 February 2026 (and retroactively via support for older DBs). This eliminates
the "external provider" requirement that drove the 5.9 deploy notes. A new Render
Postgres instance in the Frankfurt region sits on the same private network as the
`findme-api` web service, removing a cross-provider network hop and avoiding the
async-driver friction that comes with Supabase's Supavisor pooler. At the Pro-1GB
tier (~$45/month), it is cost-competitive with Supabase Pro ($25/month base but
with compute add-ons) and cheaper than Neon for always-on workloads. The 135k-row
catalog is well within Render's 10 GB storage envelope. The migration path is a
single `pg_dump / pg_restore` plus `alembic upgrade head` — no re-embedding
required because the vector data dumps cleanly.

The only hard verify before committing: confirm the Frankfurt region is selectable
for Render Postgres in the dashboard (it is listed as a Render region but the docs
do not yet enumerate Postgres region parity explicitly).

---

## FindMe-Specific Facts Confirmed

| Fact | Value | Source |
|------|-------|--------|
| Postgres image (local/docker) | `pgvector/pgvector:pg16` | `docker-compose.yml` |
| Embedding column type | `vector(768)` | `0003_embedding_vector_768.py` (migration note: originally `vector(1536)`, resized to 768 for Gemini `text-embedding-004`) |
| Index type | `ivfflat (embedding_vector vector_cosine_ops) WITH (lists = 100)` | `0003_embedding_vector_768.py` |
| Async driver | `asyncpg==0.30.0` | `requirements.txt` |
| DB URL scheme | `postgresql+asyncpg://` | `api/dependencies.py` |
| Row count | ~135,865 products, ~99.3% embedded (~134,800 vector rows) | CLAUDE.md |
| Migration head | 0008 (+ an unlabeled store-enrichment migration) | `db/migrations/versions/` |
| Estimated data size | ~135k rows × 768 dims × 4 bytes = ~415 MB for vectors alone; full DB with text columns likely 1–3 GB | calculated |

---

## Comparison Table

| Criterion | Render Postgres (native, post-Feb-2026) | Supabase Pro | Neon Launch |
|-----------|------------------------------------------|--------------|-------------|
| **pgvector support** | Yes — `CREATE EXTENSION vector;` on PG 13+ [1] | Yes — pre-installed on all plans [2] | Yes — available, enable per project [3] |
| **pgvector version** | Not published — verify [1] | Latest stable (ships with platform) [2] | Latest stable (ships with platform) [3] |
| **Postgres version** | 14, 15, 16 available [1] | 15 (default), 16 (verify) | 16 [3] |
| **Price (entry paid)** | $45/month (Pro-1GB, 10 GB storage) [4] | $25/month base + compute add-ons (cheapest add-on ~$12/month → effective ~$37+) [5] | ~$19–50/month usage-based (compute $0.106/CU-hr; storage $0.35/GB-month) [6] |
| **Region — EU Frankfurt** | Yes (`eu-central` / Frankfurt listed as a Render region) [7] — verify Postgres parity | Yes (`eu-central-1` / Frankfurt on AWS) [8] | Yes (`aws-eu-central-1`, active infra expansion Jun 2026) [9] |
| **Latency to Israel** | ~30–40 ms Frankfurt → Tel Aviv (estimate; same as all Frankfurt-hosted providers) | Same Frankfurt AWS region — same estimate | Same Frankfurt AWS region — same estimate |
| **Connection pooling** | **No built-in pooler** — raw PG connections only [4] | Supavisor (transaction mode, port 6543) [10] | PgBouncer (transaction mode) with prepared-statement support since PgBouncer 1.22 [11] |
| **asyncpg compatibility** | Native — no pooler friction | Requires `statement_cache_size=0` in asyncpg if using pooled port 6543 [12] | Requires `max_prepared_statements > 0` or `statement_cache_size=0` on pooled URL [11] |
| **Max connections (pooled)** | Depends on plan RAM (~25–100 direct PG conns for Pro-1GB) — no pooler | Supavisor client cap per compute tier; effectively hundreds of pooled clients | Up to 10,000 pooled connections [3] |
| **Cold start / always-on** | Always-on (no suspend) | Always-on | **Scale-to-zero by default** — cold start 300–800 ms per search query [6] — risk on hot path |
| **Storage (entry paid)** | 10 GB (Pro-1GB) [4] | 8 GB (Pro base) [5] | Usage-based, $0.35/GB-month [6] |
| **Migration effort** | Low — same PG16+pgvector, pg_dump/restore, alembic upgrade head | Low — same schema; Supavisor URL change + asyncpg tweak | Low — same schema; pooler URL + asyncpg tweak |
| **Notable risks** | No pooler → must use SQLAlchemy pool carefully; storage non-shrinkable [4] | asyncpg prepared-statement friction; Supavisor transaction mode has edge cases [12] | Cold start on the vector-search hot path; usage-based cost unpredictable at scale [6] |
| **Same-network as Render app** | Yes — Render internal networking (no egress costs) [7] | No — cross-provider internet / VPC peering not available | No — cross-provider |
| **Free tier** | 30-day trial only [4] | Yes (0.5 GB, pauses after 1 week inactivity) [5] | Yes (limited compute hours) [6] |

---

## Per-Provider Detail

### 1. Render Postgres (native, managed)

**Status (2026):** pgvector is fully supported on all Postgres 13+ databases. The Render
docs confirm `CREATE EXTENSION vector;` works and list pgvector under supported extensions.
The article "Simplify Your AI Stack with Managed PostgreSQL and pgvector" on render.com
confirms the integration. The 5.9 deploy note ("Render's native Postgres does not include
the pgvector extension") was accurate at the time of writing (early 2026 or earlier) but
**is now out of date** — Render retroactively enabled pgvector for older DBs via support
and natively for all new DBs.

**Pricing:** Pro-1GB ($45/month, 1 GB RAM, 1 vCPU, 10 GB storage) is the right tier for
a ~1–3 GB catalog DB. Storage overage at $0.30/GB/month.

**Connection pooling:** Render Postgres has **no built-in connection pooler**. FastAPI with
SQLAlchemy + asyncpg already maintains an internal connection pool (`pool_size`, `max_overflow`
in the engine settings). For the current load (single Render web service, modest concurrent
users), this is fine — but the SQLAlchemy engine pool settings must be tuned to stay within
the plan's PG `max_connections` (likely 25–100 on Pro-1GB; verify).

**Latency / region:** The app service and DB are on Render's internal network — no public
internet round-trip for DB queries. This is the best-case latency scenario.

**Risk:** Storage autoscales permanently and is non-shrinkable. After initial schema + data
load, make sure you are on the right tier before the first autoscale trigger.

Sources: [1] [Render pgvector extensions](https://render.com/docs/postgresql-extensions),
[4] [Render Postgres pricing breakdown (Kuberns)](https://kuberns.com/blogs/render-postgres-pricing-setup-limits/)

---

### 2. Supabase Pro

**pgvector:** Pre-installed on all plans, no extra charge. Supports IVFFlat and HNSW.
Frankfurt (`eu-central-1`) is an available region.

**Connection pooling:** Supabase replaced PgBouncer with Supavisor (enabled for all projects
since late 2023). Transaction mode (port 6543) is the default pooled endpoint. **asyncpg
breaks with transaction mode** unless `statement_cache_size=0` is passed to the asyncpg
pool/engine. This is a one-line fix but must be applied everywhere the connection is created
(SQLAlchemy engine `connect_args`, `asyncpg.create_pool`, etc.) and must be documented.
Supavisor has made progress on named prepared statements in 2026 but the issue tracker
shows it is not fully resolved for all async drivers.

**Pricing:** $25/month base is misleading. The nano compute add-on ($0/month in free,
$12/month in Pro) is required for production. Effective Pro entry price is ~$37/month
for the smallest production compute, rising quickly with heavier queries.

**Risk:** asyncpg + Supavisor friction is the main risk — one misconfigured connection in
the codebase hits "prepared statement does not exist" errors under load, which are hard
to debug. Cross-provider networking adds ~2–5 ms per query.

Sources: [2] [Supabase pgvector (Kreante)](https://www.kreante.co/post/build-smart-apps-with-supabase-vector-database-semantic-search-guide),
[5] [Supabase pricing (Automation Atlas)](https://automationatlas.io/answers/supabase-pricing-explained-2026/),
[8] [Supabase regions docs](https://supabase.com/docs/guides/platform/regions),
[10] [Supabase connecting to Postgres](https://supabase.com/docs/guides/database/connecting-to-postgres),
[12] [asyncpg + Supavisor issue (Medium)](https://medium.com/@patrickduch93/supabase-pooling-and-asyncpg-dont-mix-here-s-the-real-fix-44f700b05249)

---

### 3. Neon (serverless)

**pgvector:** Supported. Frankfurt (`aws-eu-central-1`) is available with recent capacity
expansion (Jun 2026 changelog). PgBouncer in transaction mode is the pooler; asyncpg
requires `max_prepared_statements` config tweak, similar to Supabase.

**Cold start:** Neon scales to zero by default on the free and Launch tiers. A cold start
takes 300–800 ms before the first query can run. Since `search_products` is on the hot
path of every chat turn, a cold Neon instance would visibly stall the streaming response.
To avoid this, you must either (a) keep the compute always-on (costs extra) or (b)
implement a keep-warm ping every ~5 minutes — adding operational overhead.

**Pricing:** Usage-based since the Databricks acquisition mid-2025. Compute at $0.106/CU-hr.
A 1 CU always-on instance runs ~$76/month (730 hrs × $0.106) before storage. This makes
Neon more expensive than Render or Supabase Pro for an always-on workload.

**Branching:** Neon's signature feature (instant DB branching for dev/staging) is
irrelevant for FindMe — the catalog data is read-heavy and branching would not accelerate
any current workflow.

**Risk:** Cold start on the search hot path is the decisive disqualifier unless always-on
is explicitly configured (raising cost above Render/Supabase). Usage-based billing
also makes monthly cost harder to bound.

Sources: [3] [Neon regions docs](https://neon.com/docs/introduction/regions),
[6] [Neon pricing breakdown (Vela/Simplyblock)](https://vela.simplyblock.io/articles/neon-serverless-postgres-pricing-2026/),
[9] [Neon Frankfurt infra expansion (Neon changelog)](https://neon.com/docs/changelog/2026-06-05),
[11] [Neon PgBouncer prepared statements](https://neon.com/blog/pgbouncer-the-one-with-prepared-statements)

---

## Migration Steps (Recommended: Render Postgres)

These steps assume the recommended provider. Estimated total time: 2–4 hours of engineer
effort + ~30 minutes for data transfer.

### Pre-migration

1. **Confirm pgvector in Render dashboard.** Create a new Render Postgres instance
   (Pro-1GB, Frankfurt region). Run `CREATE EXTENSION vector;` and verify it succeeds.
   If it fails, contact Render support to enable pgvector on the instance.

2. **Pin the local Postgres version.** The local image is `pgvector/pgvector:pg16`.
   Choose PG 16 in the Render Postgres creation wizard for maximum compatibility.

3. **Get the Render DB connection strings.** Render provides both an internal URL
   (for the web service) and an external URL (for admin/Alembic CLI). Note both.

### Data migration

```bash
# 1. Dump from the local (or current source) DB
pg_dump \
  --no-owner --no-acl \
  -h localhost -U barakganon -d buyme_search \
  -F c -f findme_prod_dump.pgdump

# 2. Restore to Render Postgres (use the external/direct URL)
pg_restore \
  --no-owner --no-acl \
  -d "$RENDER_DATABASE_URL_EXTERNAL" \
  findme_prod_dump.pgdump
# pg_restore handles vector columns natively — no special handling needed
# because the vector extension is pre-enabled before restore.
```

> If the dump fails on the `vector` type (e.g. the target DB lacks the extension),
> run `CREATE EXTENSION vector;` on the Render DB first, then re-run pg_restore.

### Schema / Alembic

```bash
# Run Alembic to stamp or advance the migration head.
# If restoring a full dump (schema + data), stamp to current head:
DATABASE_URL_SYNC="$RENDER_DATABASE_URL_SYNC" \
  python -m alembic stamp head

# If restoring data-only (--data-only flag on pg_dump), run migrations first:
DATABASE_URL_SYNC="$RENDER_DATABASE_URL_SYNC" \
  python -m alembic upgrade head
```

### Render secrets

Set these in Render → `findme-api` → Environment → Secrets:

| Secret | Value |
|--------|-------|
| `DATABASE_URL` | `postgresql+asyncpg://<user>:<pass>@<render-internal-host>/<db>` |
| `DATABASE_URL_SYNC` | `postgresql+psycopg2://<user>:<pass>@<render-external-host>/<db>` |

### Smoke test

```bash
# After deploy, hit the health endpoint and check DB connectivity:
curl https://findme-api.onrender.com/api/admin/health/detailed

# Spot-check that vectors are queryable:
# POST /search with a short Hebrew query and confirm results return.
```

### Connection pool tuning (no pooler on Render)

In `api/dependencies.py` (or wherever the SQLAlchemy engine is created), ensure:

```python
engine = create_async_engine(
    settings.database_url,
    pool_size=5,          # conservative; Render Pro-1GB max_connections ~25
    max_overflow=10,
    pool_pre_ping=True,
)
```

No `statement_cache_size=0` needed — Render Postgres is direct PG, so asyncpg
prepared statements work as expected.

---

## Open Questions / Verify Before Committing

1. **Render Postgres region parity (CRITICAL):** Confirm Frankfurt is selectable for
   Postgres (not just for web services) in the Render dashboard. The Render region list
   includes Frankfurt, but Postgres regional availability is not explicitly documented.
   *Action: create a test Render Postgres instance in Frankfurt before any data migration.*

2. **Render Postgres `max_connections` on Pro-1GB:** The exact value is not published
   in public docs. Check `SHOW max_connections;` on a fresh Pro-1GB instance. If it is
   below ~25, the SQLAlchemy pool settings must be tightened.

3. **pgvector version on Render:** The Render extensions page does not publish the
   pgvector version. The IVFFlat index with `lists = 100` is supported by all pgvector
   versions ≥ 0.4.0; verify the installed version with `SELECT extversion FROM pg_extension WHERE extname = 'vector';` after enabling.

4. **Storage autoscale behavior:** Render's storage cannot be shrunk. Confirm the
   initial data size (dump + restore + indexes) before committing to a tier. If the
   DB approaches 9 GB on Pro-1GB (10 GB cap), upgrade manually before the 90%-trigger
   autoscale fires.

5. **Render free tier for development:** The 30-day free trial DB expires. Use a paid
   staging instance or restore to a local docker-compose PG for development to avoid
   data loss.

6. **IVFFlat `lists = 100` tuning:** The index was built with 100 lists. pgvector
   recommends `lists ≈ sqrt(row_count)` for up to a few hundred thousand rows. For
   135k rows, `sqrt(135865) ≈ 369` — the current value of 100 is conservative (faster
   build, slightly lower recall). Rebuilding the index post-migration with `lists = 350`
   is optional but worth scheduling before the soft launch.

7. **Supabase pricing confirmation:** The $25/month Pro base + compute add-on structure
   may have changed since these sources were written. Verify current Supabase pricing
   at supabase.com/pricing before dismissing it.

---

## Sources

1. [Render PostgreSQL Extensions docs](https://render.com/docs/postgresql-extensions)
2. [Supabase pgvector setup guide (Kreante, 2026)](https://www.kreante.co/post/build-smart-apps-with-supabase-vector-database-semantic-search-guide)
3. [Neon Regions docs](https://neon.com/docs/introduction/regions)
4. [Render Postgres pricing breakdown (Kuberns, 2026)](https://kuberns.com/blogs/render-postgres-pricing-setup-limits/)
5. [Supabase pricing explained 2026 (Automation Atlas)](https://automationatlas.io/answers/supabase-pricing-explained-2026/)
6. [Neon pricing breakdown 2026 (Vela/Simplyblock)](https://vela.simplyblock.io/articles/neon-serverless-postgres-pricing-2026/)
7. [Render simplify AI stack with pgvector (Render blog)](https://render.com/articles/simplify-ai-stack-managed-postgresql-pgvector)
8. [Supabase platform regions docs](https://supabase.com/docs/guides/platform/regions)
9. [Neon changelog Jun 2026 — Frankfurt infra expansion](https://neon.com/docs/changelog/2026-06-05)
10. [Supabase connecting to Postgres (Supabase docs)](https://supabase.com/docs/guides/database/connecting-to-postgres)
11. [Neon PgBouncer + prepared statements blog](https://neon.com/blog/pgbouncer-the-one-with-prepared-statements)
12. [asyncpg + Supavisor incompatibility (Medium)](https://medium.com/@patrickduch93/supabase-pooling-and-asyncpg-dont-mix-here-s-the-real-fix-44f700b05249)
