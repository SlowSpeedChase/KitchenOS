# Recipe Images Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add recipe images (from recipe websites and YouTube thumbnails) to Obsidian recipe files, stored locally, with CSS snippet to hide on mobile.

**Architecture:** Images are collected during extraction (website JSON-LD `image` field preferred, YouTube thumbnail fallback) and downloaded to `Recipes/Images/` in the Obsidian vault. The recipe template adds `banner` and `cssclasses` frontmatter plus an inline `![[image]]` embed. A CSS snippet allows hiding images on iPhone.

**Tech Stack:** Python 3.11, requests (already a dependency), YouTube Data API (already used)

---

### Task 1: Add image URL extraction from JSON-LD scrapes

**Files:**
- Modify: `recipe_sources.py:245-268` (`parse_json_ld_recipe`)
- Test: `tests/test_recipe_sources.py`

**Step 1: Write the failing test**

Add to `tests/test_recipe_sources.py`:

```python
class TestImageExtraction:
    def test_parse_json_ld_extracts_image_url(self):
        """parse_json_ld_recipe should extract image URL from JSON-LD"""
        json_ld = {
            "name": "Test Recipe",
            "image": "https://example.com/photo.jpg",
            "recipeIngredient": [],
            "recipeInstructions": [],
        }
        result = parse_json_ld_recipe(json_ld)
        assert result["image_url"] == "https://example.com/photo.jpg"

    def test_parse_json_ld_extracts_image_from_list(self):
        """image field can be a list of URLs"""
        json_ld = {
            "name": "Test Recipe",
            "image": ["https://example.com/small.jpg", "https://example.com/large.jpg"],
            "recipeIngredient": [],
            "recipeInstructions": [],
        }
        result = parse_json_ld_recipe(json_ld)
        assert result["image_url"] == "https://example.com/small.jpg"

    def test_parse_json_ld_extracts_image_from_object(self):
        """image field can be an ImageObject with url"""
        json_ld = {
            "name": "Test Recipe",
            "image": {"@type": "ImageObject", "url": "https://example.com/photo.jpg"},
            "recipeIngredient": [],
            "recipeInstructions": [],
        }
        result = parse_json_ld_recipe(json_ld)
        assert result["image_url"] == "https://example.com/photo.jpg"

    def test_parse_json_ld_no_image_returns_none(self):
        """Missing image field returns None"""
        json_ld = {
            "name": "Test Recipe",
            "recipeIngredient": [],
            "recipeInstructions": [],
        }
        result = parse_json_ld_recipe(json_ld)
        assert result["image_url"] is None
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_recipe_sources.py::TestImageExtraction -v`
Expected: FAIL — `KeyError: 'image_url'`

**Step 3: Write minimal implementation**

In `recipe_sources.py`, add a helper function before `parse_json_ld_recipe`:

```python
def _extract_image_url(image_field) -> Optional[str]:
    """Extract image URL from JSON-LD image field.

    Handles string, list of strings, and ImageObject formats.
    """
    if not image_field:
        return None
    if isinstance(image_field, str):
        return image_field
    if isinstance(image_field, list):
        for item in image_field:
            if isinstance(item, str):
                return item
            if isinstance(item, dict):
                url = item.get("url")
                if url:
                    return url
        return None
    if isinstance(image_field, dict):
        return image_field.get("url")
    return None
```

Then in `parse_json_ld_recipe`, add to the recipe dict:

```python
"image_url": _extract_image_url(json_ld.get("image")),
```

**Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_recipe_sources.py::TestImageExtraction -v`
Expected: PASS (4 tests)

**Step 5: Commit**

```bash
git add recipe_sources.py tests/test_recipe_sources.py
git commit -m "feat: extract image URL from JSON-LD recipe scrapes"
```

---

### Task 2: Add YouTube thumbnail URL to video metadata

**Files:**
- Modify: `main.py:102-130` (`get_video_metadata` and `get_video_metadata_ytdlp`)
- Test: `tests/test_recipe_sources.py` (or a new lightweight test)

**Step 1: Write the failing test**

Create `tests/test_main.py`:

```python
from main import get_video_metadata, get_video_metadata_ytdlp


