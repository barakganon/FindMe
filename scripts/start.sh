#!/usr/bin/env sh
# scripts/start.sh — port-agnostic uvicorn launcher.
# Render injects $PORT at runtime; fall back to 8000 locally.
#
# --proxy-headers + --forwarded-allow-ips='*' make uvicorn honor the
# X-Forwarded-For header set by Render's reverse proxy, so request.client.host
# (and slowapi's per-IP rate limiting + the anon cost-cap IP fallback) see the
# real client IP instead of the proxy's internal IP. Without this, every request
# shares one IP bucket and per-IP limits are meaningless.
set -e
exec uvicorn api.main:app \
    --host 0.0.0.0 \
    --port "${PORT:-8000}" \
    --proxy-headers \
    --forwarded-allow-ips='*'
