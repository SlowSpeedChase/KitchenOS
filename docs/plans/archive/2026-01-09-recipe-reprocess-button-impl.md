# Recipe Reprocess Button Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add "Re-extract" and "Refresh Template" buttons to recipes in Obsidian that regenerate files via the API server.

**Architecture:** Two new GET endpoints (`/reprocess`, `/refresh`) in the existing Flask API. Buttons rendered via Obsidian Buttons plugin in a collapsible callout. Notes preserved, backups created, old backups auto-cleaned.

**Tech Stack:** Python 3.11, Flask, Obsidian Buttons plugin

---

## Task 1: Add cleanup_old_backups() to lib/backup.py

**Files:**
- Modify: `lib/backup.py`
- Test: `tests/test_backup.py`

**Step 1: Write the failing test**

Add to `tests/test_backup.py`:

```python
import time
from lib.backup import cleanup_old_backups


def test_cleanup_old_backups_removes_old_files():
    """Cleanup should remove backups older than max_age_days"""
    with tempfile.TemporaryDirectory() as tmpdir:
        history_dir = Path(tmpdir) / ".history"
        history_dir.mkdir()

        # Create an "old" backup (fake the mtime)
        old_backup = history_dir / "recipe_2026-01-01T00-00-00.md"
        old_backup.write_text("old content")
        old_time = time.time() - (31 * 24 * 60 * 60)  # 31 days ago
        os.utime(old_backup, (old_time, old_time))

        # Create a "new" backup
        new_backup = history_dir / "recipe_2026-01-08T00-00-00.md"
        new_backup.write_text("new content")

        removed = cleanup_old_backups(history_dir, max_age_days=30)

        assert not old_backup.exists()
        assert new_backup.exists()
        assert removed == 1


def test_cleanup_old_backups_handles_missing_dir():
    """Cleanup should return 0 if directory doesn't exist"""
    with tempfile.TemporaryDirectory() as tmpdir:
        missing_dir = Path(tmpdir) / "nonexistent"
        removed = cleanup_old_backups(missing_dir)
        assert removed == 0
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_backup.py::test_cleanup_old_backups_removes_old_files -v`
Expected: FAIL with "cannot import name 'cleanup_old_backups'"

**Step 3: Write minimal implementation**

Add to `lib/backup.py`:

```python
def cleanup_old_backups(history_dir: Path, max_age_days: int = 30) -> int:
    """Remove backup files older than max_age_days.

    Args:
        history_dir: Path to .history directory
        max_age_days: Maximum age in days (default 30)

    Returns:
        Number of files removed
    """
    history_dir = Path(history_dir)

    if not history_dir.exists():
        return 0

    import time
    cutoff_time = time.time() - (max_age_days * 24 * 60 * 60)
    removed = 0

    for backup_file in history_dir.glob("*.md"):
        if backup_file.stat().st_mtime < cutoff_time:
            backup_file.unlink()
            removed += 1

    return removed
```

**Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_backup.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add lib/backup.py tests/test_backup.py
git commit -m "feat: add cleanup_old_backups() for history management

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 2: Add Tools callout to recipe template

**Files:**
- Modify: `templates/recipe_template.py`
- Test: `tests/test_recipe_template.py` (create)

**Step 1: Write the failing test**

Create `tests/test_recipe_template.py`:

```python
"""Tests for recipe template"""
from templates.recipe_template import format_recipe_markdown, generate_tools_callout


def test_generate_tools_callout():
    """Tools callout should include both buttons with correct filename"""
    callout = generate_tools_callout("pasta-aglio-e-olio.md")

    assert "> [!tools]- Tools" in callout
    assert "name Re-extract" in callout
    assert "name Refresh Template" in callout
    assert "reprocess?file=pasta-aglio-e-olio.md" in callout
    assert "refresh?file=pasta-aglio-e-olio.md" in callout


def test_format_recipe_markdown_includes_tools_callout():
    """Recipe markdown should include tools callout after frontmatter"""
    recipe_data = {
        "recipe_name": "Test Recipe",
        "description": "A test",
        "ingredients": [],
        "instructions": [],
    }

    result = format_recipe_markdown(
        recipe_data,
        video_url="https://youtube.com/watch?v=abc123",
        video_title="Test Video",
        channel="Test Channel"
    )

    assert "> [!tools]- Tools" in result
    assert "reprocess?file=test-recipe.md" in result
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_recipe_template.py -v`
Expected: FAIL with "cannot import name 'generate_tools_callout'"

