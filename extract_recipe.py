#!/usr/bin/env python3
"""
KitchenOS - YouTube Recipe Extractor
Extracts recipes from cooking videos and saves to Obsidian vault.

Usage:
    python extract_recipe.py "https://www.youtube.com/watch?v=VIDEO_ID"
"""

import argparse
import json
import sys
import os
import requests
from pathlib import Path

from lib.backup import create_backup
from lib.recipe_parser import find_existing_recipe, parse_recipe_file, extract_my_notes
from lib.ingredient_validator import validate_ingredients
from lib.ingredient_parser import parse_ingredient

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main import youtube_parser, get_video_metadata, get_transcript
from prompts.recipe_extraction import SYSTEM_PROMPT, build_user_prompt
from templates.recipe_template import format_recipe_markdown, generate_filename
from templates.recipemd_template import format_recipemd, generate_recipemd_filename
from recipe_sources import (
    find_recipe_link,
    scrape_recipe_from_url,
    parse_recipe_from_description,
    extract_cooking_tips,
    search_creator_website,
)

# Configuration
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "mistral:7b"
OBSIDIAN_RECIPES_PATH = Path("/Users/chaseeasterling/Library/Mobile Documents/iCloud~md~obsidian/Documents/KitchenOS/Recipes")


def normalize_instructions(instructions: list) -> list:
    """Normalize instructions to {step, text, time} format.

    Handles AI responses that return instructions as plain strings
    instead of the requested {step, text, time} dicts.
    """
    if not instructions:
        return []

    normalized = []
    for i, inst in enumerate(instructions, 1):
        if isinstance(inst, str):
            # Plain string - convert to dict
            normalized.append({
                "step": i,
                "text": inst,
                "time": None
            })
        elif isinstance(inst, dict):
            # Already a dict - ensure it has required keys
            normalized.append({
                "step": inst.get("step", i),
                "text": inst.get("text", inst.get("description", "")),
                "time": inst.get("time")
            })
        else:
            # Unknown format - skip
            continue

    return normalized


def normalize_ingredients(ingredients: list) -> list:
    """Normalize ingredients to {amount, unit, item, inferred} format.

    Handles AI responses that use old format (name, quantity) instead of
    the requested (amount, unit, item) schema.
    """
    if not ingredients:
        return []

    normalized = []
    for ing in ingredients:
        if not isinstance(ing, dict):
            continue

        # Already in correct format?
        if 'amount' in ing and 'unit' in ing and 'item' in ing:
            normalized.append(ing)
            continue

        # Old format: {name: "...", quantity: "..."}
        if 'name' in ing:
            name = str(ing.get('name', ''))
            quantity = str(ing.get('quantity', ''))
            # Combine quantity and name for re-parsing
            combined = f"{quantity} {name}".strip() if quantity else name
            parsed = parse_ingredient(combined)
            parsed['inferred'] = ing.get('inferred', False)
            normalized.append(parsed)
            continue

        # Legacy format: {quantity: "...", item: "..."}
        if 'quantity' in ing:
            quantity = str(ing.get('quantity', ''))
            item = str(ing.get('item', ''))
            combined = f"{quantity} {item}".strip()
            parsed = parse_ingredient(combined)
            parsed['inferred'] = ing.get('inferred', False)
            normalized.append(parsed)
            continue

        # Unknown format - try to make sense of it
        item = str(ing.get('item', ing.get('name', '')))
        if item:
            parsed = parse_ingredient(item)
            parsed['inferred'] = ing.get('inferred', False)
            normalized.append(parsed)

    return normalized


def extract_recipe_with_ollama(title, channel, description, transcript):
    """Send video data to Ollama and extract recipe as JSON."""
    prompt = f"{SYSTEM_PROMPT}\n\n{build_user_prompt(title, channel, description, transcript)}"

    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "format": "json"
            },
            timeout=180
        )
        response.raise_for_status()

        result = response.json()
        recipe_json = result.get("response", "")

        # Parse the JSON response
        recipe_data = json.loads(recipe_json)
        return recipe_data, None

    except requests.exceptions.ConnectionError:
        return None, "Cannot connect to Ollama. Is it running? Try: ollama serve"
    except requests.exceptions.Timeout:
        return None, "Ollama request timed out (180s). Video may be too long."
    except json.JSONDecodeError as e:
        return None, f"Failed to parse Ollama response as JSON: {e}"
    except Exception as e:
        return None, f"Ollama error: {e}"


