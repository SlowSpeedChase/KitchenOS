#!/usr/bin/env python3
"""
KitchenOS - Cuisine Data Cleanup & Seasonal Population Migration

Fixes inconsistent cuisine values and populates seasonal ingredient data.

Usage:
    python migrate_cuisine.py [--dry-run] [--no-seasonal]
"""

import argparse
import re
import sys
import os
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.backup import create_backup
from lib.recipe_parser import parse_recipe_file, parse_ingredient_table

OBSIDIAN_RECIPES_PATH = Path(
    "/Users/chaseeasterling/Library/Mobile Documents/"
    "iCloud~md~obsidian/Documents/KitchenOS/Recipes"
)

# Variant consolidation — maps non-standard cuisine values to standard ones.
# None means "clear this value" (handled per-recipe in RECIPE_OVERRIDES or left null).
CUISINE_CORRECTIONS = {
    "Asian-inspired": "Asian",
    "Korean-inspired": "Korean",
    "Korean-American": "Korean",
    "Japanese-American fusion": "Japanese",
    "Chinese (Sichuan) or Asian": "Chinese",
    "Italian (inferred from Murcattt channel)": "Italian",
    "Vegan": None,
    "Vegetarian": None,
    "Not specified": None,
    "International": None,
    "Fusion": None,
    "protein:": None,
}

# Per-recipe overrides — applied first, wins over CUISINE_CORRECTIONS.
# Keys are recipe filenames (stem, no .md extension).
RECIPE_OVERRIDES = {
    # Misclassified
    "Seneyet Jaj O Batata": "Middle Eastern",
    "Macarona Bi Laban": "Middle Eastern",
    "Beef Steak Pepper Lunch Skillet": "Japanese",
    "Spicy Baked Black Bean Nachos": "Tex-Mex",
    "Queso Dip Recipe": "Tex-Mex",
    "Chili Cheese Tortillas": "Tex-Mex",
    "Cilantro Lime Chicken": "Mexican",
    "Ginger-Lime Marinade For Chicken": "Asian",
    # Dietary labels → actual cuisine
    "200G Lentils And 1 Sweet Potato": "Indian",
    "Cauliflower Steak With Butter Bean Puree And Chimichurri": "South American",
    "High-Protein Bean Lentil Dip (Crouton)": "Middle Eastern",
    # Null fills — misclassified or obviously inferable
    "Pasta Aglio E Olio Inspired By Chef": "Italian",
    "Hash Brown Casserole": "American",
    "Rich Fudgy Chocolate Cake": "American",
    "Large Batch Freezer Biscuits": "American",
    "Lime Cheesecake": "American",
    "Meal Prep Systems": "American",
    "19 Calorie Fudgy Brownies (Crouton)": "American",
    "5-Ingredient Cottage Cheese Cookie Dough": "American",
    "Blended Chocolate Salted Caramel Chia Pudding Mousse": "American",
    "Blueberry Donut Holes (Cottage Cheese Or Yogurt)": "American",
    "Charred Cabbage": "American",
    "Cherry Vanilla Breakfast Smoothie": "American",
    "Chewy Peanut Butter Cookies": "American",
    "Chocolate Chip Protein Cookies": "American",
    "Chocolate Cream Pie": "American",
    "Cosmic Brownie Protein Ice Cream": "American",
    "Cottage Cheese Chicken Caesar Wrap": "American",
    "Dairy-Free Dill Dressing": "American",
    "Deconstructed Strawberry Cheesecake 20G Protein": "American",
    "Double Dark Chocolate Granola": "American",
    "Dr. Rupy's No Bake Protein Bar": "American",
    "Goddess Salad": "American",
    "Healthy Blueberry Apple Oatmeal Cake": "American",
    "Healthy Delicious Recipe": "American",
    "High Protein Low Cal Chicken Sandwich": "American",
    "High Protein Sweet Potato, Beef, And Cottage Cheese Bowl": "American",
    "High-Protein Chocolate Chia Pudding Recipe": "American",
    "Matcha Smoothie": "American",
    "Nutella Protein Dessert": "American",
    "Oat Flour Pancakes": "American",
    "Oats With Chia Seeds & Yogurt Recipe": "American",
    "Peanut Butter Chocolate Coffee Smoothie": "American",
    "Protein Cabbage Wraps (Meatless)": "American",
    "Protein Cheesecake": "American",
    "Salted Honey Pistachio Cookies": "American",
    "Slutty Brownie Recipe": "American",
    "Strawberry Buttercream Frosting": "American",
    "Untitled-Recipe": "American",
    # Sriracha Lime → Asian-Inspired
    "Sriracha Lime Chicken Bowls": "Asian",
    # Breakfast Lentils → Indian
    "Breakfast Lentils Vegan Porridge": "Indian",
}


