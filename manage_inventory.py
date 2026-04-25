#!/usr/bin/env python3
"""Kitchen inventory CLI.

Subcommands:
    --init     Write an empty Inventory.md skeleton (one section per shelf)
                  derived from config/storage_locations.json.
    --paste    Read a markdown table from stdin (or --file), preview the
                  routed rows, and append them to Inventory.md unless
                  --dry-run is set.
    --labels   Write Kitchen Labels.md to the vault for printing.

Vault path defaults to the same location used by the rest of KitchenOS
(``OBSIDIAN_VAULT`` constant in shopping_list.py / sync_calendar.py). Override
with --vault.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from lib.inventory import (
    INVENTORY_FILENAME,
    append_rows,
    load_layout,
)
from lib.receipt_paster import parse_paste
from templates.inventory_template import render_skeleton
from templates.labels_template import render_labels

DEFAULT_VAULT = Path(
    "/Users/chaseeasterling/Library/Mobile Documents/iCloud~md~obsidian/Documents/KitchenOS"
)
LABELS_FILENAME = "Kitchen Labels.md"


def cmd_init(vault: Path, force: bool) -> int:
    layout = load_layout()
    target = vault / INVENTORY_FILENAME
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and not force:
        print(f"refusing to overwrite existing {target}; pass --force to replace.")
        return 1
    target.write_text(render_skeleton(layout), encoding="utf-8")
    print(f"wrote skeleton: {target}")
    return 0


def cmd_paste(vault: Path, source: str | None, dry_run: bool) -> int:
    layout = load_layout()
    markdown = Path(source).read_text(encoding="utf-8") if source else sys.stdin.read()
    if not markdown.strip():
        print("no input received on stdin (or --file is empty)", file=sys.stderr)
        return 2

    rows, warnings = parse_paste(markdown, layout)
    for w in warnings:
        print(f"warn: {w}", file=sys.stderr)

    if not rows:
        print("no rows parsed from input", file=sys.stderr)
        return 2

    print(f"\nParsed {len(rows)} row(s):\n")
    print(f"{'Item':<24} {'Qty':>5} {'Unit':<8} {'Group':<18} {'Location':<24} Expires")
    print("-" * 96)
    for r in rows:
        shelf = layout.shelf_by_location(r.location)
        loc_label = shelf.section_heading if shelf else r.location
        print(f"{r.item[:24]:<24} {r.qty:>5} {r.unit:<8} {r.group:<18} {loc_label[:24]:<24} {r.expires or '-'}")
        for w in r.warnings:
            print(f"  ! {w}")

    if dry_run:
        print("\n(dry-run) no changes written.")
        return 0

    target = append_rows(rows, layout, vault)
    print(f"\nappended {len(rows)} row(s) -> {target}")
    return 0


def cmd_labels(vault: Path) -> int:
    layout = load_layout()
    target = vault / LABELS_FILENAME
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_labels(layout), encoding="utf-8")
    print(f"wrote: {target}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="KitchenOS inventory CLI")
    parser.add_argument("--vault", type=Path, default=DEFAULT_VAULT,
                        help=f"Obsidian vault path (default: {DEFAULT_VAULT})")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--init", action="store_true", help="write empty Inventory.md skeleton")
    group.add_argument("--paste", action="store_true", help="ingest a markdown table")
    group.add_argument("--labels", action="store_true", help="write Kitchen Labels.md")

    parser.add_argument("--file", type=str, default=None,
                        help="read paste markdown from a file instead of stdin")
    parser.add_argument("--dry-run", action="store_true",
                        help="preview --paste without writing Inventory.md")
    parser.add_argument("--force", action="store_true",
                        help="overwrite existing Inventory.md on --init")
    args = parser.parse_args()

    if args.init:
        return cmd_init(args.vault, args.force)
    if args.paste:
        return cmd_paste(args.vault, args.file, args.dry_run)
    if args.labels:
        return cmd_labels(args.vault)
    parser.error("no command selected")
    return 1


if __name__ == "__main__":
    sys.exit(main())
