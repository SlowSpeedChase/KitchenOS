# Recipe Update System Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enable updating existing recipe files without duplication, with backup safety and protected user content.

**Architecture:** Three new modules (backup, recipe parser, migration) plus modifications to existing extract_recipe.py and template. The backup module handles file versioning, the parser reads existing recipes, and migration applies schema changes in bulk.

**Tech Stack:** Python 3.9, pathlib, yaml parsing via regex (no external deps), shutil for file ops.

---

## Task 1: Create Backup Module

**Files:**
- Create: `lib/__init__.py`
- Create: `lib/backup.py`
- Create: `tests/__init__.py`
- Create: `tests/test_backup.py`

**Step 1: Create lib directory structure**

```bash
mkdir -p lib tests
touch lib/__init__.py tests/__init__.py
```

**Step 2: Write the failing test**

Create `tests/test_backup.py`:

```python
"""Tests for backup module"""
import tempfile
import os
from pathlib import Path
from lib.backup import create_backup, HISTORY_DIR


def test_create_backup_creates_history_dir():
    """Backup should create .history directory if it doesn't exist"""
    with tempfile.TemporaryDirectory() as tmpdir:
        recipes_dir = Path(tmpdir)
        original = recipes_dir / "test-recipe.md"
        original.write_text("# Test Recipe\n\nContent here")

        backup_path = create_backup(original)

        history_dir = recipes_dir / HISTORY_DIR
        assert history_dir.exists()
        assert history_dir.is_dir()


def test_create_backup_preserves_content():
    """Backup should contain exact same content as original"""
    with tempfile.TemporaryDirectory() as tmpdir:
        recipes_dir = Path(tmpdir)
        original = recipes_dir / "test-recipe.md"
        content = "---\ntitle: Test\n---\n\n# Test Recipe\n\nContent here"
        original.write_text(content)

        backup_path = create_backup(original)

        assert backup_path.read_text() == content


def test_create_backup_uses_timestamp_in_name():
    """Backup filename should include timestamp"""
    with tempfile.TemporaryDirectory() as tmpdir:
        recipes_dir = Path(tmpdir)
        original = recipes_dir / "2026-01-07-pasta.md"
        original.write_text("content")

        backup_path = create_backup(original)

        # Should be like: 2026-01-07-pasta_2026-01-07T14-30-00.md
        assert backup_path.name.startswith("2026-01-07-pasta_")
        assert "T" in backup_path.name  # ISO timestamp has T separator
        assert backup_path.name.endswith(".md")


def test_create_backup_returns_path():
    """Backup should return the path to the backup file"""
    with tempfile.TemporaryDirectory() as tmpdir:
        recipes_dir = Path(tmpdir)
        original = recipes_dir / "test-recipe.md"
        original.write_text("content")

        backup_path = create_backup(original)

        assert isinstance(backup_path, Path)
        assert backup_path.exists()
```

**Step 3: Run test to verify it fails**

```bash
cd /Users/chaseeasterling/KitchenOS/.worktrees/recipe-update-system
.venv/bin/python -m pytest tests/test_backup.py -v
```

Expected: FAIL with "No module named 'lib.backup'"

**Step 4: Write minimal implementation**

Create `lib/backup.py`:

```python
"""Backup management for recipe files"""
from datetime import datetime
from pathlib import Path
import shutil

HISTORY_DIR = ".history"


def create_backup(file_path: Path) -> Path:
    """Create a timestamped backup of a file in .history directory.

    Args:
        file_path: Path to the file to back up

    Returns:
        Path to the created backup file

    Raises:
        FileNotFoundError: If the file doesn't exist
        OSError: If backup creation fails
    """
    file_path = Path(file_path)

    if not file_path.exists():
        raise FileNotFoundError(f"Cannot backup non-existent file: {file_path}")

    # Create .history directory in same folder as file
    history_dir = file_path.parent / HISTORY_DIR
    history_dir.mkdir(exist_ok=True)

    # Generate timestamped backup filename
    timestamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    backup_name = f"{file_path.stem}_{timestamp}{file_path.suffix}"
    backup_path = history_dir / backup_name

    # Copy file to backup location
    shutil.copy2(file_path, backup_path)

    return backup_path
```

