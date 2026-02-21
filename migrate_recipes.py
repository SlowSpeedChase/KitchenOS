#!/usr/bin/env python3
"""
KitchenOS - Recipe Migration Tool
Applies template changes to existing recipe files.

Usage:
    python migrate_recipes.py [--dry-run]
"""

import argparse
import json
import re
import sys
import os
from pathlib import Path
from typing import List, Tuple

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.backup import create_backup
from lib.recipe_parser import parse_recipe_file, extract_my_notes, parse_ingredient_table
from lib.seasonality import match_ingredients_to_seasonal, get_peak_months
from templates.recipe_template import RECIPE_SCHEMA, generate_tools_callout

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "mistral:7b"

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


def infer_meal_occasion(frontmatter: dict) -> list:
    """Use Ollama to infer meal_occasion from existing recipe metadata.

    Args:
        frontmatter: Parsed frontmatter dict with title, cuisine, dish_type, etc.

    Returns:
        List of up to 3 slugified occasion strings, or empty list on failure.
    """
    title = frontmatter.get('title', '')
    cuisine = frontmatter.get('cuisine', '')
    dish_type = frontmatter.get('dish_type', '')
    protein = frontmatter.get('protein', '')
    difficulty = frontmatter.get('difficulty', '')
    prep_time = frontmatter.get('prep_time', '')
    cook_time = frontmatter.get('cook_time', '')

    prompt = f"""Given this recipe, return a JSON array of up to 3 meal occasions describing when someone would make this.

Recipe: {title}
Cuisine: {cuisine}
Type: {dish_type}
Protein: {protein}
Difficulty: {difficulty}
Prep time: {prep_time}
Cook time: {cook_time}

Use slugified values like: weeknight-dinner, grab-and-go-breakfast, meal-prep, weekend-project, packed-lunch, afternoon-snack, date-night, post-workout, crowd-pleaser, lazy-sunday

Return ONLY a JSON array of strings, nothing else. Example: ["weeknight-dinner", "meal-prep"]"""

    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "format": "json"
            },
            timeout=60
        )
        response.raise_for_status()
        result = response.json()
        raw = result.get("response", "")
        parsed = json.loads(raw)

        # Handle both {"meal_occasion": [...]} and bare [...] responses
        if isinstance(parsed, dict):
            occasions = parsed.get("meal_occasion", parsed.get("occasions", []))
        elif isinstance(parsed, list):
            occasions = parsed
        else:
            return []

        return [
            o.strip().lower().replace(' ', '-')
            for o in occasions if o and isinstance(o, str)
        ][:3]
    except Exception as e:
        print(f"    Warning: Could not infer meal_occasion: {e}")
        return []


def match_seasonal_produce(body: str) -> tuple[list[str], list[int]]:
    """Match ingredients from recipe body to seasonal produce.

    Args:
        body: Recipe markdown body containing ingredient table

    Returns:
        Tuple of (seasonal_ingredients, peak_months)
    """
    ing_match = re.search(r'## Ingredients\n\n((?:\|[^\n]+\n)+)', body)
    if not ing_match:
        return [], []

    ingredients = parse_ingredient_table(ing_match.group(1))
    if not ingredients:
        return [], []

    seasonal = match_ingredients_to_seasonal(ingredients)
    months = get_peak_months(seasonal)
    return seasonal, months


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
    - Replacing localhost URLs with Tailscale IP
    - Adding 'Add to Meal Plan' button if missing from Tools callout

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

    # Migrate localhost URLs to Tailscale IP
    if "localhost:5001" in new_content:
        new_content = new_content.replace("http://localhost:5001", "http://100.111.6.10:5001")
        changes.append("Updated button URLs from localhost to Tailscale IP")

    # Add "Add to Meal Plan" button if Tools callout exists but button is missing
    if has_tools_callout(new_content) and "Add to Meal Plan" not in new_content and filename:
        from urllib.parse import quote
        encoded_filename = quote(filename, safe='')
        meal_plan_button = (
            f'> ```button\n'
            f'> name Add to Meal Plan\n'
            f'> type link\n'
            f'> url http://100.111.6.10:5001/add-to-meal-plan?recipe={encoded_filename}\n'
            f'> ```\n'
        )
        # Insert before the closing of the tools callout (before the blank line after last ```)
        last_button_end = new_content.rfind('> ```\n')
        if last_button_end != -1:
            insert_pos = last_button_end + len('> ```\n')
            new_content = new_content[:insert_pos] + meal_plan_button + new_content[insert_pos:]
            changes.append("Added 'Add to Meal Plan' button")

    # Add cssclasses if missing
    if "cssclasses:" not in new_content:
        parts = new_content.split('---', 2)
        if len(parts) >= 3:
            frontmatter = parts[1]
            frontmatter = frontmatter.rstrip('\n') + '\ncssclasses:\n  - recipe\n'
            new_content = f"---{frontmatter}---{parts[2]}"
            changes.append("Added cssclasses: [recipe] to frontmatter")

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

    # Infer meal_occasion via Ollama if missing
    inferred_occasion = []
    if 'meal_occasion' in missing_fields:
        inferred_occasion = infer_meal_occasion(frontmatter)
        if inferred_occasion:
            changes.append(f"Inferred meal_occasion: {inferred_occasion}")

    # Infer seasonal ingredients via Ollama if missing
    inferred_seasonal = []
    inferred_peak_months = []
    if 'seasonal_ingredients' in missing_fields:
        inferred_seasonal, inferred_peak_months = match_seasonal_produce(parsed['body'])
        if inferred_seasonal:
            changes.append(f"Matched seasonal produce: {inferred_seasonal}")

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
                    if field == 'meal_occasion' and inferred_occasion:
                        quote = '"'
                        yaml_list = f"[{', '.join(quote + o + quote for o in inferred_occasion)}]"
                        new_lines.append(f"meal_occasion: {yaml_list}")
                    elif field == 'seasonal_ingredients' and inferred_seasonal:
                        quote = '"'
                        yaml_list = f"[{', '.join(quote + s + quote for s in inferred_seasonal)}]"
                        new_lines.append(f"seasonal_ingredients: {yaml_list}")
                    elif field == 'peak_months' and inferred_peak_months:
                        yaml_list = f"[{', '.join(str(m) for m in inferred_peak_months)}]"
                        new_lines.append(f"peak_months: {yaml_list}")
                    elif RECIPE_SCHEMA[field] == list:
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
    - Has localhost URLs that need Tailscale IP replacement
    - Missing 'Add to Meal Plan' button in Tools callout
    """
    # Look for 2-column table header (Amount | Ingredient) without Unit
    if '| Amount | Ingredient |' in content:
        return True
    # Check for missing Tools callout
    if not has_tools_callout(content):
        return True
    # Check for localhost URLs that need Tailscale IP replacement
    if "localhost:5001" in content:
        return True
    # Check for missing 'Add to Meal Plan' button
    if has_tools_callout(content) and "Add to Meal Plan" not in content:
        return True
    # Check for missing cssclasses
    if "cssclasses:" not in content:
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
                if 'meal_occasion' in missing:
                    changes.append("Would infer meal_occasion via Ollama")
                if 'seasonal_ingredients' in missing:
                    changes.append("Would match seasonal ingredients via Ollama")
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
