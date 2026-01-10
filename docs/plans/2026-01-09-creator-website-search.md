# Creator Website Search Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add fallback to search creator websites before AI extraction, fixing bad extractions from YouTube Shorts with empty descriptions.

**Architecture:** New step in pipeline between description parsing and Ollama fallback. Uses channel→website mapping file with DuckDuckGo search fallback. Reuses existing `scrape_recipe_from_url()` for JSON-LD extraction.

**Tech Stack:** Python 3.11, duckduckgo-search package, JSON config file

---

## Task 1: Add duckduckgo-search Dependency

**Files:**
- Modify: `requirements.txt`

**Step 1: Add the dependency**

Add to `requirements.txt`:
```
duckduckgo-search>=6.0.0
```

**Step 2: Install in worktree venv**

Run: `.venv/bin/pip install duckduckgo-search`
Expected: Successfully installed duckduckgo-search-X.X.X

**Step 3: Verify import works**

Run: `.venv/bin/python -c "from duckduckgo_search import DDGS; print('OK')"`
Expected: `OK`

**Step 4: Commit**

```bash
git add requirements.txt
git commit -m "chore: add duckduckgo-search dependency

For creator website search fallback feature.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 2: Create Creator Website Mapping Config

**Files:**
- Create: `config/creator_websites.json`

**Step 1: Create config directory**

Run: `mkdir -p config`

**Step 2: Create mapping file**

Create `config/creator_websites.json`:
```json
{
  "_comment": "Channel name (lowercase) → website domain. Use null for creators without recipe sites.",
  "feelgoodfoodie": "feelgoodfoodie.net",
  "joshua weissman": "joshuaweissman.com",
  "babish culinary universe": "bingingwithbabish.com",
  "binging with babish": "bingingwithbabish.com",
  "ethan chlebowski": "ethanchlebowski.com",
  "internet shaquille": "internetshaquille.com",
  "j. kenji lópez-alt": "seriouseats.com",
  "kenji's cooking show": "seriouseats.com",
  "bon appétit": "bonappetit.com",
  "bon appetit": "bonappetit.com",
  "tasty": "tasty.co",
  "delish": "delish.com",
  "serious eats": "seriouseats.com",
  "adam ragusea": null,
  "pro home cooks": null,
  "america's test kitchen": "americastestkitchen.com"
}
```

**Step 3: Verify JSON is valid**

Run: `.venv/bin/python -c "import json; json.load(open('config/creator_websites.json')); print('Valid JSON')"`
Expected: `Valid JSON`

**Step 4: Commit**

```bash
git add config/creator_websites.json
git commit -m "feat: add creator website mapping config

Maps YouTube channel names to their recipe website domains.
Supports null values for channels without recipe sites.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 3: Add load_creator_mapping() Function

**Files:**
- Modify: `recipe_sources.py`
- Create: `tests/test_creator_search.py`

**Step 1: Write the failing test**

