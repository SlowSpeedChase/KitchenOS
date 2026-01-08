# Competitive Research: Recipe Extraction & Management Tools

Date: 2026-01-08

## Executive Summary

Research into similar projects for YouTube-to-recipe extraction and recipe management to inform KitchenOS roadmap. Key findings: KitchenOS's local-first, Obsidian-native approach is unique. Main gaps are YouTube Shorts support, shopping list generation, and recipe format interoperability.

---

## 1. Direct Competitors: YouTube-to-Recipe Extractors

### YT Recipe (ytrecipe.com)
- **Features**: 20+ language support, PDF export, nutritional data, cost analysis
- **How it works**: AI analyzes video in ~20 seconds, extracts ingredients/measurements/steps
- **Pricing**: Free
- **Limitations**: Cloud-based, no local storage, no Obsidian integration

### Video2Recipe (video2recipe.com)
- **Features**: AI-powered, simple URL input, step-by-step instructions
- **Pricing**: Tiered paid plans
- **Limitations**: No export format options documented

### Clip Recipe (cliprecipe.com)
- **Features**: Multi-platform (YouTube, TikTok, Instagram, Pinterest, Facebook)
- **Export formats**: Print, Notion, Evernote, PDF, plain text
- **Strength**: Broad platform support

### Recipe Extractor (recipeextractor.com)
- **Features**: URL-based extraction from any source including social media
- **Strength**: Automatic video transcription
- **Use case**: General-purpose, not video-specialized

### Cooking Guru (cooking.guru)
- **Features**: Free, supports YouTube Shorts, Instagram Reels, TikTok
- **Strength**: Short-form video specialist
- **Limitation**: Only short-form content

### Get The Recipe (Chrome Extension)
- **Features**: Browser extension for in-context extraction
- **Strength**: No copy-paste workflow needed

### SocialKit API
- **Features**: Developer API for recipe extraction
- **Output**: Structured JSON with title, ingredients, measurements, steps, prep time, servings
- **Use case**: Building apps, not end-user tool

---

## 2. Self-Hosted Recipe Managers

### Mealie (github.com/mealie-recipes/mealie)
- **Stars**: 10,800+
- **Stack**: Python backend (REST API) + Vue.js frontend
- **Key features**:
  - URL-based recipe import (auto-extracts from recipe websites)
  - Manual recipe entry with UI editor
  - Meal planning calendar
  - Shopping lists organized by store aisle
  - Cookbooks (recipe grouping)
  - 35+ language support
- **Deployment**: Docker
- **License**: AGPL-3.0

### KitchenOwl (github.com/TomBursch/kitchenowl)
- **Stack**: Flask backend + Flutter frontend (cross-platform mobile)
- **Key features**:
  - Real-time sync across users
  - Shopping list with offline support
  - Meal planning
  - Expense tracking for households
  - Recipe import via recipe-scraper
- **License**: AGPL-3.0

### Tandoor Recipes (tandoor.dev)
- **Key features**:
  - Website importer for recipes
  - Shopping list generation and export
  - Cookbook organization
  - Multi-user support
- **Deployment**: Self-hosted or cloud options

### OpenEats (github.com/open-eats/OpenEats)
- Basic self-hosted recipe management
- Less actively maintained

---

## 3. Obsidian Recipe Ecosystem

### Cooksync Plugin
- Imports recipes from cooksync.app into Obsidian
- Uses Handlebars templating for export format control
- Default format follows Recipe.md specification

### Recipe View Plugin (github.com/lachsh/obsidian-recipe-view)
- Displays markdown recipes as interactive cooking cards
- Keeps recipes as portable markdown files
- Good for "cooking mode" in the kitchen

### Meal Plan Plugin (github.com/tmayoff/obsidian-meals)
- Weekly meal planning
- Search/filter recipes by ingredients you have
- Supports RecipeMD and simpler heading-based formats
- Can import recipes from URLs

### CookLang Editor Plugin
- Syntax highlighting for .cook files
- Preview mode with ingredients, tools, steps
- Inline timer notifications
- Can convert markdown to CookLang format

### Recipe Grabber Plugin
- Import from URLs
- Strips blog fluff (personal anecdotes)
- Extracts clean structured recipes

---

## 4. Recipe Format Standards

### CookLang (cooklang.org)

**Specification**: https://cooklang.org/docs/spec/

**Syntax**:
```
Preheat #oven to 180°C.

Cream @butter{100%g} and @sugar{100%g} until fluffy.

Bake for ~{25%minutes}.
```

**Key features**:
- `@` for ingredients with `{quantity%unit}`
- `#` for cookware
- `~` for timers
- YAML front matter for metadata
- Automatic recipe scaling (lock with `=` prefix)
- Image support (same filename as recipe)

**Pros**: Human-readable while cooking, inline markup, auto-scaling
**Cons**: Requires learning syntax, .cook file extension

### RecipeMD (recipemd.org)

**Specification**: https://recipemd.org/specification.html

**Format**: Standard CommonMark markdown with conventions:
- Title as H1
- Description paragraph
- Ingredient lists (can be grouped with headings)
- Instructions as ordered/unordered lists
- Linked ingredients reference other recipes

**Pros**: Pure markdown, no special syntax to learn
**Cons**: Less structured, no inline measurements

### Schema.org Recipe (JSON-LD)

