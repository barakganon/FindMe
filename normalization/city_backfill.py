"""
normalization/city_backfill.py — reversible backfill of missing store city.

Only ~22 of the 182 null-city stores have an `address` to parse (the rest are
online/addressless and legitimately have no city). Israeli addresses put the city
last, after a comma ("תנופה 7, טירת כרמל"). This sets `city` from that trailing
segment for the comma-delimited, digit-free cases only — conservative, to avoid
guessing. Reversible: backfilled (id, city) pairs are dumped to JSON; `--restore`
sets those back to NULL.

Usage:
    python -m normalization.city_backfill --dry-run | --apply | --restore <file>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from api.dependencies import _normalize_async_db_url, get_settings

_DIR = os.path.join(os.path.dirname(__file__), "..", "_bmad-output", "remediation")


def _engine():
    return create_async_engine(_normalize_async_db_url(get_settings().database_url))


def _city_from_address(addr: str | None) -> str | None:
    """Trailing comma segment, if it's a clean Hebrew city token (no digits)."""
    if not addr or "," not in addr:
        return None
    tail = addr.rsplit(",", 1)[-1].strip()
    # Reject if empty, contains digits (still a street), or implausibly long.
    if not tail or re.search(r"\d", tail) or len(tail) > 30:
        return None
    return tail


async def _collect(conn):
    rows = await conn.execute(text(
        "SELECT id, address FROM stores WHERE (city IS NULL OR city = '') "
        "AND address IS NOT NULL AND address <> ''"
    ))
    out = []
    for r in rows:
        city = _city_from_address(r.address)
        if city:
            out.append({"id": str(r.id), "city": city})
    return out


async def dry_run() -> None:
    eng = _engine()
    async with eng.connect() as conn:
        rows = await _collect(conn)
    await eng.dispose()
    print(f"[dry-run] would set city on {len(rows)} stores:")
    for r in rows:
        print(f"  {r['city']}")


async def apply() -> None:
    eng = _engine()
    async with eng.begin() as conn:
        rows = await _collect(conn)
        if not rows:
            print("Nothing to backfill.")
            await eng.dispose()
            return
        os.makedirs(_DIR, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        bfile = os.path.join(_DIR, f"city-backfill-{stamp}.json")
        with open(bfile, "w", encoding="utf-8") as fh:
            json.dump({"created_utc": stamp, "rows": rows}, fh, ensure_ascii=False, indent=2)
        for r in rows:
            await conn.execute(
                text("UPDATE stores SET city = :c WHERE id = :id"),
                {"c": r["city"], "id": r["id"]},
            )
    await eng.dispose()
    print(f"Backfilled city on {len(rows)} stores → {os.path.relpath(bfile)}.")
    print("Restore with: python -m normalization.city_backfill --restore " + os.path.relpath(bfile))


async def restore(path: str) -> None:
    with open(path, encoding="utf-8") as fh:
        rows = json.load(fh)["rows"]
    eng = _engine()
    async with eng.begin() as conn:
        await conn.execute(
            text("UPDATE stores SET city = NULL WHERE id = ANY(:ids)"),
            {"ids": [r["id"] for r in rows]},
        )
    await eng.dispose()
    print(f"Reset city to NULL on {len(rows)} stores.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Reversible store-city backfill from address.")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    g.add_argument("--restore", metavar="BACKFILL_JSON")
    args = ap.parse_args()
    if args.dry_run:
        asyncio.run(dry_run())
    elif args.apply:
        asyncio.run(apply())
    else:
        asyncio.run(restore(args.restore))


if __name__ == "__main__":
    main()
