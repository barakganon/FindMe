Read CLAUDE.md at /Users/barakganon/PycharmProjects/PythonProject/FindMe/CLAUDE.md fully before doing anything.
Read STATUS.md at /Users/barakganon/PycharmProjects/PythonProject/FindMe/STATUS.md fully before doing anything.
Read the "Git Workflow" section of CLAUDE.md — this is mandatory for every agent.

You are the Orchestrator for FindMe. Execute three sprints using parallel subagents.
Base branch: master. Remote: origin (https://github.com/barakganon/FindMe.git)

---

## GIT RULES — apply to every agent, no exceptions

1. Every agent starts with: `git checkout master && git pull origin master && git checkout -b <branch>`
2. Commit after every working piece — minimum 1 commit per task, target 2–3
3. Format: `feat(scope): description` / `fix(scope): description` / `chore(scope): description`
4. Always stage specific files: `git add path/to/file.py` — never `git add .`
5. Push branch when done: `git push origin <branch-name>`
6. A task is NOT complete until the branch is pushed to origin
7. The orchestrator merges all branches to master in Phase 4 using --no-ff

---

## PHASE 1 — UI Sprint (single agent, run first, ~45 min)

Spawn one subagent:

```
You are the Frontend UI Agent for FindMe.
Project: /Users/barakganon/PycharmProjects/PythonProject/FindMe
Read CLAUDE.md sections "Active Sprint: UI Redesign", "UI Design Spec", and "Git Workflow" fully.

GIT SETUP — do this before any file changes:
git checkout master && git pull origin master
git checkout -b feature/chat-ui-redesign

TASK 1 — frontend/src/App.tsx
Delete tab switcher, product search panel, store search panel, and ALL their state.
Keep only: SessionContext state, ChatInterface rendering, header, footer.
Commit: git add frontend/src/App.tsx && git commit -m "feat(ui): remove tabs, make chat the single screen"

TASK 2 — frontend/src/components/ChatInterface.tsx
Full redesign per UI Design Spec in CLAUDE.md:
- Fixed header (56px): FindMe logo + BuyMe badge
- Suggestion chips on first load (hide after first message sent):
  "🍽️ מסעדות בתל אביב" | "🎧 אוזניות סוני" | "👗 חנויות אופנה לידי" | "💄 ספא וטיפוח"
- User bubble: right, bg-blue-600, rounded-2xl rounded-tr-sm
- Assistant bubble: left, bg-white border-gray-100 shadow-sm, rounded-2xl rounded-tl-sm
- GPS button inline in assistant bubble when needs_location=true; auto-resend after GPS acquired
- Results grid below bubble (max 6, horizontal scroll mobile, 3-col desktop)
- StoreMap (220px) below cards when coordinates available
- Loading: 3 bouncing dots
- Fixed input bar: RTL input + blue circle send button (arrow-up SVG)
- Opening message: "שלום! 👋 אני FindMe. תגיד לי מה אתה מחפש ואני אמצא היכן להשתמש בכרטיס BuyMe שלך."
Commit: git add frontend/src/components/ChatInterface.tsx && git commit -m "feat(ui): redesign ChatInterface with WhatsApp-style bubbles and suggestion chips"

TASK 3 — frontend/src/components/ResultCard.tsx
Compact card for use inside chat bubbles. Show image_url if available. "מחיר לא זמין" when null.
Commit: git add frontend/src/components/ResultCard.tsx && git commit -m "feat(ui): compact ResultCard with image support and null-price handling"

TASK 4 — frontend/src/components/StoreCard.tsx
Colored category badges: מסעדה=orange, חנות=blue, ספא=purple. Show distance + product count.
Commit: git add frontend/src/components/StoreCard.tsx && git commit -m "feat(ui): add colored category badges and distance to StoreCard"

TASK 5 — frontend/index.html + frontend/src/index.css
PWA meta tags, system font, title "FindMe — חיפוש BuyMe", smooth scroll.
Commit: git add frontend/index.html frontend/src/index.css && git commit -m "chore(pwa): add theme-color meta, system font, smooth scroll"

PUSH:
git push origin feature/chat-ui-redesign

Verify: cd frontend && npm run dev — zero TypeScript errors. No tabs visible. Chips on load.

Append to STATUS.md:
## UI Agent — [date]
| Task | Status | Commits |
|------|--------|---------|
| App.tsx — remove tabs | ✅ Done | feat(ui): remove tabs |
| ChatInterface.tsx redesign | ✅ Done | feat(ui): redesign ChatInterface |
| ResultCard.tsx compact | ✅ Done | feat(ui): compact ResultCard |
| StoreCard.tsx badges | ✅ Done | feat(ui): colored category badges |
| PWA meta + fonts | ✅ Done | chore(pwa): add meta tags |
Branch: feature/chat-ui-redesign → pushed ✅
```

Wait for this agent to complete (STATUS.md shows ✅) before launching Phase 2.

---

## PHASE 2 — 6 parallel agents (launch simultaneously after Phase 1 done)

---

### AGENT 1 — DB Agent

```
You are the DB Agent for FindMe.
Project: /Users/barakganon/PycharmProjects/PythonProject/FindMe
Read CLAUDE.md "Infrastructure Sprint Task List" and "Future Sprint: User Accounts" DB Schema.
Read the "Git Workflow" section.

GIT SETUP:
git checkout master && git pull origin master
git checkout -b infra/db-migrations-price-users

TASK 1 — Alembic migration 0005 (price_changes table)
File: db/migrations/versions/0005_price_changes.py
Table: price_changes (id UUID PK, store_product_id UUID FK, old_price, new_price,
old_availability BOOL, new_availability BOOL, detected_at TIMESTAMPTZ)
Indexes: (store_product_id, detected_at DESC) and (detected_at DESC)
Commit: git add db/migrations/versions/0005_price_changes.py && git commit -m "feat(db): add price_changes table migration 0005"

TASK 2 — Add PriceChange ORM model
File: db/models.py
Commit: git add db/models.py && git commit -m "feat(db): add PriceChange SQLAlchemy model"

TASK 3 — Alembic migration 0006 (all 7 user tables)
File: db/migrations/versions/0006_user_accounts.py
Tables in order: users, user_locations, user_voucher_cards, user_preferences,
user_implicit_signals, user_inferred_attributes, user_search_history, user_favorite_stores
All with correct FKs, indexes, and UNIQUE constraints as specified in CLAUDE.md.
Commit: git add db/migrations/versions/0006_user_accounts.py && git commit -m "feat(db): add 7 user account tables migration 0006"

TASK 4 — Add all 7 user ORM models
File: db/models.py
back_populates not backref. cascade="all, delete-orphan" on user→child.
Commit: git add db/models.py && git commit -m "feat(db): add User, UserLocation, VoucherCard, Preferences, ImplicitSignals, InferredAttributes, SearchHistory, FavoriteStore ORM models"

TASK 5 — Run migrations
source .venv/bin/activate && python -m alembic upgrade head
Confirm both 0005 and 0006 applied. If errors, fix and commit the fix.

PUSH:
git push origin infra/db-migrations-price-users

Append to STATUS.md:
## DB Agent — [date]
| Task | Status | Commits |
|------|--------|---------|
| Migration 0005 price_changes | ✅ Done | feat(db): add price_changes |
| PriceChange ORM model | ✅ Done | feat(db): add PriceChange model |
| Migration 0006 user tables | ✅ Done | feat(db): add 7 user tables |
| User ORM models | ✅ Done | feat(db): add User* models |
| Migrations applied | ✅ Done | alembic upgrade head OK |
Branch: infra/db-migrations-price-users → pushed ✅
```

---

### AGENT 2 — API Infra Agent (Redis + Cache + Admin)

```
You are the API Infrastructure Agent for FindMe.
Project: /Users/barakganon/PycharmProjects/PythonProject/FindMe
Read CLAUDE.md "Infrastructure Sprint" Component 1 (Redis) and Component 4 (Admin).
Read the "Git Workflow" section.

GIT SETUP:
git checkout master && git pull origin master
git checkout -b infra/redis-cache-admin

TASK 1 — api/dependencies.py: add get_redis() + redis_url to Settings
Commit: git add api/dependencies.py && git commit -m "feat(infra): add get_redis() async dependency and redis_url setting"

TASK 2 — api/cache.py (new file)
Functions: get_search_cache, set_search_cache, get_intent_cache, set_intent_cache
SHA256 keys. Always try/except. Cache miss returns None.
Commit: git add api/cache.py && git commit -m "feat(cache): add Redis search and intent cache helpers"

TASK 3 — api/routes/search.py: wire cache
Check cache before embed → return if hit. Set cache after search.
Commit: git add api/routes/search.py && git commit -m "feat(cache): wire Redis cache into POST /search — skip Gemini on cache hit"

TASK 4 — api/routes/chat.py: wire intent cache in _parse_intent()
Commit: git add api/routes/chat.py && git commit -m "feat(cache): wire Redis intent cache into _parse_intent()"

TASK 5 — api/routes/admin.py (new file): GET /api/admin/health
Query DB stats, check redis.ping(), return JSON as per CLAUDE.md spec.
Commit: git add api/routes/admin.py && git commit -m "feat(admin): add GET /api/admin/health endpoint with DB and Redis stats"

TASK 6 — api/main.py: register admin router + update .env.example
Commit: git add api/main.py .env.example && git commit -m "chore(infra): register admin router, add REDIS_URL to .env.example"

PUSH:
git push origin infra/redis-cache-admin

Verify: uvicorn api.main:app --reload — starts clean. GET /api/admin/health returns JSON.

Append to STATUS.md:
## API Infra Agent — [date]
Branch: infra/redis-cache-admin → pushed ✅
6 commits. Cache wired into search + chat. /api/admin/health live.
```

---

### AGENT 3 — Scraper/Celery Agent

```
You are the Scraper Agent for FindMe.
Project: /Users/barakganon/PycharmProjects/PythonProject/FindMe
Read CLAUDE.md "Infrastructure Sprint" Component 2 (Scheduler) fully.
Read scraper/scheduler.py fully before editing.
Read the "Git Workflow" section.

GIT SETUP:
git checkout master && git pull origin master
git checkout -b infra/celery-tasks

TASK 1 — scrape_buyme_store_list: wire DB upsert
asyncpg upsert on buyme_url conflict. Enqueue scrape_shopify_stores for new stores.
Write ScrapeRun row.
Commit: git add scraper/scheduler.py && git commit -m "feat(scraper): wire scrape_buyme_store_list to DB upsert + enqueue new stores"

TASK 2 — add scrape_shopify_stores task
Query stores WHERE scrape_status='success'. Run ShopifyProductScraper. Upsert products.
Write price_changes on price diff. Call embed_new_products.delay() after.
Commit: git add scraper/scheduler.py && git commit -m "feat(scraper): add scrape_shopify_stores weekly Celery task"

TASK 3 — add scrape_sitemap_stores task
Same as Task 2 but WHERE scrape_status='done' and use SitemapScraper.
Commit: git add scraper/scheduler.py && git commit -m "feat(scraper): add scrape_sitemap_stores bi-weekly Celery task"

TASK 4 — add embed_new_products task
Query WHERE embedding_vector IS NULL LIMIT 5000. Batch embed via Gemini. Update DB.
Commit: git add scraper/scheduler.py && git commit -m "feat(scraper): add embed_new_products daily Celery task"

TASK 5 — fill in detect_price_changes (remove TODO stub)
Commit: git add scraper/scheduler.py && git commit -m "feat(scraper): implement detect_price_changes task"

TASK 6 — update beat_schedule with all 4 schedules per CLAUDE.md
Commit: git add scraper/scheduler.py && git commit -m "chore(scraper): update beat_schedule with 4 production cron schedules"

PUSH:
git push origin infra/celery-tasks

Append to STATUS.md:
## Scraper Agent — [date]
Branch: infra/celery-tasks → pushed ✅
6 commits. All 4 Celery tasks implemented and scheduled.
```

---

### AGENT 4 — DevOps Agent

```
You are the DevOps Agent for FindMe.
Project: /Users/barakganon/PycharmProjects/PythonProject/FindMe
Read CLAUDE.md "Infrastructure Sprint" Component 5 (Docker) and "New .env variables" section.
Read the "Git Workflow" section.

GIT SETUP:
git checkout master && git pull origin master
git checkout -b infra/docker-devops

TASK 1 — docker-compose.yml (new)
Services: redis, postgres, celery-worker, celery-beat. Volumes: redis_data, postgres_data.
Commit: git add docker-compose.yml && git commit -m "infra(docker): add docker-compose with redis, postgres, celery worker+beat"

TASK 2 — Dockerfile (new)
FROM python:3.11-slim. Install requirements. playwright install chromium.
Commit: git add Dockerfile && git commit -m "infra(docker): add Dockerfile for API service"

TASK 3 — .dockerignore (new)
Exclude .venv, __pycache__, .env, node_modules, etc.
Commit: git add .dockerignore && git commit -m "chore(docker): add .dockerignore"

TASK 4 — requirements.txt
Add: redis[asyncio], python-jose[cryptography]==3.3.0, passlib[bcrypt]==1.7.4, authlib==1.3.0
Commit: git add requirements.txt && git commit -m "chore(deps): add redis[asyncio], python-jose, passlib, authlib"

TASK 5 — .env.example
Add all missing keys: REDIS_URL, CELERY_*, SEARCH_CACHE_TTL, GOOGLE_MAPS_API_KEY, JWT_SECRET, GOOGLE_CLIENT_*.
Commit: git add .env.example && git commit -m "chore(config): add Redis, JWT, Google OAuth keys to .env.example"

PUSH:
git push origin infra/docker-devops

Append to STATUS.md:
## DevOps Agent — [date]
Branch: infra/docker-devops → pushed ✅
5 commits. Docker Compose, Dockerfile, deps, env vars all done.
```

---

### AGENT 5 — API Auth Agent

```
You are the API Auth Agent for FindMe.
Project: /Users/barakganon/PycharmProjects/PythonProject/FindMe
Read CLAUDE.md "Future Sprint: User Accounts" — Auth Strategy, User Profile API,
How Preferences Improve Search Results, LLM Attribute Inference, Anonymous→Registered path.
Read the "Git Workflow" section.
WAIT: Check STATUS.md — DB Agent must have pushed infra/db-migrations-price-users before you start.

GIT SETUP:
git checkout master && git pull origin master
git checkout -b feature/auth-backend

TASK 1 — api/auth.py (new)
JWT: create_access_token, decode_access_token. Passwords: hash_password, verify_password.
get_current_user (raises 401), get_optional_user (returns None — NEVER raises).
Commit: git add api/auth.py && git commit -m "feat(auth): add JWT utils, get_current_user, get_optional_user dependencies"

TASK 2 — api/routes/auth.py (new)
POST /auth/register, POST /auth/login, POST /auth/google, GET /auth/me, POST /auth/import-session
Commit: git add api/routes/auth.py && git commit -m "feat(auth): add register, login, google OAuth, me, import-session routes"

TASK 3 — api/routes/users.py (new)
All profile endpoints: me, locations, vouchers, preferences, favorites, history, inferred.
Commit: git add api/routes/users.py && git commit -m "feat(auth): add user profile, locations, vouchers, preferences, favorites, history, inferred endpoints"

TASK 4 — api/chat_utils.py (new)
build_user_context_block(), merge_preferences_into_search(), apply_inferred_attributes()
Commit: git add api/chat_utils.py && git commit -m "feat(personalization): add user context builder and preference merge utilities"

TASK 5 — api/inference.py (new)
extract_and_update_attributes() — ATTRIBUTE_EXTRACTOR_SYSTEM Hebrew prompt, asyncio.create_task pattern.
Never raises. Confidence threshold 0.5.
Commit: git add api/inference.py && git commit -m "feat(inference): add LLM attribute extractor with upsert and confidence threshold"

TASK 6 — api/routes/chat.py: wire auth + personalization
Add get_optional_user dependency. If user: load prefs → build context → merge → infer (fire+forget).
Anonymous users: identical behavior to before.
Commit: git add api/routes/chat.py && git commit -m "feat(personalization): wire user context and inference into POST /api/chat"

TASK 7 — api/main.py: register auth + users routers
Commit: git add api/main.py && git commit -m "chore(auth): register auth and users routers in FastAPI app"

PUSH:
git push origin feature/auth-backend

Verify: uvicorn starts. POST /api/auth/register returns token. Anonymous POST /api/chat still works.

Append to STATUS.md:
## API Auth Agent — [date]
Branch: feature/auth-backend → pushed ✅
7 commits. Auth, user routes, personalization, inference all implemented.
```

---

### AGENT 6 — Frontend Auth Agent

```
You are the Frontend Auth Agent for FindMe.
Project: /Users/barakganon/PycharmProjects/PythonProject/FindMe
Read CLAUDE.md "Future Sprint: User Accounts" — Frontend Auth UX fully.
Read the "Git Workflow" section.
WAIT: Check STATUS.md — UI Agent AND API Auth Agent must both show ✅ before you start.

GIT SETUP:
git checkout master && git pull origin master
git checkout -b feature/auth-frontend

TASK 1 — frontend/src/store/auth.ts (new)
AuthState interface. loadAuth(), saveAuth(), clearAuth(), getAuthHeader() functions.
JWT stored in localStorage.
Commit: git add frontend/src/store/auth.ts && git commit -m "feat(auth): add auth state store with JWT localStorage handling"

TASK 2 — frontend/src/types.ts: add auth types
User, AuthState, UserLocation, VoucherCard, UserPreferences, InferredAttribute, FavoriteStore, SearchHistoryItem
Commit: git add frontend/src/types.ts && git commit -m "feat(auth): add User, InferredAttribute, and auth-related TypeScript types"

TASK 3 — frontend/src/api.ts: add auth API functions + auth headers
Add getAuthHeader() to all existing fetches.
Add: register, login, loginGoogle, getMe, importSession, updatePreferences,
getInferred, deleteInferred, confirmInferred, addFavorite, getFavorites.
Commit: git add frontend/src/api.ts && git commit -m "feat(auth): add register/login/profile API functions and auth header to all requests"

TASK 4 — frontend/src/components/ChatInterface.tsx: wire auth UX
On load: call loadAuth() → greet by name if logged in.
Avatar/initials circle in header. Click → open ProfileDrawer.
Soft registration prompt after 3rd search (inline form, no page navigation).
On register success: call saveAuth() + importSession().
Commit: git add frontend/src/components/ChatInterface.tsx && git commit -m "feat(auth): add inline registration prompt, avatar header, and auth state to ChatInterface"

TASK 5 — frontend/src/components/ProfileDrawer.tsx (new)
Side drawer: locations, voucher cards, preferences, history, inferred attributes section.
Inferred section shows confidence bars + confirm/delete buttons.
Low-confidence items grayed with "לא משפיע על חיפושים עד שתאשר".
Commit: git add frontend/src/components/ProfileDrawer.tsx && git commit -m "feat(auth): add ProfileDrawer with locations, vouchers, preferences, and inferred attributes UI"

TASK 6 — frontend/src/App.tsx: add profileDrawerOpen state
Commit: git add frontend/src/App.tsx && git commit -m "chore(auth): add profileDrawerOpen state to App.tsx"

PUSH:
git push origin feature/auth-frontend

Verify: npm run dev — no TypeScript errors. Anonymous mode works. Register flow works inline.

Append to STATUS.md:
## Frontend Auth Agent — [date]
Branch: feature/auth-frontend → pushed ✅
6 commits. Auth store, types, API functions, ChatInterface wired, ProfileDrawer done.
```

---

## PHASE 3 — Tests (single agent, after all Phase 2 agents show ✅)

```
You are the Test Agent for FindMe.
Project: /Users/barakganon/PycharmProjects/PythonProject/FindMe
Read all new files from Phase 2 before writing tests.
Read the "Git Workflow" section.

GIT SETUP:
git checkout master && git pull origin master
git checkout -b test/auth-cache-inference

TASK 1 — tests/api/test_auth.py (8 tests)
register, duplicate email, login valid, login wrong password, get_me, invalid token,
anonymous chat still works, import-session.
Commit when passing: git add tests/api/test_auth.py && git commit -m "test(auth): add 8 auth route tests"

TASK 2 — tests/api/test_preferences.py (6 tests)
get empty, set preference, preference applied to search, get inferred empty,
inferred stored after chat, delete inferred.
Mock Gemini. Commit when passing: git add tests/api/test_preferences.py && git commit -m "test(preferences): add 6 preference and inference tests"

TASK 3 — tests/api/test_cache.py (4 tests)
search cache miss, search cache hit (Gemini NOT called), intent cache miss, intent cache hit.
Use fakeredis. Commit when passing: git add tests/api/test_cache.py && git commit -m "test(cache): add 4 Redis cache tests with fakeredis"

PUSH:
git push origin test/auth-cache-inference

Run: pytest tests/ -v — report total passing count.

Append to STATUS.md:
## Test Agent — [date]
Branch: test/auth-cache-inference → pushed ✅
18 new tests passing. Total: [N] passed, 0 failed.
```

---

## PHASE 4 — Orchestrator merges all branches (you do this)

Check STATUS.md — all agents must show branch pushed ✅.

Merge in this order (each must have clean merge before next):
```bash
cd /Users/barakganon/PycharmProjects/PythonProject/FindMe
source .venv/bin/activate

# 1. DevOps (no conflicts — new files only)
git checkout master && git pull origin master
git merge --no-ff infra/docker-devops -m "Merge branch 'infra/docker-devops': Docker Compose, Dockerfile, deps"
git push origin master

# 2. DB migrations (must be second — other branches depend on models)
git merge --no-ff infra/db-migrations-price-users -m "Merge branch 'infra/db-migrations-price-users': price_changes + user tables"
git push origin master

# 3. Redis cache + admin
git merge --no-ff infra/redis-cache-admin -m "Merge branch 'infra/redis-cache-admin': Redis cache layer and admin health endpoint"
git push origin master

# 4. Celery tasks
git merge --no-ff infra/celery-tasks -m "Merge branch 'infra/celery-tasks': 4 Celery scraper tasks wired"
git push origin master

# 5. UI redesign
git merge --no-ff feature/chat-ui-redesign -m "Merge branch 'feature/chat-ui-redesign': single-screen chat, WhatsApp UI"
git push origin master

# 6. Auth backend (after DB merged)
git merge --no-ff feature/auth-backend -m "Merge branch 'feature/auth-backend': JWT auth, user routes, inference engine"
git push origin master

# 7. Auth frontend (after auth-backend merged)
git merge --no-ff feature/auth-frontend -m "Merge branch 'feature/auth-frontend': inline auth, ProfileDrawer, inferred attributes UI"
git push origin master

# 8. Tests
git merge --no-ff test/auth-cache-inference -m "Merge branch 'test/auth-cache-inference': 18 new tests for auth, cache, inference"
git push origin master

# Final verification
redis-server &
python -m alembic upgrade head
uvicorn api.main:app --reload &
pytest tests/ -v
```

After all merges pass and tests green:
- Update CLAUDE.md "Current State" section
- Update STATUS.md with final merge summary
- Delete all merged local branches: git branch -d infra/docker-devops infra/db-migrations-price-users etc.

---

## HARD RULES FOR ALL AGENTS

- api/schemas.py and api/prompts.py are READ-ONLY — never modify
- Never rewrite search.py or stores.py — import and reuse
- get_optional_user NEVER blocks anonymous users — critical invariant
- Inference failures are ALWAYS swallowed silently — never affect user response
- Inferred attributes BOOST only, NEVER filter/restrict
- All user-facing text in Hebrew
- Never `git add .` — stage specific files only
- Branch pushed = task done. Not pushed = not done.