**Specification**: https://schema.org/Recipe

**Key properties**:
- `name`, `author`, `image`
- `prepTime`, `cookTime`, `totalTime` (ISO 8601 duration)
- `recipeIngredient` (array of strings)
- `recipeInstructions` (array of HowToStep)
- `recipeYield` (servings)
- `nutrition` (NutritionInformation)

**Pros**: Industry standard, SEO benefits, Google rich snippets
**Cons**: Verbose JSON, not human-readable for cooking

---

## 5. Common Challenges in AI Recipe Extraction

### Transcript-Based Extraction Issues

Source: https://insight7.io/transcribing-youtube-cooking-videos-extracting-recipes-and-instructions/

| Challenge | Description |
|-----------|-------------|
| Fast-paced speech | Chefs speak quickly, measurements get missed |
| Culinary jargon | Specialized terms not in general vocabulary |
| Scattered information | Ingredients mentioned throughout, not listed upfront |
| Missing measurements | "Add some butter" without quantities |
| Background noise | Audio quality affects transcription accuracy |

### AI-Generated Recipe Problems

Source: https://blog.cheftalk.ai/we-cannot-trust-ai-to-create-recipes/

- Inconsistent outputs (same prompt = different recipes)
- Inaccurate measurements
- Missing crucial steps
- Food safety issues (unsafe canning instructions, wrong ratios)
- Drawing from unreliable training data (SEO-optimized blog recipes)

### Best Practices for Extraction

1. Combine ASR + NLP + video analysis
2. Use structured output templates
3. Cross-reference visual elements for verification
4. Include confidence scores for uncertain data
5. Mark recipes for human review when uncertain

---

## 6. YouTube Shorts Technical Considerations

### Problem
YouTube Data API cannot fetch metadata for Shorts directly.

### Solution: yt-dlp
```python
from yt_dlp import YoutubeDL

def fetch_video_metadata(video_id):
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'dump_single_json': True
    }
    with YoutubeDL(ydl_opts) as ydl:
        url = f'https://www.youtube.com/shorts/{video_id}'
        info = ydl.extract_info(url, download=False)
        return info
```

### Key yt-dlp Options
- `--ignore-no-formats-error`: Extract metadata even if video unavailable
- `--skip-download`: Metadata only, no video download
- `--dump-single-json`: Output as JSON

### Shorts-Specific Notes
- Shorts URLs: `/shorts/VIDEO_ID`
- Can extract parent video attribution if present
- yt-dlp handles Shorts the same as regular videos

---

## 7. Feature Gap Analysis: KitchenOS vs Competitors

| Feature | Competitors | KitchenOS |
|---------|-------------|-----------|
| YouTube video extraction | All | ✅ |
| YouTube Shorts | Cooking Guru, Clip Recipe | ❌ Planned |
| TikTok/Instagram | Clip Recipe, Cooking Guru | ❌ |
| Local-first/offline | Mealie, KitchenOwl (partial) | ✅ |
| Obsidian integration | Cooksync, Recipe Grabber | ✅ Native |
| Shopping list generation | Mealie, KitchenOwl, Tandoor | ❌ |
| Meal planning | Mealie, KitchenOwl, Tandoor | ❌ |
| Recipe scaling | CookLang tools | ❌ |
| Multi-format export | Clip Recipe | ❌ |
| Nutritional data | YT Recipe | ❌ |
| Cost calculation | YT Recipe | ❌ |
| Cooking mode | Recipe View plugin | ❌ (could integrate) |
| Multi-user | Mealie, KitchenOwl | ❌ |
| Mobile app | KitchenOwl | ❌ (iOS Shortcut only) |

---

## 8. Recommended Roadmap Priorities

Based on research, prioritized by value vs complexity:

### High Priority (Unique Value, Moderate Effort)
1. **YouTube Shorts support** - Use yt-dlp, already have infrastructure
2. **Shopping list generation** - Aggregate ingredients, export for grocery apps
3. **Recipe format export** - CookLang/RecipeMD for interoperability

### Medium Priority (Nice to Have)
4. **Recipe scaling** - Adjust servings, recalculate quantities
5. **Cooking mode integration** - Partner with Recipe View plugin
6. **Timer extraction** - Parse times from instructions

### Lower Priority (Significant Effort)
7. **TikTok/Instagram support** - Different APIs, authentication challenges
8. **Nutritional estimation** - Requires ingredient database
9. **Meal planning calendar** - Would need calendar UI

### Research Items
10. **Volume → weight conversion** - Requires ingredient density database; see sugarcube library

---

## Sources

- https://www.ytrecipe.com/
- https://video2recipe.com/
- https://www.cliprecipe.com/
- https://cooking.guru/
- https://recipeextractor.com/
- https://github.com/mealie-recipes/mealie
- https://github.com/TomBursch/kitchenowl
- https://tandoor.dev/
- https://cooklang.org/docs/spec/
- https://recipemd.org/specification.html
- https://schema.org/Recipe
- https://insight7.io/transcribing-youtube-cooking-videos-extracting-recipes-and-instructions/
- https://github.com/yt-dlp/yt-dlp
- https://forum.obsidian.md/t/new-plugin-cooksync-recipe-collector/97773
- https://github.com/lachsh/obsidian-recipe-view
- https://github.com/tmayoff/obsidian-meals