Create `tests/test_creator_search.py`:
```python
"""Tests for creator website search functionality."""

import pytest
from pathlib import Path


class TestLoadCreatorMapping:
    """Tests for load_creator_mapping function."""

    def test_loads_mapping_from_config(self):
        """Should load channel → website mapping from JSON file."""
        from recipe_sources import load_creator_mapping

        mapping = load_creator_mapping()

        assert isinstance(mapping, dict)
        assert mapping.get("feelgoodfoodie") == "feelgoodfoodie.net"

    def test_returns_none_for_channels_without_sites(self):
        """Should return None for channels marked as having no site."""
        from recipe_sources import load_creator_mapping

        mapping = load_creator_mapping()

        # Adam Ragusea is mapped to null (no recipe site)
        assert "adam ragusea" in mapping
        assert mapping["adam ragusea"] is None

    def test_returns_empty_dict_if_config_missing(self, tmp_path, monkeypatch):
        """Should return empty dict and log warning if config file missing."""
        from recipe_sources import load_creator_mapping, CONFIG_DIR

        # Point to non-existent directory
        monkeypatch.setattr("recipe_sources.CONFIG_DIR", tmp_path / "nonexistent")

        mapping = load_creator_mapping()

        assert mapping == {}
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_creator_search.py::TestLoadCreatorMapping -v`
Expected: FAIL with `ImportError` or `AttributeError` (function doesn't exist)

**Step 3: Write minimal implementation**

Add to top of `recipe_sources.py` after existing imports:
```python
from pathlib import Path

# Config directory
CONFIG_DIR = Path(__file__).parent / "config"
```

Add function after `extract_cooking_tips()`:
```python
def load_creator_mapping() -> Dict[str, Optional[str]]:
    """
    Load channel → website mapping from config file.

    Returns:
        Dict mapping lowercase channel names to website domains.
        Value is None for channels known to have no recipe site.
        Returns empty dict if config file is missing.
    """
    config_path = CONFIG_DIR / "creator_websites.json"

    if not config_path.exists():
        print(f"  -> Warning: Creator mapping not found at {config_path}")
        return {}

    try:
        with open(config_path, 'r') as f:
            data = json.load(f)
        # Filter out comments
        return {k: v for k, v in data.items() if not k.startswith('_')}
    except (json.JSONDecodeError, IOError) as e:
        print(f"  -> Warning: Could not load creator mapping: {e}")
        return {}
```

**Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_creator_search.py::TestLoadCreatorMapping -v`
Expected: 3 passed

**Step 5: Commit**

```bash
git add recipe_sources.py tests/test_creator_search.py
git commit -m "feat: add load_creator_mapping function

Loads channel → website mapping from config/creator_websites.json.
Returns empty dict with warning if file missing.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 4: Add search_for_recipe_url() Function

**Files:**
- Modify: `recipe_sources.py`
- Modify: `tests/test_creator_search.py`

**Step 1: Write the failing test**

Add to `tests/test_creator_search.py`:
```python
class TestSearchForRecipeUrl:
    """Tests for search_for_recipe_url function."""

    def test_constructs_site_restricted_query(self, mocker):
        """Should search with site: restriction when domain provided."""
        from recipe_sources import search_for_recipe_url

        # Mock DDGS
        mock_ddgs = mocker.patch("recipe_sources.DDGS")
        mock_instance = mock_ddgs.return_value.__enter__.return_value
        mock_instance.text.return_value = [
            {"href": "https://feelgoodfoodie.net/recipe/chocolate-peanut-butter-bars/"}
        ]

        result = search_for_recipe_url(
            channel="feelgoodfoodie",
            title="Chocolate Peanut Butter Bars",
            site="feelgoodfoodie.net"
        )

        # Check query includes site restriction
        call_args = mock_instance.text.call_args
        query = call_args[0][0]
        assert "site:feelgoodfoodie.net" in query
        assert result == "https://feelgoodfoodie.net/recipe/chocolate-peanut-butter-bars/"

    def test_constructs_open_query_without_site(self, mocker):
        """Should search without site restriction when domain not provided."""
        from recipe_sources import search_for_recipe_url

        mock_ddgs = mocker.patch("recipe_sources.DDGS")
        mock_instance = mock_ddgs.return_value.__enter__.return_value
        mock_instance.text.return_value = [
            {"href": "https://example.com/some-recipe/"}
        ]

        result = search_for_recipe_url(
            channel="unknown channel",
            title="Some Recipe"
        )

        call_args = mock_instance.text.call_args
        query = call_args[0][0]
        assert "site:" not in query
        assert "unknown channel" in query.lower()

    def test_filters_excluded_domains(self, mocker):
        """Should skip results from excluded domains like youtube.com."""
        from recipe_sources import search_for_recipe_url

        mock_ddgs = mocker.patch("recipe_sources.DDGS")
        mock_instance = mock_ddgs.return_value.__enter__.return_value
        mock_instance.text.return_value = [
            {"href": "https://www.youtube.com/watch?v=123"},
            {"href": "https://pinterest.com/pin/123"},
            {"href": "https://feelgoodfoodie.net/recipe/good-one/"}
        ]

        result = search_for_recipe_url(channel="test", title="test")

        assert result == "https://feelgoodfoodie.net/recipe/good-one/"

    def test_returns_none_on_no_results(self, mocker):
        """Should return None when search returns no valid results."""
        from recipe_sources import search_for_recipe_url

        mock_ddgs = mocker.patch("recipe_sources.DDGS")
        mock_instance = mock_ddgs.return_value.__enter__.return_value
        mock_instance.text.return_value = []

        result = search_for_recipe_url(channel="test", title="test")

        assert result is None

    def test_returns_none_on_timeout(self, mocker):
        """Should return None and not crash on timeout."""
        from recipe_sources import search_for_recipe_url

        mock_ddgs = mocker.patch("recipe_sources.DDGS")
        mock_instance = mock_ddgs.return_value.__enter__.return_value
        mock_instance.text.side_effect = Exception("Timeout")

        result = search_for_recipe_url(channel="test", title="test")

        assert result is None
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_creator_search.py::TestSearchForRecipeUrl -v`
Expected: FAIL with `ImportError` (function doesn't exist)

**Step 3: Write minimal implementation**

Add import at top of `recipe_sources.py`:
```python
from duckduckgo_search import DDGS
```

Add to `EXCLUDED_DOMAINS` list:
```python
    "pinterest.com",
    "pinterest.co.uk",
```

Add function after `load_creator_mapping()`:
```python
def search_for_recipe_url(
    channel: str,
    title: str,
    site: Optional[str] = None
) -> Optional[str]:
    """
    Search DuckDuckGo for a recipe URL.

    Args:
        channel: YouTube channel name
        title: Video title
        site: Optional domain to restrict search (e.g., "feelgoodfoodie.net")

    Returns:
        Recipe URL if found, None otherwise
    """
    # Clean up title (remove channel name if present, common suffixes)
    clean_title = title
    for suffix in [" | " + channel, " - " + channel, " by " + channel]:
        if clean_title.lower().endswith(suffix.lower()):
            clean_title = clean_title[:-len(suffix)]

    # Build query
    if site:
        query = f'"{clean_title}" recipe site:{site}'
    else:
        query = f'"{channel}" "{clean_title}" recipe'

    try:
        with DDGS() as ddgs:
            results = ddgs.text(query, max_results=5)

            for result in results:
                url = result.get("href", "")

                # Skip excluded domains
                if _is_excluded_domain(url):
                    continue

                # Prefer URLs with /recipe/ in path
                if "/recipe/" in url.lower():
                    return url

                # Accept first non-excluded result
                return url

            return None

    except Exception as e:
        print(f"  -> DuckDuckGo search failed: {e}")
        return None
```

**Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_creator_search.py::TestSearchForRecipeUrl -v`
Expected: 5 passed

**Step 5: Commit**

```bash
git add recipe_sources.py tests/test_creator_search.py
git commit -m "feat: add search_for_recipe_url function

Searches DuckDuckGo for recipe URLs with optional site restriction.
Filters excluded domains and prefers /recipe/ URLs.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 5: Add search_creator_website() Orchestrator

**Files:**
- Modify: `recipe_sources.py`
- Modify: `tests/test_creator_search.py`

**Step 1: Write the failing test**

Add to `tests/test_creator_search.py`:
```python
class TestSearchCreatorWebsite:
    """Tests for search_creator_website orchestrator."""

    def test_uses_mapped_domain_for_known_creator(self, mocker):
        """Should use domain from mapping for known creators."""
        from recipe_sources import search_creator_website

        # Mock the mapping
        mocker.patch("recipe_sources.load_creator_mapping", return_value={
            "feelgoodfoodie": "feelgoodfoodie.net"
        })
        mock_search = mocker.patch("recipe_sources.search_for_recipe_url")
        mock_search.return_value = "https://feelgoodfoodie.net/recipe/test/"

        result = search_creator_website("Feelgoodfoodie", "Test Recipe")

        mock_search.assert_called_once_with(
            channel="Feelgoodfoodie",
            title="Test Recipe",
            site="feelgoodfoodie.net"
        )
        assert result == "https://feelgoodfoodie.net/recipe/test/"

    def test_skips_search_for_null_mapped_creators(self, mocker):
        """Should return None without searching for creators mapped to null."""
        from recipe_sources import search_creator_website

        mocker.patch("recipe_sources.load_creator_mapping", return_value={
            "adam ragusea": None
        })
        mock_search = mocker.patch("recipe_sources.search_for_recipe_url")

        result = search_creator_website("Adam Ragusea", "Some Recipe")

        mock_search.assert_not_called()
        assert result is None

    def test_searches_without_site_for_unknown_creators(self, mocker):
        """Should search without site restriction for unmapped creators."""
        from recipe_sources import search_creator_website

        mocker.patch("recipe_sources.load_creator_mapping", return_value={})
        mock_search = mocker.patch("recipe_sources.search_for_recipe_url")
        mock_search.return_value = "https://example.com/recipe/"

        result = search_creator_website("Unknown Creator", "Test Recipe")

        mock_search.assert_called_once_with(
            channel="Unknown Creator",
            title="Test Recipe",
            site=None
        )

    def test_normalizes_channel_name_for_lookup(self, mocker):
        """Should normalize channel name (lowercase, strip) for mapping lookup."""
        from recipe_sources import search_creator_website

        mocker.patch("recipe_sources.load_creator_mapping", return_value={
            "feelgoodfoodie": "feelgoodfoodie.net"
        })
        mock_search = mocker.patch("recipe_sources.search_for_recipe_url")

        # Test with different casing and whitespace
        search_creator_website("  FeelGoodFoodie  ", "Test")

        mock_search.assert_called_once()
        assert mock_search.call_args[1]["site"] == "feelgoodfoodie.net"
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_creator_search.py::TestSearchCreatorWebsite -v`
Expected: FAIL with `ImportError` (function doesn't exist)

**Step 3: Write minimal implementation**

Add function after `search_for_recipe_url()`:
```python
def search_creator_website(channel: str, title: str) -> Optional[str]:
    """
    Attempt to find recipe URL on creator's website.

    1. Load channel → website mapping
    2. If mapped to null → return None (creator has no site)
    3. If mapped to domain → search that domain
    4. If not mapped → search DuckDuckGo without site restriction

    Args:
        channel: YouTube channel name
        title: Video title

    Returns:
        Recipe URL if found, None otherwise
    """
    # Normalize channel name for lookup
    channel_key = channel.lower().strip()

    # Load mapping
    mapping = load_creator_mapping()

    # Check if channel is in mapping
    if channel_key in mapping:
        site = mapping[channel_key]

        # null means creator has no recipe site - don't search
        if site is None:
            print(f"  -> {channel} has no recipe website (skipping search)")
            return None

        print(f"  -> Searching {site} for \"{title}\"...")
    else:
        site = None
        print(f"  -> Searching web for \"{channel}\" \"{title}\"...")

    url = search_for_recipe_url(channel=channel, title=title, site=site)

    if url:
        print(f"  -> Found: {url}")
    else:
        print(f"  -> No recipe URL found")

    return url
```

**Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_creator_search.py::TestSearchCreatorWebsite -v`
Expected: 4 passed

**Step 5: Commit**

```bash
git add recipe_sources.py tests/test_creator_search.py
git commit -m "feat: add search_creator_website orchestrator

Coordinates mapping lookup and web search for creator recipes.
Skips search for creators known to have no recipe site.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 6: Integrate into extract_recipe.py Pipeline

**Files:**
- Modify: `extract_recipe.py`

**Step 1: Add import**

Add to imports in `extract_recipe.py`:
```python
from recipe_sources import (
    find_recipe_link,
    scrape_recipe_from_url,
    parse_recipe_from_description,
    extract_cooking_tips,
    search_creator_website,  # NEW
)
```

**Step 2: Add new pipeline step**

In `extract_single_recipe()`, find the priority chain section (around line 284-314).

Replace this block:
```python
        # 2. Try parsing recipe from description
        if not recipe_data:
            recipe_data = parse_recipe_from_description(description, title, channel)
            if recipe_data:
                source = "description"

        # 3. Fall back to AI extraction from transcript
        if not recipe_data:
```

With this:
```python
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
```

**Step 3: Test with dry-run**

Run: `.venv/bin/python extract_recipe.py --dry-run "https://www.youtube.com/shorts/DECP3dLN9X0"`

Expected output should include:
```
Searching feelgoodfoodie.net for "Chocolate Peanut Butter Bars"...
  -> Found: https://feelgoodfoodie.net/recipe/chocolate-peanut-butter-bars/
Would extract: Chocolate Peanut Butter Bars
```

**Step 4: Commit**

```bash
git add extract_recipe.py
git commit -m "feat: integrate creator website search into pipeline

Adds step 3 to priority chain: search creator website before AI fallback.
Uses search_creator_website() → scrape_recipe_from_url() flow.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 7: Run All Tests and Fix Issues

**Step 1: Run full test suite**

Run: `.venv/bin/python -m pytest tests/ -v`

Expected: All tests pass

**Step 2: Fix any failures**

If tests fail, debug and fix. Common issues:
- Missing imports
- Mock patches with wrong paths
- Typos in function names

**Step 3: Run end-to-end test**

Run: `.venv/bin/python extract_recipe.py --dry-run "https://www.youtube.com/shorts/DECP3dLN9X0"`

Verify:
- Searches feelgoodfoodie.net
- Finds the recipe URL
- Shows "creator_website" as source

**Step 4: Commit any fixes**

```bash
git add -A
git commit -m "fix: test and integration fixes

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 8: Update Documentation

**Files:**
- Modify: `CLAUDE.md`

**Step 1: Update Architecture section**

In CLAUDE.md, update the Pipeline Flow:
```
recipe_sources.py:
  1. find_recipe_link() → scrape_recipe_from_url()
  2. parse_recipe_from_description()
  3. search_creator_website() → scrape_recipe_from_url()  ← NEW
  4. extract_recipe_with_ollama() (fallback)
```

**Step 2: Update Key Functions section**

Add to `recipe_sources.py` functions:
```
- `load_creator_mapping()` - Loads channel → website mapping from config
- `search_for_recipe_url()` - Searches DuckDuckGo for recipe URL
- `search_creator_website()` - Orchestrates creator website search
```

**Step 3: Add config file documentation**

Add new section or update existing:
```markdown
### Creator Website Mapping

**File:** `config/creator_websites.json`

Maps YouTube channel names to their recipe website domains. Used to search creator websites when video description is empty (common with Shorts).

```json
{
  "feelgoodfoodie": "feelgoodfoodie.net",
  "adam ragusea": null
}
```

- `null` value means creator has no recipe website (skip search)
- Add new creators as you discover them
```

**Step 4: Mark feature complete in Future Enhancements**

The YouTube Shorts support is already marked complete, but add a note about this enhancement if desired.

**Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md with creator website search

Documents new pipeline step, functions, and config file.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 9: Final Integration Test

**Step 1: Test the problem video**

Run: `.venv/bin/python extract_recipe.py "https://www.youtube.com/shorts/DECP3dLN9X0" --force`

Verify:
- Recipe extracts with source "creator_website"
- Ingredients have proper quantities (1.5 cups peanut butter, etc.)
- File saved to Obsidian vault

**Step 2: Test a regular video (regression)**

Run: `.venv/bin/python extract_recipe.py --dry-run "https://www.youtube.com/watch?v=bJUiWdM__Qw"`

Verify: Still works, uses existing extraction path

**Step 3: Test unknown creator**

Run: `.venv/bin/python extract_recipe.py --dry-run "https://www.youtube.com/shorts/SOME_OTHER_SHORT"`

Verify: Falls back gracefully (either finds via search or uses AI)

---

## Task 10: Merge Back to Main

**Step 1: Check git status**

Run: `git log --oneline main..HEAD`

Review commits look good.

**Step 2: Switch to main worktree and merge**

```bash
cd /Users/chaseeasterling/KitchenOS
git merge feature/creator-website-search
```

**Step 3: Install new dependency in main**

```bash
.venv/bin/pip install duckduckgo-search
```

**Step 4: Restart API server**

```bash
launchctl unload ~/Library/LaunchAgents/com.kitchenos.api.plist
launchctl load ~/Library/LaunchAgents/com.kitchenos.api.plist
```

**Step 5: Clean up worktree**

```bash
git worktree remove .worktrees/creator-website-search
git branch -d feature/creator-website-search
```

---

## Summary

| Task | Description | Tests |
|------|-------------|-------|
| 1 | Add duckduckgo-search dependency | Import check |
| 2 | Create creator_websites.json config | JSON validation |
| 3 | Add load_creator_mapping() | 3 unit tests |
| 4 | Add search_for_recipe_url() | 5 unit tests |
| 5 | Add search_creator_website() | 4 unit tests |
| 6 | Integrate into pipeline | Dry-run test |
| 7 | Run all tests | Full suite |
| 8 | Update documentation | N/A |
| 9 | Final integration test | E2E test |
| 10 | Merge and cleanup | N/A |
