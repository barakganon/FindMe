---
project_name: FindMe
generated: 2026-05-03
generated_by: bmad-create-epics-and-stories (manually authored after code audit)
source_documents:
  - CLAUDE.md
  - STATUS.md
  - START_PROMPT.md
  - ANALYTICS.md
status: draft (pending user review)
---

# FindMe — Epics & Stories

> Conversational search assistant for Israeli BuyMe gift-card holders.
> The product is **feature-complete locally** (29 tests passing, full chat UX, JWT auth, scheduler).
> The active work is **shipping it publicly** and proving it works for real users.

---

## State of play (2026-05-03, post-audit)

### Already shipped (do not re-plan)

| Capability | Evidence |
|---|---|
| Hybrid search (pgvector + ILIKE fallback) | [api/routes/search.py:488](api/routes/search.py) |
| LLM intent parser + response composer | [api/prompts.py](api/prompts.py), [api/routes/chat.py:794](api/routes/chat.py) |
| Store search with geo + chain awareness | [api/routes/stores.py:305](api/routes/stores.py) |
| JWT auth + Google OAuth | [api/auth.py](api/auth.py), [api/routes/auth.py:172](api/routes/auth.py) |
| Inferred-attributes pipeline | [api/inference.py:136](api/inference.py) |
| User profile API (locations, vouchers, prefs, favorites, history, inferred) | [api/routes/users.py:680](api/routes/users.py) |
| Admin health endpoints | [api/routes/admin.py:118](api/routes/admin.py) |
| Redis search + intent cache | [api/cache.py:58](api/cache.py) |
| Celery scheduler — **all 7 tasks fully implemented** | [scraper/scheduler.py:913](scraper/scheduler.py) |
| Frontend chat UI (RTL, GPS inline, suggestion chips, profile drawer) | [frontend/src/components/ChatInterface.tsx:485](frontend/src/components/ChatInterface.tsx) |
| Multi-stage Dockerfile (Playwright fix landed) | [Dockerfile](Dockerfile) |
| Render MCP wired at user scope | `~/.claude.json` |
| Render+Vercel deploy plan | [START_PROMPT.md](START_PROMPT.md) |
| Post-launch SQL playbook | [ANALYTICS.md](ANALYTICS.md) |
| Test baseline | 29/29 passing |
| DB migrations | head = `26d06a1f803b_add_store_enrichment_fields` (past 0008) |
| Local data | 135,988 products / 134,963 embedded / 1,236 stores / 426 geocoded |

### Pending (drives the epics below)

- Pre-deploy data + UI cleanup (Phase 0 of START_PROMPT.md)
- Actual Render + Vercel deployment (Phases 1-4)
- Post-launch monitoring + first-week analytics
- Permanent fix for installment-price scraper (week-1 follow-up)
- Multi-voucher-network expansion (Tav HaZahav, Nofshonit) — backlog
- Mobile-specific UI tuning — backlog (drive from real user feedback)

---

## Epic 1: Public Launch — ship FindMe to real users

**Goal:** Move FindMe from a working local stack to a public URL that real Israeli consumers can use.

**Why now:** The product passes all 29 tests, returns sensible Hebrew results to canonical queries, and has a polished chat UX. Every additional day not in front of users is a day of zero learning. The deploy plan is fully written ([START_PROMPT.md](START_PROMPT.md)) and the Render MCP is wired up.

**Success criteria:**
- Frontend reachable at `https://<vercel-host>` and backend at `https://findme-api.onrender.com`
- All 5 canonical queries return expected intent + result counts against production
- A first non-developer human can register, search, and get useful answers
- Cost stays at the planned ~$22-32/mo (Render Starter × 3 + Vercel Hobby)

**KPIs (verified post-launch via [ANALYTICS.md](ANALYTICS.md) Tier-1 queries):**
- ≥ 99% embedding coverage on production Postgres
- p95 chat latency < 5s for warm cache, < 12s cold
- Anonymous → registered conversion ≥ 5% within first 50 sessions
- ≥ 1 successful end-to-end search per session (no zero-result loops)

**Status:** in-progress

### Story 1.1 — Pre-deploy cleanup

**As** the deploy operator
**I want** the known-bad data and UI issues fixed before users see them
**So that** initial impressions aren't shaped by misleading prices or confusing sold-out items

**Source:** [START_PROMPT.md](START_PROMPT.md) Phase 0

