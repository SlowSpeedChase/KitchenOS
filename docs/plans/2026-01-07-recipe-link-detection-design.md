# Recipe Link Detection Design

**Date:** 2026-01-07
**Status:** Approved

## Overview

Add recipe link detection to the extraction pipeline. Before running AI extraction on video transcripts, check the video description for:
1. Links to recipe webpages (scrape structured data)
2. Inline recipes written in the description

This improves accuracy (structured data vs. inferred from speech) and speed (less AI processing when recipes already exist).

## Priority Chain

```
YouTube URL
    ↓
Fetch video metadata + transcript (existing)
    ↓
Check description for recipe link
    ↓ found                    ↓ not found
Fetch webpage             Parse description for inline recipe
    ↓                          ↓ found        ↓ not found
Extract via JSON-LD       Use parsed       AI extraction (existing)
or AI fallback            recipe
    ↓                          ↓                  ↓
Extract cooking tips from transcript
    ↓
Merge: base recipe + video tips + video metadata
    ↓
Format as markdown → Save to Obsidian (existing)
```

## Component Details

### 1. Recipe Link Detection

**Function:** `find_recipe_link(description: str) -> Optional[str]`

Detection rules (priority order):

1. **Explicit label** - Line starts with "Recipe:" followed by URL
2. **Nearby keyword** - URL on same line as "recipe", "ingredients", "full recipe"
3. **Known domains** - URL matches recipe sites (bingingwithbabish.com, seriouseats.com, bonappetit.com, food52.com, smittenkitchen.com, budgetbytes.com)

Exclusions:
- Social media (patreon.com, instagram.com, twitter.com, facebook.com)
- Affiliate links (amazon.com, amzn.to)
- Other videos (youtube.com)

Returns first matching URL or `None`.

### 2. Webpage Scraping

**Function:** `scrape_recipe_from_url(url: str) -> Optional[dict]`

**Step 1: Fetch**
- GET request with 10s timeout
- Handle redirects and errors gracefully
- Return `None` on failure (triggers fallback)

**Step 2: JSON-LD extraction**
- Parse HTML with BeautifulSoup
- Find `<script type="application/ld+json">` tags
- Look for `"@type": "Recipe"` objects

**Schema.org mapping:**

| Schema.org | Our field |
|------------|-----------|
| `name` | `recipe_name` |
| `description` | `description` |
| `prepTime` | `prep_time` |
| `cookTime` | `cook_time` |
| `recipeYield` | `servings` |
| `recipeIngredient[]` | `ingredients` |
| `recipeInstructions[]` | `instructions` |
| `recipeCuisine` | `cuisine` |

**Step 3: AI fallback**
- If no JSON-LD found, extract page text
- Send to Ollama with webpage extraction prompt

### 3. Description Recipe Parsing

**Function:** `parse_recipe_from_description(description: str) -> Optional[dict]`

**Detection heuristics:**
- Line containing "Ingredients" or "*Ingredients*"
- Multiple lines with quantities (numbers + units)
- Line containing "Method", "Instructions", or "Directions"

**Extraction:**
- Use Ollama with description-specific prompt
- Simpler than transcript (text already structured)
- Set `needs_review: false` by default (explicit text source)

### 4. Cooking Tips Extraction

**Function:** `extract_cooking_tips(transcript: str, recipe: dict) -> list[str]`

**Include:**
- Visual/sensory cues ("when you see it turning brown")
- Timing guidance ("this only takes 30 seconds")
- Technique details ("stir constantly")
- Warnings ("be careful not to burn")
- Substitutions mentioned

**Exclude:**
- Ingredients already in recipe
- Instructions already covered
- Banter, jokes, personal stories
- Sponsorships, outros

**Implementation:**
- Send transcript + recipe JSON to Ollama
- Request 3-5 practical tips not in written recipe
- Returns list of tip strings

## Integration

**Modified:** `extract_recipe.py`

```python
def extract_recipe(url: str, dry_run: bool = False):
    # 1. Fetch video data (existing)
    video_data = fetch_video_data(url)

    # 2. Try priority chain
    recipe = None
    source = None

    # Try webpage first
    recipe_url = find_recipe_link(video_data['description'])
    if recipe_url:
        recipe = scrape_recipe_from_url(recipe_url)
        source = "webpage"

    # Try description if no webpage
    if not recipe:
        recipe = parse_recipe_from_description(video_data['description'])
        source = "description"

    # Fall back to AI extraction (existing)
    if not recipe:
        recipe = extract_recipe_with_ollama(video_data)
        source = "ai_extraction"

    # 3. Extract tips if from webpage/description
    if source in ("webpage", "description"):
        recipe['video_tips'] = extract_cooking_tips(
            video_data['transcript'], recipe
        )

    # 4. Add metadata and save
    recipe['source'] = source
    recipe['source_url'] = recipe_url if recipe_url else None
    save_recipe_to_obsidian(recipe, video_data, dry_run)
```

**New file:** `recipe_sources.py`
- `find_recipe_link()`
- `scrape_recipe_from_url()`
- `parse_recipe_from_description()`
- `extract_cooking_tips()`

## New Recipe Fields

| Field | Type | Description |
|-------|------|-------------|
| `source` | string | "webpage", "description", or "ai_extraction" |
| `source_url` | string or null | Original recipe link if found |
| `video_tips` | list[string] | Tips extracted from video transcript |

## Error Handling

| Scenario | Behavior |
|----------|----------|
| Webpage fetch fails (timeout, 404) | Fall back to description |
| No JSON-LD schema on page | AI extraction on page content |
| AI page extraction fails | Fall back to description |
| No recipe in description | Fall back to transcript AI extraction |
| Tips extraction fails | Set `video_tips: []`, continue |
| Multiple recipe links | Use first match |
| Paywalled recipe | AI extraction on visible content |

**Logging:**
- Print source used: `"✓ Recipe extracted from webpage"`
- Print fallback chain: `"→ No recipe link found, checking description..."`

## Dependencies

**New:** BeautifulSoup (`beautifulsoup4`) for HTML parsing

## Template Changes

`templates/recipe_template.py` adds "Tips from the video" section:

```markdown
## Tips from the Video

- When you see the garlic turning brown, add the pepper flakes immediately
- Stir constantly while the garlic cooks to prevent burning
- Reserve pasta water before draining - you'll need it for the sauce
```

Only rendered if `video_tips` is non-empty.

## Test Cases

1. **Babish video with recipe link** - Should scrape from bingingwithbabish.com
2. **Video with inline recipe only** - Should parse from description
3. **Video with no recipe** - Should fall back to AI extraction
4. **Dead recipe link** - Should fall back gracefully
5. **Recipe site without JSON-LD** - Should use AI extraction on page
