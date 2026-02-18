#!/usr/bin/env python3
"""
Import recipes from Crouton iOS app (.crumb files) into KitchenOS Obsidian vault.

Usage:
    python import_crouton.py "/path/to/Crouton Recipes"
    python import_crouton.py --dry-run "/path/to/Crouton Recipes"
    python import_crouton.py --no-enrich "/path/to/Crouton Recipes"
"""

import argparse
import json
import sys
import re
import requests
from datetime import date
from pathlib import Path

from lib.crouton_parser import parse_crumb_file
from prompts.crouton_enrichment import CROUTON_ENRICHMENT_PROMPT, build_enrichment_prompt
from templates.recipe_template import format_recipe_markdown, generate_filename, generate_tools_callout
from templates.recipemd_template import format_recipemd, generate_recipemd_filename

# Configuration (matches extract_recipe.py)
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "mistral:7b"
OBSIDIAN_RECIPES_PATH = Path(
    "/Users/chaseeasterling/Library/Mobile Documents"
    "/iCloud~md~obsidian/Documents/KitchenOS/Recipes"
)


def enrich_with_ollama(recipe_data: dict) -> dict:
    """Call Ollama to infer missing metadata fields.

    Returns updated recipe_data with enriched fields (or unchanged on failure).
    """
    prompt = (
        f"{CROUTON_ENRICHMENT_PROMPT}\n\n"
        f"{build_enrichment_prompt(recipe_data['recipe_name'], recipe_data['ingredients'], recipe_data['instructions'])}"
    )

    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "format": "json",
            },
            timeout=120,
        )
        response.raise_for_status()
        result = json.loads(response.json().get("response", "{}"))

        # Merge enriched fields into recipe_data
        for field in ("description", "cuisine", "protein", "difficulty", "dish_type"):
            val = result.get(field)
            if val and isinstance(val, str):
                recipe_data[field] = val

        # List fields
        for field in ("meal_occasion", "dietary", "equipment"):
            val = result.get(field)
            if val and isinstance(val, list):
                recipe_data[field] = val

        # Normalize meal_occasion to slugified strings
        occasion = recipe_data.get("meal_occasion", [])
        if isinstance(occasion, str):
            occasion = [occasion]
        recipe_data["meal_occasion"] = [
            o.strip().lower().replace(" ", "-")
            for o in occasion
            if o and isinstance(o, str)
        ][:3]

        return recipe_data

    except Exception as e:
        print(f"    Ollama enrichment failed: {e}", file=sys.stderr)
        return recipe_data


def check_duplicate(recipe_name: str) -> bool:
    """Check if a recipe with this name already exists in the vault."""
    filename = generate_filename(recipe_name)
    return (OBSIDIAN_RECIPES_PATH / filename).exists()


