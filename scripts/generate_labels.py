#!/usr/bin/env python3
"""Write Kitchen Labels.md to the Obsidian vault for printing.

Thin wrapper over ``manage_inventory.py --labels``. Kept under ``scripts/``
so it parallels the other one-shot helpers (``add_button_to_meal_plans.py``).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running this file directly from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.inventory import load_layout
from templates.labels_template import render_labels

DEFAULT_VAULT = Path(
    "/Users/chaseeasterling/Library/Mobile Documents/iCloud~md~obsidian/Documents/KitchenOS"
)
LABELS_FILENAME = "Kitchen Labels.md"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Kitchen Labels.md")
    parser.add_argument("--vault", type=Path, default=DEFAULT_VAULT)
    parser.add_argument("--dry-run", action="store_true",
                        help="print to stdout instead of writing")
    args = parser.parse_args()

    layout = load_layout()
    content = render_labels(layout)

    if args.dry_run:
        sys.stdout.write(content)
        return 0

    target = args.vault / LABELS_FILENAME
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    print(f"wrote: {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
