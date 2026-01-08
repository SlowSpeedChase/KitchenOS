#!/usr/bin/env python3
"""
KitchenOS - Recipe Migration Tool
Applies template changes to existing recipe files.

Usage:
    python migrate_recipes.py [--dry-run]
"""

import argparse
import sys
import os
from pathlib import Path
from typing import List, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.backup import create_backup
from lib.recipe_parser import parse_recipe_file, extract_my_notes
from templates.recipe_template import RECIPE_SCHEMA

OBSIDIAN_RECIPES_PATH = Path("/Users/chaseeasterling/Library/Mobile Documents/iCloud~md~obsidian/Documents/KitchenOS/Recipes")


def migrate_recipe_file(filepath: Path) -> List[str]:
    """Migrate a single recipe file to current schema."""
    changes = []
    content = filepath.read_text(encoding='utf-8')
    parsed = parse_recipe_file(content)
    frontmatter = parsed['frontmatter']

    missing_fields = []
    for field in RECIPE_SCHEMA.keys():
        if field not in frontmatter:
            missing_fields.append(field)
            changes.append(f"Added field '{field}'")

    if not missing_fields:
        return changes

    lines = content.split('\n')
    new_lines = []
    in_frontmatter = False

    for line in lines:
        if line.strip() == '---':
            if not in_frontmatter:
                in_frontmatter = True
                new_lines.append(line)
            else:
                for field in missing_fields:
                    field_type = RECIPE_SCHEMA[field]
                    if field_type == list:
                        new_lines.append(f"{field}: []")
                    else:
                        new_lines.append(f"{field}: null")
                new_lines.append(line)
                in_frontmatter = False
        else:
            new_lines.append(line)

    new_content = '\n'.join(new_lines)
    filepath.write_text(new_content, encoding='utf-8')
    return changes


def run_migration(recipes_dir: Path, dry_run: bool = False) -> dict:
    """Run migration on all recipe files in directory."""
    results = {'updated': [], 'skipped': [], 'errors': []}

    if not recipes_dir.exists():
        print(f"Recipes directory not found: {recipes_dir}")
        return results

    for md_file in sorted(recipes_dir.glob("*.md")):
        if md_file.name.startswith('.'):
            continue

        try:
            content = md_file.read_text(encoding='utf-8')
            parsed = parse_recipe_file(content)

            if 'source_url' not in parsed['frontmatter']:
                results['skipped'].append((md_file.name, 'no source_url'))
                continue

            missing = [f for f in RECIPE_SCHEMA.keys() if f not in parsed['frontmatter']]

            if not missing:
                results['skipped'].append((md_file.name, 'already up to date'))
                continue

            if dry_run:
                results['updated'].append((md_file.name, [f"Would add '{f}'" for f in missing]))
            else:
                backup_path = create_backup(md_file)
                changes = migrate_recipe_file(md_file)
                results['updated'].append((md_file.name, changes, backup_path.name))

        except Exception as e:
            results['errors'].append((md_file.name, str(e)))

    return results


def print_results(results: dict, dry_run: bool):
    """Print migration results summary."""
    prefix = "Would update" if dry_run else "Updated"

    if results['updated']:
        print(f"\n{prefix}: {len(results['updated'])} file(s)")
        for item in results['updated']:
            if dry_run:
                name, changes = item
                print(f"  - {name}")
                for change in changes[:3]:
                    print(f"      {change}")
                if len(changes) > 3:
                    print(f"      ... and {len(changes) - 3} more")
            else:
                name, changes, backup = item
                print(f"  - {name} (backup: {backup})")

    if results['skipped']:
        print(f"\nSkipped: {len(results['skipped'])} file(s)")
        for name, reason in results['skipped']:
            print(f"  - {name} ({reason})")

    if results['errors']:
        print(f"\nErrors: {len(results['errors'])} file(s)")
        for name, error in results['errors']:
            print(f"  - {name}: {error}")


def main():
    parser = argparse.ArgumentParser(description="Migrate recipe files to current template schema")
    parser.add_argument('--dry-run', action='store_true', help='Show what would change without modifying files')
    parser.add_argument('--path', type=str, help='Path to recipes directory (default: Obsidian vault)')
    args = parser.parse_args()

    recipes_dir = Path(args.path) if args.path else OBSIDIAN_RECIPES_PATH

    if args.dry_run:
        print("DRY RUN - No files will be modified\n")

    print(f"Scanning: {recipes_dir}")
    results = run_migration(recipes_dir, dry_run=args.dry_run)
    print_results(results, args.dry_run)

    if not args.dry_run and results['updated']:
        print("\nMigration complete!")


if __name__ == "__main__":
    main()