**Step 5: Run test to verify it passes**

```bash
.venv/bin/python -m pytest tests/test_backup.py -v
```

Expected: PASS (4 tests)

**Step 6: Commit**

```bash
git add lib/ tests/
git commit -m "feat: add backup module for recipe file versioning

Creates timestamped backups in .history/ directory before file updates.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 2: Create Recipe Parser Module

**Files:**
- Create: `lib/recipe_parser.py`
- Create: `tests/test_recipe_parser.py`

**Step 1: Write the failing test**

Create `tests/test_recipe_parser.py`:

```python
"""Tests for recipe parser module"""
from lib.recipe_parser import parse_recipe_file, extract_my_notes, extract_video_id


def test_parse_recipe_file_extracts_frontmatter():
    """Should extract frontmatter as dict"""
    content = '''---
title: "Pasta Aglio e Olio"
source_url: "https://www.youtube.com/watch?v=bJUiWdM__Qw"
servings: 2
---

# Pasta Aglio e Olio

Content here
'''
    result = parse_recipe_file(content)

    assert result['frontmatter']['title'] == 'Pasta Aglio e Olio'
    assert result['frontmatter']['source_url'] == 'https://www.youtube.com/watch?v=bJUiWdM__Qw'
    assert result['frontmatter']['servings'] == 2


def test_parse_recipe_file_extracts_body():
    """Should extract body content after frontmatter"""
    content = '''---
title: "Test"
---

# Test Recipe

Some content here.
'''
    result = parse_recipe_file(content)

    assert '# Test Recipe' in result['body']
    assert 'Some content here.' in result['body']


def test_extract_my_notes_returns_notes_section():
    """Should extract content after ## My Notes heading"""
    content = '''# Recipe

## Ingredients

- flour

## My Notes

This is my personal note.
I added extra garlic.
'''
    notes = extract_my_notes(content)

    assert 'This is my personal note.' in notes
    assert 'I added extra garlic.' in notes


def test_extract_my_notes_returns_empty_when_missing():
    """Should return empty string if no My Notes section"""
    content = '''# Recipe

## Ingredients

- flour
'''
    notes = extract_my_notes(content)

    assert notes == ''


def test_extract_my_notes_preserves_formatting():
    """Should preserve markdown formatting in notes"""
    content = '''## My Notes

- Item 1
- Item 2

**Bold text** and *italic*
'''
    notes = extract_my_notes(content)

    assert '- Item 1' in notes
    assert '**Bold text**' in notes


def test_extract_video_id_from_watch_url():
    """Should extract video ID from standard YouTube URL"""
    url = "https://www.youtube.com/watch?v=bJUiWdM__Qw"

    video_id = extract_video_id(url)

    assert video_id == "bJUiWdM__Qw"


def test_extract_video_id_from_short_url():
    """Should extract video ID from youtu.be URL"""
    url = "https://youtu.be/bJUiWdM__Qw"

    video_id = extract_video_id(url)

    assert video_id == "bJUiWdM__Qw"


def test_extract_video_id_with_extra_params():
    """Should extract video ID even with extra URL params"""
    url = "https://www.youtube.com/watch?v=bJUiWdM__Qw&t=120"

    video_id = extract_video_id(url)

    assert video_id == "bJUiWdM__Qw"
```

**Step 2: Run test to verify it fails**

```bash
.venv/bin/python -m pytest tests/test_recipe_parser.py -v
```

Expected: FAIL with "cannot import name 'parse_recipe_file'"

**Step 3: Write minimal implementation**

Create `lib/recipe_parser.py`:

```python
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
```

**Step 4: Run test to verify it passes**

```bash
.venv/bin/python -m pytest tests/test_recipe_parser.py -v
```

Expected: PASS (8 tests)

**Step 5: Commit**

```bash
git add lib/recipe_parser.py tests/test_recipe_parser.py
git commit -m "feat: add recipe parser for reading existing files

Parses frontmatter, extracts My Notes section, and identifies video IDs.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 3: Add Find Existing Recipe Function

