# Story 5.9 — Adversarial Code Review

**Branch:** `feature/5-9-cost-deploy-hardening`
**Reviewer:** automated deep-review (2026-06-14)
**Scope:** cost guard, rate limiting, body-size middleware, schemas, render.yaml/deploy, imports

---

## Executive Summary

Seven confirmed issues, three unverified but plausible. The **critical blocker** is rate limiting silently failing in production behind Render's reverse proxy — every client maps to the same internal proxy IP and either (a) shares one rate-limit bucket or (b) never trips 429 at all, depending on whether the bucket fills before midnight. The second-priority issue is the `allow_credentials=True` + wildcard CORS combination, which is a W3C spec violation that browsers enforce by blocking the response (though starlette's own workaround may partially mitigate it). The cost-cap logic, body-size middleware, and deploy config all have lesser but real issues.

---

## Finding 1 — CRITICAL: Rate limiting broken in production (proxy IP shared)

**Severity:** HIGH  
**File:** `scripts/start.sh`, `api/dependencies.py:71`

**Failure scenario:** Render terminates TLS and proxies HTTP internally. The real client IP arrives in the `X-Forwarded-For` header. However, `slowapi`'s `get_remote_address` reads `request.client.host` — which uvicorn sets to the **connecting peer's IP**, i.e. the Render internal proxy/load-balancer, not the browser.

Without `--proxy-headers` (or `--forwarded-allow-ips`) in the uvicorn command, uvicorn does **not** trust or propagate `X-Forwarded-For` into `request.client`. Confirmed by reading `slowapi.util.get_remote_address`:

```python
def get_remote_address(request: Request) -> str:
    if not request.client or not request.client.host:
        return "127.0.0.1"
    return request.client.host  # ← proxy IP, not client IP
```

And `scripts/start.sh`:

```sh
exec uvicorn api.main:app --host 0.0.0.0 --port "${PORT:-8000}"
# ↑ no --proxy-headers flag
```

**Concrete failure:** Every request from every user resolves to the same proxy IP. The "20/minute" chat rate limit fires after the 20th total request *across all users combined*, blocking everyone. Alternatively, the in-memory counter resets on each deploy/restart, so in practice this may never trip at all if the service restarts frequently — making the rate limit silently inoperable.

**Fix:** Add `--proxy-headers --forwarded-allow-ips='*'` to `scripts/start.sh`:

```sh
exec uvicorn api.main:app --host 0.0.0.0 --port "${PORT:-8000}" \
  --proxy-headers --forwarded-allow-ips='*'
```

Alternatively, replace `get_remote_address` with a custom key function that reads `request.headers.get("x-forwarded-for", request.client.host).split(",")[0].strip()`. Either fix is necessary before deploy.

---

## Finding 2 — HIGH: CORS wildcard + `allow_credentials=True` is a spec violation

**Severity:** HIGH  
**File:** `api/main.py:93–98`

**Failure scenario:** The W3C CORS specification explicitly forbids a response with both `Access-Control-Allow-Origin: *` and `Access-Control-Allow-Credentials: true`. Inspecting Starlette's `CORSMiddleware` source (lines 25–27):

```python
simple_headers["Access-Control-Allow-Origin"] = "*"
if allow_credentials:
    simple_headers["Access-Control-Allow-Credentials"] = "true"
```

Both headers are emitted together when `cors_origins="*"` (the default). Modern browsers (Chrome, Firefox) **reject** such responses — they refuse to expose the response body to JavaScript and the fetch() call fails. This means:

1. In development (default CORS_ORIGINS=*): every credentialed CORS request (Google OAuth, JWT cookie) silently fails in the browser.
2. In production, if an operator forgets to set `CORS_ORIGINS` to the frontend URL, the same breakage applies.

Additionally, `allow_credentials=True` is set unconditionally — even when a specific origin list is configured in production, this allows any cross-origin site in the allowed list to send cookies/auth headers. If the allowed list is ever misconfigured to be too broad, this is an escalation path.

