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

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main import youtube_parser, get_video_metadata, get_transcript
from prompts.recipe_extraction import SYSTEM_PROMPT, build_user_prompt
from templates.recipe_template import format_recipe_markdown, generate_filename
from recipe_sources import (
    find_recipe_link,
    scrape_recipe_from_url,
    parse_recipe_from_description,
    extract_cooking_tips,
)

# Configuration
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "mistral:7b"
OBSIDIAN_RECIPES_PATH = Path("/Users/chaseeasterling/Library/Mobile Documents/iCloud~md~obsidian/Documents/KitchenOS/Recipes")


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
    the My Notes section before overwriting.
    """
    # Check for existing recipe
    existing = find_existing_recipe(OBSIDIAN_RECIPES_PATH, video_id)
    preserved_notes = ""
    filepath = None

    if existing:
        print(f"Found existing recipe: {existing.name}")

        # Create backup
        backup_path = create_backup(existing)
        print(f"Backup created: {backup_path.name}")

        # Preserve My Notes section
        old_content = existing.read_text(encoding='utf-8')
        preserved_notes = extract_my_notes(old_content)
        if preserved_notes:
            print("Preserving My Notes section")

        # Reuse existing filepath
        filepath = existing
    else:
        # Generate new filename
        filename = generate_filename(recipe_data.get('recipe_name', 'untitled-recipe'))
        filepath = OBSIDIAN_RECIPES_PATH / filename

    # Ensure directory exists
    OBSIDIAN_RECIPES_PATH.mkdir(parents=True, exist_ok=True)

    # Generate markdown
    markdown = format_recipe_markdown(recipe_data, video_url, video_title, channel)

    # If we have preserved notes, replace the empty My Notes section
    if preserved_notes:
        empty_notes = "## My Notes\n\n<!-- Your personal notes, ratings, and modifications go here -->"
        filled_notes = f"## My Notes\n\n{preserved_notes}"
        markdown = markdown.replace(empty_notes, filled_notes)

    # Write file
    filepath.write_text(markdown, encoding='utf-8')

    return filepath


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
    args = parser.parse_args()

    # Parse video ID
    video_id = youtube_parser(args.url)
    video_url = f"https://www.youtube.com/watch?v={video_id}"

    print(f"Fetching video data for: {video_id}")

    # Get video metadata
    metadata = get_video_metadata(video_id)
    if not metadata:
        print("Error: Could not fetch video metadata", file=sys.stderr)
        sys.exit(1)

    title = metadata['title']
    channel = metadata['channel']
    description = metadata['description']

    print(f"Title: {title}")
    print(f"Channel: {channel}")

    # Get transcript
    transcript_result = get_transcript(video_id)
    transcript = transcript_result['text']

    if not transcript:
        print(f"Warning: No transcript available ({transcript_result.get('error', 'unknown error')})")
        print("Proceeding with description only...")
    else:
        print(f"Transcript source: {transcript_result['source']}")
        print(f"Transcript length: {len(transcript)} characters")

    # === PRIORITY CHAIN ===
    recipe_data = None
    source = None
    recipe_link = None

    # 1. Check for recipe link in description
    print("\nChecking for recipe link...")
    recipe_link = find_recipe_link(description)

    if recipe_link:
        print(f"  -> Found: {recipe_link}")
        print("  -> Fetching recipe from webpage...")
        recipe_data = scrape_recipe_from_url(recipe_link)
        if recipe_data:
            source = "webpage"
            print("  -> Recipe extracted from webpage")
        else:
            print("  -> Webpage scraping failed, trying description...")

    # 2. Try parsing recipe from description
    if not recipe_data:
        print("Checking description for inline recipe...")
        recipe_data = parse_recipe_from_description(description, title, channel)
        if recipe_data:
            source = "description"
            print("  -> Recipe extracted from description")
        else:
            print("  -> No inline recipe found")

    # 3. Fall back to AI extraction from transcript
    if not recipe_data:
        print(f"\nExtracting recipe via Ollama ({OLLAMA_MODEL})...")
        recipe_data, error = extract_recipe_with_ollama(title, channel, description, transcript)
        if error:
            print(f"Error: {error}", file=sys.stderr)
            sys.exit(1)
        source = "ai_extraction"

    # 4. Extract cooking tips if we got recipe from webpage or description
    if source in ("webpage", "description") and transcript:
        print("Extracting cooking tips from video...")
        tips = extract_cooking_tips(transcript, recipe_data)
        recipe_data['video_tips'] = tips
        if tips:
            print(f"  -> Found {len(tips)} tips")
        else:
            print("  -> No additional tips found")

    # Add source metadata
    recipe_data['source'] = source
    recipe_data['source_url'] = recipe_link

    recipe_name = recipe_data.get('recipe_name', 'Unknown Recipe')
    print(f"\nExtracted: {recipe_name} (source: {source})")

    if args.dry_run:
        # Print markdown to stdout
        markdown = format_recipe_markdown(recipe_data, video_url, title, channel)
        print("\n" + "="*50)
        print("RECIPE MARKDOWN:")
        print("="*50)
        print(markdown)
    else:
        # Save to Obsidian
        filepath = save_recipe_to_obsidian(recipe_data, video_url, title, channel, video_id)
        print(f"\nSaved to: {filepath}")
        print(f"SAVED:{filepath}")

    print("\nDone!")


if __name__ == "__main__":
    main()
