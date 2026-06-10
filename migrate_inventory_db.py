#!/usr/bin/env python3
"""One-time migration: import legacy Inventory.md into data/kitchenos.db.

Parses the existing markdown table, inserts rows into the inventory table,
leaves Inventory.md.bak behind, and regenerates Inventory.md as the new
read-only view. Refuses to run if the DB inventory table already has rows.

Usage: .venv/bin/python migrate_inventory_db.py [--dry-run]
"""
import argparse
import shutil

from lib.inventory import (
    inventory_path,
    parse_inventory_markdown,
    read_inventory,
    write_inventory,
)


def migrate(dry_run: bool = False) -> dict:
    path = inventory_path()
    if not path.exists():
        print("No Inventory.md found — nothing to migrate.")
        return {"imported": 0}
    if read_inventory():
        print("DB inventory table is not empty — refusing to overwrite.")
        return {"imported": 0}

    items = parse_inventory_markdown(path.read_text(encoding="utf-8"))
    print(f"Parsed {len(items)} items from {path}")
    if dry_run:
        for it in items:
            print(f"  {it.name} — {it.quantity} {it.unit} ({it.location})")
        return {"imported": 0}

    shutil.copy2(path, path.with_suffix(".md.bak"))
    write_inventory(items)  # writes DB + regenerates the view
    # verify round-trip
    count = len(read_inventory())
    if count != len(items):
        raise RuntimeError(f"round-trip count mismatch: parsed {len(items)}, DB has {count}")
    print(f"Imported {len(items)} items. Backup at {path.with_suffix('.md.bak')}")
    return {"imported": len(items)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    migrate(dry_run=ap.parse_args().dry_run)