**Fix (immediate):** Change the CORS block to:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=_allowed_origins != ["*"],  # only when specific origins are set
    allow_methods=["*"],
    allow_headers=["*"],
)
```

Or, refuse to start with a wildcard origin in non-development mode:

```python
if settings.app_env == "production" and _allowed_origins == ["*"]:
    raise RuntimeError("CORS_ORIGINS must be set to a specific URL in production")
```

---

## Finding 3 — HIGH: `session_id=None` silently disables per-session cost cap for anonymous single-turn users

**Severity:** HIGH (cost safety)  
**File:** `api/routes/chat_v2.py:124`, `api/routes/chat_v2_stream.py:105`

**Failure scenario:** `derive_session_id` returns `None` when the user is anonymous AND no `X-Session-ID` header is provided. The session cap guard is:

```python
if session_id and await is_session_over_budget(redis, session_id, session_budget_usd()):
    raise HTTPException(...)
```

When `session_id is None`, the guard is entirely skipped. An anonymous attacker who deliberately omits the `X-Session-ID` header gets:
- No session cap
- No per-session cost accounting (register_session_cost is called with None, which no-ops due to the guard inside that function)

The only protection left is: per-turn `$0.10` cap in `run_agent`, and the global daily `$20` cap. A single anonymous user can make unlimited calls (within per-turn limits) until the daily budget is exhausted for everyone.

**Severity note:** The per-turn cap provides a meaningful backstop, so this is not unlimited-cost exploitation, but the session cap's intent is defeated for the most-abusable path (unauthenticated, no session header).

**Fix:** Generate a server-side session ID based on client IP when `session_id is None`, or enforce IP-based session cost accounting instead of relying on the client-provided `X-Session-ID`.

---

## Finding 4 — MEDIUM: TOCTOU race in session cost cap (concurrent turns)

**Severity:** MEDIUM  
**File:** `api/agent/cost_guard.py:152–160`

**Failure scenario:** Two simultaneous requests for the same session (rare but possible with frontend retry or tab duplication) both call `is_session_over_budget` before either call completes. Both read `0.40` from Redis (budget = $0.50), both see `0.40 < 0.50`, both proceed to `run_agent`. Each turn costs $0.10, so combined session cost becomes $0.60 — 20% over budget.

This is a classic read-then-act (TOCTOU) pattern. Redis INCRBYFLOAT is atomic, but the read-and-check before the LLM call is not.

**Assessment:** Likely acceptable in practice. The session budget is a soft cap, not a hard financial limit. Redis INCRBYFLOAT ensures the counter is accurate; only the gate check is racy. A 1–2x overshoot on the per-turn cap ($0.10 max overage) is within the design's fail-open philosophy. Document this as a known limitation rather than fix.

**Fix if hardening required:** Replace read-then-act with a Redis Lua script that atomically checks-and-increments, returning whether the pre-increment total was already at budget. This would require restructuring cost accounting to reserve budget before the LLM call.

---

## Finding 5 — MEDIUM: `register_session_cost` not called when `run_agent` raises in streaming path

**Severity:** MEDIUM  
**File:** `api/routes/chat_v2_stream.py:140–143`

**Failure scenario:** Inside `event_stream()`, if `run_agent` raises an exception, the handler yields an error SSE event and immediately returns (early exit at line 143). The `register_session_cost` call at line 178 is never reached.

```python
try:
    result = await run_agent(...)
except Exception as exc:
    yield _sse("error", {...})
    return   # ← exits here; register_session_cost is never called
