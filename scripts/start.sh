#!/usr/bin/env sh
# scripts/start.sh — port-agnostic uvicorn launcher.
# Render injects $PORT at runtime; fall back to 8000 locally.
set -e
exec uvicorn api.main:app --host 0.0.0.0 --port "${PORT:-8000}"
