#!/usr/bin/env python3
"""Validation harness — measure nutrition accuracy against a hand-labeled golden set.

This is how "reliable" becomes measurable. It recomputes per-serving macros for
each golden recipe with the gram-based engine and compares to the recipe's
published nutrition, reporting per-macro error and a pass/fail at tolerance.

    .venv/bin/python scripts/validate_nutrition.py                # new engine
    .venv/bin/python scripts/validate_nutrition.py --no-llm       # deterministic only
    .venv/bin/python scripts/validate_nutrition.py --legacy       # old lookup (before/after)
    .venv/bin/python scripts/validate_nutrition.py --ollama-viability

Needs a real ``USDA_FDC_API_KEY`` (DEMO_KEY is rate-limited to ~30 req/hr and
will leave most ingredients unresolved on the first, uncached run).

The ``--ollama-viability`` mode answers the open question from the plan: is local
mistral:7b good enough for the two constrained jobs (food pick + portion grams),
or do we need Claude? It scores both against tests/golden/resolution_golden.json.
"""
import argparse
import json
import os
import sys
from pathlib import Path
from statistics import median

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402
load_dotenv()

from lib import paths  # noqa: E402
from lib.recipe_parser import parse_recipe_file  # noqa: E402
from backfill_nutrition import extract_ingredients  # noqa: E402

GOLDEN_DIR = Path(__file__).resolve().parent.parent / "tests" / "golden"
MACROS = ["calories", "protein", "carbs", "fat"]
# Pass tolerances (fraction): calories tighter than individual macros.
TOLERANCE = {"calories": 0.15, "protein": 0.20, "carbs": 0.20, "fat": 0.20}

# Ollama viability bars (the plan's gate).
RESOLUTION_BAR = 0.85       # ≥ this fraction of food picks correct
PORTION_MEDIAN_BAR = 0.20   # ≤ this median % error on portion grams


def _pct_err(actual: float, expected: float) -> float:
    if expected == 0:
        return 0.0 if actual == 0 else 1.0
    return abs(actual - expected) / expected


def _compute(entry: dict, legacy: bool, use_llm: bool):
    """Return per-serving macro dict for one golden recipe, or None."""
    recipe_path = paths.recipes_dir() / entry["file"]
    if not recipe_path.exists():
        return None, "file not found"
    parsed = parse_recipe_file(recipe_path.read_text(encoding="utf-8"))
    ingredients = extract_ingredients(parsed["body"])
    if not ingredients:
        return None, "no ingredients"

    if legacy:
        from lib.nutrition_lookup import calculate_recipe_nutrition as legacy_calc
        res = legacy_calc(ingredients, int(entry["servings"] or 1))
        if not res:
            return None, "unresolved"
        return res.nutrition.to_dict(), res.source

    from lib.nutrition_engine import calculate_recipe_nutrition
    res = calculate_recipe_nutrition(ingredients, entry["servings"], use_llm=use_llm)
    if not res:
        return None, "unresolved"
    return res.per_serving.to_dict(), res.source


def run_golden(legacy: bool, use_llm: bool, limit):
    data = json.loads((GOLDEN_DIR / "nutrition_golden.json").read_text())
    recipes = data["recipes"][:limit] if limit else data["recipes"]

    label = "LEGACY lookup" if legacy else ("engine (deterministic)" if not use_llm else "engine (+LLM)")
    print(f"\nNutrition validation — {label}")
    print(f"Tolerance: cal ±{int(TOLERANCE['calories']*100)}%, macros ±20%\n")
    header = f"{'recipe':32} {'cal':>13} {'protein':>11} {'carbs':>11} {'fat':>11}   verdict"
    print(header)
    print("-" * len(header))

    passes = 0
    counted = 0
    err_accum = {m: [] for m in MACROS}

    for entry in recipes:
        computed, src = _compute(entry, legacy, use_llm)
        name = entry["file"].replace(".md", "")[:32]
        if computed is None:
            print(f"{name:32} {'— ' + str(src):>61}")
            continue

        counted += 1
        pub = entry["published"]
        cells = []
        recipe_pass = True
        for m in MACROS:
            a, e = computed.get(m, 0), pub.get(m, 0)
            err = _pct_err(a, e)
            err_accum[m].append(err)
            ok = err <= TOLERANCE[m]
            recipe_pass = recipe_pass and ok
            mark = "" if ok else "!"
            cells.append(f"{a:>4.0f}/{e:<4.0f}{int(err*100):>3}%{mark}")
        verdict = "PASS" if recipe_pass else "FAIL"
        passes += recipe_pass
        print(f"{name:32} " + " ".join(f"{c:>11}" for c in cells) + f"   {verdict}  [{src}]")

    print("-" * len(header))
    if counted:
        mean_err = {m: sum(err_accum[m]) / len(err_accum[m]) for m in MACROS if err_accum[m]}
        print(f"Recipes scored: {counted}/{len(recipes)}   Passing: {passes}/{counted}")
        print("Mean abs % error: " + ", ".join(
            f"{m}={mean_err.get(m, 0)*100:.0f}%" for m in MACROS))
    else:
        print("No recipes could be scored (check USDA_FDC_API_KEY / network).")
    print()