```

If `run_agent` partially executed (e.g. completed 2 of 3 tool calls, incurring real LLM cost, then raised on the third), the actual cost from partial execution is not credited to the session counter. This can allow a session to run slightly over budget by the unreported amount.

**Note:** The non-streaming `chat_v2.py` path does NOT have this bug because `run_agent` is awaited before the session cost check — but `run_agent` raising means no result object exists, so `result.total_cost_usd` would also not be available. The fundamental issue is that partial-run cost is inaccessible from outside `run_agent` when it raises.

**Fix:** Have `run_agent` return a partial result (with `total_cost_usd`) even on exception, or expose cost as a side-channel (e.g. pass a mutable cost accumulator). Short-term: document the known gap.

---

## Finding 6 — MEDIUM: Body-size middleware only checks `Content-Length` — chunked transfer bypasses it entirely

**Severity:** MEDIUM  
**File:** `api/middleware.py:36–49`

**Failure scenario:** An attacker sending a request with `Transfer-Encoding: chunked` and no `Content-Length` header bypasses the check entirely — `content_length` is `None`, the guard is skipped, and the full body is delivered to the route handler. The middleware's own docstring acknowledges this explicitly:

> "NOTE: we deliberately do NOT buffer the request stream to count bytes for chunked/header-less requests."

The docstring claims "uvicorn's own framing limits backstop the chunked edge case," but uvicorn has no default limit on request body size — it streams indefinitely until the route handler reads or closes the body. There is no backstop.

**Concrete attack:** `curl -X POST http://host/api/chat/v2/stream -H "Transfer-Encoding: chunked" --data-binary @/dev/urandom` streams unlimited data. With a slow consumer, this can exhaust server memory or connection pool limits. With a crafted payload that is under-chunked, the JSON parser will consume arbitrary amounts of memory parsing history arrays.

**Severity note:** The Pydantic `max_length=50` on history and `max_length=2000` on messages limits how much content gets processed — even if a large body arrives, Pydantic will reject it at 422. However, the body must be fully read into memory before Pydantic can validate it. Memory exhaustion is still achievable.

**Fix:** Configure uvicorn's `--limit-max-requests` or use a reverse proxy (nginx/Render's own proxy) that enforces a body size limit at the network layer. The ideal fix is adding `--limit-concurrency` and relying on Render's proxy to enforce request size — document this dependency explicitly.

**256 KiB headroom assessment:** 50 messages × 2000 chars ≈ 100KB of message content alone. With JSON overhead (keys, brackets, base64 if any), 256 KiB (262144 bytes) is tight for a legitimate full-history request. A 50-message history with Unicode (Hebrew averages ~2 bytes/char in UTF-8) can hit 200KB+ easily. This is a legitimate usability concern, not just a security concern. Consider 512 KiB as a safer limit.

---

## Finding 7 — MEDIUM: `@limiter.limit(get_settings().chat_rate_limit)` evaluated at import time

**Severity:** MEDIUM (correctness)  
**File:** `api/routes/chat.py:518`, `api/routes/chat_v2.py:88`, `api/routes/chat_v2_stream.py:70`, `api/routes/search.py:176`, `api/routes/stores.py:131`

**Failure scenario:** Python evaluates decorator arguments at module import time, not at request time. `get_settings().chat_rate_limit` is called when the route module is first imported. The `get_settings()` function is `@lru_cache`, so the limit string is frozen to whatever `CHAT_RATE_LIMIT` was at startup.

This is actually **mostly fine** in production because you want the limit to be fixed at startup. However, it creates a subtle problem:

1. **In tests that use `monkeypatch.setenv`** to override `CHAT_RATE_LIMIT`: the `lru_cache` means the patched value is never seen by the already-instantiated `Limiter` route registrations. Tests that rely on env-var overrides to change rate limits at test time won't work as expected.

2. **The `@limiter.limit` call registers the limit string, not the resolved Limit object** — slowapi re-parses the string on each request. So the string "20/minute" is correct, but if `CHAT_RATE_LIMIT` is set to an invalid string (e.g. "20 per minute"), the error surfaces only on the first request, not at startup.

**Confirmed:** No startup validation of the rate limit string. An invalid `CHAT_RATE_LIMIT` env var silently succeeds at startup, then raises `ValueError` on every request.

