#!/usr/bin/env python3
"""
KitchenOS - Recipe Migration Tool
Applies template changes to existing recipe files.

Usage:
    python migrate_recipes.py [--dry-run]
"""

import argparse
import re
import sys
import os
from pathlib import Path
from typing import List, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.backup import create_backup
from lib.recipe_parser import parse_recipe_file, extract_my_notes, parse_ingredient_table
from templates.recipe_template import RECIPE_SCHEMA, generate_tools_callout

OBSIDIAN_RECIPES_PATH = Path("/Users/chaseeasterling/Library/Mobile Documents/iCloud~md~obsidian/Documents/KitchenOS/Recipes")


def has_tools_callout(content: str) -> bool:
    """Check if content already has a Tools callout."""
    return "> [!tools]" in content.lower()


def add_tools_callout(content: str, filename: str) -> str:
    """Add Tools callout after frontmatter.

    Args:
        content: Full file content
        filename: Recipe filename for button URLs

    Returns:
        Content with Tools callout inserted
    """
    # Find end of frontmatter
    parts = content.split('---', 2)
    if len(parts) < 3:
        return content  # No frontmatter, skip

    frontmatter = parts[1]
    body = parts[2]

    # Generate callout
    callout = generate_tools_callout(filename)

    # Insert callout at start of body (after frontmatter)
    # Body typically starts with "\n\n# Title"
    new_body = "\n\n" + callout + body.lstrip('\n')

    return f"---{frontmatter}---{new_body}"


def migrate_ingredient_table(table_text: str) -> str:
    """Convert 2-column ingredient table to 3-column format.

    Args:
        table_text: Markdown table text (2-column format)

    Returns:
        New markdown table in 3-column format
    """
    ingredients = parse_ingredient_table(table_text)

    lines = ["| Amount | Unit | Ingredient |", "|--------|------|------------|"]
    for ing in ingredients:
        lines.append(f"| {ing['amount']} | {ing['unit']} | {ing['item']} |")

    return '\n'.join(lines)


def migrate_recipe_content(content: str, filename: str = None) -> Tuple[str, List[str]]:
    """
    Migrate recipe markdown content to new format.

    Handles:
    - Converting 2-column ingredient tables to 3-column format
    - Adding Tools callout with reprocess buttons

    Args:
        content: Full markdown file content
        filename: Recipe filename (for Tools callout URLs)

    Returns:
        Tuple of (new_content, list_of_changes)
    """
    changes = []
    new_content = content

    # Find and replace ingredient table
    # Pattern matches: ## Ingredients\n\n followed by table rows
    table_pattern = r'(## Ingredients\n\n)(\|[^\n]+\n\|[-|\s]+\n(?:\|[^\n]+\n)*)'

    def replace_table(match):
        header = match.group(1)
        old_table = match.group(2)
        # Check if already 3-column format
        if '| Amount | Unit | Ingredient |' in old_table:
            return match.group(0)
        new_table = migrate_ingredient_table(old_table)
        changes.append("Converted ingredient table to 3-column format")
        return f"{header}{new_table}\n"

    new_content = re.sub(table_pattern, replace_table, new_content)

    # Add Tools callout if missing
    if filename and not has_tools_callout(new_content):
        new_content = add_tools_callout(new_content, filename)
        changes.append("Added Tools callout with reprocess buttons")

    return new_content, changes


def migrate_recipe_file(filepath: Path) -> List[str]:
    """Migrate a single recipe file to current schema.

    Handles:
    - Adding missing frontmatter fields
    - Converting 2-column ingredient tables to 3-column format
    """
    changes = []
    content = filepath.read_text(encoding='utf-8')
    parsed = parse_recipe_file(content)
    frontmatter = parsed['frontmatter']

    # Track missing frontmatter fields
    missing_fields = []
    for field in RECIPE_SCHEMA.keys():
        if field not in frontmatter:
            missing_fields.append(field)
            changes.append(f"Added field '{field}'")

    # Migrate content (pass filename for Tools callout)
    new_content, content_changes = migrate_recipe_content(content, filepath.name)
    changes.extend(content_changes)

    # If no frontmatter changes needed, just apply content changes
    if not missing_fields:
        if content_changes:
            filepath.write_text(new_content, encoding='utf-8')
        return changes

    # Add missing frontmatter fields
    lines = new_content.split('\n')
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

    final_content = '\n'.join(new_lines)
    filepath.write_text(final_content, encoding='utf-8')
    return changes


def needs_content_migration(content: str) -> bool:
    """Check if content needs any content migration.

    Returns True if:
    - There's a 2-column ingredient table that needs conversion
    - Missing Tools callout
    """
    # Look for 2-column table header (Amount | Ingredient) without Unit
    if '| Amount | Ingredient |' in content:
        return True
    # Check for missing Tools callout
    if not has_tools_callout(content):
        return True
    return False


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

            # Check for frontmatter fields that need migration
            missing = [f for f in RECIPE_SCHEMA.keys() if f not in parsed['frontmatter']]

            # Check for content that needs migration
            needs_content = needs_content_migration(content)

            if not missing and not needs_content:
                results['skipped'].append((md_file.name, 'already up to date'))
                continue

            if dry_run:
                changes = [f"Would add '{f}'" for f in missing]
                if '| Amount | Ingredient |' in content:
                    changes.append("Would convert ingredient table to 3-column format")
                if not has_tools_callout(content):
                    changes.append("Would add Tools callout with reprocess buttons")
                results['updated'].append((md_file.name, changes))
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
