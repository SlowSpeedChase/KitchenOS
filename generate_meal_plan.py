#!/usr/bin/env python3
"""Generate weekly meal plan templates.

Creates meal plan markdown files in the Obsidian vault.
Designed to run via LaunchAgent, creating plans 2 weeks in advance.

Usage:
    python generate_meal_plan.py                  # Generate for 2 weeks ahead
    python generate_meal_plan.py --week 2026-W05  # Generate specific week
    python generate_meal_plan.py --dry-run        # Preview without creating
    python generate_meal_plan.py --force          # Overwrite existing file
"""

import argparse
import re
import sys
from datetime import date, timedelta
from pathlib import Path

from templates.meal_plan_template import generate_meal_plan_markdown, generate_filename, get_week_start
from lib.backup import cleanup_old_backups
from lib.seasonality import calculate_season_score, load_seasonal_config
from lib.recipe_parser import parse_recipe_file

# Configuration
OBSIDIAN_VAULT = Path("/Users/chaseeasterling/Library/Mobile Documents/iCloud~md~obsidian/Documents/KitchenOS")
MEAL_PLANS_PATH = OBSIDIAN_VAULT / "Meal Plans"
RECIPES_HISTORY_PATH = OBSIDIAN_VAULT / "Recipes" / ".history"


def parse_week_string(week_str: str) -> tuple[int, int]:
    """Parse a week string like '2026-W03' into (year, week)."""
    match = re.match(r'^(\d{4})-W(\d{2})$', week_str)
    if not match:
        raise ValueError(f"Invalid week format: {week_str}. Expected format: YYYY-WNN (e.g., 2026-W03)")

    year = int(match.group(1))
    week = int(match.group(2))

    if week < 1 or week > 53:
        raise ValueError(f"Invalid week number: {week}. Must be 1-53.")

    return year, week


def get_target_week() -> tuple[int, int]:
    """Get the week that's 2 weeks from now."""
    target_date = date.today() + timedelta(weeks=2)
    iso_cal = target_date.isocalendar()
    return iso_cal.year, iso_cal.week


RECIPES_PATH = OBSIDIAN_VAULT / "Recipes"


def get_seasonal_suggestions(recipes_dir: Path, year: int, week: int, limit: int = 15) -> str:
    """Generate seasonal recipe suggestions section for meal plan.

    Scores recipes by seasonal ingredients, clusters by shared produce.

    Args:
        recipes_dir: Path to recipes directory
        year: ISO year
        week: ISO week number
        limit: Max recipes to suggest

    Returns:
        Markdown string with seasonal suggestions, or empty string
    """
    week_start = get_week_start(year, week)
    month = week_start.month

    config = load_seasonal_config()

    # Score all recipes
    scored = []
    for md_file in recipes_dir.glob("*.md"):
        if md_file.name.startswith('.'):
            continue
        try:
            content = md_file.read_text(encoding='utf-8')
            parsed = parse_recipe_file(content)
            fm = parsed['frontmatter']
            seasonal = fm.get('seasonal_ingredients', [])
            if not seasonal or not isinstance(seasonal, list):
                continue
            score = calculate_season_score(seasonal, month=month)
            if score > 0:
                scored.append({
                    'name': fm.get('title', md_file.stem),
                    'score': score,
                    'seasonal': [s for s in seasonal
                                 if config['ingredients'].get(s, {}).get('peak_months', [])
                                 and month in config['ingredients'][s]['peak_months']],
                })
        except Exception:
            continue

    if not scored:
        return ""

    # Sort by score descending
    scored.sort(key=lambda x: x['score'], reverse=True)
    scored = scored[:limit]

    # Group recipes by their top seasonal ingredient
    groups = {}
    for r in scored:
        key = r['seasonal'][0] if r['seasonal'] else 'other'
        if key not in groups:
            groups[key] = []
        groups[key].append(r)

    lines = ["\n## Seasonal Suggestions\n"]
    lines.append(f"*In season for {week_start.strftime('%B')}:*\n")

    for ingredient, recipes in sorted(groups.items(), key=lambda x: -len(x[1])):
        lines.append(f"**{ingredient.title()}** ({len(recipes)} recipes)")
        for r in recipes:
            lines.append(f"- [[{r['name']}]]")
        lines.append("")

    return '\n'.join(lines)


def ensure_meal_plans_folder():
    """Create Meal Plans folder if it doesn't exist."""
    if not MEAL_PLANS_PATH.exists():
        MEAL_PLANS_PATH.mkdir(parents=True)
        print(f"Created folder: {MEAL_PLANS_PATH}")


def main():
    parser = argparse.ArgumentParser(description="Generate weekly meal plan templates")
    parser.add_argument('--week', type=str, help='Week to generate (e.g., 2026-W03)')
    parser.add_argument('--dry-run', action='store_true', help='Preview without creating file')
    parser.add_argument('--force', action='store_true', help='Overwrite existing file')
    args = parser.parse_args()

    # Determine target week
    if args.week:
        try:
            year, week = parse_week_string(args.week)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        year, week = get_target_week()

    filename = generate_filename(year, week)
    filepath = MEAL_PLANS_PATH / filename

    print(f"Target: {year}-W{week:02d}")
    print(f"File: {filepath}")

    # Check if file exists
    if filepath.exists() and not args.force:
        print(f"File already exists. Use --force to overwrite.")
        return

    # Generate content
    content = generate_meal_plan_markdown(year, week)

    # Append seasonal suggestions if recipes have seasonal data
    if RECIPES_PATH.exists():
        suggestions = get_seasonal_suggestions(RECIPES_PATH, year, week)
        if suggestions:
            content += suggestions
            print("Added seasonal recipe suggestions")

    if args.dry_run:
        print("\n--- Preview ---")
        print(content)
        print("--- End Preview ---")
        print("\nDry run complete. No file created.")
        return

    # Ensure folder exists
    ensure_meal_plans_folder()

    # Write file
    filepath.write_text(content, encoding='utf-8')
    print(f"Created: {filepath}")

    # Cleanup old recipe backups (runs daily with meal plan generation)
    if RECIPES_HISTORY_PATH.exists():
        removed = cleanup_old_backups(RECIPES_HISTORY_PATH, max_age_days=30)
        if removed > 0:
            print(f"Cleaned up {removed} old backup(s)")


if __name__ == "__main__":
    main()
