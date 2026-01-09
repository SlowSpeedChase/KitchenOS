#!/usr/bin/env python3
"""Generate shopping list from meal plan.

Reads recipe links from a Meal Plan note, aggregates ingredients,
and pushes the combined list to Apple Reminders.

Usage:
    python shopping_list.py                    # Auto-detect current week's plan
    python shopping_list.py --week 2026-W03   # Use specific week's plan
    python shopping_list.py --plan custom.md  # Use custom file
    python shopping_list.py --dry-run          # Preview without adding
    python shopping_list.py --output list.txt  # Save to file
    python shopping_list.py --clear            # Clear list first
"""

import argparse
import re
import sys
from datetime import date
from pathlib import Path

from lib.recipe_parser import parse_recipe_file, parse_ingredient_table
from lib.ingredient_aggregator import aggregate_ingredients, format_ingredient
from lib.reminders import add_to_reminders, clear_reminders_list, create_reminders_list
from lib.shopping_list_generator import (
    parse_week_string,
    extract_ingredient_table,
    find_recipe_file,
    MEAL_PLANS_PATH,
)

# Configuration
OBSIDIAN_VAULT = Path("/Users/chaseeasterling/Library/Mobile Documents/iCloud~md~obsidian/Documents/KitchenOS")
LEGACY_MEAL_PLAN_PATH = OBSIDIAN_VAULT / "Meal Plan.md"
REMINDERS_LIST = "Shopping"


def get_current_week_plan() -> Path | None:
    """Get the meal plan file for the current week.

    Returns:
        Path to current week's meal plan, or None if not found.
    """
    today = date.today()
    iso_cal = today.isocalendar()
    filename = f"{iso_cal.year}-W{iso_cal.week:02d}.md"
    filepath = MEAL_PLANS_PATH / filename

    if filepath.exists():
        return filepath
    return None


def resolve_meal_plan_path(args) -> Path:
    """Determine which meal plan file to use.

    Priority:
    1. --plan (explicit file path)
    2. --week (specific week)
    3. Auto-detect current week
    4. Fallback to legacy Meal Plan.md
    """
    if args.plan:
        return args.plan

    if args.week:
        return parse_week_string(args.week)

    # Try auto-detect current week
    current_week_plan = get_current_week_plan()
    if current_week_plan:
        return current_week_plan

    # Fallback to legacy path
    return LEGACY_MEAL_PLAN_PATH


def parse_meal_plan(meal_plan_path):
    """Extract recipe links from meal plan note.

    Returns:
        List of recipe names (without [[brackets]])
    """
    if not meal_plan_path.exists():
        print(f"Error: Meal plan not found: {meal_plan_path}", file=sys.stderr)
        sys.exit(1)

    content = meal_plan_path.read_text(encoding='utf-8')

    # Find all [[wiki links]]
    links = re.findall(r'\[\[([^\]]+)\]\]', content)

    return links


def main():
    parser = argparse.ArgumentParser(description="Generate shopping list from meal plan")
    parser.add_argument('--week', type=str, help='Week to use (e.g., 2026-W03)')
    parser.add_argument('--plan', type=Path, help='Custom meal plan file')
    parser.add_argument('--dry-run', action='store_true', help='Preview without adding to Reminders')
    parser.add_argument('--output', type=Path, help='Output to file instead of Reminders')
    parser.add_argument('--clear', action='store_true', help='Clear list before adding')
    args = parser.parse_args()

    # Resolve meal plan path
    try:
        meal_plan_path = resolve_meal_plan_path(args)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Using meal plan: {meal_plan_path.name}")

    # Parse meal plan
    recipe_names = parse_meal_plan(meal_plan_path)
    print(f"Found {len(recipe_names)} recipes in meal plan")

    if not recipe_names:
        print("No recipes found. Add [[Recipe Name]] links to your meal plan.")
        return

    # Load all ingredients
    all_ingredients = []
    loaded_recipes = 0

    for name in recipe_names:
        recipe_file = find_recipe_file(name)
        if recipe_file:
            try:
                content = recipe_file.read_text(encoding='utf-8')
                parsed = parse_recipe_file(content)
                # Extract ingredients from body table, not frontmatter
                table_text = extract_ingredient_table(parsed['body'])
                if table_text:
                    ingredients = parse_ingredient_table(table_text)
                    all_ingredients.extend(ingredients)
                    loaded_recipes += 1
                else:
                    print(f"Warning: No ingredients table found in {name}")
            except Exception as e:
                print(f"Warning: Could not parse {name}: {e}", file=sys.stderr)
        else:
            print(f"Warning: Recipe not found: {name}")

    print(f"Loaded ingredients from {loaded_recipes} recipes")

    if not all_ingredients:
        print("No ingredients found.")
        return

    # Aggregate
    aggregated = aggregate_ingredients(all_ingredients)
    formatted = [format_ingredient(ing) for ing in aggregated]

    print(f"Aggregated to {len(formatted)} items")

    if args.dry_run:
        print("\nShopping List:")
        for item in formatted:
            print(f"  - {item}")
        return

    if args.output:
        args.output.write_text('\n'.join(formatted), encoding='utf-8')
        print(f"Saved to {args.output}")
        return

    # Add to Reminders
    try:
        create_reminders_list(REMINDERS_LIST)

        if args.clear:
            clear_reminders_list(REMINDERS_LIST)
            print(f"Cleared {REMINDERS_LIST} list")

        add_to_reminders(formatted, REMINDERS_LIST)
        print(f"Added {len(formatted)} items to {REMINDERS_LIST}")
    except Exception as e:
        print(f"Error adding to Reminders: {e}", file=sys.stderr)
        print("You can use --output to save to a file instead.")
        sys.exit(1)


if __name__ == "__main__":
    main()
