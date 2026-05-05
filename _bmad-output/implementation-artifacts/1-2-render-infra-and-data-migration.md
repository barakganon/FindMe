# Story 1.2: Provision Render infra + migrate data

Status: backlog

> **Spec source of truth:** [START_PROMPT.md](../../START_PROMPT.md) Phases 1–2.
> This file is a thin BMad-shaped index over those phases — DO NOT duplicate
> the deploy commands here. Read START_PROMPT.md and execute it directly.

## Story

As the deploy operator,
I want the production database, cache, and API service stood up via the Render MCP and seeded with the local catalog,
so that the first deploy can serve real queries against real data.

## Acceptance Criteria

1. **Postgres provisioned** — `findme-db` (Render Starter, frankfurt, postgres 16, `vector` extension enabled). Internal + external `DATABASE_URL` saved.
2. **Key Value provisioned** — `findme-cache` (Starter, frankfurt, `allkeys-lru`). Internal `REDIS_URL` saved.
3. **Web Service provisioned** — `findme-api` (Docker runtime, frankfurt, Starter, master branch, auto-deploy). Env vars set per START_PROMPT.md Task 1.4 — `JWT_SECRET` is a fresh `secrets.token_urlsafe(64)`, `CORS_ORIGINS` set to placeholder Vercel URL (will be overwritten in Story 1.3).
4. **First deploy reaches Build OK** — runtime errors at this stage are expected (empty DB).
5. **Alembic migrations applied to Render Postgres** — `python -m alembic upgrade head` reports head = `26d06a1f803b` (or whatever current HEAD is).
6. **Local DB dumped + restored** — `pg_dump --format=custom --compress=9 --exclude-extension=plpgsql` (~120 MB), then `pg_restore --data-only --disable-triggers --jobs=4`.
7. **Counts verified via MCP `query_render_postgres`** — within rounding of: stores ≈ 1,236; products ≈ 135,988; embedded ≈ 134,963; store_products ≈ 181,517.
8. **HNSW embedding index exists** — `SELECT indexname FROM pg_indexes WHERE tablename='products' AND indexname LIKE '%embedding%'` returns a row; if missing, `CREATE INDEX … USING hnsw (embedding_vector vector_cosine_ops)` runs cleanly.
9. **Fresh deploy after data load passes health probes** — `/health` returns 200; `/api/admin/health` reports ≈ 99.2% embedding coverage, DB+Redis up.

## Tasks / Subtasks

- [ ] Task 1: Phase 1 — Render infrastructure (AC: #1, #2, #3, #4)
  - [ ] Generate fresh `JWT_SECRET` via `secrets.token_urlsafe(64)` — START_PROMPT Task 1.1
  - [ ] Create `findme-db` Postgres via Render MCP — START_PROMPT Task 1.2
  - [ ] Create `findme-cache` Key Value via Render MCP — START_PROMPT Task 1.3
  - [ ] Create `findme-api` Web Service via Render MCP, set all env vars — START_PROMPT Task 1.4
  - [ ] Wait for first deploy to reach Build OK (runtime fail expected) — START_PROMPT Task 1.5
- [ ] Task 2: Phase 2 — Data migration (AC: #5, #6, #7, #8, #9)
  - [ ] `pg_dump` local → `/tmp/findme-local.dump` — START_PROMPT Task 2.1
  - [ ] Run alembic upgrade head against Render Postgres via MCP shell or Render Shell — START_PROMPT Task 2.2
  - [ ] `pg_restore --data-only --disable-triggers` against external Render DB URL — START_PROMPT Task 2.3
  - [ ] Verify counts via `query_render_postgres` — START_PROMPT Task 2.4
  - [ ] Rebuild HNSW index if pg_restore didn't bring it through — START_PROMPT Task 2.5
  - [ ] Trigger fresh deploy via env var touch or empty commit — START_PROMPT Task 2.6
  - [ ] Hit `/health` and `/api/admin/health` — START_PROMPT Task 2.7

## Dev Notes

### Authoritative reference

Every command, expected output, and decision lives in [START_PROMPT.md](../../START_PROMPT.md). Do not paraphrase it here — execute it. This stub file exists only so BMad's `/bmad-dev-story` workflow can find and load context.

### Critical safety rules

- **Use Render MCP tools** (`list_services`, `create_postgres`, `create_key_value`, `create_web_service`, `update_environment_variables`, `list_logs`, `query_render_postgres`, etc.). Do NOT walk the user through dashboard clicks — the MCP collapses ~30 min of clicking into ~5 min of natural-language commands.
- **`DATABASE_URL` vs `DATABASE_URL_SYNC`** — internal Postgres URL needs prefix swap: `postgresql+asyncpg://` for the async runtime, `postgresql+psycopg2://` for Alembic. Both go into the env vars on `findme-api`.
- **CORS_ORIGINS placeholder** — set to `https://findme.vercel.app` for now. Story 1.3 will overwrite with the actual Vercel hostname after Vercel provisions.
- **Region** — frankfurt is closest to Israel; Render has no Middle East region. Do not change without asking.
- **First deploy will fail at runtime** — that's normal (empty DB before migrations). Do NOT panic and start poking the service.

### Dependencies

- Story 1.1 (done) — clean code on master
- Render MCP wired at user scope (already done — see STATUS.md "Render MCP — wired up via Claude Code")
- Pre-flight: Vercel signup done, GOOGLE_MAPS_API_KEY available, Gemini paid tier confirmed (per START_PROMPT.md "Pre-flight" section)

### Cost

- Postgres Starter: $7/mo
- Key Value Starter: $7/mo
- Web Service Starter: $7/mo
- Total recurring from this story: $21/mo

### Failure modes to watch

- `pg_restore` warnings about `alembic_version` already populated — expected, harmless
- Vector index missing after pg_restore — see Task 2.5; CREATE INDEX takes 5-10 min for 134K vectors
- pgvector extension not enabled — Render's Postgres requires explicit `vector` extension flag at creation time. If forgotten, drop and recreate the DB (no data lost yet).

### Project Structure Notes

No new files in this story. All work is operational (provisioning + data load). Code is unchanged from master HEAD.

### References

- [START_PROMPT.md](../../START_PROMPT.md) — Phases 1-2, the authoritative spec
- [STATUS.md](../../STATUS.md) — Session 2026-05-03 (Render MCP wiring) and Session 2026-05-03 later (Phase 0 results, current data state)
- [_bmad-output/planning-artifacts/epics.md](../planning-artifacts/epics.md#story-12--provision-render-infra--data-migration) — full story context

## Dev Agent Record

### Agent Model Used

(to be filled by dev agent)

### Debug Log References

(to be filled by dev agent)

### Completion Notes List

(to be filled by dev agent)

### File List

(none expected — this story does not modify code)

## Change Log

(to be filled by dev agent)
