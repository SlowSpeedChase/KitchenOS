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

        # Deliberately not yaml.safe_load: it resolves `date_added: 2026-01-09`
        # to a datetime.date, and every consumer in this repo treats those as
        # ISO strings. The divergences that were *defects* are fixed below and
        # pinned by tests/test_recipe_parser.py; the date one is kept on purpose.
        lines = yaml_content.split('\n')
        i = 0
        while i < len(lines):
            raw = lines[i]
            i += 1
            stripped = raw.strip()
            if not stripped or stripped.startswith('#'):
                continue

            # Indentation is meaning, not whitespace. Stripping first made an
            # indented `- item` look like a candidate key and a nested mapping's
            # child look top-level, so a block list read as '' and a nested
            # `calories:` masqueraded as the legacy nutrition key.
            if raw[:1].isspace():
                continue

            kv_match = re.match(r'^(\w+):\s*(.*)$', raw)
            if not kv_match:
                continue

            key = kv_match.group(1)
            value = kv_match.group(2).strip()

            # A bare `key:` may head a block list. Consume the indented `- item`
            # lines that follow; an empty key with none is an empty list, which
            # is what `dietary:` means on a recipe with no dietary tags.
            if not value:
                items = []
                while i < len(lines):
                    nxt = lines[i]
                    if not nxt.strip():
                        i += 1
                        continue
                    item = re.match(r'^\s+-\s*(.*)$', nxt)
                    if not item:
                        break
                    items.append(_coerce_scalar(item.group(1).strip()))
                    i += 1
                frontmatter[key] = items
                continue

            if value.startswith('[') and value.endswith(']'):
                frontmatter[key] = _split_flow_list(value[1:-1])
                continue

            frontmatter[key] = _coerce_scalar(value)

    return {'frontmatter': frontmatter, 'body': body}


def _split_flow_list(inner: str) -> list:
    """Split a flow list's body on commas that are not inside a quoted item.

    A plain ``inner.split(',')`` turned ``"large, well-seasoned cast-iron
    skillet"`` into two items, each carrying half a quote — ten corpus recipes
    have equipment lists written that way.
    """
    items, buf, quote = [], [], None
    for ch in inner:
        if quote:
            if ch == quote:
                quote = None
            buf.append(ch)
        elif ch in ('"', "'"):
            quote = ch
            buf.append(ch)
        elif ch == ',':
            items.append(''.join(buf))
            buf = []
        else:
            buf.append(ch)
    items.append(''.join(buf))
    return [_coerce_scalar(x.strip()) for x in items if x.strip()]


def _coerce_scalar(value: str):
    """One scalar's worth of YAML, minus the date resolution.

    Shared by plain values, flow-list items and block-list items so all three
    agree — they used to disagree, which is how `peak_months` came back as
    `['9', '10']` from a flow list while yaml.safe_load said `[9, 10]`.
    """
    # Single quotes matter too: one corpus file had a title in them, and the
    # double-quote-only rule handed back a value with a leading apostrophe.
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        return value[1:-1]
    if value == 'null' or value == '~':
        return None
    if value == 'true':
        return True
    if value == 'false':
        return False
    try:
        return float(value) if '.' in value else int(value)
    except ValueError:
        return value


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


def find_existing_recipe_by_source_url(recipes_dir: Path, url: str) -> Optional[Path]:
    """Find an existing recipe file by exact source_url match.

    Used for web-scraped recipes (no YouTube video ID) to avoid duplicates.
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
            if parsed['frontmatter'].get('source_url') == url:
                return md_file
        except Exception:
            continue
    return None


def extract_ingredients_section(body: str) -> str:
    """The whole `## Ingredients` section, sub-headings and all.

    The one extractor for this — `shopping_list_generator.extract_ingredient_table`
    delegates here. Two near-copies of this regex existed and **both** silently
    dropped ingredients:

    - `parse_recipe_body` matched one *contiguous* run of table rows
      (`## Ingredients\\n\\n((?:\\|[^\\n]+\\n)+)`), so it stopped at the first blank
      line. A recipe grouped as "…thighs / ### For the spice rub / …paprika" kept
      the thighs and lost every spice. It also returned *nothing* when the table
      wasn't preceded by exactly one blank line.
    - This function's own predecessor stopped at `\\n##`, which matches the first
      two hashes of `\\n###` — so a sub-heading truncated the section here too.

    Hence `#{1,2}\\s`: a heading only ends the section when it's h1/h2, because the
    trailing `\\s` can't match the third `#` of an h3. Everything between is
    returned verbatim; `parse_ingredient_table` already skips non-table lines,
    separators and repeated headers, so grouped tables parse as one list.
    """
    match = re.search(r'##\s+Ingredients\s*\n(.*?)(?=\n#{1,2}\s|\Z)', body,
                      re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else ""


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

    # Extract ingredients — the whole section, so sub-grouped tables
    # ("### For the spice rub") contribute their rows too.
    ingredients_section = extract_ingredients_section(body)
    if ingredients_section:
        result['ingredients'] = parse_ingredient_table(ingredients_section)

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