def apply_cuisine_corrections(recipe_name: str, current_cuisine) -> str | None:
    """Apply deterministic cuisine corrections for a recipe.

    Priority: RECIPE_OVERRIDES > CUISINE_CORRECTIONS > pass-through.

    Args:
        recipe_name: Recipe filename stem (no .md)
        current_cuisine: Current cuisine value (str or None)

    Returns:
        Corrected cuisine string, or None if should be null
    """
    # 1. Per-recipe override (highest priority)
    if recipe_name in RECIPE_OVERRIDES:
        return RECIPE_OVERRIDES[recipe_name]

    # 2. General correction map
    if current_cuisine in CUISINE_CORRECTIONS:
        return CUISINE_CORRECTIONS[current_cuisine]

    # 3. Pass through
    return current_cuisine


def update_frontmatter_field(content: str, field: str, value) -> str:
    """Update a single frontmatter field in recipe markdown content.

    Args:
        content: Full markdown file content with YAML frontmatter
        field: Frontmatter field name to update
        value: New value (str, list, int, or None)

    Returns:
        Updated content with the field changed
    """
    # Format value for YAML
    if value is None:
        yaml_value = "null"
    elif isinstance(value, list):
        if not value:
            yaml_value = "[]"
        elif isinstance(value[0], str):
            yaml_value = "[" + ", ".join(f'"{v}"' for v in value) + "]"
        else:
            yaml_value = "[" + ", ".join(str(v) for v in value) + "]"
    elif isinstance(value, str):
        yaml_value = f'"{value}"'
    else:
        yaml_value = str(value)

    # Replace the field line in frontmatter
    pattern = rf'^({field}:\s*).*$'
    replacement = rf'\g<1>{yaml_value}'
    return re.sub(pattern, replacement, content, count=1, flags=re.MULTILINE)


def run_cuisine_migration(recipes_dir: Path, dry_run: bool = False) -> dict:
    """Run cuisine correction migration on all recipe files.

    Args:
        recipes_dir: Path to Recipes folder
        dry_run: If True, report changes without modifying files

    Returns:
        dict with 'updated', 'skipped', 'errors' lists
    """
    results = {"updated": [], "skipped": [], "errors": []}

    if not recipes_dir.exists():
        print(f"Recipes directory not found: {recipes_dir}")
        return results

    for md_file in sorted(recipes_dir.glob("*.md")):
        if md_file.name.startswith("."):
            continue

        try:
            content = md_file.read_text(encoding="utf-8")
            parsed = parse_recipe_file(content)
            fm = parsed["frontmatter"]
            recipe_name = md_file.stem
            current_cuisine = fm.get("cuisine")

            corrected = apply_cuisine_corrections(recipe_name, current_cuisine)

            if corrected == current_cuisine:
                results["skipped"].append((md_file.name, "cuisine already correct"))
                continue

            old_display = current_cuisine or "null"
            new_display = corrected or "null"
            change_desc = f'{old_display} → {new_display}'

            if dry_run:
                results["updated"].append((md_file.name, change_desc))
            else:
                create_backup(md_file)
                new_content = update_frontmatter_field(content, "cuisine", corrected)
                md_file.write_text(new_content, encoding="utf-8")
                results["updated"].append((md_file.name, change_desc))

        except Exception as e:
            results["errors"].append((md_file.name, str(e)))

    return results


