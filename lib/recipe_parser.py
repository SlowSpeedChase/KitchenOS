"""Parser for existing recipe markdown files"""
import re
from typing import Optional


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
