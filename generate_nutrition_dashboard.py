#!/usr/bin/env python3
"""Generate nutrition dashboard from meal plans.

Usage:
    # Generate for current week
    .venv/bin/python generate_nutrition_dashboard.py

    # Generate for specific week
    .venv/bin/python generate_nutrition_dashboard.py --week 2026-W03

    # Dry run (preview without saving)
    .venv/bin/python generate_nutrition_dashboard.py --dry-run
"""

import argparse
from datetime import date
from pathlib import Path

from lib.nutrition_dashboard import generate_dashboard, save_dashboard


# Obsidian vault path
VAULT_PATH = Path(
    "/Users/chaseeasterling/Library/Mobile Documents"
    "/iCloud~md~obsidian/Documents/KitchenOS"
)


def get_current_week() -> str:
    """Get current ISO week string."""
    today = date.today()
    return f"{today.isocalendar().year}-W{today.isocalendar().week:02d}"


def main():
    parser = argparse.ArgumentParser(
        description="Generate nutrition dashboard from meal plans"
    )
    parser.add_argument(
        "--week",
        help="Week to generate dashboard for (e.g., 2026-W03). Defaults to current week.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview without saving to vault",
    )
    args = parser.parse_args()

    week = args.week or get_current_week()
    print(f"Generating nutrition dashboard for {week}...")

    try:
        if args.dry_run:
            markdown, warnings = generate_dashboard(week, VAULT_PATH)
            print("\n--- Preview ---")
            print(markdown)
            print("--- End Preview ---\n")
        else:
            output_path, warnings = save_dashboard(week, VAULT_PATH)
            print(f"Dashboard saved to: {output_path}")

        if warnings:
            print("\nWarnings:")
            for warning in warnings:
                print(f"  - {warning}")

    except FileNotFoundError as e:
        print(f"Error: {e}")
        return 1
    except ValueError as e:
        print(f"Error: {e}")
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
