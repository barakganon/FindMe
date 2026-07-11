#!/usr/bin/env bash
# migrate_catalog.sh — copy the FindMe product catalog (incl. vector(768)
# embeddings + ivfflat index) from a source Postgres to a target Postgres
# (e.g. the Render-managed findme-db).
#
# SAFE BY DEFAULT: without --confirm this script only PRINTS the commands
# it would run (pg_dump / pg_restore / psql). Nothing touches either
# database until you pass --confirm explicitly.
#
# Usage:
#   scripts/migrate_catalog.sh --source <SOURCE_DB_URL> --target <TARGET_DB_URL> [--confirm]
#
# Or via env vars:
#   SOURCE_DB_URL=... TARGET_DB_URL=... scripts/migrate_catalog.sh [--confirm]
#
# Examples:
#   # Dry run (default) — just shows what would happen
#   scripts/migrate_catalog.sh \
#     --source postgresql://user:pass@localhost:5432/buyme_search \
#     --target postgresql://user:pass@dpg-xxxx.frankfurt-postgres.render.com/findme_db
#
#   # Actually run it
#   scripts/migrate_catalog.sh \
#     --source postgresql://user:pass@localhost:5432/buyme_search \
#     --target postgresql://user:pass@dpg-xxxx.frankfurt-postgres.render.com/findme_db \
#     --confirm
#
# Requires: pg_dump, pg_restore, psql (matching or newer major version than
# both source and target Postgres — use the same client tooling version as
# the target, i.e. PG16 client binaries for a PG16 Render DB).

set -euo pipefail

SOURCE_DB_URL="${SOURCE_DB_URL:-}"
TARGET_DB_URL="${TARGET_DB_URL:-}"
CONFIRM=false
DUMP_FILE="${DUMP_FILE:-findme_catalog_$(date +%Y%m%d_%H%M%S).pgdump}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --source)
      SOURCE_DB_URL="$2"; shift 2 ;;
    --target)
      TARGET_DB_URL="$2"; shift 2 ;;
    --dump-file)
      DUMP_FILE="$2"; shift 2 ;;
    --confirm)
      CONFIRM=true; shift ;;
    -h|--help)
      grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *)
      echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

if [[ -z "$SOURCE_DB_URL" || -z "$TARGET_DB_URL" ]]; then
  echo "ERROR: --source and --target (or SOURCE_DB_URL / TARGET_DB_URL env vars) are required." >&2
  exit 1
fi

echo "== FindMe catalog migration =="
echo "Source: ${SOURCE_DB_URL%%@*}@***  (redacted)"
echo "Target: ${TARGET_DB_URL%%@*}@***  (redacted)"
echo "Dump file: $DUMP_FILE"
echo "Mode: $([ "$CONFIRM" = true ] && echo LIVE || echo DRY-RUN)"
echo

CREATE_EXT_CMD=(psql "$TARGET_DB_URL" -v ON_ERROR_STOP=1 -c "CREATE EXTENSION IF NOT EXISTS vector;")
DUMP_CMD=(pg_dump --no-owner --no-acl -F c -f "$DUMP_FILE" "$SOURCE_DB_URL")
RESTORE_CMD=(pg_restore --no-owner --no-acl --clean --if-exists -d "$TARGET_DB_URL" "$DUMP_FILE")

echo "Step 1/3 — ensure pgvector extension exists on target:"
printf '  %q ' "${CREATE_EXT_CMD[@]}"; echo
echo
echo "Step 2/3 — dump source catalog:"
printf '  %q ' "${DUMP_CMD[@]}"; echo
echo
echo "Step 3/3 — restore dump into target:"
printf '  %q ' "${RESTORE_CMD[@]}"; echo
echo

if [[ "$CONFIRM" != true ]]; then
  echo "Dry run only — no commands executed. Re-run with --confirm to perform the migration."
  exit 0
fi

echo ">>> Running Step 1/3 (CREATE EXTENSION vector on target)..."
"${CREATE_EXT_CMD[@]}"

echo ">>> Running Step 2/3 (pg_dump source)..."
"${DUMP_CMD[@]}"

echo ">>> Running Step 3/3 (pg_restore into target)..."
"${RESTORE_CMD[@]}"

echo
echo "Done. Verify row counts, e.g.:"
echo "  psql \"$TARGET_DB_URL\" -c \"SELECT count(*) FROM products;\""
echo "  psql \"$TARGET_DB_URL\" -c \"SELECT count(*) FROM products WHERE embedding_vector IS NOT NULL;\""