def run_ollama_viability(limit):
    from lib import food_db, food_resolver
    data = json.loads((GOLDEN_DIR / "resolution_golden.json").read_text())

    print("\nOllama viability — constrained LLM jobs (mistral:7b)\n")

    # Job 1: food resolution.
    res_cases = data["food_resolution"][:limit] if limit else data["food_resolution"]
    correct = scored = 0
    print("Food resolution:")
    for case in res_cases:
        candidates = food_db.usda_search(case["ingredient"])
        if not candidates:
            print(f"  {case['ingredient']:32} — no USDA candidates (key/network?)")
            continue
        picked = food_resolver.resolve_food_llm(case["ingredient"], candidates)
        if picked is None:
            print(f"  {case['ingredient']:32} — LLM no answer (ollama down?)")
            continue
        scored += 1
        desc = candidates[picked[0]].description.lower()
        ok = any(k.lower() in desc for k in case["expect_keywords"])
        correct += ok
        print(f"  {case['ingredient']:32} -> {desc[:40]:40} {'OK' if ok else 'MISS'}")
    res_rate = correct / scored if scored else 0.0

    # Job 2: portion grams.
    port_cases = data["portions"][:limit] if limit else data["portions"]
    errs = []
    print("\nPortion grams:")
    for case in port_cases:
        est = food_resolver.estimate_portion_grams_llm(case["unit"], case["item"])
        if est is None:
            print(f"  {case['item']:32} — LLM no answer")
            continue
        err = _pct_err(est[0], case["expected_grams"])
        errs.append(err)
        print(f"  {case['item']:32} est={est[0]:6.0f}g exp={case['expected_grams']:>4}g  {int(err*100)}%")
    port_median = median(errs) if errs else 1.0

    print("\n" + "=" * 50)
    res_ok = res_rate >= RESOLUTION_BAR and scored > 0
    port_ok = port_median <= PORTION_MEDIAN_BAR and errs
    print(f"Resolution accuracy: {res_rate*100:.0f}% (bar ≥{int(RESOLUTION_BAR*100)}%)  "
          f"{'PASS' if res_ok else 'FAIL'}")
    print(f"Portion median error: {port_median*100:.0f}% (bar ≤{int(PORTION_MEDIAN_BAR*100)}%)  "
          f"{'PASS' if port_ok else 'FAIL'}")
    verdict = "VIABLE" if (res_ok and port_ok) else "NOT VIABLE — consider Claude for these jobs"
    print(f"\nOllama for constrained jobs: {verdict}\n")


def main():
    ap = argparse.ArgumentParser(description="Validate nutrition accuracy vs golden set")
    ap.add_argument("--no-llm", action="store_true", help="Engine, deterministic only (no LLM fallback)")
    ap.add_argument("--legacy", action="store_true", help="Use the old nutrition_lookup (before/after)")
    ap.add_argument("--ollama-viability", action="store_true", help="Score mistral:7b on the two LLM jobs")
    ap.add_argument("--limit", type=int, help="Limit number of cases")
    args = ap.parse_args()

    if args.ollama_viability:
        run_ollama_viability(args.limit)
    else:
        run_golden(legacy=args.legacy, use_llm=not args.no_llm, limit=args.limit)


if __name__ == "__main__":
    main()