**Acceptance criteria:**

1. **Installment prices nulled at affected stores.** `UPDATE store_products SET price=NULL` for stores in {FOX, Fox Home, שילב, רשת Bגוד, Babystar, SOHO, אהבה קטנה, SWEETWEET, Femina} where `price < 40`. Row count documented in STATUS.md before the UPDATE is committed.
2. **Out-of-stock visual treatment in [ResultCard.tsx](frontend/src/components/ResultCard.tsx).** Card opacity reduced + gray-50 background when `!availability`; replace tiny "● אזל" with prominent red `אזל המלאי` badge; purchase link disabled or relabeled to "לפרטים ←".
3. **In-stock-first sort in [api/routes/chat.py](api/routes/chat.py).** After search results merge in `_run_product_search`, sort `availability=true` rows ahead of `availability=false` rows.
4. **Venv recreated.** `rm -rf .venv && python3 -m venv .venv && pip install -r requirements.txt`. Verified via `head -1 .venv/bin/uvicorn` (shebang must point to `personal_projects`, not `PycharmProjects`).
5. **Tests still pass.** `.venv/bin/pytest tests/ -q` reports `29 passed`.
6. **Frontend still builds.** `cd frontend && npm run build` succeeds.
7. **Branch merged to master.** `deploy/pre-launch-cleanup` merged with `--no-ff`, pushed to `origin/master`.

**Out of scope (deliberately deferred):**
- Permanent scraper-level fix for installment prices → Story 3.1
- Mobile UI fixes → driven by post-launch feedback
- Geocoding the remaining 500 stores → optional (Task 0.6 in START_PROMPT.md, can run from Render Shell post-deploy)
- Bulk deduplication beyond initial 10 merges → optional (Task 0.7)

**Dependencies:** none (all tooling local).

**Estimate:** 45-60 min.

**Status:** ready-for-dev

---

### Story 1.2 — Provision Render infra + migrate data

**As** the deploy operator
**I want** the production database, cache, and API service stood up via the Render MCP and seeded with the local catalog
**So that** the first deploy can serve real queries against real data

**Source:** [START_PROMPT.md](START_PROMPT.md) Phases 1-2

**Acceptance criteria:**

1. **Postgres provisioned.** `findme-db` (Render Starter, frankfurt, postgres 16, `vector` extension enabled). Internal + external `DATABASE_URL` saved.
2. **Key Value provisioned.** `findme-cache` (Starter, frankfurt, `allkeys-lru`). Internal `REDIS_URL` saved.
3. **Web Service provisioned.** `findme-api` (Docker runtime, frankfurt, Starter, master branch, auto-deploy). Env vars set per START_PROMPT.md Task 1.4 — `JWT_SECRET` is a fresh `secrets.token_urlsafe(64)`, `CORS_ORIGINS` set to placeholder Vercel URL (will be overwritten in Story 1.3).
4. **First deploy reaches Build OK.** Runtime errors at this stage are expected (empty DB) — that's the migration phase.
5. **Alembic migrations applied to Render Postgres.** Run via Render Shell or MCP shell tool: `python -m alembic upgrade head`. Output reports `26d06a1f803b` as head.
6. **Local DB dumped + restored.** `pg_dump --format=custom --compress=9 --exclude-extension=plpgsql` → ~120 MB; `pg_restore --data-only --disable-triggers --jobs=4` against `findme-db`.
7. **Counts verified via MCP `query_render_postgres`.** Within rounding of: stores ≈ 1,236; products ≈ 135,988; embedded ≈ 134,963; store_products ≈ 181,517.
8. **HNSW embedding index exists.** `SELECT indexname FROM pg_indexes WHERE tablename='products' AND indexname LIKE '%embedding%'` returns a row; if missing, `CREATE INDEX … USING hnsw (embedding_vector vector_cosine_ops)` runs cleanly.
9. **Fresh deploy after data load passes health probes.** `/health` returns 200; `/api/admin/health` reports ≈ 99.2% embedding coverage, DB+Redis up.

**Out of scope:**
- Background workers (Celery worker + beat) — Story 2.3 (saves $14/mo, manual scrape suffices for v1)
- CMEK / private connectivity hardening — not pre-launch critical

**Dependencies:** Story 1.1 (clean code on master).

**Estimate:** 45 min.

**Status:** backlog

---

### Story 1.3 — Frontend on Vercel + CORS wiring

