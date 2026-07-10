#!/usr/bin/env python3
"""Build the portion ledger — Component C of nutrition-batch-ledger.

Enumerates the unique (item, unit) pairs across the vault whose FOOD resolves but
whose grams conversion fails (the "food known, grams failed" bucket), asks the LLM
once per pair for a grams-per-unit estimate, band-validates it, and writes it to the
deterministic ``portion_ledger`` (or an Obsidian review-queue note for out-of-band /
low-confidence). The engine then reads the ledger with no LLM at resolve time.

Usage:
    .venv/bin/python scripts/build_portion_ledger.py [--provider ollama|claude]
                                                      [--limit N] [--dry-run]
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from lib import paths, inventory_db, fdc_local, food_resolver, units
from lib.recipe_parser import parse_recipe_file
from lib.nutrition_engine import calculate_recipe_nutrition
from backfill_nutrition import extract_ingredients, collect_all_recipes


def _resolved(li):
    return (getattr(li, "grams", 0) or 0) > 0 or getattr(li, "grams_method", "") == "negligible"


def collect_failures(limit=None):
    """{(item_norm, unit): {item, unit, per_100g}} for food-known/grams-failed lines."""
    out = {}
    for md in collect_all_recipes(paths.recipes_dir()):
        parsed = parse_recipe_file(md.read_text(encoding="utf-8"))
        if "source_url" not in parsed["frontmatter"]:
            continue
        ings = extract_ingredients(parsed["body"])
        if not ings:
            continue
        res = calculate_recipe_nutrition(ings, 1, offline=True)
        if not res:
            continue
        for li in res.line_items:
            if _resolved(li):
                continue
            item = getattr(li, "item", "") or ""
            unit = (getattr(li, "unit", "") or "").strip().lower()
            p = getattr(li, "per_100g", None) or {}
            kcal = p.get("calories", 0) if isinstance(p, dict) else getattr(p, "calories", 0)
            if not item or not unit or unit == "to taste" or not kcal:
                continue  # need a known food (kcal) + a real unit
            key = (units._normalize_item(item), unit)
            out.setdefault(key, {"item": item, "unit": unit,
                                 "per_100g": p if isinstance(p, dict) else {"calories": kcal}})
        if limit and len(out) >= limit:
            break
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default="ollama", choices=["ollama", "claude"])
    ap.add_argument("--limit", type=int, default=None, help="cap unique pairs (for a test batch)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--pairs-cache", default=None,
                    help="JSON file to cache/reuse the collected failing pairs "
                         "(skips the slow re-collection on resume)")
    args = ap.parse_args()

    cache = args.pairs_cache
    if cache and os.path.exists(cache):
        with open(cache) as f:
            failures = {tuple(k.split("\t")): v for k, v in json.load(f).items()}
        print(f"reusing {len(failures)} cached pairs from {os.path.basename(cache)}",
              flush=True)
    else:
        failures = collect_failures(args.limit)
        if cache:
            with open(cache, "w") as f:
                json.dump({"\t".join(k): v for k, v in failures.items()}, f)
    print(f"{len(failures)} unique (item, unit) pairs need portion estimates "
          f"[provider={args.provider}]", flush=True)

    conn = inventory_db.connect()
    fdc_local.ensure_schema(conn)
    written = rejected = skipped = 0
    review = []
    for (item_norm, unit), info in failures.items():
        if fdc_local.ledger_grams(conn, item_norm, unit) is not None:
            skipped += 1
            continue
        est = food_resolver.estimate_portion_grams(unit, info["item"], None, args.provider)
        if est is None:
            review.append((info["item"], unit, "no estimate"))
            continue
        grams, conf = est
        ok, reason = fdc_local.validate_portion_grams(info["item"], unit, grams, info["per_100g"])
        if not ok or conf < 0.4:
            rejected += 1
            review.append((info["item"], unit, f"{grams:.0f}g rejected: {reason if not ok else 'low conf'}"))
            continue
        print(f"  {info['item'][:30]!r:32} [{unit}] -> {grams:.1f}g (conf {conf:.2f})", flush=True)
        if not args.dry_run:
            fdc_local.ledger_put(conn, item_norm, unit, grams, conf, args.provider,
                                 f"1 {unit} {info['item']}")
        written += 1

    print(f"\nwritten {written}, rejected {rejected}, skipped(existing) {skipped}, "
          f"review-queue {len(review)}")
    if review:
        print("review queue (out-of-band / no estimate):")
        for it, u, why in review[:20]:
            print(f"  {it[:34]!r} [{u}]: {why}")


if __name__ == "__main__":
    main()
