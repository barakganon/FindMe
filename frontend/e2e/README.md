# FindMe E2E — Epic 6 kill-gate + Story 5.7 checklist automation

One command replaces the Epic 6 launch-validation manual checklist and the
outstanding Story 5.7 manual UI checks.

## Running the full local stack

```bash
# terminal 1 — postgres + redis (adjust if you run these via docker-compose)
docker-compose up postgres redis

# terminal 2 — backend
cd /Users/barakganon/personal_projects/FindMe
source .venv/bin/activate
python -m alembic upgrade head   # only if migrations are pending
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000

# terminal 3 — frontend dev server (vite proxies /api -> :8000)
cd frontend
npm run dev   # serves on http://localhost:5173

# terminal 4 — run the suite
cd frontend
npm ci
npx playwright install chromium   # first run only
npm run e2e
```

`playwright.config.ts` targets `http://localhost:5173` by default. Override
with `E2E_BASE_URL=https://<render-url> npm run e2e` to point at a deployed
environment once Epic 6 deploy lands.

## Test -> kill-gate / checklist mapping

| Test | Epic 6 gate / 5.7 item | What it asserts |
|---|---|---|
| `anonymous visitor completes a Hebrew gift-card search` | 6.2 / 6.5 — anonymous visitor completes a search | Loads app with no auth, submits a Hebrew free-text query, observes the streaming state line (חושב…/מחפש בקטלוג…/etc.) then at least one rendered result (tray populated or an inline result card image) |
| `3-turn conversation accumulates and dedupes the tray` | 5.7 — tray accumulates/dedupes across turns | Sends 3 turns (2nd is a refinement, 3rd repeats the 1st query verbatim) and asserts tray item count never exceeds `TRAY_MAX` (20) and never shrinks turn-over-turn |
| `memory chip strip renders after inference-bearing turn` | 5.7 — memory chips render | Sends a query carrying inferable attributes (child age, location) and confirms the conversation advances without error; chip content itself is inference-dependent so this is a smoke check, not a snapshot |
| `tray persists across reload via localStorage.findme_tray` | 5.7 — tray persists across reload | Sends a turn, reads `localStorage.findme_tray`, reloads the page, confirms the blob is unchanged and the tray still renders populated (not reset to empty state) |

## Known limitations / deferred

- Live execution against a running stack was **deferred** for this task —
  Postgres/Redis/uvicorn were not already running in the sandbox this suite
  was authored in, and provisioning them was out of scope. Before Epic 6
  launch, run the 4-terminal sequence above and confirm all 4 tests pass.
- Test 3's dedup assertion is intentionally loose (`<= 20`, monotonic
  non-decreasing) because live backend result sets vary. Tighten to an exact
  count once a fixture/mock backend is wired in, if stricter regression
  coverage is wanted.
- Test 1's "at least one result" check accepts either a populated tray OR an
  inline `<img alt>` in the assistant bubble, to stay resilient to whether
  the search returns products vs. only stores vs. zero results needing a
  clarify follow-up. If BuyMe inventory ever returns zero results for the
  seeded query, swap in a query known to have supply.
- Selectors are Hebrew-string/role based (per `ChatInterface.tsx` UI copy).
  If that copy changes, update `PLACEHOLDER`, `SEND_LABEL`,
  `TRAY_EMPTY_TEXT`, `TRAY_HEADER_TEXT` constants at the top of
  `killgate.spec.ts`.