class TestThumbnailURL:
    def test_thumbnail_url_constructed_from_video_id(self):
        """YouTube thumbnails follow a predictable URL pattern"""
        # We don't need to call the API - just test the URL construction helper
        from main import get_thumbnail_url
        result = get_thumbnail_url("dQw4w9WgXcQ")
        assert result == "https://i.ytimg.com/vi/dQw4w9WgXcQ/maxresdefault.jpg"
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_main.py::TestThumbnailURL -v`
Expected: FAIL — `ImportError: cannot import name 'get_thumbnail_url'`

**Step 3: Write minimal implementation**

In `main.py`, add a helper function:

```python
def get_thumbnail_url(video_id: str) -> str:
    """Construct YouTube thumbnail URL from video ID.

    Uses maxresdefault (1280x720) which is available for most videos.
    """
    return f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg"
```

Then update `get_video_metadata` to include `thumbnail_url` in its return dict:

```python
return {
    'title': snippet.get('title', ''),
    'channel': snippet.get('channelTitle', ''),
    'description': snippet.get('description', ''),
    'thumbnail_url': get_thumbnail_url(video_id),
}
```

And update `get_video_metadata_ytdlp` similarly:

```python
return {
    'title': info.get('title', ''),
    'channel': info.get('channel', '') or info.get('uploader', ''),
    'description': info.get('description', ''),
    'thumbnail_url': get_thumbnail_url(video_id),
}
```

**Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_main.py::TestThumbnailURL -v`
Expected: PASS

**Step 5: Commit**

```bash
git add main.py tests/test_main.py
git commit -m "feat: add YouTube thumbnail URL to video metadata"
```

---

### Task 3: Add image download utility

**Files:**
- Create: `lib/image_downloader.py`
- Test: `tests/test_image_downloader.py`

**Step 1: Write the failing test**

Create `tests/test_image_downloader.py`:

```python
import tempfile
from pathlib import Path
from unittest.mock import patch, Mock

from lib.image_downloader import download_image


class TestDownloadImage:
    def test_downloads_image_to_path(self):
        """Should download image and save to specified path"""
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "test.jpg"
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.headers = {"content-type": "image/jpeg"}
            mock_response.iter_content = Mock(return_value=[b"fake image data"])
            mock_response.raise_for_status = Mock()
            mock_response.__enter__ = Mock(return_value=mock_response)
            mock_response.__exit__ = Mock(return_value=False)

            with patch("lib.image_downloader.requests.get", return_value=mock_response):
                result = download_image("https://example.com/photo.jpg", target)

            assert result == target
            assert target.exists()
            assert target.read_bytes() == b"fake image data"

    def test_creates_parent_directory(self):
        """Should create parent directories if they don't exist"""
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "Images" / "test.jpg"
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.headers = {"content-type": "image/jpeg"}
            mock_response.iter_content = Mock(return_value=[b"data"])
            mock_response.raise_for_status = Mock()
            mock_response.__enter__ = Mock(return_value=mock_response)
            mock_response.__exit__ = Mock(return_value=False)

            with patch("lib.image_downloader.requests.get", return_value=mock_response):
                result = download_image("https://example.com/photo.jpg", target)

            assert target.parent.exists()
            assert target.exists()

    def test_returns_none_on_failure(self):
        """Should return None on download failure"""
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "test.jpg"
            with patch("lib.image_downloader.requests.get", side_effect=Exception("Network error")):
                result = download_image("https://example.com/photo.jpg", target)

            assert result is None
            assert not target.exists()

    def test_returns_none_for_non_image_content(self):
        """Should return None if response is not an image"""
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "test.jpg"
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.headers = {"content-type": "text/html"}
            mock_response.raise_for_status = Mock()
            mock_response.__enter__ = Mock(return_value=mock_response)
            mock_response.__exit__ = Mock(return_value=False)

            with patch("lib.image_downloader.requests.get", return_value=mock_response):
                result = download_image("https://example.com/photo.jpg", target)

            assert result is None
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_image_downloader.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lib.image_downloader'`

**Step 3: Write minimal implementation**

Create `lib/image_downloader.py`:

```python
"""Download and save recipe images."""

import sys
from pathlib import Path
from typing import Optional

import requests


def download_image(url: str, target_path: Path) -> Optional[Path]:
    """Download an image from a URL and save it locally.

    Args:
        url: Image URL to download
        target_path: Local path to save the image

    Returns:
        Path to saved image, or None on failure
    """
    try:
        response = requests.get(url, timeout=15, stream=True, headers={
            "User-Agent": "Mozilla/5.0 (compatible; KitchenOS/1.0)"
        })
        response.raise_for_status()

        # Verify it's actually an image
        content_type = response.headers.get("content-type", "")
        if not content_type.startswith("image/"):
            print(f"  -> Not an image: {content_type}", file=sys.stderr)
            return None

        # Create parent directory
        target_path.parent.mkdir(parents=True, exist_ok=True)

        # Write image data
        with open(target_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        return target_path

    except Exception as e:
        print(f"  -> Image download failed: {e}", file=sys.stderr)
        # Clean up partial download
        if target_path.exists():
            target_path.unlink()
        return None
```

**Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_image_downloader.py -v`
Expected: PASS (4 tests)

**Step 5: Commit**

```bash
git add lib/image_downloader.py tests/test_image_downloader.py
git commit -m "feat: add image download utility"
```

---

### Task 4: Update recipe template with image support

**Files:**
- Modify: `templates/recipe_template.py`
- Test: `tests/test_recipe_template.py`

**Step 1: Write the failing test**

Add to `tests/test_recipe_template.py`:

```python
class TestImageSupport:
    def test_template_includes_cssclasses(self):
        """Recipe frontmatter should include cssclasses: [recipe]"""
        recipe_data = {
            "recipe_name": "Test Recipe",
            "description": "A test",
            "ingredients": [],
            "instructions": [],
        }
        result = format_recipe_markdown(recipe_data, "http://test.com", "Test", "Channel")
        assert "cssclasses:" in result
        assert "recipe" in result

    def test_template_includes_banner_when_image(self):
        """Frontmatter should include banner when image_filename is provided"""
        recipe_data = {
            "recipe_name": "Test Recipe",
            "description": "A test",
            "ingredients": [],
            "instructions": [],
            "image_filename": "Test Recipe.jpg",
        }
        result = format_recipe_markdown(recipe_data, "http://test.com", "Test", "Channel")
        assert 'banner: "[[Test Recipe.jpg]]"' in result

    def test_template_includes_inline_image_when_image(self):
        """Body should include ![[image]] embed when image_filename is provided"""
        recipe_data = {
            "recipe_name": "Test Recipe",
            "description": "A test",
            "ingredients": [],
            "instructions": [],
            "image_filename": "Test Recipe.jpg",
        }
        result = format_recipe_markdown(recipe_data, "http://test.com", "Test", "Channel")
        assert "![[Test Recipe.jpg]]" in result

    def test_template_no_banner_without_image(self):
        """Frontmatter should have banner: null when no image"""
        recipe_data = {
            "recipe_name": "Test Recipe",
            "description": "A test",
            "ingredients": [],
            "instructions": [],
        }
        result = format_recipe_markdown(recipe_data, "http://test.com", "Test", "Channel")
        assert "banner: null" in result

    def test_template_no_inline_image_without_image(self):
        """Body should not include ![[]] embed when no image"""
        recipe_data = {
            "recipe_name": "Test Recipe",
            "description": "A test",
            "ingredients": [],
            "instructions": [],
        }
        result = format_recipe_markdown(recipe_data, "http://test.com", "Test", "Channel")
        assert "![[" not in result

    def test_inline_image_before_description(self):
        """Image embed should appear before the description blockquote"""
        recipe_data = {
            "recipe_name": "Test Recipe",
            "description": "A test",
            "ingredients": [],
            "instructions": [],
            "image_filename": "Test Recipe.jpg",
        }
        result = format_recipe_markdown(recipe_data, "http://test.com", "Test", "Channel")
        image_pos = result.find("![[Test Recipe.jpg]]")
        desc_pos = result.find("> A test")
        assert image_pos < desc_pos
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_recipe_template.py::TestImageSupport -v`
Expected: FAIL — assertions about `cssclasses` and `banner` fail

**Step 3: Write minimal implementation**

In `templates/recipe_template.py`:

1. Add `banner` and `cssclasses` to `RECIPE_SCHEMA`:

```python
RECIPE_SCHEMA = {
    "title": str,
    "banner": str,
    # ... existing fields ...
}
```

2. Update `RECIPE_TEMPLATE` string to add `banner` and `cssclasses` to frontmatter, and `{image_embed}` to body:

In the frontmatter section, add after `confidence_notes`:
```
banner: {banner}
cssclasses:
  - recipe