def save_imported_recipe(recipe_data: dict) -> tuple[Path, bool]:
    """Save a Crouton-imported recipe to the Obsidian vault.

    Handles duplicate naming and generates both main + Cooking Mode files.

    Returns:
        Tuple of (filepath, is_duplicate).
    """
    recipe_name = recipe_data["recipe_name"]
    is_duplicate = check_duplicate(recipe_name)

    if is_duplicate:
        recipe_name_for_file = f"{recipe_name} (Crouton)"
    else:
        recipe_name_for_file = recipe_name

    # Generate markdown using existing template
    source_url = recipe_data.get("source_url", "")
    source_channel = recipe_data.get("source_channel", "") or "Crouton"
    today = date.today().isoformat()

    # For the template, use source_channel as "video_title" display
    video_title = f"Crouton — {source_channel}" if source_channel != "Crouton" else "Crouton"

    # Override recipe_name for filename generation (but keep original in data)
    file_recipe_data = dict(recipe_data)
    file_recipe_data["recipe_name"] = recipe_name_for_file

    markdown = format_recipe_markdown(
        file_recipe_data,
        video_url=source_url,
        video_title=video_title,
        channel=source_channel,
        date_added=today,
    )

    # Replace the footer line to say "Imported from Crouton" instead of "Extracted from"
    if source_url:
        new_footer = f"*Imported from Crouton — [source]({source_url}) on {today}*"
    else:
        new_footer = f"*Imported from Crouton on {today}*"
    markdown = re.sub(
        r'\*Extracted from \[.*?\]\(.*?\) on ' + re.escape(today) + r'\*',
        new_footer,
        markdown,
    )

    # Inject Crouton notes into My Notes section if present
    crouton_notes = recipe_data.get("notes", "")
    if crouton_notes:
        empty_notes = "## My Notes\n\n<!-- Your personal notes, ratings, and modifications go here -->"
        filled_notes = f"## My Notes\n\n*From Crouton:*\n{crouton_notes}"
        markdown = markdown.replace(empty_notes, filled_notes)

    # Write main recipe file
    OBSIDIAN_RECIPES_PATH.mkdir(parents=True, exist_ok=True)
    filename = generate_filename(recipe_name_for_file)
    filepath = OBSIDIAN_RECIPES_PATH / filename
    filepath.write_text(markdown, encoding="utf-8")

    # Write Cooking Mode file
    recipemd_content = format_recipemd(
        file_recipe_data,
        video_url=source_url,
        video_title=video_title,
        channel=source_channel,
    )
    recipemd_dir = OBSIDIAN_RECIPES_PATH / "Cooking Mode"
    recipemd_dir.mkdir(parents=True, exist_ok=True)
    recipemd_filename = generate_recipemd_filename(recipe_name_for_file)
    recipemd_path = recipemd_dir / recipemd_filename
    recipemd_path.write_text(recipemd_content, encoding="utf-8")

    return filepath, is_duplicate


def main():
    parser = argparse.ArgumentParser(
        description="Import Crouton .crumb recipes into KitchenOS"
    )
    parser.add_argument(
        "crouton_dir",
        type=str,
        help="Path to folder containing .crumb files",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would be imported without writing files",
    )
    parser.add_argument(
        "--no-enrich",
        action="store_true",
        help="Skip Ollama enrichment (faster, but metadata fields will be null)",
    )
    args = parser.parse_args()

    crouton_dir = Path(args.crouton_dir)
    if not crouton_dir.is_dir():
        print(f"Error: {crouton_dir} is not a directory", file=sys.stderr)
        sys.exit(1)

    crumb_files = sorted(crouton_dir.glob("*.crumb"))
    if not crumb_files:
        print(f"No .crumb files found in {crouton_dir}")
        sys.exit(0)

    total = len(crumb_files)
    imported = 0
    duplicates = 0
    failed = 0

    print(f"Found {total} .crumb files in {crouton_dir}")
    if args.dry_run:
        print("DRY RUN — no files will be written\n")
    if args.no_enrich:
        print("Skipping Ollama enrichment\n")

    for i, crumb_path in enumerate(crumb_files, 1):
        prefix = f"[{i:3d}/{total}]"

        try:
            with open(crumb_path, encoding="utf-8") as f:
                crumb_data = json.load(f)

            recipe_data = parse_crumb_file(crumb_data)
            recipe_name = recipe_data["recipe_name"]
            is_dup = check_duplicate(recipe_name)
            dup_label = " (duplicate)" if is_dup else ""

            if args.dry_run:
                suffix = f" → {recipe_name} (Crouton).md" if is_dup else ""
                print(f"{prefix} {recipe_name}{dup_label}{suffix}")
                if is_dup:
                    duplicates += 1
                imported += 1
                continue

            # Enrich with Ollama
            if not args.no_enrich:
                print(f"{prefix} {recipe_name}{dup_label} ... enriching", end="", flush=True)
                recipe_data = enrich_with_ollama(recipe_data)
                print(" ... ", end="", flush=True)
            else:
                print(f"{prefix} {recipe_name}{dup_label} ... ", end="", flush=True)

            # Save
            filepath, was_dup = save_imported_recipe(recipe_data)
            print(f"saved → {filepath.name}")

            imported += 1
            if was_dup:
                duplicates += 1

        except Exception as e:
            print(f"{prefix} {crumb_path.stem} ... FAILED: {e}", file=sys.stderr)
            failed += 1

    print(f"\nDone: {imported} imported ({duplicates} duplicates), {failed} failed")


if __name__ == "__main__":
    main()
