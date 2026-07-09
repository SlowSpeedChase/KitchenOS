#!/usr/bin/env python3
"""Calorie-weighted coverage meter for the nutrition engine.

Grams/item coverage understates the macro problem: a missed spice counts the same
as a missed protein. This meter reports the number that actually predicts whether
per-serving macros are usable:

  - item coverage         : fraction of ingredient lines resolved to a weight
  - fully-covered recipes : recipes where every line resolved (macros trustworthy)
  - calorie coverage      : est. fraction of each recipe's calories the engine
                            captures (missing-line calories estimated with a rough
                            gram fallback -- treat as +/- 0.1, direction is robust)
  - grams-failed buckets  : of unresolved MATERIAL lines, split into
                            'food known / portion failed' (the addressable lever)
                            vs 'food not found', and spices (~0 kcal, de-noised)

Runs over a deterministic first-N sample so before/after runs compare like-for-like.
This is the accuracy gate for the portion-resolution work -- re-run before/after
each change. See docs/plans/nutrition-portion-resolution.md.

Usage:
    .venv/bin/python scripts/calorie_coverage_report.py [--limit N] [--verbose]
"""
import argparse
import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from lib import paths
from lib.recipe_parser import parse_recipe_file
from lib.nutrition_engine import calculate_recipe_nutrition
from backfill_nutrition import extract_ingredients, collect_all_recipes

# Words that mark a calorically-negligible seasoning/garnish. Used only to split
# the coverage report -- NOT the engine's resolution path.
SPICE_WORDS = {
    "powder", "pepper", "paprika", "cumin", "salt", "cinnamon", "oregano",
    "coriander", "chili", "bay", "thyme", "nutmeg", "clove", "cloves", "seasoning",
    "cayenne", "turmeric", "dill", "basil", "parsley", "cilantro", "rosemary",
    "sage", "allspice", "cardamom", "fennel", "poppy", "flakes", "zest", "extract",
    "vanilla", "sweetener", "erythritol", "stevia", "baking soda", "baking powder",
    "yeast", "garlic powder", "chives", "mint", "garam masala", "curry powder",
    "italian seasoning", "red pepper",
}

VOL_ML = {"cup": 240, "cups": 240, "tbsp": 15, "tablespoon": 15, "tablespoons": 15,
          "tsp": 5, "teaspoon": 5, "teaspoons": 5, "ml": 1, "l": 1000, "liter": 1000}


def _resolved(li):
    return (getattr(li, "grams", 0) or 0) > 0 or getattr(li, "grams_method", "") == "negligible"


def _is_spice(text):
    t = (text or "").lower()
    return any(w in t for w in SPICE_WORDS)


def _parse_amt(a):
    try:
        if a is None:
            return None
        s = str(a).strip()
        if " " in s:
            w, f = s.split(" ", 1)
            return float(w) + (_parse_amt(f) or 0)
        if "/" in s:
            n, d = s.split("/")
            return float(n) / float(d)
        return float(s)
    except (ValueError, ZeroDivisionError):
        return None


def _est_grams(amount, unit):
    """Rough gram estimate for an unresolved line, for calorie-weighting only."""
    q = _parse_amt(amount)
    u = (unit or "").strip().lower()
    if u in {"g", "gram", "grams"}:
        return q or 50.0
    if u in {"oz", "ounce", "ounces"}:
        return (q or 1) * 28.35
    if u in {"lb", "lbs", "pound", "pounds"}:
        return (q or 1) * 453.6
    if u in VOL_ML:
        return (q or 1) * VOL_ML[u]
    return (q or 1) * 50.0


def _kcal_per_100g(li):
    p = getattr(li, "per_100g", None) or {}
    if isinstance(p, dict):
        return p.get("calories", 0) or 0
    return getattr(p, "calories", 0) or 0


def _contrib_cal(li):
    c = getattr(li, "contribution", None) or {}
    return (c.get("calories", 0) if isinstance(c, dict) else getattr(c, "calories", 0)) or 0


def collect(recipes_dir, limit=None, offline=False):
    recs = []
    for md in collect_all_recipes(recipes_dir):
        parsed = parse_recipe_file(md.read_text(encoding="utf-8"))
        if "source_url" not in parsed["frontmatter"]:
            continue
        ings = extract_ingredients(parsed["body"])
        if not ings:
            continue
        res = calculate_recipe_nutrition(ings, 1, offline=offline)
        if res:
            recs.append((md.stem, res.line_items or []))
        if limit and len(recs) >= limit:
            break
    return recs


def report(recs):
    tot = res_ok = full = 0
    covered_cal = missing_cal = 0.0
    spice = material = food_known = food_missing = 0
    for _, items in recs:
        n = len(items)
        ok = sum(1 for li in items if _resolved(li))
        res_ok += ok
        tot += n
        if n and ok == n:
            full += 1
        for li in items:
            covered_cal += _contrib_cal(li)
            if _resolved(li):
                continue
            if _is_spice(getattr(li, "item", "")):
                spice += 1
                continue
            material += 1
            g = _est_grams(getattr(li, "amount", None), getattr(li, "unit", None))
            k100 = _kcal_per_100g(li)
            if k100 > 0:
                food_known += 1
                missing_cal += g * k100 / 100.0
            else:
                food_missing += 1
                missing_cal += g * 150 / 100.0  # generic ~150 kcal/100g
    return {
        "recipes": len(recs), "lines": tot, "resolved": res_ok, "full": full,
        "covered_cal": covered_cal, "missing_cal": missing_cal,
        "spice": spice, "material": material,
        "food_known": food_known, "food_missing": food_missing,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="first-N recipes (default: all)")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--offline", action="store_true",
                    help="cache-only: no live USDA/OFF lookups (rate-limit-immune)")
    args = ap.parse_args()

    recs = collect(paths.recipes_dir(), args.limit, offline=args.offline)
    if args.verbose:
        for name, items in recs:
            n = len(items)
            ok = sum(1 for li in items if _resolved(li))
            print(f"  {ok/n if n else 0:.2f}  {ok:>2}/{n:<2}  {name}")
    r = report(recs)
    denom = r["covered_cal"] + r["missing_cal"]
    print(f"\nrecipes: {r['recipes']}   ingredient lines: {r['lines']}")
    print(f"item coverage:         {r['resolved']}/{r['lines']} = "
          f"{r['resolved']/r['lines']:.3f}" if r["lines"] else "no lines")
    print(f"fully-covered recipes: {r['full']}/{r['recipes']} = "
          f"{r['full']/r['recipes']:.2%}" if r["recipes"] else "")
    print(f"calorie coverage:      {r['covered_cal']/denom:.3f}  (est., +/-0.1)"
          if denom else "no calories")
    print("\nunresolved material misses (the calorie leak):")
    print(f"  food KNOWN, portion failed: {r['food_known']}  <- addressable (portion/density/LLM)")
    print(f"  food NOT FOUND:             {r['food_missing']}  <- match/normalization")
    print(f"  spices/seasonings (~0 kcal): {r['spice']}  <- de-noise, not a macro problem")


if __name__ == "__main__":
    main()