def save_recipe_to_obsidian(recipe_data, video_url, video_title, channel, video_id):
    """Format recipe as markdown and save to Obsidian vault.

    If a recipe for this video already exists, backs it up and preserves
    the My Notes section and date_added before overwriting.
    """
    # Check for existing recipe
    existing = find_existing_recipe(OBSIDIAN_RECIPES_PATH, video_id)
    preserved_notes = ""
    preserved_date_added = None
    filepath = None

    if existing:
        print(f"Found existing recipe: {existing.name}")

        # Create backup
        backup_path = create_backup(existing)
        print(f"Backup created: {backup_path.name}")

        # Preserve My Notes section and date_added
        old_content = existing.read_text(encoding='utf-8')
        preserved_notes = extract_my_notes(old_content)
        if preserved_notes:
            print("Preserving My Notes section")

        # Preserve original date_added
        try:
            parsed = parse_recipe_file(old_content)
            preserved_date_added = parsed['frontmatter'].get('date_added')
            if preserved_date_added:
                print(f"Preserving original date_added: {preserved_date_added}")
        except Exception:
            pass  # If parsing fails, just use today's date

        # Reuse existing filepath
        filepath = existing
    else:
        # Generate new filename
        filename = generate_filename(recipe_data.get('recipe_name', 'untitled-recipe'))
        filepath = OBSIDIAN_RECIPES_PATH / filename

    # Ensure directory exists
    OBSIDIAN_RECIPES_PATH.mkdir(parents=True, exist_ok=True)

    # Generate markdown
    markdown = format_recipe_markdown(recipe_data, video_url, video_title, channel, preserved_date_added)

    # If we have preserved notes, replace the empty My Notes section
    if preserved_notes:
        empty_notes = "## My Notes\n\n<!-- Your personal notes, ratings, and modifications go here -->"
        filled_notes = f"## My Notes\n\n{preserved_notes}"
        markdown = markdown.replace(empty_notes, filled_notes)

    # Write file
    filepath.write_text(markdown, encoding='utf-8')

    # Generate and save RecipeMD version to Cooking Mode subdirectory
    recipemd_content = format_recipemd(recipe_data, video_url, video_title, channel)
    recipemd_dir = OBSIDIAN_RECIPES_PATH / "Cooking Mode"
    recipemd_dir.mkdir(parents=True, exist_ok=True)
    recipemd_filename = generate_recipemd_filename(recipe_data.get('recipe_name', 'Untitled Recipe'))
    recipemd_path = recipemd_dir / recipemd_filename
    recipemd_path.write_text(recipemd_content, encoding='utf-8')

    return filepath


