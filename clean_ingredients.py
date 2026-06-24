#!/usr/bin/env python3
"""Clean existing recipes' ingredient tables (Phase A: decimals + amount/unit accuracy).

Rewrites each recipe's ``## Ingredients`` markdown table through
``lib.ingredient_cleaner``: amounts become decimals (Unicode fractions expanded,
ranges → midpoint), amounts/units embedded in the item are recovered, garnish/
seasoning rows are marked negligible, and non-ingredient rows (leaked oven temps,
empty/unit-only) are dropped. Item-text presentation (markers, dup words) is left
for Phase B.

Safe by default — prints a preview and writes nothing. Pass ``--apply`` to write
(a backup is made via ``lib.backup`` first; re-run the nutrition backfill after).

Usage:
    .venv/bin/python clean_ingredients.py                 # dry-run preview (all)
    .venv/bin/python clean_ingredients.py --limit 5       # preview first 5
    .venv/bin/python clean_ingredients.py --apply          # write changes
"""
import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from lib import paths
from lib.backup import create_backup
from lib.recipe_parser import parse_recipe_file, parse_ingredient_table
from lib.ingredient_cleaner import clean_ingredients

# Captures the "## Ingredients" header plus the contiguous markdown table rows.
_ING_TABLE_RE = re.compile(r"(## Ingredients\s*\n\n)((?:\|[^\n]*\n)+)")


def render_table(cleaned) -> str:
    """Render cleaned (non-dropped) ingredients as a markdown table."""
    lines = ["| Amount | Unit | Ingredient |", "|--------|------|------------|"]
    for c in cleaned:
        if c.dropped:
            continue
        lines.append(f"| {c.amount} | {c.unit} | {c.item} |")
    return "\n".join(lines) + "\n"


def clean_recipe(path: Path, apply: bool):
    """Clean one recipe's ingredient table. Returns (cleaned, changed) or None."""
    content = path.read_text(encoding="utf-8")
    m = _ING_TABLE_RE.search(content)
    if not m:
        return None

    raw_rows = parse_ingredient_table(m.group(2))
    if not raw_rows:
        return None
    cleaned = clean_ingredients(raw_rows)

    new_table = render_table(cleaned)
    new_content = content[:m.start(2)] + new_table + content[m.end(2):]
    changed = new_content != content

    if changed and apply:
        create_backup(path)
        path.write_text(new_content, encoding="utf-8")

    return cleaned, changed


def _print_diff(name: str, cleaned) -> None:
    print(f"  {name}")
    for c in cleaned:
        if c.dropped:
            print(f"      DROP   {c.item[:40]:40}  ({c.note})")
        else:
            flag = "  [review]" if c.needs_review else ""
            note = f"  ← {c.note}" if c.note else ""
            print(f"      {c.amount:>6} {c.unit:10} {c.item[:34]:34}{flag}{note}")


def main():
    ap = argparse.ArgumentParser(description="Clean recipe ingredient tables")
    ap.add_argument("--apply", action="store_true", help="Write changes (default: preview only)")
    ap.add_argument("--limit", type=int, help="Process at most N recipes")
    ap.add_argument("--quiet", action="store_true", help="Summary only, no per-row diff")
    args = ap.parse_args()

    recipes_dir = paths.recipes_dir()
    files = [f for f in sorted(recipes_dir.glob("*.md")) if not f.name.startswith(".")]
    if args.limit:
        files = files[: args.limit]

    if not args.apply:
        print("PREVIEW — no files will be modified (use --apply to write)\n")
    print(f"Scanning: {recipes_dir}  ({len(files)} recipes)\n")

    recipes_changed = rows_total = rows_dropped = rows_review = 0

    for path in files:
        result = clean_recipe(path, apply=args.apply)
        if result is None:
            continue
        cleaned, changed = result
        rows_total += len(cleaned)
        rows_dropped += sum(1 for c in cleaned if c.dropped)
        rows_review += sum(1 for c in cleaned if c.needs_review and not c.dropped)
        if changed:
            recipes_changed += 1
            if not args.quiet:
                _print_diff(path.name, cleaned)

    print(f"\n{'[APPLIED]' if args.apply else '[PREVIEW]'} "
          f"Recipes changed: {recipes_changed}/{len(files)}")
    print(f"  Ingredient rows: {rows_total}")
    print(f"  Dropped (non-food): {rows_dropped}")
    print(f"  Flagged needs_review: {rows_review}")
    if not args.apply:
        print("\nRun with --apply to write (backups saved to .history/), "
              "then re-run: backfill_nutrition.py --force")


if __name__ == "__main__":
    main()
