#!/usr/bin/env python3
"""Measure ingredient-data quality across the vault — the accuracy gate.

Reports the % of ingredient rows that are "clean" (macro-ready) before and after
running lib/ingredient_cleaner over them, so the Phase A cleaning work can be
verified (target: raise clean% substantially) and re-run as a regression metric.

    .venv/bin/python scripts/ingredient_quality_report.py
    .venv/bin/python scripts/ingredient_quality_report.py --examples   # show samples

Read-only: never modifies recipe files.
"""
import argparse
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402
load_dotenv()

from lib import paths  # noqa: E402
from lib.recipe_parser import parse_recipe_file  # noqa: E402
from backfill_nutrition import extract_ingredients  # noqa: E402
from lib.ingredient_cleaner import clean_ingredient  # noqa: E402
from lib.ingredient_parser import WORD_NUMBERS  # noqa: E402
from lib.units import get_unit_family, parse_amount_to_float, COUNT_UNITS, VOLUME_ML, MASS_G  # noqa: E402

import re  # noqa: E402

_INSTR = ("°", "preheat", "degrees", "fahrenheit")


def _is_clean_raw(ing: dict) -> bool:
    """Is a raw row already macro-ready (numeric amount, known unit, food item)?"""
    amount = str(ing.get("amount", "")).strip()
    unit = str(ing.get("unit", "")).strip()
    item = str(ing.get("item", "")).strip().lower()
    if not item or item in COUNT_UNITS or item in VOLUME_ML or item in MASS_G:
        return False
    if any(m in (amount + " " + item).lower() for m in _INSTR):
        return False
    amount_junk = bool(re.search(r"[a-zA-Z]", amount)) and amount.lower() not in WORD_NUMBERS
    if amount_junk or parse_amount_to_float(amount) is None:
        return False
    if get_unit_family(unit) == "other":
        return False
    return True


def main():
    ap = argparse.ArgumentParser(description="Ingredient data quality report")
    ap.add_argument("--examples", action="store_true", help="Print example rows per bucket")
    args = ap.parse_args()

    recipes_dir = paths.recipes_dir()
    files = [f for f in sorted(recipes_dir.glob("*.md")) if not f.name.startswith(".")]

    total = clean_before = clean_after = dropped = review_after = 0
    notes = Counter()
    examples = {"recovered": [], "dropped": [], "flagged": []}

    for f in files:
        try:
            body = parse_recipe_file(f.read_text(encoding="utf-8"))["body"]
            ings = extract_ingredients(body)
        except Exception:
            continue
        for ing in ings:
            total += 1
            before = _is_clean_raw(ing)
            clean_before += before
            c = clean_ingredient(ing)
            if c.dropped:
                dropped += 1
                if args.examples and len(examples["dropped"]) < 6:
                    examples["dropped"].append((f.name, ing, c.note))
                continue
            if c.needs_review:
                review_after += 1
                if args.examples and len(examples["flagged"]) < 6:
                    examples["flagged"].append((f.name, ing, c.note))
            else:
                clean_after += 1
            if c.note:
                notes[c.note.split(";")[0].strip()] += 1
            if args.examples and not before and not c.needs_review and "recovered" in c.note \
                    and len(examples["recovered"]) < 6:
                examples["recovered"].append((f.name, ing, c.to_ingredient()))

    pct = lambda n: f"{100*n/total:.1f}%" if total else "0%"
    print(f"\nIngredient data quality — {len(files)} recipes, {total} ingredient rows\n")
    print(f"  Clean BEFORE cleaning : {clean_before:5d}  ({pct(clean_before)})")
    print(f"  Clean AFTER  cleaning : {clean_after:5d}  ({pct(clean_after)})")
    print(f"  Flagged needs_review  : {review_after:5d}  ({pct(review_after)})")
    print(f"  Dropped (non-food)    : {dropped:5d}  ({pct(dropped)})")
    print(f"\n  Macro-ready (clean, after): {pct(clean_after)}  "
          f"[+{100*(clean_after-clean_before)/total:.1f} pts vs before]")

    print("\nTop cleaning actions:")
    for note, n in notes.most_common(8):
        if note:
            print(f"  {n:5d}  {note}")

    if args.examples:
        for bucket, rows in examples.items():
            if rows:
                print(f"\n--- {bucket} ---")
                for name, raw, out in rows:
                    print(f"  [{name[:30]}] {raw} -> {out}")
    print()


if __name__ == "__main__":
    main()
