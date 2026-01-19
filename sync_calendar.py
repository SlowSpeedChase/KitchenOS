#!/usr/bin/env python3
"""Sync meal plans to ICS calendar file.

Reads all meal plan files and generates a single ICS file for
Obsidian Full Calendar plugin and Apple Calendar subscription.

Usage:
    python sync_calendar.py           # Generate calendar
    python sync_calendar.py --dry-run # Preview without writing
"""

import argparse
import re
import sys
from pathlib import Path

from lib.meal_plan_parser import parse_meal_plan
from lib.ics_generator import generate_ics

# Configuration
OBSIDIAN_VAULT = Path("/Users/chaseeasterling/Library/Mobile Documents/iCloud~md~obsidian/Documents/KitchenOS")
MEAL_PLANS_PATH = OBSIDIAN_VAULT / "Meal Plans"
ICS_OUTPUT_PATH = OBSIDIAN_VAULT / "meal_calendar.ics"


def parse_week_from_filename(filename: str) -> tuple[int, int] | None:
    """Extract year and week from filename like '2026-W04.md'.

    Returns:
        Tuple of (year, week) or None if invalid format
    """
    match = re.match(r'^(\d{4})-W(\d{2})\.md$', filename)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def collect_all_days() -> list[dict]:
    """Collect all days from all meal plan files.

    Returns:
        List of day dicts sorted by date
    """
    all_days = []

    if not MEAL_PLANS_PATH.exists():
        return all_days

    for file_path in MEAL_PLANS_PATH.glob('*.md'):
        parsed = parse_week_from_filename(file_path.name)
        if not parsed:
            continue

        year, week = parsed
        try:
            content = file_path.read_text(encoding='utf-8')
            days = parse_meal_plan(content, year, week)
            all_days.extend(days)
        except Exception as e:
            print(f"Warning: Could not parse {file_path.name}: {e}", file=sys.stderr)

    # Sort by date
    all_days.sort(key=lambda d: d['date'])
    return all_days


def main():
    parser = argparse.ArgumentParser(description="Sync meal plans to ICS calendar")
    parser.add_argument('--dry-run', action='store_true', help='Preview without writing file')
    args = parser.parse_args()

    print("Collecting meal plans...")
    days = collect_all_days()

    if not days:
        print("No meal plans found.")
        return

    # Count days with meals
    days_with_meals = sum(1 for d in days if any([d['breakfast'], d['lunch'], d['snack'], d['dinner']]))
    print(f"Found {len(days)} days across meal plans ({days_with_meals} with meals)")

    # Generate ICS
    ics_content = generate_ics(days)

    if args.dry_run:
        print("\n--- Preview (first 2000 chars) ---")
        print(ics_content.decode('utf-8')[:2000])
        print("--- End Preview ---")
        print(f"\nDry run complete. Would write to: {ICS_OUTPUT_PATH}")
        return

    # Write file
    ICS_OUTPUT_PATH.write_bytes(ics_content)
    print(f"Written: {ICS_OUTPUT_PATH}")


if __name__ == "__main__":
    main()
