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

from templates.meal_plan_template import generate_meal_plan_markdown, generate_filename

# Configuration
OBSIDIAN_VAULT = Path("/Users/chaseeasterling/Library/Mobile Documents/iCloud~md~obsidian/Documents/KitchenOS")
MEAL_PLANS_PATH = OBSIDIAN_VAULT / "Meal Plans"


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


if __name__ == "__main__":
    main()
