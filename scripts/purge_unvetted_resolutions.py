#!/usr/bin/env python3
"""Evict cached food matches that share no word with the ingredient.

``lib/resolution_guard`` stops new ones being written, but it cannot help what
is already cached — and a high-confidence entry is never re-examined, so these
stay wrong forever and silently set recipe calories:

    blueberries, fresh   -> Basil, fresh                 confidence 1.0
    breadcrumbs          -> Abiyuch, raw                 confidence 0.95
    aleppo pepper        -> Frankfurter, beef, heated     confidence 0.9

Deleting the entry is safe: the next resolve re-runs the search, and the guard
now downgrades a bad answer to 0.2 instead of caching it at 1.0 — so a wrong
match becomes visible and flagged rather than permanent and silent.

Human-pinned resolutions are never touched.

    .venv/bin/python scripts/purge_unvetted_resolutions.py            # preview
    .venv/bin/python scripts/purge_unvetted_resolutions.py --apply
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from lib import inventory_db  # noqa: E402
from lib.resolution_guard import shares_a_food_word  # noqa: E402


def find_unvetted(conn) -> list[tuple]:
    """(query_norm, description, resolver, confidence) for every bad match."""
    rows = conn.execute(
        """SELECT r.query_norm, f.description, r.resolver, r.confidence
           FROM food_resolution r
           JOIN fdc_foods f ON f.fdc_id = r.source_id"""
    ).fetchall()
    out = []
    for query_norm, description, resolver, confidence in rows:
        # A human said so; that outranks any heuristic here.
        if str(resolver or "").startswith("human"):
            continue
        if not shares_a_food_word(query_norm, description):
            out.append((query_norm, description, resolver, confidence))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="delete (default: preview)")
    ap.add_argument("--limit", type=int, default=25, help="how many to list")
    args = ap.parse_args()

    conn = inventory_db.read_conn()
    bad = find_unvetted(conn)
    total = conn.execute("SELECT COUNT(*) FROM food_resolution").fetchone()[0]

    print(f"cached resolutions              : {total}")
    print(f"sharing no food word with the ingredient: {len(bad)}")
    high = [b for b in bad if (b[3] or 0) >= 0.9]
    print(f"  ...cached at confidence >= 0.9 : {len(high)}   <- never re-examined\n")

    for query_norm, description, resolver, confidence in sorted(bad)[: args.limit]:
        print(f"  {query_norm[:30]:<32} -> {description[:44]:<46} "
              f"conf {confidence} [{resolver}]")
    if len(bad) > args.limit:
        print(f"  ...and {len(bad) - args.limit} more")

    if not args.apply:
        print("\nPREVIEW — nothing deleted. Re-run with --apply, then:"
              "\n  .venv/bin/python backfill_nutrition.py --force")
        return 0

    write = inventory_db.write_conn() if hasattr(inventory_db, "write_conn") else conn
    keys = [b[0] for b in bad]
    for key in keys:
        write.execute("DELETE FROM food_resolution WHERE query_norm = ?", (key,))
        write.execute("DELETE FROM food_cache WHERE query_norm = ?", (key,))
    write.commit()
    print(f"\nDeleted {len(keys)} resolutions (and their cached records).")
    print("Next resolve re-runs the search with the guard active. Now run:"
          "\n  .venv/bin/python backfill_nutrition.py --force")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
