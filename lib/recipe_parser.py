"""Parser for existing recipe markdown files"""
import re
from pathlib import Path
from typing import Optional, List

from lib.ingredient_parser import parse_ingredient


def parse_recipe_file(content: str) -> dict:
    """Parse a recipe markdown file into frontmatter and body.

    Args:
        content: The full markdown file content

    Returns:
        dict with 'frontmatter' (dict) and 'body' (str) keys
    """
    frontmatter = {}
    body = content

    # Check for YAML frontmatter (--- delimited)
    frontmatter_pattern = r'^---\s*\n(.*?)\n---\s*\n(.*)$'
    match = re.match(frontmatter_pattern, content, re.DOTALL)

    if match:
        yaml_content = match.group(1)
        body = match.group(2)

        # Simple YAML parsing (handles our specific format)
        for line in yaml_content.split('\n'):
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            # Match key: value pairs
            kv_match = re.match(r'^(\w+):\s*(.*)$', line)
            if kv_match:
                key = kv_match.group(1)
                value = kv_match.group(2).strip()

                # Parse value types
                if value.startswith('"') and value.endswith('"'):
                    value = value[1:-1]  # Remove quotes
                elif value == 'null':
                    value = None
                elif value == 'true':
                    value = True
                elif value == 'false':
                    value = False
                elif value.startswith('[') and value.endswith(']'):
                    # Simple array parsing
                    inner = value[1:-1].strip()
                    if inner:
                        # Handle quoted items
                        value = [item.strip().strip('"') for item in inner.split(',')]
                    else:
                        value = []
                else:
                    # Try to parse as number
                    try:
                        if '.' in value:
                            value = float(value)
                        else:
                            value = int(value)
                    except ValueError:
                        pass  # Keep as string

                frontmatter[key] = value

    return {'frontmatter': frontmatter, 'body': body}


def extract_my_notes(content: str) -> str:
    """Extract content from the ## My Notes section.

    Args:
        content: The markdown content (body or full file)

    Returns:
        The content after ## My Notes heading, or empty string if not found
    """
    # Find ## My Notes heading (case insensitive)
    pattern = r'##\s+My\s+Notes\s*\n(.*?)(?=\n##\s|\Z)'
    match = re.search(pattern, content, re.IGNORECASE | re.DOTALL)

    if match:
        return match.group(1).strip()

    return ''


def extract_video_id(url: str) -> Optional[str]:
    """Extract YouTube video ID from various URL formats.

    Args:
        url: YouTube URL or video ID

    Returns:
        Video ID string, or None if not found
    """
    if not url:
        return None

    # Try standard watch URL: youtube.com/watch?v=ID
    match = re.search(r'[?&]v=([^&]+)', url)
    if match:
        return match.group(1)

    # Try short URL: youtu.be/ID
    match = re.search(r'youtu\.be/([^?&]+)', url)
    if match:
        return match.group(1)

    # Try embed URL: youtube.com/embed/ID
    match = re.search(r'youtube\.com/embed/([^?&]+)', url)
    if match:
        return match.group(1)

    return None


def find_existing_recipe(recipes_dir: Path, video_id: str) -> Optional[Path]:
    """Find an existing recipe file by video ID.

    Scans all .md files in recipes_dir (excluding .history) and checks
    if their source_url contains the given video ID.

    Args:
        recipes_dir: Path to the recipes directory
        video_id: YouTube video ID to search for

    Returns:
        Path to matching recipe file, or None if not found
    """
    recipes_dir = Path(recipes_dir)

    if not recipes_dir.exists():
        return None

    for md_file in recipes_dir.glob("*.md"):
        if md_file.name.startswith('.'):
            continue

        try:
            content = md_file.read_text(encoding='utf-8')
            parsed = parse_recipe_file(content)
            source_url = parsed['frontmatter'].get('source_url', '')

            if source_url and video_id in source_url:
                return md_file
        except Exception:
            continue

    return None


def parse_recipe_body(body: str) -> dict:
    """Parse recipe body into structured data for re-rendering.

    Extracts ingredients and instructions from markdown body.

    Args:
        body: The markdown body (after frontmatter)

    Returns:
        dict with 'ingredients', 'instructions', 'description', 'video_tips'
    """
    result = {
        'ingredients': [],
        'instructions': [],
        'description': '',
        'video_tips': [],
    }

    # Extract description (first blockquote after title)
    desc_match = re.search(r'^>\s*(.+?)$', body, re.MULTILINE)
    if desc_match:
        result['description'] = desc_match.group(1).strip()

    # Extract ingredients table
    ing_match = re.search(r'## Ingredients\n\n((?:\|[^\n]+\n)+)', body)
    if ing_match:
        result['ingredients'] = parse_ingredient_table(ing_match.group(1))

    # Extract instructions
    inst_match = re.search(r'## Instructions\n\n(.*?)(?=\n## |\Z)', body, re.DOTALL)
    if inst_match:
        inst_text = inst_match.group(1).strip()
        # Parse numbered steps
        steps = re.findall(r'^(\d+)\.\s+(.+?)(?=\n\d+\.\s|\Z)', inst_text, re.MULTILINE | re.DOTALL)
        for step_num, step_text in steps:
            result['instructions'].append({
                'step': int(step_num),
                'text': step_text.strip(),
                'time': None
            })

    # Extract video tips
    tips_match = re.search(r'## Tips from the Video\n\n(.*?)(?=\n## |\Z)', body, re.DOTALL)
    if tips_match:
        tips_text = tips_match.group(1).strip()
        result['video_tips'] = [t.strip('- ').strip() for t in tips_text.split('\n') if t.strip().startswith('-')]

    return result


def parse_ingredient_table(table_text: str) -> List[dict]:
    """
    Parse a markdown ingredient table into structured data.

    Handles both old 2-column (Amount | Ingredient) and
    new 3-column (Amount | Unit | Ingredient) formats.

    Args:
        table_text: Markdown table text

    Returns:
        List of ingredient dicts with 'amount', 'unit', 'item' keys
    """
    lines = table_text.strip().split('\n')
    ingredients = []

    for line in lines:
        # Skip non-table lines
        if not line.startswith('|'):
            continue
        # Skip separator lines
        if '---' in line:
            continue
        # Skip header lines
        if 'Amount' in line and 'Ingredient' in line:
            continue

        # Parse table row - split by | and remove empty first/last cells
        cells = [c.strip() for c in line.split('|')]
        # Remove empty strings at start/end caused by leading/trailing |
        cells = [c for c in cells if c or cells.index(c) not in (0, len(cells)-1)]
        # Actually just slice off first and last empty
        cells = line.split('|')[1:-1]
        cells = [c.strip() for c in cells]

        if len(cells) == 2:
            # Old format: Amount | Ingredient
            amount_cell, ingredient_cell = cells
            combined = f"{amount_cell} {ingredient_cell}".strip()
            parsed = parse_ingredient(combined)
            ingredients.append(parsed)
        elif len(cells) == 3:
            # New format: Amount | Unit | Ingredient
            ingredients.append({
                "amount": cells[0] if cells[0] else "1",
                "unit": cells[1] if cells[1] else "whole",
                "item": cells[2].lower(),
            })

    return ingredients