**Fix:** Add a startup validation that parses the rate limit strings before serving:

```python
from limits import parse as parse_limit
# In an @app.on_event("startup") or lifespan:
try:
    parse_limit(get_settings().chat_rate_limit)
    parse_limit(get_settings().search_rate_limit)
except ValueError as e:
    raise RuntimeError(f"Invalid rate limit config: {e}")
```

---

## Finding 8 — LOW: `render.yaml` health check path requires live DB + Redis — cold deploys may fail

**Severity:** LOW (deploy reliability)  
**File:** `render.yaml:24`

**Failure scenario:** `healthCheckPath: /api/admin/health` executes a multi-table DB query and a Redis PING. During a cold deploy where the DB or Redis connection is temporarily unavailable (cold pool, slow startup, connection limit hit), the health check fails and Render rolls back the deploy or marks the service as unhealthy, blocking traffic. This is particularly risky on the first deploy or during Redis restarts.

The existing `/health` endpoint at `api/main.py:108` returns `{"status": "ok"}` with no external dependencies — it's the correct liveness probe.

**Fix:** Change `render.yaml` to use the lightweight endpoint:

```yaml
healthCheckPath: /health
```

If deep health is needed for readiness, add a separate `/api/admin/health/ready` endpoint that Render can use separately, or accept the risk with a longer `healthCheckTimeout`.

---

## Finding 9 — LOW: Schemas hardcode length caps, diverging from Settings values

**Severity:** LOW (maintainability)  
**File:** `api/schemas.py:197, 240–243`

**Failure scenario:** `ChatMessage.content` has `max_length=2000` and `ChatRequest.history` has `max_length=50` hardcoded in the Pydantic field definitions. Comments note these "mirror Settings.max_message_length (2000)" but they are not dynamically derived from Settings. If an operator sets `MAX_MESSAGE_LENGTH=1000` in their env, the Pydantic schema still accepts 2000-char messages — the setting has no effect on schema validation.

The `voucher_network` field in both `ChatMessage`, `ChatRequest`, and `SessionContext` has no length cap — an attacker can send an arbitrarily long string. It's not used in LLM context directly, but it's logged and returned in responses, creating a minor denial-of-service vector (large log entries, large response bodies).

**Fix:** Either:
1. Accept the duplication and document it as intentional (schemas are independent of runtime config), or
2. Use a `model_validator` or `field_validator` that reads Settings at validation time for dynamic caps.

For `voucher_network`: add `max_length=64` to all three fields.

---

## Finding 10 — LOW: Duplicate import in `tests/api/test_cache.py`

**Severity:** LOW (code quality)  
**File:** `tests/api/test_cache.py:24`

```python
from api.dependencies import get_db, get_redis, get_settings, Settings, get_settings, Settings
```

`get_settings` and `Settings` are imported twice in the same `from ... import` statement. Python silently accepts this (the second import just rebinds the same name), but it's a clear artifact of copy-paste from the parallel workstream merge. Non-blocking but should be cleaned up.

**Fix:** Deduplicate to:
```python
from api.dependencies import get_db, get_redis, get_settings, Settings
```

---

## Finding 11 — LOW (unverified): `limiter` in-memory storage persists between test runs

**Severity:** LOW (test reliability, unverified)  
**File:** `tests/api/test_rate_limit.py`

slowapi's default backend is in-memory (`MemoryStorage`), and the `limiter` singleton is shared across the entire test process (imported once at `api.dependencies` module load). The `tight_limit_on_chat` fixture restores `_route_limits`, but it does NOT clear the in-memory counter storage. If test ordering causes the `1/day` limit to be partially consumed before `test_chat_returns_429_when_limit_exceeded` runs, the first request may also 429, flipping the assertion.