**Files:**
- Modify: `lib/recipe_parser.py`
- Modify: `tests/test_recipe_parser.py`

**Step 1: Write the failing test**

Add to `tests/test_recipe_parser.py`:

```python
import tempfile
from pathlib import Path
from lib.recipe_parser import find_existing_recipe


def test_find_existing_recipe_finds_match():
    """Should find recipe file with matching video ID"""
    with tempfile.TemporaryDirectory() as tmpdir:
        recipes_dir = Path(tmpdir)

        # Create a recipe file
        recipe = recipes_dir / "2026-01-07-pasta.md"
        recipe.write_text('''---
title: "Pasta"
source_url: "https://www.youtube.com/watch?v=bJUiWdM__Qw"
---

# Pasta
''')

        result = find_existing_recipe(recipes_dir, "bJUiWdM__Qw")

        assert result == recipe


def test_find_existing_recipe_returns_none_when_not_found():
    """Should return None when no matching recipe exists"""
    with tempfile.TemporaryDirectory() as tmpdir:
        recipes_dir = Path(tmpdir)

        result = find_existing_recipe(recipes_dir, "nonexistent123")

        assert result is None


def test_find_existing_recipe_ignores_history_folder():
    """Should not search in .history directory"""
    with tempfile.TemporaryDirectory() as tmpdir:
        recipes_dir = Path(tmpdir)
        history_dir = recipes_dir / ".history"
        history_dir.mkdir()

        # Put matching file only in history
        backup = history_dir / "2026-01-07-pasta.md"
        backup.write_text('''---
source_url: "https://www.youtube.com/watch?v=bJUiWdM__Qw"
---
''')

        result = find_existing_recipe(recipes_dir, "bJUiWdM__Qw")

        assert result is None
```

**Step 2: Run test to verify it fails**

```bash
.venv/bin/python -m pytest tests/test_recipe_parser.py::test_find_existing_recipe_finds_match -v
```

Expected: FAIL with "cannot import name 'find_existing_recipe'"

**Step 3: Write minimal implementation**

Add to `lib/recipe_parser.py`:

```python
from pathlib import Path


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
        # Skip hidden files and .history contents
        if md_file.name.startswith('.'):
            continue

        try:
            content = md_file.read_text(encoding='utf-8')
            parsed = parse_recipe_file(content)
            source_url = parsed['frontmatter'].get('source_url', '')

            if source_url and video_id in source_url:
                return md_file
        except Exception:
            # Skip files that can't be read/parsed
            continue

    return None
```

**Step 4: Run test to verify it passes**

```bash
.venv/bin/python -m pytest tests/test_recipe_parser.py -v
```

Expected: PASS (11 tests)

**Step 5: Commit**

```bash
git add lib/recipe_parser.py tests/test_recipe_parser.py
git commit -m "feat: add find_existing_recipe to detect duplicates

Scans recipes folder for files matching a video ID.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 4: Update Template with My Notes Section

**Files:**
- Modify: `templates/recipe_template.py`

**Step 1: Locate the template constant**

The template is in `RECIPE_TEMPLATE` at line 60-105.

**Step 2: Add My Notes section to template**

Modify `templates/recipe_template.py`. Update `RECIPE_TEMPLATE` to add My Notes after notes_section:

Find this section (around line 102-105):
```python
{notes_section}
---
*Extracted from [{video_title}]({source_url}) on {date_added}*
'''
```

Replace with:
```python
{notes_section}
## My Notes

<!-- Your personal notes, ratings, and modifications go here -->

---
*Extracted from [{video_title}]({source_url}) on {date_added}*
'''
```

**Step 3: Add RECIPE_SCHEMA constant**

Add after the imports (around line 5):

```python
# Schema definition for recipe frontmatter
# Used by migration to add missing fields
RECIPE_SCHEMA = {
    "title": str,
    "source_url": str,
    "source_channel": str,
    "date_added": str,
    "video_title": str,
    "prep_time": str,
    "cook_time": str,
    "total_time": str,
    "servings": int,
    "difficulty": str,
    "cuisine": str,
    "protein": str,
    "dish_type": str,
    "dietary": list,
    "equipment": list,
    "needs_review": bool,
    "confidence_notes": str,
}

