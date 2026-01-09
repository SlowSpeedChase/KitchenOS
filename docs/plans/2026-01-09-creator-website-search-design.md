# Creator Website Search Design

**Date:** 2026-01-09
**Status:** Approved

## Problem

YouTube Shorts and videos with empty descriptions fall back to AI extraction (Ollama), which hallucinates badly when the transcript contains no quantities. Example: "Chocolate Peanut Butter Bars" from FeelGoodFoodie extracted as "1 whole whole peanut butter" because the Short's transcript had no measurements.

## Solution

Add a new pipeline step that searches creator websites for the full recipe before falling back to AI extraction.

## Pipeline Integration

```
Current:
1. find_recipe_link(description) → scrape_recipe_from_url()
2. parse_recipe_from_description()
3. extract_recipe_with_ollama()  ← AI guessing

New:
1. find_recipe_link(description) → scrape_recipe_from_url()
2. parse_recipe_from_description()
3. search_creator_website(channel, title) → scrape_recipe_from_url()  ← NEW
4. extract_recipe_with_ollama()  ← only if steps 1-3 fail
```

## Components

### 1. Creator Website Mapping

**File:** `config/creator_websites.json`

```json
{
  "feelgoodfoodie": "feelgoodfoodie.net",
  "joshua weissman": "joshuaweissman.com",
  "babish culinary universe": "bingingwithbabish.com",
  "adam ragusea": null
}
```

- Normalized channel name → website domain
- `null` value = creator has no recipe site (skip search)
- Missing entry = try DuckDuckGo search

### 2. DuckDuckGo Search

**Package:** `duckduckgo-search` (PyPI)

**Query construction:**
- Known site: `"chocolate peanut butter bars" recipe site:feelgoodfoodie.net`
- Unknown creator: `"feelgoodfoodie" "chocolate peanut butter bars" recipe`

**Result filtering:**
- Skip excluded domains (youtube.com, pinterest.com, etc.)
- Prefer URLs containing `/recipe/`
- Return first valid match

### 3. Recipe Extraction

Uses existing `scrape_recipe_from_url()` which parses JSON-LD. No HTML fallback - most recipe sites use JSON-LD for SEO.

### 4. New Recipe Source Type

When this path succeeds:
- `recipe_source: "creator_website"`
- `recipe_url: "<found URL>"`

Distinct from `"webpage"` (found in description link).

## New Functions

**In `recipe_sources.py`:**

```python
def load_creator_mapping() -> Dict[str, Optional[str]]:
    """Load channel → website mapping from config file."""

def search_for_recipe_url(channel: str, title: str, site: str = None) -> Optional[str]:
    """Search DuckDuckGo for recipe URL."""

def search_creator_website(channel: str, title: str) -> Optional[str]:
    """Orchestrator: mapping lookup → search → return URL or None."""
```

## Error Handling

| Scenario | Behavior |
|----------|----------|
| Config file missing | Log warning, proceed to DuckDuckGo |
| DuckDuckGo timeout | Log warning, return None |
| No results found | Return None silently |
| JSON-LD parsing fails | Return None, fall through to Ollama |

## Timeouts

- DuckDuckGo search: 10 seconds
- Total function: 15 seconds max

## Files Changed

| File | Change |
|------|--------|
| `config/creator_websites.json` | New - mapping file |
| `recipe_sources.py` | Add search functions |
| `extract_recipe.py` | Integrate new step |
| `requirements.txt` | Add `duckduckgo-search` |

## Future Enhancements (Not In Scope)

- Google Custom Search API for better results
- HTML parsing fallback for sites without JSON-LD
- Auto-learn mapping from successful searches