**As** the deploy operator
**I want** the frontend live on Vercel and the API CORS allowlist updated to match
**So that** real users can hit the chat from a real URL with no console errors

**Source:** [START_PROMPT.md](START_PROMPT.md) Phase 3

**Acceptance criteria:**

1. **Vercel project created** — barakganon/FindMe, root `frontend`, framework Vite, `VITE_API_URL=<Render API URL>`. (User does this manually; no Vercel MCP exists.)
2. **First Vercel deploy succeeds** and serves the chat at the assigned `*.vercel.app` URL.
3. **`CORS_ORIGINS` env var on Render updated via MCP** to include the actual Vercel hostname; redeploy of `findme-api` triggered automatically and finishes cleanly.
4. **Browser smoke test:** open the Vercel URL, send "אוזניות סוני" → 10 products render with proper RTL; click "הירשם" → register a test account → confirm logged-in state; send "מסעדות לידי" → GPS prompt appears.
5. **No CORS errors** in browser DevTools Network/Console panels for the test session.

**Dependencies:** Story 1.2 (Render API live).

**Estimate:** 20 min.

**Status:** backlog

---

### Story 1.4 — Production smoke test + deploy marker

**As** the deploy operator
**I want** an end-to-end check of the live deployment and a permanent record of the launch state
**So that** future regressions can be diagnosed against a known-good baseline

**Source:** [START_PROMPT.md](START_PROMPT.md) Phase 4

**Acceptance criteria:**

1. **Five canonical queries run against production.** Loop in START_PROMPT.md Task 4.1 executes against `https://findme-api.onrender.com/api/chat`. Expected:
   - `אוזניות סוני בבת ים` → intent=product_search, ≥ 5 products
   - `תמצא מסעדות באילת` → intent=store_search (0 stores acceptable — known data gap)
   - `חנויות בגדים באזור שלי, מכנסיים לחתונה, תקציב 200 ש״ח` → intent=clarify (no GPS in curl)
   - `מה אפשר לקנות ב-BuyMe?` → intent=help, returns categories
   - `אני רוצה ל` (truncated) → intent=clarify with Hebrew clarifying question
2. **STATUS.md updated** with a "Session: 2026-05-XX — Production Deploy" section listing both URLs, Render service IDs, and a one-line summary per AC above.
3. **Master commit pushed** with conventional message `docs(status): production deploy complete — live at <url>`.

**Dependencies:** Story 1.3.

**Estimate:** 15 min.

**Status:** backlog

---

### Story 1.5 — Private-beta QA blocker fixes

**As** the operator running a private beta with friends and family
**I want** the 5 BLOCK-tier issues found during the 2026-05-05/06 solo QA pass fixed
**So that** non-developer users get a working app on first impression rather than seeing earrings when they search for Sony headphones

**Source:** [_bmad-output/qa-findings/2026-05-05-solo-qa.md](../qa-findings/2026-05-05-solo-qa.md)

**Acceptance criteria (all BLOCK-tier — must ship together):**

1. **F-11 city matching expanded.** "מסעדות בתל אביב" returns ≥ 50 stores from the `ת"א והסביבה` BuyMe bucket (currently 1). Synonym map handles: `תל אביב` ↔ `ת"א` ↔ `ת״א` ↔ `תא` ↔ `יפו` ↔ `ת"א והסביבה`. Same treatment for Jerusalem (ירושלים ↔ י-ם ↔ ירושלים והסביבה), Haifa (חיפה ↔ חיפה והסביבה), and the 5 other BuyMe regional buckets that include a recognizable city name.

2. **F-01/F-08 brand+category search relevance.** When the parsed intent has a non-null `brand`, search results are restricted to products where `products.brand ILIKE '%<brand>%'`. "Sony headphones" returns Sony products only, no Edifier in the top slot. "Apple Watch" returns watches (not Lightning cables). If the brand filter would yield 0 results, fall back to fuzzy match with a clarifying note in the response message.

3. **F-02 intent parser determinism.** Gemini intent-parse calls use `temperature=0`. Running the same query 10× returns the same `intent` and `needs_user_location` value 10/10 times. Specifically: "מסעדות בתל אביב" is `store_search` 10/10 (was ~80%); "כיסא ארגונומי לעבודה" is `product_search` 10/10.