def run_seasonal_migration(recipes_dir: Path, dry_run: bool = False) -> dict:
    """Populate seasonal_ingredients and peak_months for recipes with empty data.

    Requires Ollama running with mistral:7b.

    Args:
        recipes_dir: Path to Recipes folder
        dry_run: If True, report what would change without modifying files

    Returns:
        dict with 'updated', 'skipped', 'errors' lists
    """
    from lib.seasonality import match_ingredients_to_seasonal, get_peak_months

    results = {"updated": [], "skipped": [], "errors": []}

    if not recipes_dir.exists():
        print(f"Recipes directory not found: {recipes_dir}")
        return results

    md_files = sorted(recipes_dir.glob("*.md"))
    total = len([f for f in md_files if not f.name.startswith(".")])
    count = 0

    for md_file in md_files:
        if md_file.name.startswith("."):
            continue

        count += 1

        try:
            content = md_file.read_text(encoding="utf-8")
            parsed = parse_recipe_file(content)
            fm = parsed["frontmatter"]

            existing_seasonal = fm.get("seasonal_ingredients", [])
            if existing_seasonal:
                results["skipped"].append((md_file.name, "already has seasonal data"))
                continue

            # Parse ingredients from body
            ing_match = re.search(
                r"## Ingredients\n\n((?:\|[^\n]+\n)+)", parsed["body"]
            )
            if not ing_match:
                results["skipped"].append((md_file.name, "no ingredient table"))
                continue

            ingredients = parse_ingredient_table(ing_match.group(1))
            if not ingredients:
                results["skipped"].append((md_file.name, "empty ingredient table"))
                continue

            print(f"  [{count}/{total}] {md_file.stem}...", end=" ", flush=True)

            if dry_run:
                results["updated"].append((md_file.name, "would populate seasonal data"))
                print("(dry run)")
                continue

            seasonal = match_ingredients_to_seasonal(ingredients)
            months = get_peak_months(seasonal)

            if not seasonal:
                results["skipped"].append((md_file.name, "no seasonal matches"))
                print("no matches")
                continue

            new_content = update_frontmatter_field(content, "seasonal_ingredients", seasonal)
            new_content = update_frontmatter_field(new_content, "peak_months", months)
            md_file.write_text(new_content, encoding="utf-8")

            results["updated"].append(
                (md_file.name, f"matched: {seasonal}, months: {months}")
            )
            print(f"matched {len(seasonal)} items")

        except Exception as e:
            results["errors"].append((md_file.name, str(e)))
            print(f"error: {e}")

    return results


def print_results(results: dict, label: str, dry_run: bool):
    """Print migration results summary."""
    prefix = "Would update" if dry_run else "Updated"

    print(f"\n--- {label} ---")

    if results["updated"]:
        print(f"{prefix}: {len(results['updated'])} file(s)")
        for name, detail in results["updated"]:
            print(f"  {name}: {detail}")

    if results["skipped"]:
        print(f"Skipped: {len(results['skipped'])} file(s)")

    if results["errors"]:
        print(f"Errors: {len(results['errors'])} file(s)")
        for name, error in results["errors"]:
            print(f"  {name}: {error}")


def main():
    parser = argparse.ArgumentParser(
        description="Clean up cuisine data and populate seasonal ingredients"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Show what would change without modifying files"
    )
    parser.add_argument(
        "--no-seasonal", action="store_true", help="Skip seasonal data population (Ollama)"
    )
    parser.add_argument(
        "--path", type=str, help="Path to recipes directory (default: Obsidian vault)"
    )
    args = parser.parse_args()

    recipes_dir = Path(args.path) if args.path else OBSIDIAN_RECIPES_PATH

    if args.dry_run:
        print("DRY RUN — no files will be modified\n")

    # Phase 1: Cuisine cleanup
    print(f"Scanning: {recipes_dir}")
    print("\nPhase 1: Cuisine corrections...")
    cuisine_results = run_cuisine_migration(recipes_dir, dry_run=args.dry_run)
    print_results(cuisine_results, "Cuisine Cleanup", args.dry_run)

    # Phase 2: Seasonal data population
    if not args.no_seasonal:
        print("\nPhase 2: Seasonal data population (Ollama)...")
        seasonal_results = run_seasonal_migration(recipes_dir, dry_run=args.dry_run)
        print_results(seasonal_results, "Seasonal Data", args.dry_run)
    else:
        print("\nPhase 2: Skipped (--no-seasonal)")

    print("\nDone!")


if __name__ == "__main__":
    main()