This is **unverified** — depends on test ordering, which pytest does not guarantee. The use of a unique fake IP `"10.0.0.1"` via `X-Forwarded-For` reduces but does not eliminate the risk (uvicorn in tests doesn't honor `X-Forwarded-For` without `--proxy-headers`, so all test requests share `127.0.0.1` as the client host).

---

## Finding 12 — LOW (unverified): `runtime: docker` may not be valid Render Blueprint syntax

**Severity:** LOW (deploy, unverified)  
**File:** `render.yaml:19`

Render Blueprint spec documentation (as of early 2025) specifies `runtime: docker` for native Docker builds from a Dockerfile. However, Render periodically updates its Blueprint schema, and some older or alternate Blueprint parsers expect just `type: web` with implicit Dockerfile detection. The comment in the YAML ("'docker' runtime tells Render to build from the repo's Dockerfile") suggests this was verified, but was not confirmed against live Render docs during this review.

**Unverified** — test by actually clicking "Apply Blueprint" in the Render dashboard. If `runtime: docker` is not recognized, the Blueprint will fail silently or ignore the Dockerfile, falling back to Render's auto-detect.

---

## Summary Table

| # | Severity | Area | File | Status |
|---|----------|------|------|--------|
| 1 | HIGH | Rate limiting broken behind proxy | `scripts/start.sh` | **CONFIRMED** |
| 2 | HIGH | CORS wildcard + credentials spec violation | `api/main.py:93` | **CONFIRMED** |
| 3 | HIGH | Session cap bypassed when `session_id=None` | `chat_v2.py:124`, `chat_v2_stream.py:105` | **CONFIRMED** |
| 4 | MEDIUM | TOCTOU race in session cost gate | `cost_guard.py:152` | **CONFIRMED** (acceptable) |
| 5 | MEDIUM | Session cost not registered on `run_agent` error | `chat_v2_stream.py:140` | **CONFIRMED** |
| 6 | MEDIUM | Chunked transfer bypasses body-size middleware | `api/middleware.py:36` | **CONFIRMED** |
| 7 | MEDIUM | Rate limit string not validated at startup | `api/routes/chat.py:518` | **CONFIRMED** |
| 8 | LOW | Health check path requires DB+Redis | `render.yaml:24` | **CONFIRMED** |
| 9 | LOW | Schema caps diverge from Settings; `voucher_network` unbounded | `api/schemas.py:197` | **CONFIRMED** |
| 10 | LOW | Duplicate import in test_cache.py | `tests/api/test_cache.py:24` | **CONFIRMED** |
| 11 | LOW | Rate limit counter persists between tests | `tests/api/test_rate_limit.py` | **UNVERIFIED** |
| 12 | LOW | `runtime: docker` may not be valid Blueprint syntax | `render.yaml:19` | **UNVERIFIED** |

---

## Must-Fix Before Deploy

1. **Finding 1** — Add `--proxy-headers` to `scripts/start.sh`. Without this, rate limiting is inoperable in production.
2. **Finding 2** — Fix CORS to not combine wildcard origin with `allow_credentials=True`. This breaks credentialed requests in-browser with the default config.
3. **Finding 8** — Change `healthCheckPath` to `/health`. Using `/api/admin/health` risks deploy failures on cold start.

## Recommended Fixes (Before Merge)

4. **Finding 9** — Add `max_length=64` to `voucher_network` fields.
5. **Finding 10** — Deduplicate the import in `test_cache.py`.
6. **Finding 3** — Document that anonymous users without `X-Session-ID` are not covered by the session cap (even if not fixed immediately).

## Deferred / Acceptable

- Finding 4 (TOCTOU): acceptable per fail-open design; document in cost_guard.py.
- Finding 5 (streaming error cost): needs `run_agent` refactor; log as deferred-work.
- Finding 6 (chunked bypass): document reliance on Render's proxy for body-size enforcement.
- Finding 7 (startup validation): add to deferred-work or backlog.
- Finding 11 (test counter): investigate if test ordering issues emerge in CI.
- Finding 12 (render.yaml syntax): verify when actually deploying.