4. **F-04 reply text never contradicts results.** Response composer cannot output a "no results" framing (לא מצאנו, לא נמצא, etc.) when `len(product_results) > 0`. Enforce in code, not in prompt.

5. **F-09 single brand name returns product_search.** "סמסונג" / "Apple" / "Sony" alone routes to `product_search` with the brand applied, not clarify. Specific test: "סמסונג" returns ≥ 5 products, all with `brand ILIKE '%samsung%'`.

6. **F-03 needs_location synonyms.** Belt-and-suspenders regex post-processing in the chat handler: if the user message matches `(?i)(לידי|באזור שלי|קרוב אלי|קרוב|פה|כאן|near me|by me)`, force `parsed.needs_user_location = True` regardless of what Gemini returned. "חנויות בגדים באזור שלי" returns `needs_location=True`.

7. **F-13 query-time dedup.** When merging hybrid search results, deduplicate by `canonical_name + normalized_price` (where `normalized_price = round(price, 0) if price else 0`). "איפור" no longer returns 4 identical Niveah Rose Care rows.

8. **F-05 / F-12 hide product_count for non-retail stores.** `StoreCard.tsx` hides the `מוצרים` count when `buyme_category` is one of `restaurant`, `spa`, `hotel`, `leisure`. Restaurant cards no longer claim "0 products".

9. **F-06 no English fragments in Hebrew replies.** Response composer never quotes the parsed `product_query` or `store_type` value back to the user. "ספא בירושלים" reply does not contain the word `spa`. Verified via 5-query manual sample.

**Decisions baked in (from user 2026-05-07):**

- F-01 fix approach: **strict brand filter** with empty-fallback to fuzzy
- F-11 fix scope: **synonym map only** for now; geo-radius fallback deferred to Story 3.2
- F-13 dedup approach: **query-time dedup** now; algorithm rewrite deferred to Story 3.1

**Test gates:**

- All 9 ACs validated by re-running the relevant entries from the QA battery in [qa-findings/2026-05-05-solo-qa.md](../qa-findings/2026-05-05-solo-qa.md)
- 29/29 existing tests still pass (no regressions on auth, cache, anonymous fallback, OOS sort, SQL safety)
- New unit tests: brand filter behavior (F-01), city synonym expansion (F-11), location regex (F-03), price-based dedup (F-13), reply contradiction guard (F-04)

**Out of scope (deferred to other stories or future sessions):**

- Permanent installment-price scraper rewrite (Story 3.1 already covers this)
- Geo-radius store search fallback (Story 3.2)
- Bulk dedup algorithm rewrite (separate future story)
- F-07 wrong-category store tagging (Story 3.3 covers this)
- Batteries 2-7 fix-soon issues that didn't make BLOCK tier — these stay open in qa-findings doc for a future Story 1.6 if needed

**Dependencies:** none (all changes are within already-shipped code).

**Estimate:** 1.5–2 dev days for all 9 ACs.

**Status:** ready-for-dev

---

## Epic 2: Post-launch hardening — keep it up, learn from real users

**Goal:** Detect outages within minutes and turn the first 7 days of real usage into product decisions.

**Why now:** Once strangers can hit the URL, the cost of silent breakage rises sharply. And the first week of real queries answers questions that no amount of internal testing can — what cities people actually search, which categories produce zero results, where the LLM mis-routes intent.

**Success criteria:**
- Any outage > 5 min triggers an email alert
- All Tier-1 queries from [ANALYTICS.md](ANALYTICS.md) run and have written interpretations at 24h, 72h, and 7 days
- At least one product decision (scraper priority, prompt tweak, UI fix) traceable to an analytics finding

**Status:** backlog (unblocked by Epic 1 completion)

### Story 2.1 — UptimeRobot monitoring

**As** the operator
**I want** external uptime checks on the frontend and backend health endpoint
**So that** I learn about outages from a notification, not a complaint

**Source:** [START_PROMPT.md](START_PROMPT.md) Phase 5.1

**Acceptance criteria:**
1. UptimeRobot account created (free tier).
2. Two HTTP monitors at 5-min interval:
   - `https://findme-api.onrender.com/health`
   - `https://<vercel-host>/`
3. Email alert on down state, configured to barak@qbiq.ai.

**Dependencies:** Story 1.4.
**Estimate:** 10 min.
**Status:** backlog

---

### Story 2.2 — First-week analytics passes