# Section renames for migration
SECTION_RENAMES = {
    # "Old Section Name": "New Section Name",
}
```

**Step 4: Verify template still works**

```bash
.venv/bin/python -c "from templates.recipe_template import format_recipe_markdown, RECIPE_SCHEMA; print('Schema fields:', len(RECIPE_SCHEMA))"
```

Expected: "Schema fields: 17"

**Step 5: Commit**

```bash
git add templates/recipe_template.py
git commit -m "feat: add My Notes section and schema definition to template

- Adds ## My Notes section for user content preservation
- Adds RECIPE_SCHEMA for migration field detection

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 5: Update extract_recipe.py for Update Flow

**Files:**
- Modify: `extract_recipe.py`

**Step 1: Add imports**

Add after line 15 (`from pathlib import Path`):

```python
from lib.backup import create_backup
from lib.recipe_parser import find_existing_recipe, parse_recipe_file, extract_my_notes
```

**Step 2: Modify save_recipe_to_obsidian function**

Replace the existing `save_recipe_to_obsidian` function (lines 64-79) with:

```python
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
```

**Step 3: Update main() to pass video_id**

Find the call to `save_recipe_to_obsidian` in main() (around line 148) and update it:

Before:
```python
filepath = save_recipe_to_obsidian(recipe_data, video_url, title, channel)
```

After:
```python
filepath = save_recipe_to_obsidian(recipe_data, video_url, title, channel, video_id)
```

**Step 4: Test the changes**

```bash
.venv/bin/python extract_recipe.py --dry-run "https://www.youtube.com/watch?v=bJUiWdM__Qw"
```

Expected: Should complete without errors, showing "## My Notes" in output

**Step 5: Commit**

```bash
git add extract_recipe.py
git commit -m "feat: add update flow with backup and notes preservation

- Detects existing recipes by video ID
- Creates backup before overwriting
- Preserves My Notes section content

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 6: Create Migration Script

**Files:**
- Create: `migrate_recipes.py`
- Create: `tests/test_migrate.py`

**Step 1: Write the failing test**

Create `tests/test_migrate.py`:

```python
"""Tests for recipe migration"""
import tempfile
from pathlib import Path
from migrate_recipes import migrate_recipe_file, run_migration


def test_migrate_recipe_adds_missing_fields():
    """Should add missing frontmatter fields with null value"""
    with tempfile.TemporaryDirectory() as tmpdir:
        recipes_dir = Path(tmpdir)
        recipe = recipes_dir / "test.md"

        # Old recipe missing some fields
        recipe.write_text('''---
title: "Test"
source_url: "https://youtube.com/watch?v=abc123"
---

# Test
''')

        changes = migrate_recipe_file(recipe)

        new_content = recipe.read_text()
        assert 'cuisine:' in new_content
        assert 'difficulty:' in new_content
        assert len(changes) > 0


def test_migrate_recipe_preserves_existing_values():
    """Should not overwrite existing field values"""
    with tempfile.TemporaryDirectory() as tmpdir:
        recipes_dir = Path(tmpdir)
        recipe = recipes_dir / "test.md"

        recipe.write_text('''---
title: "Pasta"
cuisine: "Italian"
---

# Pasta
''')

        migrate_recipe_file(recipe)

        new_content = recipe.read_text()
        assert 'cuisine: "Italian"' in new_content or "cuisine: Italian" in new_content


def test_migrate_recipe_preserves_my_notes():
    """Should preserve My Notes section during migration"""
    with tempfile.TemporaryDirectory() as tmpdir:
        recipes_dir = Path(tmpdir)
        recipe = recipes_dir / "test.md"

        recipe.write_text('''---
title: "Test"
---

# Test

## My Notes

My important personal notes here!
''')

        migrate_recipe_file(recipe)

        new_content = recipe.read_text()
        assert 'My important personal notes here!' in new_content