```

In the body, add `{image_embed}` between the title `# {title}` and the description `> {description}`:
```
{tools_callout}# {title}

{image_embed}> {description}
```

3. Update `format_recipe_markdown` to handle the new fields:

Add image filename and banner/embed logic:
```python
image_filename = recipe_data.get('image_filename')
banner = f'"[[{image_filename}]]"' if image_filename else "null"
image_embed = f"![[{image_filename}]]\n\n" if image_filename else ""
```

Pass `banner=banner` and `image_embed=image_embed` to `RECIPE_TEMPLATE.format(...)`.

**Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_recipe_template.py -v`
Expected: ALL PASS (existing + new tests)

**Step 5: Commit**

```bash
git add templates/recipe_template.py tests/test_recipe_template.py
git commit -m "feat: add image support to recipe template"
```

---

### Task 5: Wire image downloading into extract_recipe pipeline

**Files:**
- Modify: `extract_recipe.py:227-454` (`extract_single_recipe` and `save_recipe_to_obsidian`)

**Step 1: Add imports to extract_recipe.py**

At the top of `extract_recipe.py`, add:

```python
from lib.image_downloader import download_image
from main import get_thumbnail_url
```

**Step 2: Add image download logic to `extract_single_recipe`**

After the recipe source priority chain resolves (after step 5 "Extract cooking tips") and before saving, add:

```python
# Download recipe image
image_filename = None
image_url = recipe_data.get('image_url')  # From JSON-LD scrape
if not image_url:
    # Fallback to YouTube thumbnail
    image_url = get_thumbnail_url(video_id)

if image_url:
    status("Downloading recipe image...")
    recipe_name = recipe_data.get('recipe_name', 'Untitled Recipe')
    # Use same name as recipe file but with .jpg extension
    safe_name = re.sub(r'[<>:"/\\|?*]', '', recipe_name)
    safe_name = ' '.join(safe_name.split()).title()
    image_target = OBSIDIAN_RECIPES_PATH / "Images" / f"{safe_name}.jpg"
    downloaded = download_image(image_url, image_target)
    if downloaded:
        image_filename = f"{safe_name}.jpg"
        status(f"Image saved: {image_filename}")

recipe_data['image_filename'] = image_filename
```

**Step 3: Test manually**

Run: `.venv/bin/python extract_recipe.py --dry-run "https://www.youtube.com/watch?v=bJUiWdM__Qw"`

Verify no errors. (Dry run won't save but the image_filename gets set in recipe_data.)

**Step 4: Commit**

```bash
git add extract_recipe.py
git commit -m "feat: wire image download into recipe extraction pipeline"
```

---

### Task 6: Add `cssclasses` migration for existing recipes

**Files:**
- Modify: `migrate_recipes.py`
- Test: `tests/test_migrate.py`

**Step 1: Write the failing test**

Add to `tests/test_migrate.py`:

```python
class TestCssclassesMigration:
    def test_migration_adds_cssclasses_to_frontmatter(self):
        """Migration should add cssclasses: [recipe] to existing recipes"""
        with tempfile.TemporaryDirectory() as tmpdir:
            recipes_dir = Path(tmpdir)
            recipe = recipes_dir / "test.md"
            recipe.write_text('''---
title: "Test"
source_url: "https://youtube.com/watch?v=abc123"
---

> [!tools]- Tools
> test

# Test
''')
            from migrate_recipes import migrate_recipe_content
            content = recipe.read_text()
            new_content, changes = migrate_recipe_content(content, "test.md")
            assert "cssclasses:" in new_content
            assert any("cssclasses" in c for c in changes)

    def test_migration_skips_existing_cssclasses(self):
        """Should not duplicate cssclasses if already present"""
        content = '''---
title: "Test"
cssclasses:
  - recipe
---

> [!tools]- Tools
> test

# Test
'''
        from migrate_recipes import migrate_recipe_content
        new_content, changes = migrate_recipe_content(content, "test.md")
        assert new_content.count("cssclasses:") == 1
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_migrate.py::TestCssclassesMigration -v`
Expected: FAIL — no cssclasses added

**Step 3: Write minimal implementation**

In `migrate_recipes.py`, update `migrate_recipe_content` to add cssclasses migration:

```python
# Add cssclasses if missing
if "cssclasses:" not in new_content:
    # Insert cssclasses before closing --- of frontmatter
    parts = new_content.split('---', 2)
    if len(parts) >= 3:
        frontmatter = parts[1]
        frontmatter = frontmatter.rstrip('\n') + '\ncssclasses:\n  - recipe\n'
        new_content = f"---{frontmatter}---{parts[2]}"
        changes.append("Added cssclasses: [recipe] to frontmatter")
