# 6.4 Monitoring Setup Runbook

> **Status: pre-deploy draft.**
> Nothing here is wired up yet — no UptimeRobot account, no prod URL, no alert contacts configured.
> Execute these steps **after Story 6.1 (Render deploy) is live** and the production URL is known.

---

## 1. Uptime Monitoring — UptimeRobot

### Which endpoint to monitor

| Endpoint | Purpose | Use as uptime monitor? |
|----------|---------|----------------------|
| `GET /health` | Liveness only — returns `{"status":"ok"}` instantly, no DB/Redis calls | **Yes — primary monitor** |
| `GET /api/admin/health/detailed` | Component health (DB + Redis) — may report Redis degraded during blips | No — too noisy for paging |
| `GET /api/admin/health` | DB stats + scrape runs — requires DB connection | No — would page on DB slowness |

Use `/health` for uptime. It has no external dependencies and will only go down if the process itself is dead.

### Setup steps (do after 6.1 deploy — needs the prod URL)

1. Create a free UptimeRobot account at https://uptimerobot.com.
2. Add a new **HTTP(s)** monitor:
   - **URL:** `https://<prod-domain>/health`
   - **Friendly name:** FindMe — liveness
   - **Check interval:** 5 minutes
   - **Alert contacts:** add your email (and optionally a Slack webhook if available).
3. Optionally add a second **keyword** monitor against `/api/admin/health/detailed` with keyword `"ok"` for deeper component checks — but set this as a **warning-only** alert (not a page), since a Redis blip should not wake anyone up.

---

## 2. Cost Monitoring — `/api/admin/cost-summary`

### Endpoint (added in Story 6.4)

```
GET /api/admin/cost-summary
```

**Sample response:**

```json
{
  "date": "2026-06-15",
  "daily_cost_usd": 3.47,
  "daily_budget_usd": 20.0,
  "daily_pct_used": 17.35,
  "daily_over_budget": false,
  "redis_available": true
}
```

Fields:
- `date` — UTC date the counter covers (YYYY-MM-DD).
- `daily_cost_usd` — cumulative LLM spend today.
- `daily_budget_usd` — configured limit (`DAILY_COST_BUDGET_USD` env var, default $20).
- `daily_pct_used` — `daily_cost / budget * 100`; can exceed 100 if budget was tripped.
- `daily_over_budget` — true if the cost guard is currently rejecting new v2 chat requests.
- `redis_available` — false if Redis is down (cost counters unreadable; guard is fail-open).

### Thresholds to watch

| Condition | Action |
|-----------|--------|
| `daily_pct_used` > 80 | Investigate traffic spike; consider raising `DAILY_COST_BUDGET_USD` temporarily or checking for abuse via rate-limit logs |
| `daily_over_budget: true` | Budget tripped — v2 chat is falling back to v1 single-shot. Investigate same day; reset counter requires Redis key deletion or waiting for midnight UTC |
| `redis_available: false` | Redis is down — cost guard is fail-open (requests pass through). Fix Redis ASAP |

### How to check

**Option A — Manual daily check (recommended for soft launch):**
```bash
curl https://<prod-domain>/api/admin/cost-summary | jq .
```
Run once a day until traffic patterns are understood.

**Option B — UptimeRobot keyword monitor:**
Add a keyword monitor on `/api/admin/cost-summary` checking that the response body does **not** contain `"daily_over_budget": true`. Set alert interval to 30 minutes. This gives a near-real-time page if budget trips during the day.

**Option C — Daily cron (future):**
A lightweight cron job (Celery beat task) that fetches the summary, logs the result, and emails if `daily_pct_used > 80`. Add this in a later story if Option B proves too noisy.

---

## 3. Error Logging

The app already emits structured `logging` output (Python stdlib). Cost-guard and agent-loop failures are logged at `WARNING`/`ERROR` level.

### Render log stream

Render streams all stdout/stderr to the **Logs** tab in the dashboard. No extra setup needed.

### Recommended log-based alerts (post-deploy)

Configure a log alert in Render (or pipe logs to a service like Papertrail / Logtail) for these patterns:

| Pattern | Severity | Meaning |
|---------|----------|---------|
| `cost_guard: read failed` | WARNING | Redis read error in cost guard — fail-open, requests still served |
| `cost_guard: write failed` | WARNING | Redis write error — cost counter not updated (undercounting) |
| `agent loop error` | ERROR | Unhandled exception in agentic loop — user saw a 500 or degraded response |
| `is_over_budget` (tripped) | INFO | Budget trip — already handled by the cost-summary endpoint |

Alert on any ERROR-level line appearing more than 5 times in a 10-minute window.

---

## 4. What Is NOT Set Up Yet

- No UptimeRobot account created.
- No production URL exists (pending Story 6.1 Render deploy).
- No alert contacts configured.
- No Render log forwarding configured.
- Per-session cost enumeration is intentionally absent from `/api/admin/cost-summary` — iterating all session keys requires a Redis SCAN (O(N)) which is out of scope for a health endpoint. If needed in the future, add a Celery periodic task to aggregate session costs.
