#!/usr/bin/env python3
"""Backfill nutrition data for existing recipes using USDA + AI estimation.

Processes all recipes with nutrition_calories: null. For each recipe:
  1. Parse the ingredient table from the recipe body.
  2. Look up nutrition per ingredient via USDA FoodData Central (free).
  3. Fall back to Ollama AI estimate for any ingredients USDA can't find.
  4. Write nutrition_calories/protein/carbs/fat back to the recipe file.

Usage:
    .venv/bin/python backfill_nutrition.py [--dry-run] [--limit N] [--force]
"""

import argparse
import re
import sys
import os
from pathlib import Path
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import paths
from lib.backup import create_backup
from lib.nutrition import NutritionData
from lib.nutrition_lookup import lookup_usda, estimate_with_ai, NutritionLookupResult
from lib.recipe_parser import parse_recipe_file, parse_ingredient_table


def lookup_usda_ai(ingredients: list[dict]) -> Optional[NutritionLookupResult]:
    """Look up nutrition using USDA per-ingredient, AI for fallback.

    Returns the *total* (not per-serving) nutrition for all ingredients combined.
    Division by servings is the caller's responsibility (backfill_recipe).

    Args:
        ingredients: List of dicts with 'amount', 'unit', 'item' keys.

    Returns:
        NutritionLookupResult with total nutrition, or None if all lookups fail.
    """
    total = NutritionData.empty()
    any_usda = False
    failed_strs = []

    for ing in ingredients:
        result = lookup_usda(ing.get("item", ""))
        if result:
            total = total + result.nutrition
            any_usda = True
        else:
            failed_strs.append(
                f"{ing.get('amount', '1')} {ing.get('unit', '')} {ing.get('item', '')}".strip()
            )

    if failed_strs:
        ai_result = estimate_with_ai(failed_strs)
        if ai_result:
            total = total + ai_result.nutrition
            source = "usda+ai" if any_usda else "ai"
        elif not any_usda:
            return None
        else:
            source = "usda"
    else:
        source = "usda"

    return NutritionLookupResult(nutrition=total, source=source)


def extract_ingredients(body: str) -> list[dict]:
    """Extract structured ingredients from recipe body markdown."""
    match = re.search(r"## Ingredients\n\n((?:\|[^\n]+\n)+)", body)
    if not match:
        return []
    return parse_ingredient_table(match.group(1))


def write_nutrition_to_file(filepath: Path, nutrition: NutritionData, source: str) -> None:
    """Write nutrition values back into a recipe file's frontmatter."""
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
        pattern = rf"(?m)^(\s*{re.escape(key)}:\s*)null"
        frontmatter = re.sub(pattern, rf"\g<1>{value}", frontmatter)

    filepath.write_text(f"---{frontmatter}---{parts[2]}", encoding="utf-8")


def backfill_recipe(filepath: Path, dry_run: bool = False) -> bool:
    """Backfill nutrition for a single recipe file.

    Looks up total nutrition for all ingredients, then divides by servings
    before writing per-serving values to the frontmatter.

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

    result = lookup_usda_ai(ingredients)
    if result is None:
        return False

    # Divide totals by servings here — lookup_usda_ai returns totals
    servings = max(servings, 1)
    per_serving = result.nutrition * (1.0 / servings)

    if not dry_run:
        create_backup(filepath)
        write_nutrition_to_file(filepath, per_serving, result.source)

    return True


def collect_recipes_needing_backfill(recipes_dir: Path, force: bool = False) -> list[Path]:
    """Return recipe files with null nutrition_calories."""
    files = []
    for md_file in sorted(recipes_dir.glob("*.md")):
        if md_file.name.startswith("."):
            continue
        content = md_file.read_text(encoding="utf-8")
        parsed = parse_recipe_file(content)
        fm = parsed["frontmatter"]
        if "source_url" not in fm:
            continue
        if force or fm.get("nutrition_calories") is None:
            files.append(md_file)
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
            result = backfill_recipe(filepath, dry_run=args.dry_run)
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