**As** the operator
**I want** structured reads of the production DB at 24h, 72h, and 7d
**So that** product decisions in week 2 are grounded in real usage rather than guesses

**Source:** [ANALYTICS.md](ANALYTICS.md) (Tier 1)

**Acceptance criteria:**
1. **24h pass.** All Tier-1 queries from [ANALYTICS.md](ANALYTICS.md) run via Render MCP `query_render_postgres`. Findings (one paragraph per query: what the number means, what we'd do about it) appended to STATUS.md.
2. **72h pass.** Same queries re-run; deltas vs 24h interpreted explicitly.
3. **7d pass.** Same queries; one written conclusion: "in week 2, ship X based on Y finding."
4. **At least one decision item** entered into Epic 3 (data quality) or Epic 4 (multi-network) backlog as a direct result of analytics.

**Dependencies:** Story 1.4 + at least 24h of real traffic.
**Estimate:** ~45 min/pass × 3 passes.
**Status:** backlog

---

### Story 2.3 — Background workers (optional, $14/mo)

**As** the operator
**I want** Celery worker + beat running on Render
**So that** the scheduled scrapers + dedup + embed-new-products jobs run automatically without me opening a Shell tab weekly

**Source:** [START_PROMPT.md](START_PROMPT.md) Phase 5.3

**Acceptance criteria:**
1. Render Background Worker `findme-celery-worker` running `celery -A scraper.scheduler worker -Q scraper --concurrency=2 --loglevel=info`.
2. Render Background Worker `findme-celery-beat` running `celery -A scraper.scheduler beat --loglevel=info`.
3. Both share the env vars of `findme-api` (`DATABASE_URL`, `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`, `GEMINI_API_KEY`).
4. After 24h, beat has fired at least one scheduled job (verifiable in Render logs and via a `scrape_runs` row).
5. Costs documented in STATUS.md (~$14/mo added).

**Decision before starting:** confirm with user that the +$14/mo is worth automation now vs. continuing weekly manual triggers via Render Shell. Skip if no.

**Dependencies:** Story 1.4.
**Estimate:** 30 min.
**Status:** backlog (decision-gated)

---

## Epic 3: Data quality — Phase 2

**Goal:** Replace the launch-day band-aids (nulled prices, out-of-stock badge) with permanent fixes once we know which problems matter most.

**Why later (not now):** Each fix here is a multi-day investment. Doing them pre-launch would delay learning what the *actual* user pain points are. ANALYTICS.md will tell us which of these to prioritize.

**Status:** backlog (unblocked by Story 2.2 — driven by analytics findings)

### Story 3.1 — Permanent fix for installment-price scraper bug

**As** a user
**I want** to see real lump-sum prices instead of "מחיר לא זמין" placeholders
**So that** I can compare options before clicking through

**Source:** [STATUS.md](STATUS.md) Session 2026-05-03 → "Installment-price extraction bug"

**Acceptance criteria:**
1. Per-scraper investigation: identify the JSON-LD or DOM selector at FOX, שילב, רשת Bגוד, Babystar, SOHO, אהבה קטנה, SWEETWEET, Femina, Fox Home that's currently returning the installment value.
2. Update each affected scraper to grab the lump-sum price (typically a sibling node or a different `priceCurrency`/`offers` key).
3. Re-scrape the ~10K affected products (manual Celery trigger via Render Shell).
4. Verify: `SELECT s.name_he, count(*) FROM store_products sp JOIN stores s ON s.id=sp.store_id WHERE s.name_he IN (…) AND sp.price IS NOT NULL AND sp.price < 40` returns 0.
5. New regression test in `tests/scraper/` that fixtures one HTML page from each affected store and asserts the parser returns lump-sum, not installment.

**Dependencies:** Story 1.4 (production live so we can see real impact); Story 2.2 24h pass (to confirm impact magnitude).
**Estimate:** 1-2 days.
**Status:** backlog

---

### Story 3.2 — Fill thin geographic categories

**As** a user
**I want** "מסעדות באילת" to return at least one result
**So that** I don't conclude the app is broken on my first regional query

**Source:** [STATUS.md](STATUS.md) — Eilat returns 0 restaurants

**Acceptance criteria:**
1. ANALYTICS Tier-1 surfaces the ranked list of zero-result city/category pairs.
2. For the top 3 such pairs (likely Eilat-restaurants, plus 2 surfaced from real traffic), confirm whether BuyMe actually has partners in that combo. If yes, scrape them. If no, document the gap and leave a graceful empty-state with explicit copy.
3. Frontend empty-state for store_search with 0 results says (in Hebrew) "BuyMe לא תומך כרגע ב<category> ב<city>. נסה <suggestion>." instead of just blank.

**Dependencies:** Story 2.2.
**Estimate:** 1 day.
**Status:** backlog

---

### Story 3.3 — Improve store enrichment + chain coverage

**As** a user searching for "כל סניפי FOX"
**I want** the system to know FOX is a chain, not 47 separate stores
**So that** map UX groups results sensibly

**Source:** Migration `26d06a1f803b_add_store_enrichment_fields` already exists with `parent_chain_id`, `buyme_categories`, `metadata_json`, `redemption_details_url`. [scraper/enrich_stores.py](scraper/enrich_stores.py) drafts the LLM enrichment. Both are landed but not run at scale.

**Acceptance criteria:**
1. Run `enrich_stores.py` against all 1,236 stores; populate `parent_chain_id`, `metadata_json` for each.
2. Validate manually: confirm at least the top 20 known Israeli chains (FOX, Castro, Greg, Isrotel, Shilav, etc.) get `parent_chain_id` set.
3. Update `api/routes/stores.py` to optionally collapse same-chain results into a "X locations" summary card.
4. Frontend StoreCard renders the chain-collapsed shape behind a feature flag (default off — flip on after manual QA).

**Dependencies:** Story 2.2 (analytics tells us if chain-collapsing is actually wanted).
**Estimate:** 2 days.
**Status:** backlog

---

## Epic 4: Multi-voucher network expansion

**Goal:** Validate that the `voucher_network` abstraction in the schema actually carries weight by adding a second network end-to-end.

**Why later:** The `voucher_network` column exists ([db/migrations/versions/0004_voucher_network.py](db/migrations/versions/0004_voucher_network.py)) and the chat layer accepts it as a parameter. But a single network in production teaches nothing about cross-network UX. Do this only after Epic 1 + 2 prove the BuyMe path works.

**Status:** backlog

### Story 4.1 — Tav HaZahav scraper + ingestion

**As** a Tav HaZahav cardholder
**I want** to search where I can spend my voucher
**So that** FindMe is useful to me, not just BuyMe holders

**Acceptance criteria:**
1. New scraper module `scraper/tav_hazahav_*.py` mirrors `buyme_store_scraper.py` shape.
2. New Celery task `scrape_tav_hazahav_store_list` registered + scheduled.
3. Ingested rows have `voucher_network='tav_hazahav'` set throughout.
4. Search returns Tav HaZahav results when `voucher_network='tav_hazahav'` is passed; mixed results when caller asks for both.

**Dependencies:** Epic 1 + Epic 2 complete.
**Estimate:** 3 days.
**Status:** backlog

---

### Story 4.2 — Frontend network selector + per-network branding

**As** a user holding multiple voucher cards
**I want** to choose which network to search against (or all)
**So that** I see only relevant results for the card I'm holding

**Acceptance criteria:**
1. Header shows the active network with a switcher (BuyMe ▾ → Tav HaZahav, Nofshonit, All).
2. Per-network color/logo applied to result cards.
3. Active network persists in `localStorage` for anonymous users; in `user_voucher_cards` for registered users.

**Dependencies:** Story 4.1.
**Estimate:** 1 day.
**Status:** backlog

---

### Story 4.3 — Nofshonit scraper

**As** a Nofshonit cardholder (vacation/leisure-focused)
**I want** the same coverage Tav HaZahav holders got in 4.1
**So that** the third network proves the abstraction generalizes

**Acceptance criteria:** mirror Story 4.1.

**Dependencies:** Story 4.1 (validates the abstraction works for one new network).
**Estimate:** 2 days (faster than 4.1 because the pattern is established).
**Status:** backlog

---

## Notes

- Stories 1.1–1.4 trace 1:1 to Phases 0-4 of [START_PROMPT.md](START_PROMPT.md) — the deploy plan is the authoritative implementation reference.
- Effort estimates assume single-developer pace; multi-agent runs (per [CLAUDE.md](CLAUDE.md) Multi-Agent Architecture) can collapse some serial dependencies.
- This file should be updated when an epic completes (add a "Completed: YYYY-MM-DD" line under the epic header) or when a story is split/merged. Don't rewrite history — append.