def test_run_migration_creates_backups():
    """Should create backups before modifying files"""
    with tempfile.TemporaryDirectory() as tmpdir:
        recipes_dir = Path(tmpdir)
        recipe = recipes_dir / "test.md"

        recipe.write_text('''---
title: "Test"
---

# Test
''')

        run_migration(recipes_dir, dry_run=False)

        history_dir = recipes_dir / ".history"
        assert history_dir.exists()
        assert len(list(history_dir.glob("*.md"))) == 1


def test_run_migration_dry_run_no_changes():
    """Dry run should not modify files"""
    with tempfile.TemporaryDirectory() as tmpdir:
        recipes_dir = Path(tmpdir)
        recipe = recipes_dir / "test.md"
        original_content = '''---
title: "Test"
---

# Test
'''
        recipe.write_text(original_content)

        run_migration(recipes_dir, dry_run=True)

        assert recipe.read_text() == original_content
        history_dir = recipes_dir / ".history"
        assert not history_dir.exists()
```

**Step 2: Run test to verify it fails**

```bash
.venv/bin/python -m pytest tests/test_migrate.py -v
```

Expected: FAIL with "No module named 'migrate_recipes'"

**Step 3: Write the implementation**

Create `migrate_recipes.py`:

```python
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

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.backup import create_backup
from lib.recipe_parser import parse_recipe_file, extract_my_notes
from templates.recipe_template import RECIPE_SCHEMA

# Configuration
OBSIDIAN_RECIPES_PATH = Path("/Users/chaseeasterling/Library/Mobile Documents/iCloud~md~obsidian/Documents/KitchenOS/Recipes")


def migrate_recipe_file(filepath: Path) -> List[str]:
    """Migrate a single recipe file to current schema.

    Args:
        filepath: Path to the recipe file

    Returns:
        List of changes made (for reporting)
    """
    changes = []
    content = filepath.read_text(encoding='utf-8')
    parsed = parse_recipe_file(content)
    frontmatter = parsed['frontmatter']
    body = parsed['body']

    # Find missing fields
    missing_fields = []
    for field in RECIPE_SCHEMA.keys():
        if field not in frontmatter:
            missing_fields.append(field)
            changes.append(f"Added field '{field}'")

    if not missing_fields:
        return changes  # Nothing to migrate

    # Preserve My Notes
    my_notes = extract_my_notes(content)

    # Rebuild frontmatter with missing fields
    lines = content.split('\n')
    new_lines = []
    in_frontmatter = False
    frontmatter_ended = False

    for i, line in enumerate(lines):
        if line.strip() == '---':
            if not in_frontmatter:
                in_frontmatter = True
                new_lines.append(line)
            else:
                # End of frontmatter - add missing fields before closing
                for field in missing_fields:
                    field_type = RECIPE_SCHEMA[field]
                    if field_type == list:
                        new_lines.append(f"{field}: []")
                    else:
                        new_lines.append(f"{field}: null")
                new_lines.append(line)
                frontmatter_ended = True
                in_frontmatter = False
        else:
            new_lines.append(line)

    # Write updated content
    new_content = '\n'.join(new_lines)
    filepath.write_text(new_content, encoding='utf-8')

    return changes


def run_migration(recipes_dir: Path, dry_run: bool = False) -> dict:
    """Run migration on all recipe files in directory.

    Args:
        recipes_dir: Path to recipes directory
        dry_run: If True, only report what would change

    Returns:
        Summary dict with 'updated', 'skipped', 'errors' lists
    """
    results = {
        'updated': [],
        'skipped': [],
        'errors': []
    }

    if not recipes_dir.exists():
        print(f"Recipes directory not found: {recipes_dir}")
        return results

    for md_file in sorted(recipes_dir.glob("*.md")):
        if md_file.name.startswith('.'):
            continue

        try:
            # Check what changes would be made
            content = md_file.read_text(encoding='utf-8')
            parsed = parse_recipe_file(content)

            # Check for required fields
            if 'source_url' not in parsed['frontmatter']:
                results['skipped'].append((md_file.name, 'no source_url'))
                continue

            # Find missing fields
            missing = [f for f in RECIPE_SCHEMA.keys()
                      if f not in parsed['frontmatter']]

            if not missing:
                results['skipped'].append((md_file.name, 'already up to date'))
                continue

            if dry_run:
                results['updated'].append((md_file.name, [f"Would add '{f}'" for f in missing]))
            else:
                # Create backup first
                backup_path = create_backup(md_file)

                # Run migration
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
                for change in changes[:3]:  # Show first 3 changes
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
    parser = argparse.ArgumentParser(
        description="Migrate recipe files to current template schema"
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would change without modifying files'
    )
    parser.add_argument(
        '--path',
        type=str,
        help='Path to recipes directory (default: Obsidian vault)'
    )
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
```

**Step 4: Run tests**

```bash
.venv/bin/python -m pytest tests/test_migrate.py -v
```

Expected: PASS (5 tests)

**Step 5: Commit**

```bash
git add migrate_recipes.py tests/test_migrate.py
git commit -m "feat: add recipe migration script

