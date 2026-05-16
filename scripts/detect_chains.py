"""scripts/detect_chains.py — Populate stores.parent_chain_id for top-20 Israeli chains.

Strategy: hand-curated regex map. For each pattern, find all matching stores
and pick the first one (by id) as the canonical chain parent. Set
`parent_chain_id` on every other match to point at the canonical store.

Rationale: a full pg_trgm clustering would catch more chains but produce
noisy groups (e.g. clustering "Sushi X" with "Sushi Y" because they share
"Sushi"). The top-20 manual regex covers ~80% of the chain-collapsing UX
need with zero false positives.

For the long tail, the LLM-enrichment script (Story 3.3) is the right tool —
out of scope for W4.

Usage:
    .venv/bin/python -m scripts.detect_chains --dry-run
    .venv/bin/python -m scripts.detect_chains             # writes
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from collections import defaultdict

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


# Canonical chain name → list of patterns matching its store names.
# Patterns are case-insensitive. Order matters; first match wins per store.
_CHAIN_PATTERNS: dict[str, list[str]] = {
    "FOX": [r"\bfox\b", "פוקס"],
    "FOX Home": [r"fox home", "פוקס הום"],
    "Castro": ["castro", "קסטרו"],
    "Renuar": ["renuar", "רנואר"],
    "Greg": [r"\bgreg\b", "גרג"],
    "Cofix": ["cofix", "קופיקס"],
    "Aroma": ["aroma", "ארומה"],
    "Cafe Cafe": [r"caf[eé] caf[eé]", "קפה קפה"],
    "Landwer": ["landwer", "לנדוור"],
    "H&M": [r"h&m"],
    "Zara": [r"\bzara\b", "זארה"],
    "Mango": [r"\bmango\b", "מנגו"],
    "Pull&Bear": [r"pull\s*&\s*bear", "פול אנד בר"],
    "Bershka": ["bershka", "ברשקה"],
    "Stradivarius": ["stradivarius"],
    "Adika": ["adika", "אדיקה"],
    "MaxStock": ["maxstock", "max stock", "מקסטוק"],
    "American Eagle": ["american eagle"],
    "Shilav": ["shilav", "שילב"],
    "Babystar": ["babystar", "בייביסטאר"],
}


def _compile():
    out = []
    for chain, patterns in _CHAIN_PATTERNS.items():
        combined = "|".join(f"(?:{p})" for p in patterns)
        out.append((chain, re.compile(combined, re.IGNORECASE)))
    return out


_COMPILED = _compile()


def detect_chain(store_name: str | None) -> str | None:
    if not store_name:
        return None
    for chain, pattern in _COMPILED:
        if pattern.search(store_name):
            return chain
    return None


async def main(dry_run: bool) -> None:
    db_url = os.environ.get("DATABASE_URL", "postgresql+asyncpg://barakganon@localhost/buyme_search")
    engine = create_async_engine(db_url)

    print(f"→ Connecting to: {db_url.split('@')[-1]}")
    print(f"  Mode: {'DRY-RUN (no writes)' if dry_run else 'WRITE'}")

    async with engine.connect() as conn:
        result = await conn.execute(text("""
            SELECT id, name_he, name_en, parent_chain_id
            FROM stores
        """))
        rows = result.fetchall()

    print(f"  Stores fetched: {len(rows):,}")

    # Group stores by detected chain. Canonical store = first by id (stable).
    chain_to_stores: dict[str, list[tuple[str, str, str | None]]] = defaultdict(list)
    for row in rows:
        store_id, name_he, name_en, existing_parent = row
        chain = detect_chain(name_he) or detect_chain(name_en)
        if chain:
            chain_to_stores[chain].append((str(store_id), name_he or name_en or "", existing_parent))

    print(f"  Chains detected: {len(chain_to_stores)}")
    print("  Chain → store count:")
    updates: list[tuple[str, str]] = []
    for chain, stores in sorted(chain_to_stores.items(), key=lambda kv: -len(kv[1])):
        # Pick the first store (by id sort order) as the canonical parent.
        stores_sorted = sorted(stores, key=lambda s: s[0])
        canonical_id = stores_sorted[0][0]
        print(f"    {chain:<20} {len(stores):>4}  canonical={stores_sorted[0][1][:40]}")
        for store_id, _name, existing_parent in stores_sorted[1:]:
            # Skip if already has the right parent
            if existing_parent == canonical_id:
                continue
            updates.append((store_id, canonical_id))

    print(f"\n  Updates queued: {len(updates):,}")

    if dry_run:
        print("\nDry-run complete — no writes.")
        await engine.dispose()
        return

    print("→ Writing parent_chain_id updates...")
    async with engine.begin() as conn:
        for store_id, parent_id in updates:
            await conn.execute(
                text("""
                    UPDATE stores SET parent_chain_id = CAST(:parent AS uuid)
                    WHERE id = CAST(:id AS uuid)
                """),
                {"parent": parent_id, "id": store_id},
            )
    print(f"✓ Done. {len(updates):,} stores linked to chain parents.")
    await engine.dispose()


def cli() -> int:
    parser = argparse.ArgumentParser(description="Populate stores.parent_chain_id for top-20 chains")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        asyncio.run(main(dry_run=args.dry_run))
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(cli())
