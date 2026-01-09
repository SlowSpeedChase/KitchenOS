#!/usr/bin/env python3
"""Add shopping list button to existing meal plans."""

from pathlib import Path

VAULT = Path("/Users/chaseeasterling/Library/Mobile Documents/iCloud~md~obsidian/Documents/KitchenOS")
MEAL_PLANS = VAULT / "Meal Plans"

BUTTON_TEMPLATE = '''```button
name Generate Shopping List
type link
action kitchenos://generate-shopping-list?week={week}
```'''


def add_button_to_meal_plan(filepath: Path) -> bool:
    """Add button to meal plan if not present.

    Returns True if modified, False if already has button.
    """
    content = filepath.read_text(encoding='utf-8')

    # Skip if already has button
    if '```button' in content:
        return False

    # Extract week from filename (2026-W04.md -> 2026-W04)
    week = filepath.stem

    # Insert button after first heading
    lines = content.split('\n')
    new_lines = []
    button_inserted = False

    for i, line in enumerate(lines):
        new_lines.append(line)
        # Insert after the # Meal Plan heading line
        if not button_inserted and line.startswith('# Meal Plan'):
            new_lines.append('')
            new_lines.append(BUTTON_TEMPLATE.format(week=week))
            button_inserted = True

    if button_inserted:
        filepath.write_text('\n'.join(new_lines), encoding='utf-8')
        return True
    return False


def main():
    if not MEAL_PLANS.exists():
        print(f"Meal Plans folder not found: {MEAL_PLANS}")
        return

    meal_plan_files = list(MEAL_PLANS.glob("*.md"))
    if not meal_plan_files:
        print("No meal plan files found.")
        return

    print(f"Found {len(meal_plan_files)} meal plan files")

    modified = 0
    skipped = 0

    for filepath in sorted(meal_plan_files):
        if add_button_to_meal_plan(filepath):
            print(f"Updated: {filepath.name}")
            modified += 1
        else:
            print(f"Skipped: {filepath.name} (already has button)")
            skipped += 1

    print(f"\nSummary: {modified} updated, {skipped} skipped")


if __name__ == "__main__":
    main()
