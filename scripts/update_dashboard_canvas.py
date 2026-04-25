#!/usr/bin/env python3
"""Update the KitchenOS Dashboard canvas to point at the latest meal plan and shopping list."""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import paths

CANVAS_PATH = paths.vault_root() / "Dashboards" / "KitchenOS Dashboard.canvas"
MEAL_PLANS_DIR = paths.meal_plans_dir()
SHOPPING_LISTS_DIR = paths.shopping_lists_dir()

WEEK_PATTERN = re.compile(r"(\d{4})-W(\d{2})\.md$")


def latest_file(directory: Path) -> str | None:
    """Find the most recent week-numbered file in a directory."""
    best = None
    best_key = (0, 0)
    for entry in directory.iterdir():
        m = WEEK_PATTERN.match(entry.name)
        if m:
            key = (int(m.group(1)), int(m.group(2)))
            if key > best_key:
                best_key = key
                best = entry.name
    return best


def update_canvas() -> bool:
    if not CANVAS_PATH.exists():
        print(f"Canvas not found: {CANVAS_PATH}", file=sys.stderr)
        return False

    with CANVAS_PATH.open("r") as f:
        canvas = json.load(f)

    latest_meal = latest_file(MEAL_PLANS_DIR)
    latest_shopping = latest_file(SHOPPING_LISTS_DIR)

    changed = False
    for node in canvas.get("nodes", []):
        if node.get("type") != "file":
            continue
        path = node.get("file", "")

        if path.startswith("Meal Plans/") and latest_meal:
            new_path = f"Meal Plans/{latest_meal}"
            if path != new_path:
                node["file"] = new_path
                changed = True
                print(f"Meal plan: {path} -> {new_path}")

        elif path.startswith("Shopping Lists/") and latest_shopping:
            new_path = f"Shopping Lists/{latest_shopping}"
            if path != new_path:
                node["file"] = new_path
                changed = True
                print(f"Shopping list: {path} -> {new_path}")

    if changed:
        with CANVAS_PATH.open("w") as f:
            json.dump(canvas, f, indent=2)
            f.write("\n")
        print("Dashboard canvas updated.")
    else:
        print("Dashboard canvas already up to date.")

    return True


if __name__ == "__main__":
    update_canvas()
