#!/usr/bin/env python3
"""Fast grams-coverage meter for the nutrition engine.

Coverage = fraction of ingredient lines the engine resolves to a weight
(grams > 0, or explicitly negligible). Low coverage corrupts per-serving macros.
Runs over a deterministic first-N sample so before/after runs compare like-for-like.

Usage:
    .venv/bin/python scripts/grams_coverage_report.py [--limit N]
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from lib import paths
from lib.recipe_parser import parse_recipe_file
from lib.nutrition_engine import calculate_recipe_nutrition
from backfill_nutrition import extract_ingredients, collect_all_recipes


def _line_resolved(li) -> bool:
    return (getattr(li, "grams", 0) or 0) > 0 or getattr(li, "grams_method", "") == "negligible"


def coverage_over(recipes_dir, limit=None):
    files = [f for f in collect_all_recipes(recipes_dir)]
    picked = []
    for md in files:
        parsed = parse_recipe_file(md.read_text(encoding="utf-8"))
        if "source_url" not in parsed["frontmatter"]:
            continue
        if extract_ingredients(parsed["body"]):
            picked.append((md, parsed))
        if limit and len(picked) >= limit:
            break

    total_items = resolved_items = 0
    per_recipe = []
    for md, parsed in picked:
        ings = extract_ingredients(parsed["body"])
        res = calculate_recipe_nutrition(ings, 1)
        items = res.line_items if res else []
        ok = sum(1 for li in items if _line_resolved(li))
        total_items += len(items)
        resolved_items += ok
        per_recipe.append((md.stem, ok, len(items)))
    return per_recipe, resolved_items, total_items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--verbose", action="store_true", help="list each recipe")
    args = ap.parse_args()

    per_recipe, resolved, total = coverage_over(paths.recipes_dir(), args.limit)
    if args.verbose:
        for name, ok, n in per_recipe:
            print(f"  {ok/n if n else 0:.2f}  {ok:>2}/{n:<2}  {name}")
    n = len(per_recipe)
    full = sum(1 for _, ok, tot in per_recipe if tot and ok == tot)
    print(f"\nrecipes sampled: {n}")
    print(f"item-level coverage: {resolved}/{total} = {resolved/total:.3f}" if total else "no items")
    print(f"fully-covered recipes: {full}/{n} = {full/n:.2f}" if n else "")


if __name__ == "__main__":
    main()
