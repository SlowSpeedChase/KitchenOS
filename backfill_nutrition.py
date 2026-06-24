#!/usr/bin/env python3
"""Backfill nutrition data for existing recipes using the gram-based engine.

For each recipe with ``nutrition_calories: null`` (or all, with ``--force``):
  1. Parse the ingredient table from the recipe body.
  2. Compute per-serving macros with ``lib.nutrition_engine`` (USDA/OFF + grams,
     LLM only for unresolved portions).
  3. Write nutrition_* / nutrition_source / nutrition_confidence back to the
     frontmatter, de-duplicating any keys a prior run left behind.

Usage:
    .venv/bin/python backfill_nutrition.py [--dry-run] [--limit N] [--force]
    .venv/bin/python backfill_nutrition.py --fix-duplicates [--dry-run]
"""

import argparse
import re
import sys
import os
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from lib import paths
from lib.backup import create_backup
from lib.nutrition_engine import calculate_recipe_nutrition
from lib.recipe_parser import parse_recipe_file, parse_ingredient_table

# Scalar frontmatter keys this tool manages — de-duplicated and (re)written.
# Limiting to scalars keeps multi-line list keys (tags:, dietary:) untouched.
_MANAGED_KEYS = {
    "nutrition_calories", "nutrition_protein", "nutrition_carbs",
    "nutrition_fat", "nutrition_source", "nutrition_confidence",
    "serving_size", "needs_review",
}


def extract_ingredients(body: str) -> list[dict]:
    """Extract structured ingredients from recipe body markdown."""
    match = re.search(r"## Ingredients\n\n((?:\|[^\n]+\n)+)", body)
    if not match:
        return []
    return parse_ingredient_table(match.group(1))


def rewrite_frontmatter(fm: str, updates: dict) -> str:
    """Rewrite frontmatter: de-duplicate managed scalar keys and apply updates.

    Duplicate occurrences of a managed key are collapsed to a single line (the
    last position wins, matching YAML "last key wins" semantics). Keys in
    ``updates`` overwrite the kept line, or are appended once if absent. Passing
    ``updates={}`` performs a pure de-duplication pass (``--fix-duplicates``).
    Non-managed keys and list/continuation lines pass through untouched.
    """
    lines = fm.split("\n")
    out: list = []
    last_idx: dict = {}

    for line in lines:
        m = re.match(r"^([A-Za-z_][\w]*):", line)
        key = m.group(1) if (m and not line[:1].isspace()) else None
        if key in _MANAGED_KEYS:
            if key in last_idx:
                out[last_idx[key]] = None  # drop the earlier duplicate
            last_idx[key] = len(out)
        out.append(line)

    # Find a good insertion point for new keys: right after the last managed key
    # if any exist, else just before the trailing blank line.
    for key, value in updates.items():
        new_line = f"{key}: {value}"
        if key in last_idx:
            out[last_idx[key]] = new_line
        else:
            out.append(new_line)
            last_idx[key] = len(out) - 1

    return "\n".join(l for l in out if l is not None)


def _split_frontmatter(content: str):
    """Return (frontmatter_text, rest) or (None, None) if no frontmatter."""
    parts = content.split("---", 2)
    if len(parts) < 3:
        return None, None
    return parts[1], parts[2]


def write_nutrition_to_file(filepath: Path, result) -> None:
    """Write engine results into a recipe file's frontmatter (de-duplicated)."""
    content = filepath.read_text(encoding="utf-8")
    fm, rest = _split_frontmatter(content)
    if fm is None:
        return

    updates = {
        "nutrition_calories": result.nutrition.calories,
        "nutrition_protein": result.nutrition.protein,
        "nutrition_carbs": result.nutrition.carbs,
        "nutrition_fat": result.nutrition.fat,
        "nutrition_source": f'"{result.source}"',
        "nutrition_confidence": result.confidence,
        "serving_size": '"1 serving"',
    }
    if result.needs_review:
        updates["needs_review"] = "true"

    new_fm = rewrite_frontmatter(fm, updates)
    filepath.write_text(f"---{new_fm}---{rest}", encoding="utf-8")


def fix_duplicates_in_file(filepath: Path) -> bool:
    """De-duplicate managed frontmatter keys in place. Returns True if changed."""
    content = filepath.read_text(encoding="utf-8")
    fm, rest = _split_frontmatter(content)
    if fm is None:
        return False
    new_fm = rewrite_frontmatter(fm, {})
    if new_fm == fm:
        return False
    filepath.write_text(f"---{new_fm}---{rest}", encoding="utf-8")
    return True


