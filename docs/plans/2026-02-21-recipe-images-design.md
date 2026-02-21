# Recipe Images Design

**Date:** 2026-02-21
**Status:** Approved

## Goal

Add recipe images to Obsidian recipe files, sourced from recipe websites and YouTube thumbnails, with the ability to hide images on mobile via CSS snippet.

## Image Sources (priority order)

1. **Recipe website image** — from JSON-LD `image` field when scraping recipe links
2. **YouTube thumbnail** — `maxresdefault` (1280x720) from YouTube API, always available as fallback

## Storage

- **Location:** `Recipes/Images/{Recipe Name}.jpg` in the Obsidian vault
- Images downloaded and saved locally during extraction
- Filename mirrors the recipe file name (e.g. `Pasta Aglio E Olio.jpg`)

## Recipe Template Changes

**Frontmatter additions:**

```yaml
banner: "[[Pasta Aglio E Olio.jpg]]"
cssclasses:
  - recipe
```

**Body:** Image embedded right after frontmatter, before description:

```markdown
![[Pasta Aglio E Olio.jpg]]
```

## CSS Snippet

File: `hide-recipe-images.css` in vault's `.obsidian/snippets/` folder:

```css
.recipe img {
  display: none;
}
```

Enable on iPhone, leave off on Mac.

## Pipeline Changes

- **`main.py`** — include thumbnail URL in metadata return
- **`recipe_sources.py`** — extract `image` field from JSON-LD scrape
- **`extract_recipe.py`** — download best available image, save to vault
- **`templates/recipe_template.py`** — add `banner`, `cssclasses`, and inline image to template
- **`migrate_recipes.py`** — add `cssclasses: [recipe]` to existing recipes (no image backfill)

## Out of Scope

- No image resizing/compression
- No Crouton image import (exports don't include images)
- No retroactive image fetching for existing recipes