**Step 3: Write implementation**

Add to `templates/recipe_template.py` after the imports:

```python
API_BASE_URL = "http://localhost:5001"


def generate_tools_callout(filename: str) -> str:
    """Generate the Tools callout block with reprocess buttons.

    Args:
        filename: The recipe filename (e.g., "pasta-aglio-e-olio.md")

    Returns:
        Markdown callout block with buttons
    """
    return f'''> [!tools]- Tools
> ```button
> name Re-extract
> type link
> url {API_BASE_URL}/reprocess?file={filename}
> ```
> ```button
> name Refresh Template
> type link
> url {API_BASE_URL}/refresh?file={filename}
> ```

'''
```

Then modify `RECIPE_TEMPLATE` to include `{tools_callout}` after the frontmatter closing `---`:

```python
RECIPE_TEMPLATE = '''---
title: "{title}"
source_url: "{source_url}"
...
confidence_notes: "{confidence_notes}"
---

{tools_callout}# {title}
...
'''
```

And update `format_recipe_markdown()` to generate and include the callout:

```python
def format_recipe_markdown(recipe_data, video_url, video_title, channel):
    """Format recipe data into markdown string"""

    # Generate filename for tools callout
    filename = generate_filename(recipe_data.get('recipe_name', 'Untitled Recipe'))
    tools_callout = generate_tools_callout(filename)

    # ... existing code ...

    return RECIPE_TEMPLATE.format(
        # ... existing params ...
        tools_callout=tools_callout,
    )
```

**Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_recipe_template.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add templates/recipe_template.py tests/test_recipe_template.py
git commit -m "feat: add Tools callout with reprocess buttons to recipe template

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 3: Add /refresh endpoint to api_server.py

**Files:**
- Modify: `api_server.py`
- Modify: `lib/recipe_parser.py` (add `parse_recipe_body()`)
- Test: `tests/test_api_server.py` (create)

**Step 1: Write the failing test**

Create `tests/test_api_server.py`:

```python
"""Tests for API server endpoints"""
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from api_server import app


@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


def test_refresh_endpoint_missing_file_param(client):
    """Refresh should return error if file param missing"""
    response = client.get('/refresh')
    assert response.status_code == 400
    assert b'file parameter required' in response.data


def test_refresh_endpoint_file_not_found(client):
    """Refresh should return error if file doesn't exist"""
    with patch('api_server.OBSIDIAN_RECIPES_PATH', Path('/nonexistent')):
        response = client.get('/refresh?file=missing.md')
        assert response.status_code == 404
        assert b'not found' in response.data.lower()
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_api_server.py::test_refresh_endpoint_missing_file_param -v`
Expected: FAIL with 404 (endpoint doesn't exist)

**Step 3: Add parse_recipe_body() to lib/recipe_parser.py**

Add to `lib/recipe_parser.py`:

```python
def parse_recipe_body(body: str) -> dict:
    """Parse recipe body into structured data for re-rendering.

    Extracts ingredients and instructions from markdown body.

    Args:
        body: The markdown body (after frontmatter)

    Returns:
        dict with 'ingredients', 'instructions', 'description', etc.
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
```

**Step 4: Add /refresh endpoint to api_server.py**

Add imports at top:

```python
from lib.backup import create_backup
from lib.recipe_parser import parse_recipe_file, extract_my_notes, parse_recipe_body
from templates.recipe_template import format_recipe_markdown, generate_filename
```

Add constant:

```python
OBSIDIAN_RECIPES_PATH = Path("/Users/chaseeasterling/Library/Mobile Documents/iCloud~md~obsidian/Documents/KitchenOS/Recipes")
```

Add endpoint:

```python
@app.route('/refresh', methods=['GET'])
def refresh_template():
    """Regenerate recipe file with current template, preserving data and notes."""
    filename = request.args.get('file')

    if not filename:
        return error_page("Error: file parameter required"), 400

    filepath = OBSIDIAN_RECIPES_PATH / filename

    if not filepath.exists():
        return error_page(f"Error: Recipe not found: {filename}"), 404

    try:
        # Read and parse existing file
        content = filepath.read_text(encoding='utf-8')
        parsed = parse_recipe_file(content)
        frontmatter = parsed['frontmatter']
        body = parsed['body']

        # Extract notes to preserve
        my_notes = extract_my_notes(content)

        # Parse body for recipe data
        body_data = parse_recipe_body(body)

        # Build recipe_data from frontmatter + body
        recipe_data = {
            'recipe_name': frontmatter.get('title', 'Untitled'),
            'description': body_data.get('description', ''),
            'prep_time': frontmatter.get('prep_time'),
            'cook_time': frontmatter.get('cook_time'),
            'total_time': frontmatter.get('total_time'),
            'servings': frontmatter.get('servings'),
            'difficulty': frontmatter.get('difficulty'),
            'cuisine': frontmatter.get('cuisine'),
            'protein': frontmatter.get('protein'),
            'dish_type': frontmatter.get('dish_type'),
            'dietary': frontmatter.get('dietary', []),
            'equipment': frontmatter.get('equipment', []),
            'ingredients': body_data.get('ingredients', []),
            'instructions': body_data.get('instructions', []),
            'video_tips': body_data.get('video_tips', []),
            'needs_review': frontmatter.get('needs_review', False),
            'confidence_notes': frontmatter.get('confidence_notes', ''),
            'source': frontmatter.get('recipe_source', 'unknown'),
        }

        # Create backup
        create_backup(filepath)

        # Regenerate markdown
        new_content = format_recipe_markdown(
            recipe_data,
            video_url=frontmatter.get('source_url', ''),
            video_title=frontmatter.get('video_title', ''),
            channel=frontmatter.get('source_channel', '')
        )

        # Inject preserved notes
        if my_notes and my_notes != "<!-- Your personal notes, ratings, and modifications go here -->":
            new_content = inject_my_notes(new_content, my_notes)

        # Write file
        filepath.write_text(new_content, encoding='utf-8')

        return success_page("Template refreshed successfully", filename)

    except Exception as e:
        return error_page(f"Error refreshing template: {str(e)}"), 500
```

Add helper functions:

```python
def error_page(message: str) -> str:
    """Generate simple HTML error page."""
    return f'''<!DOCTYPE html>
<html><head><title>KitchenOS</title></head>
<body style="font-family: system-ui; padding: 2rem; max-width: 600px; margin: 0 auto;">
<div style="background: #fee; border: 1px solid #c00; padding: 1rem; border-radius: 8px;">
<strong style="color: #c00;">Error</strong><br>{message}
</div>
<p><a href="obsidian://open?vault=KitchenOS">Return to Obsidian</a></p>
</body></html>'''


def success_page(message: str, filename: str) -> str:
    """Generate simple HTML success page."""
    return f'''<!DOCTYPE html>
<html><head><title>KitchenOS</title></head>
<body style="font-family: system-ui; padding: 2rem; max-width: 600px; margin: 0 auto;">
<div style="background: #efe; border: 1px solid #0a0; padding: 1rem; border-radius: 8px;">
<strong style="color: #0a0;">Success</strong><br>{message}
</div>
<p><a href="obsidian://open?vault=KitchenOS&file=Recipes/{filename}">Return to {filename}</a></p>
</body></html>'''


def inject_my_notes(content: str, notes: str) -> str:
    """Replace the My Notes placeholder with preserved notes."""
    placeholder = "<!-- Your personal notes, ratings, and modifications go here -->"
    return content.replace(placeholder, notes)
```

**Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_api_server.py -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add api_server.py lib/recipe_parser.py tests/test_api_server.py
git commit -m "feat: add /refresh endpoint for template-only regeneration

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 4: Add /reprocess endpoint to api_server.py

**Files:**
- Modify: `api_server.py`
- Modify: `tests/test_api_server.py`

**Step 1: Write the failing test**

Add to `tests/test_api_server.py`:

```python
def test_reprocess_endpoint_missing_file_param(client):
    """Reprocess should return error if file param missing"""
    response = client.get('/reprocess')
    assert response.status_code == 400
    assert b'file parameter required' in response.data


def test_reprocess_endpoint_no_source_url(client):
    """Reprocess should return error if recipe has no source_url"""
    with tempfile.TemporaryDirectory() as tmpdir:
        recipes_path = Path(tmpdir)
        test_file = recipes_path / "test.md"
        test_file.write_text("---\ntitle: Test\n---\n\n# Test")

        with patch('api_server.OBSIDIAN_RECIPES_PATH', recipes_path):
            response = client.get('/reprocess?file=test.md')
            assert response.status_code == 400
            assert b'no source URL' in response.data.lower()
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_api_server.py::test_reprocess_endpoint_missing_file_param -v`
Expected: FAIL with 404 (endpoint doesn't exist)

**Step 3: Add /reprocess endpoint**

Add to `api_server.py`:

```python
@app.route('/reprocess', methods=['GET'])
def reprocess_recipe():
    """Full re-extraction: fetch from YouTube, run through Ollama, regenerate."""
    filename = request.args.get('file')

    if not filename:
        return error_page("Error: file parameter required"), 400

    filepath = OBSIDIAN_RECIPES_PATH / filename

    if not filepath.exists():
        return error_page(f"Error: Recipe not found: {filename}"), 404

    try:
        # Read existing file to get source_url and notes
        content = filepath.read_text(encoding='utf-8')
        parsed = parse_recipe_file(content)
        frontmatter = parsed['frontmatter']

        source_url = frontmatter.get('source_url')
        if not source_url:
            return error_page("Error: Cannot reprocess - no source URL in recipe"), 400

        # Extract notes to preserve
        my_notes = extract_my_notes(content)

        # Create backup before re-extraction
        create_backup(filepath)

        # Run full extraction (reusing existing extract endpoint logic)
        result = subprocess.run(
            ['.venv/bin/python', 'extract_recipe.py', source_url],
            capture_output=True,
            text=True,
            cwd='/Users/chaseeasterling/KitchenOS',
            timeout=300
        )

        if result.returncode != 0:
            error_msg = result.stderr.strip() if result.stderr else 'Extraction failed'
            return error_page(f"Error: {error_msg}"), 500

        # Inject preserved notes into the newly created file
        if my_notes and my_notes != "<!-- Your personal notes, ratings, and modifications go here -->":
            # Re-read the file (extract_recipe.py may have written to different filename)
            if filepath.exists():
                new_content = filepath.read_text(encoding='utf-8')
                new_content = inject_my_notes(new_content, my_notes)
                filepath.write_text(new_content, encoding='utf-8')

        return success_page("Recipe re-extracted successfully", filename)

    except subprocess.TimeoutExpired:
        return error_page("Error: Extraction timed out (5 min)"), 504
    except Exception as e:
        return error_page(f"Error: {str(e)}"), 500
```

**Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_api_server.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add api_server.py tests/test_api_server.py
git commit -m "feat: add /reprocess endpoint for full re-extraction

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 5: Add migration for Tools callout to existing recipes

**Files:**
- Modify: `migrate_recipes.py`
- Modify: `tests/test_migrate.py`

**Step 1: Write the failing test**

Add to `tests/test_migrate.py`:

```python
from migrate_recipes import add_tools_callout, has_tools_callout


def test_has_tools_callout_detects_existing():
    """Should detect when tools callout already exists"""
    content = '''---
title: Test
---

> [!tools]- Tools
> ```button
> name Re-extract

# Test
'''
    assert has_tools_callout(content) is True


def test_has_tools_callout_detects_missing():
    """Should detect when tools callout is missing"""
    content = '''---
title: Test
---

# Test
'''
    assert has_tools_callout(content) is False


def test_add_tools_callout_inserts_after_frontmatter():
    """Should insert tools callout between frontmatter and title"""
    content = '''---
title: Test
source_url: "https://youtube.com/watch?v=abc"
---

# Test

Content here.
'''
    result = add_tools_callout(content, "test.md")

    assert "> [!tools]- Tools" in result
    assert "reprocess?file=test.md" in result
    # Callout should be before title
    callout_pos = result.find("> [!tools]-")
    title_pos = result.find("# Test")
    assert callout_pos < title_pos
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_migrate.py::test_has_tools_callout_detects_existing -v`
Expected: FAIL with "cannot import name 'has_tools_callout'"

**Step 3: Add migration functions**

Add to `migrate_recipes.py`:

```python
from templates.recipe_template import generate_tools_callout


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
```

Update `migrate_recipe_content()` to include Tools callout migration:

```python
def migrate_recipe_content(content: str, filename: str = None) -> Tuple[str, List[str]]:
    """
    Migrate recipe markdown content to new format.

    Args:
        content: Full markdown file content
        filename: Recipe filename (for Tools callout URLs)

    Returns:
        Tuple of (new_content, list_of_changes)
    """
    changes = []

    # ... existing table migration code ...

    # Add Tools callout if missing
    if filename and not has_tools_callout(new_content):
        new_content = add_tools_callout(new_content, filename)
        changes.append("Added Tools callout with reprocess buttons")

    return new_content, changes
```

Update `migrate_recipe_file()` to pass filename:

```python
def migrate_recipe_file(filepath: Path) -> List[str]:
    # ... existing code ...

    # Migrate content (pass filename for Tools callout)
    new_content, content_changes = migrate_recipe_content(content, filepath.name)
    changes.extend(content_changes)
    # ... rest of function ...
```

**Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_migrate.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add migrate_recipes.py tests/test_migrate.py
git commit -m "feat: add migration for Tools callout to existing recipes

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 6: Add backup cleanup to LaunchAgent

**Files:**
- Modify: `generate_meal_plan.py`
- Modify: `com.kitchenos.mealplan.plist` (rename to reflect broader scope)

**Step 1: Add cleanup to generate_meal_plan.py**

Add at the end of `main()` in `generate_meal_plan.py`:

```python
from lib.backup import cleanup_old_backups

def main():
    # ... existing meal plan generation code ...

    # Cleanup old backups (runs daily with meal plan generation)
    history_dir = OBSIDIAN_VAULT / "Recipes" / ".history"
    if history_dir.exists():
        removed = cleanup_old_backups(history_dir, max_age_days=30)
        if removed > 0:
            print(f"Cleaned up {removed} old backup(s)")
```

**Step 2: Test manually**

Run: `.venv/bin/python generate_meal_plan.py --dry-run`
Expected: Script runs without error, mentions cleanup if .history exists

**Step 3: Commit**

```bash
git add generate_meal_plan.py
git commit -m "feat: add daily backup cleanup to meal plan generator

Removes recipe backups older than 30 days from Recipes/.history/

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 7: Update CLAUDE.md documentation

**Files:**
- Modify: `CLAUDE.md`

**Step 1: Add reprocess documentation**

Add to "API Server" section:

```markdown
### Reprocess Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/reprocess?file=<name>` | GET | Full re-extraction from YouTube |
| `/refresh?file=<name>` | GET | Template refresh only, keeps data |

Both endpoints:
- Preserve `## My Notes` section
- Create backup in `.history/` before overwriting
- Return HTML success/error page
```

Add to "Key Functions" section:

```markdown
**api_server.py:**
- `reprocess_recipe()` - Full re-extraction endpoint
- `refresh_template()` - Template-only refresh endpoint

**lib/backup.py:**
- `cleanup_old_backups()` - Removes backups older than N days
```

**Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add reprocess button documentation

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 8: End-to-end test

**Step 1: Install Buttons plugin in Obsidian**

1. Open Obsidian
2. Settings → Community plugins → Browse
3. Search "Buttons"
4. Install and enable

**Step 2: Run migration on existing recipes**

```bash
.venv/bin/python migrate_recipes.py --dry-run  # Preview
.venv/bin/python migrate_recipes.py            # Apply
```

**Step 3: Restart API server**

```bash
launchctl unload ~/Library/LaunchAgents/com.kitchenos.api.plist
launchctl load ~/Library/LaunchAgents/com.kitchenos.api.plist
```

**Step 4: Test Refresh Template button**

1. Open any recipe in Obsidian
2. Expand "Tools" callout
3. Click "Refresh Template"
4. Verify page opens showing success
5. Check recipe file regenerated (date_added updated)
6. Check .history/ has backup
7. Check My Notes preserved

**Step 5: Test Re-extract button**

1. Open a recipe with known video
2. Click "Re-extract"
3. Wait for extraction (may take 1-2 min)
4. Verify success page
5. Check recipe content updated
6. Check My Notes preserved

**Step 6: Final commit if any fixes needed**

```bash
git add -A
git commit -m "fix: address issues found in e2e testing

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Summary

| Task | Description | Files |
|------|-------------|-------|
| 1 | Add cleanup_old_backups() | lib/backup.py, tests/test_backup.py |
| 2 | Add Tools callout to template | templates/recipe_template.py, tests/test_recipe_template.py |
| 3 | Add /refresh endpoint | api_server.py, lib/recipe_parser.py, tests/test_api_server.py |
| 4 | Add /reprocess endpoint | api_server.py, tests/test_api_server.py |
| 5 | Add migration for Tools callout | migrate_recipes.py, tests/test_migrate.py |
| 6 | Add backup cleanup to LaunchAgent | generate_meal_plan.py |
| 7 | Update documentation | CLAUDE.md |
| 8 | End-to-end testing | Manual verification |