Bulk updates existing recipes to current schema:
- Adds missing frontmatter fields with null values
- Creates backups before modifying
- Supports --dry-run mode
- Preserves My Notes sections

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 7: Integration Test and Documentation

**Files:**
- Modify: `CLAUDE.md`
- Modify: `README.md`

**Step 1: Run all tests**

```bash
.venv/bin/python -m pytest tests/ -v
```

Expected: All tests pass

**Step 2: Test extract_recipe.py manually**

```bash
# Create a test recipe first (using a real video)
.venv/bin/python extract_recipe.py --dry-run "https://www.youtube.com/watch?v=bJUiWdM__Qw"
```

Verify output includes `## My Notes` section.

**Step 3: Update CLAUDE.md**

Add to "Key Functions" section:

```markdown
**lib/backup.py:**
- `create_backup()` - Creates timestamped backup in .history/ folder

**lib/recipe_parser.py:**
- `parse_recipe_file()` - Parses frontmatter and body from recipe markdown
- `extract_my_notes()` - Extracts content from ## My Notes section
- `find_existing_recipe()` - Finds recipe file by video ID

**migrate_recipes.py:**
- `migrate_recipe_file()` - Updates single recipe to current schema
- `run_migration()` - Batch migrates all recipes
```

Add to "Running Commands" section:

```markdown
### Migrate Recipes to New Schema

```bash
# Preview what would change
.venv/bin/python migrate_recipes.py --dry-run

# Apply migrations
.venv/bin/python migrate_recipes.py
```
```

**Step 4: Update README.md**

Add to Usage section:

```markdown
### Update Existing Recipes

Re-running extraction on a previously extracted video will update the existing file instead of creating a duplicate. Your personal notes in the "## My Notes" section are preserved.

```bash
# Re-extract (updates existing file, creates backup)
.venv/bin/python extract_recipe.py "https://www.youtube.com/watch?v=VIDEO_ID"
```

### Migrate Recipes to New Template

When the template changes (new fields added), update all existing recipes:

```bash
# Preview changes
.venv/bin/python migrate_recipes.py --dry-run

# Apply changes (creates backups first)
.venv/bin/python migrate_recipes.py
```

Backups are stored in `Recipes/.history/` and can be used to recover previous versions.
```

**Step 5: Commit**

```bash
git add CLAUDE.md README.md
git commit -m "docs: add documentation for recipe update system

- Documents new lib modules in CLAUDE.md
- Adds migration and update commands to README.md

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 8: Final Verification

**Step 1: Run full test suite**

```bash
.venv/bin/python -m pytest tests/ -v
```

**Step 2: Verify imports work**

```bash
.venv/bin/python -c "
from lib.backup import create_backup
from lib.recipe_parser import find_existing_recipe, parse_recipe_file, extract_my_notes
from migrate_recipes import run_migration
from templates.recipe_template import RECIPE_SCHEMA
print('All imports successful')
print(f'Schema has {len(RECIPE_SCHEMA)} fields')
"
```

**Step 3: Test dry-run extraction**

```bash
.venv/bin/python extract_recipe.py --dry-run "https://www.youtube.com/watch?v=bJUiWdM__Qw"
```

**Step 4: Commit any final fixes if needed**

If all tests pass and everything works:

```bash
git log --oneline -10
```

Verify commit history shows all implementation commits.