```

Also update `needs_content_migration` to check for missing cssclasses:

```python
if "cssclasses:" not in content:
    return True
```

**Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_migrate.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add migrate_recipes.py tests/test_migrate.py
git commit -m "feat: add cssclasses migration for existing recipes"
```

---

### Task 7: Create CSS snippet for mobile image hiding

**Files:**
- Create CSS snippet in Obsidian vault

**Step 1: Create the snippet**

Write file to: `/Users/chaseeasterling/Library/Mobile Documents/iCloud~md~obsidian/Documents/KitchenOS/.obsidian/snippets/hide-recipe-images.css`

```css
.recipe img {
  display: none;
}
```

**Step 2: Verify**

Confirm the snippets directory exists and the file was created.

**Step 3: Commit (project files only)**

No git commit needed — this file is in the Obsidian vault, not the project repo.

**Step 4: User action required**

Tell the user: "Enable the `hide-recipe-images` snippet on your iPhone in Obsidian Settings → Appearance → CSS Snippets."

---

### Task 8: Update CLAUDE.md documentation

**Files:**
- Modify: `CLAUDE.md`

**Step 1: Update documentation**

Add to CLAUDE.md:

1. **Key Paths** table: Add `Recipes/Images/` row with purpose "Recipe images (downloaded from source)"
2. **Architecture → Pipeline Flow**: Add `download_image()` step after template
3. **Core Components** table: Add `lib/image_downloader.py` row
4. **Key Functions** section: Add `lib/image_downloader.py` subsection with `download_image()` entry
5. **Key Functions → recipe_sources.py**: Add `_extract_image_url()` entry
6. **Key Functions → main.py**: Add `get_thumbnail_url()` entry
7. **Recipe JSON Schema**: Add `image_url` and `image_filename` fields
8. **Recipe Template**: Note the new `banner` and `cssclasses` frontmatter fields
9. **Future Enhancements**: Mark "Image extraction" as completed

**Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add image support to CLAUDE.md"
```

---

### Task 9: Run full end-to-end test

**Step 1: Run extraction with a test video**

```bash
.venv/bin/python extract_recipe.py --dry-run "https://www.youtube.com/watch?v=bJUiWdM__Qw"
```

Verify: No errors, recipe_name and image info printed.

**Step 2: Run full extraction**

```bash
.venv/bin/python extract_recipe.py "https://www.youtube.com/watch?v=bJUiWdM__Qw"
```

Verify:
- Recipe file created in Obsidian vault
- Image file created in `Recipes/Images/`
- Recipe frontmatter has `banner` and `cssclasses` fields
- Recipe body has `![[image]]` embed
- Open in Obsidian — image displays correctly

**Step 3: Run all tests**

```bash
.venv/bin/python -m pytest tests/ -v
```

Expected: ALL PASS

**Step 4: Final commit if any fixes needed**

```bash
git add -A
git commit -m "fix: address e2e test findings for image support"
```
