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

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main import youtube_parser, get_video_metadata, get_transcript
from prompts.recipe_extraction import SYSTEM_PROMPT, build_user_prompt
from templates.recipe_template import format_recipe_markdown, generate_filename

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


def save_recipe_to_obsidian(recipe_data, video_url, video_title, channel):
    """Format recipe as markdown and save to Obsidian vault."""
    # Generate markdown
    markdown = format_recipe_markdown(recipe_data, video_url, video_title, channel)

    # Generate filename
    filename = generate_filename(recipe_data.get('recipe_name', 'untitled-recipe'))
    filepath = OBSIDIAN_RECIPES_PATH / filename

    # Ensure directory exists
    OBSIDIAN_RECIPES_PATH.mkdir(parents=True, exist_ok=True)

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

    # Extract recipe via Ollama
    print(f"\nExtracting recipe via Ollama ({OLLAMA_MODEL})...")
    recipe_data, error = extract_recipe_with_ollama(title, channel, description, transcript)

    if error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)

    recipe_name = recipe_data.get('recipe_name', 'Unknown Recipe')
    print(f"Extracted: {recipe_name}")

    if args.dry_run:
        # Print markdown to stdout
        markdown = format_recipe_markdown(recipe_data, video_url, title, channel)
        print("\n" + "="*50)
        print("RECIPE MARKDOWN:")
        print("="*50)
        print(markdown)
    else:
        # Save to Obsidian
        filepath = save_recipe_to_obsidian(recipe_data, video_url, title, channel)
        print(f"\nSaved to: {filepath}")

    print("\nDone!")


if __name__ == "__main__":
    main()
