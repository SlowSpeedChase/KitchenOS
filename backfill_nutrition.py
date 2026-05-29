#!/usr/bin/env python3
"""Backfill nutrition data for existing recipes using USDA + AI estimation.

Processes all recipes with nutrition_calories: null. For each recipe:
  1. Parse the ingredient table from the recipe body.
  2. Look up nutrition per ingredient via Nutritionix, then USDA, then AI.
  3. Write nutrition_calories/protein/carbs/fat back to the recipe file.

Usage:
    .venv/bin/python backfill_nutrition.py [--dry-run] [--limit N] [--force]
"""

import argparse
import re
import sys
import os
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import paths
from lib.backup import create_backup
from lib.nutrition import NutritionData
from lib.nutrition_lookup import calculate_recipe_nutrition
from lib.recipe_parser import parse_recipe_file, parse_ingredient_table


def extract_ingredients(body: str) -> list[dict]:
    """Extract structured ingredients from recipe body markdown."""
    match = re.search(r"## Ingredients\n\n((?:\|[^\n]+\n)+)", body)
    if not match:
        return []
    return parse_ingredient_table(match.group(1))


def write_nutrition_to_file(
    filepath: Path, nutrition: NutritionData, source: str, force: bool = False
) -> None:
    """Write nutrition values back into a recipe file's frontmatter.

    Args:
        filepath: Path to the recipe markdown file.
        nutrition: Per-serving nutrition data to write.
        source: Source string (e.g. "nutritionix", "usda", "ai").
        force: When True, replace any existing value (not just null).
    """
    content = filepath.read_text(encoding="utf-8")
    parts = content.split("---", 2)
    if len(parts) < 3:
        return

    frontmatter = parts[1]
    replacements = {
        "nutrition_calories": str(nutrition.calories),
        "nutrition_protein": str(nutrition.protein),
        "nutrition_carbs": str(nutrition.carbs),
        "nutrition_fat": str(nutrition.fat),
        "nutrition_source": f'"{source}"',
        "serving_size": '"1 serving"',
    }

    for key, value in replacements.items():
        if force:
            pattern = rf"(?m)^(\s*{re.escape(key)}:\s*).+"
        else:
            pattern = rf"(?m)^(\s*{re.escape(key)}:\s*)null"
        frontmatter = re.sub(pattern, rf"\g<1>{value}", frontmatter)

    filepath.write_text(f"---{frontmatter}---{parts[2]}", encoding="utf-8")


def backfill_recipe(filepath: Path, dry_run: bool = False, force: bool = False) -> bool:
    """Backfill nutrition for a single recipe file.

    Uses calculate_recipe_nutrition which handles per-serving division internally.

    Returns True if nutrition was calculated (or would be in dry_run), False if skipped.
    """
    content = filepath.read_text(encoding="utf-8")
    parsed = parse_recipe_file(content)
    frontmatter = parsed["frontmatter"]
    body = parsed["body"]

    ingredients = extract_ingredients(body)
    if not ingredients:
        return False

    try:
        servings = int(frontmatter.get("servings") or 1)
    except (ValueError, TypeError):
        servings = 1

    servings = max(servings, 1)
    result = calculate_recipe_nutrition(ingredients, servings)
    if result is None:
        return False

    if not dry_run:
        create_backup(filepath)
        write_nutrition_to_file(filepath, result.nutrition, result.source, force=force)

    return True


def collect_recipes_needing_backfill(recipes_dir: Path, force: bool = False) -> list[Path]:
    """Return recipe files with null nutrition_calories."""
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


def main():
    parser = argparse.ArgumentParser(
        description="Backfill nutrition data for recipes using USDA + AI"
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing files")
    parser.add_argument("--limit", type=int, help="Process at most N recipes")
    parser.add_argument(
        "--force", action="store_true", help="Re-process even recipes with existing data"
    )
    args = parser.parse_args()

    recipes_dir = paths.recipes_dir()
    if args.dry_run:
        print("DRY RUN — no files will be modified\n")

    print(f"Scanning: {recipes_dir}")
    candidates = collect_recipes_needing_backfill(recipes_dir, force=args.force)

    if args.limit:
        candidates = candidates[: args.limit]

    print(f"Recipes to process: {len(candidates)}\n")

    updated = skipped = failed = 0

    for filepath in candidates:
        print(f"  {filepath.name}...", end=" ", flush=True)
        try:
            result = backfill_recipe(filepath, dry_run=args.dry_run, force=args.force)
            if result:
                print("ok")
                updated += 1
            else:
                print("skipped (no ingredients)")
                skipped += 1
        except Exception as e:
            print(f"ERROR: {e}")
            failed += 1

    print(f"\n{'[DRY RUN] ' if args.dry_run else ''}Done:")
    print(f"  Updated: {updated}")
    print(f"  Skipped: {skipped}")
    print(f"  Failed:  {failed}")


if __name__ == "__main__":
    main()