def _print_audit(result) -> None:
    """Print the per-ingredient audit trail (grams, source, contribution)."""
    for li in result.line_items:
        cal = li.contribution.get("calories", 0)
        print(
            f"      {li.item[:28]:28} {li.grams:8.1f} g  {li.grams_method:14}"
            f" {li.food_source or '-':5} {cal:6.0f} kcal"
        )
    flag = " [needs review]" if result.needs_review else ""
    print(
        f"      → per serving: {result.nutrition.calories} kcal /"
        f" {result.nutrition.protein}p / {result.nutrition.carbs}c /"
        f" {result.nutrition.fat}f  (servings={result.servings_used},"
        f" conf={result.confidence}){flag}"
    )


def backfill_recipe(filepath: Path, dry_run: bool = False) -> bool:
    """Backfill nutrition for a single recipe file.

    Returns True if nutrition was calculated (or would be in dry_run).
    """
    content = filepath.read_text(encoding="utf-8")
    parsed = parse_recipe_file(content)
    body = parsed["body"]

    ingredients = extract_ingredients(body)
    if not ingredients:
        return False

    # Pass servings raw (may be None) so the engine flags servings_inferred
    # instead of silently treating the whole recipe as one serving.
    result = calculate_recipe_nutrition(ingredients, parsed["frontmatter"].get("servings"))
    if result is None:
        return False

    if dry_run:
        _print_audit(result)
    else:
        create_backup(filepath)
        write_nutrition_to_file(filepath, result)

    return True


def collect_recipes_needing_backfill(recipes_dir: Path, force: bool = False) -> list[Path]:
    """Return recipe files with null nutrition_calories (or all, with force)."""
    files = []
    for md_file in sorted(recipes_dir.glob("*.md")):
        if md_file.name.startswith("."):
            continue
        try:
            content = md_file.read_text(encoding="utf-8")
            parsed = parse_recipe_file(content)
            fm = parsed["frontmatter"]
            if "source_url" not in fm:
                continue
            if force or fm.get("nutrition_calories") is None:
                files.append(md_file)
        except Exception:
            continue
    return files


def collect_all_recipes(recipes_dir: Path) -> list[Path]:
    return [
        f for f in sorted(recipes_dir.glob("*.md")) if not f.name.startswith(".")
    ]


def run_fix_duplicates(recipes_dir: Path, dry_run: bool) -> None:
    print(f"Scanning for duplicate nutrition keys: {recipes_dir}\n")
    changed = 0
    for filepath in collect_all_recipes(recipes_dir):
        content = filepath.read_text(encoding="utf-8")
        fm, _ = _split_frontmatter(content)
        if fm is None:
            continue
        if rewrite_frontmatter(fm, {}) != fm:
            print(f"  {filepath.name}: duplicate keys"
                  f"{' (would fix)' if dry_run else ' — fixed'}")
            if not dry_run:
                create_backup(filepath)
                fix_duplicates_in_file(filepath)
            changed += 1
    print(f"\n{'[DRY RUN] ' if dry_run else ''}Files with duplicates: {changed}")


def main():
    parser = argparse.ArgumentParser(
        description="Backfill nutrition data for recipes (gram-based engine)"
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing files")
    parser.add_argument("--limit", type=int, help="Process at most N recipes")
    parser.add_argument(
        "--force", action="store_true", help="Re-process even recipes with existing data"
    )
    parser.add_argument(
        "--fix-duplicates", action="store_true",
        help="Only de-duplicate managed frontmatter keys; don't recalculate",
    )
    args = parser.parse_args()

    recipes_dir = paths.recipes_dir()

    if args.fix_duplicates:
        run_fix_duplicates(recipes_dir, args.dry_run)
        return

    if args.dry_run:
        print("DRY RUN — no files will be modified\n")

    print(f"Scanning: {recipes_dir}")
    candidates = collect_recipes_needing_backfill(recipes_dir, force=args.force)

    if args.limit:
        candidates = candidates[: args.limit]

    print(f"Recipes to process: {len(candidates)}\n")

    updated = skipped = failed = 0

    for filepath in candidates:
        print(f"  {filepath.name}...")
        try:
            if backfill_recipe(filepath, dry_run=args.dry_run):
                updated += 1
            else:
                print("    skipped (no ingredients / unresolved)")
                skipped += 1
        except Exception as e:
            print(f"    ERROR: {e}")
            failed += 1

    print(f"\n{'[DRY RUN] ' if args.dry_run else ''}Done:")
    print(f"  Updated: {updated}")
    print(f"  Skipped: {skipped}")
    print(f"  Failed:  {failed}")


if __name__ == "__main__":
    main()