def extract_single_recipe(url: str, dry_run: bool = False, force: bool = False) -> dict:
    """Extract recipe from a YouTube URL.

    Args:
        url: YouTube video URL or ID
        dry_run: If True, don't save to Obsidian
        force: If True, re-extract even if recipe already exists

    Returns:
        dict with keys:
            success: bool
            title: str (video title)
            recipe_name: str (extracted recipe name)
            filepath: Path or None (where saved)
            error: str or None (error message if failed)
            skipped: bool (True if already existed)
    """
    result = {
        "success": False,
        "title": None,
        "recipe_name": None,
        "filepath": None,
        "error": None,
        "skipped": False,
        "source": None,
    }

    try:
        # Parse video ID and detect Shorts
        parsed = youtube_parser(url)
        video_id = parsed['video_id']
        is_short = parsed['is_short']

        # Use correct URL format
        if is_short:
            video_url = f"https://www.youtube.com/shorts/{video_id}"
        else:
            video_url = f"https://www.youtube.com/watch?v={video_id}"

        # Check for existing recipe first (skip unless force=True)
        existing = find_existing_recipe(OBSIDIAN_RECIPES_PATH, video_id)
        if existing and not dry_run and not force:
            result["success"] = True
            result["skipped"] = True
            result["filepath"] = existing
            # Try to get title from existing file
            try:
                content = existing.read_text(encoding='utf-8')
                parsed = parse_recipe_file(content)
                result["title"] = parsed['frontmatter'].get('video_title', existing.stem)
                result["recipe_name"] = parsed['frontmatter'].get('recipe_name', existing.stem)
            except Exception as e:
                print(f"Warning: Could not parse existing recipe metadata: {e}", file=sys.stderr)
                result["title"] = existing.stem
                result["recipe_name"] = existing.stem
            return result

        # Get video metadata (uses yt-dlp for Shorts)
        metadata = get_video_metadata(video_id, is_short=is_short)
        if not metadata:
            result["error"] = "Could not fetch video metadata"
            return result

        title = metadata['title']
        channel = metadata['channel']
        description = metadata['description']
        result["title"] = title

        # Get transcript
        transcript_result = get_transcript(video_id)
        transcript = transcript_result['text']

        # === PRIORITY CHAIN ===
        recipe_data = None
        source = None
        recipe_link = None

        # 1. Check for recipe link in description
        recipe_link = find_recipe_link(description)

        if recipe_link:
            recipe_data = scrape_recipe_from_url(recipe_link)
            if recipe_data:
                source = "webpage"

        # 2. Try parsing recipe from description
        if not recipe_data:
            recipe_data = parse_recipe_from_description(description, title, channel)
            if recipe_data:
                source = "description"

        # 3. Search creator's website for full recipe
        if not recipe_data:
            creator_url = search_creator_website(channel, title)
            if creator_url:
                recipe_data = scrape_recipe_from_url(creator_url)
                if recipe_data:
                    source = "creator_website"
                    recipe_link = creator_url  # For metadata

        # 4. Fall back to AI extraction from transcript
        if not recipe_data:
            recipe_data, error = extract_recipe_with_ollama(title, channel, description, transcript)
            if error:
                result["error"] = error
                return result
            source = "ai_extraction"

        # 5. Extract cooking tips if we got recipe from webpage, description, or creator website
        if source in ("webpage", "description", "creator_website") and transcript:
            tips = extract_cooking_tips(transcript, recipe_data)
            recipe_data['video_tips'] = tips

        # Add source metadata
        recipe_data['source'] = source
        recipe_data['source_url'] = recipe_link

        # Normalize AI output to standard formats (handles schema variations)
        recipe_data['ingredients'] = normalize_ingredients(
            recipe_data.get('ingredients', [])
        )
        recipe_data['instructions'] = normalize_instructions(
            recipe_data.get('instructions', [])
        )

        # Validate and repair ingredients (fixes AI extraction errors)
        recipe_data['ingredients'] = validate_ingredients(
            recipe_data.get('ingredients', []),
            verbose=True
        )

        recipe_name = recipe_data.get('recipe_name', 'Unknown Recipe')
        result["recipe_name"] = recipe_name
        result["source"] = source

        if dry_run:
            result["success"] = True
            return result

        # Save to Obsidian
        filepath = save_recipe_to_obsidian(recipe_data, video_url, title, channel, video_id)
        result["success"] = True
        result["filepath"] = filepath
        return result

    except Exception as e:
        result["error"] = str(e)
        return result


def main():
    parser = argparse.ArgumentParser(
        description="Extract recipes from YouTube cooking videos"
    )
    parser.add_argument(
        'url',
        type=str,
        help='YouTube video URL or ID'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Print recipe without saving to Obsidian'
    )
    parser.add_argument(
        '--force',
        action='store_true',
        help='Re-extract even if recipe already exists'
    )
    args = parser.parse_args()

    parsed = youtube_parser(args.url)
    video_id = parsed['video_id']
    is_short = parsed['is_short']
    video_type = "Short" if is_short else "video"
    print(f"Fetching {video_type} data for: {video_id}")

    result = extract_single_recipe(args.url, dry_run=args.dry_run, force=args.force)

    if not result["success"]:
        print(f"Error: {result['error']}", file=sys.stderr)
        sys.exit(1)

    if result["skipped"]:
        print(f"Recipe already exists: {result['filepath']}")
    elif args.dry_run:
        # For dry run, we need to regenerate the markdown for display
        # Re-fetch and display (simplified)
        print(f"Would extract: {result['recipe_name']}")
        print("(Use without --dry-run to save)")
    else:
        print(f"Title: {result['title']}")
        print(f"Extracted: {result['recipe_name']} (source: {result['source']})")
        print(f"Saved to: {result['filepath']}")
        print(f"SAVED: {result['filepath']}")

    print("\nDone!")


if __name__ == "__main__":
    main()
