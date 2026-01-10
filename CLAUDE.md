# CLAUDE.md

Development guide for Claude Code when working with this repository.

## Project Overview

**KitchenOS** is a YouTube-to-Obsidian recipe extraction pipeline. It captures cooking videos, extracts structured recipe data using AI (Ollama local), and saves formatted markdown files to an Obsidian vault for browsing with Dataview.

### User Context

- **Primary user**: Home cook who watches YouTube cooking videos
- **Use case**: Save recipes from videos that don't have written recipes
- **Workflow**: Watch video → run command → recipe appears in Obsidian
- **Browsing**: Uses Obsidian + Dataview to search/filter recipes

### Design Principles

| Principle | Rationale |
|-----------|-----------|
| **Local-first** | Privacy, no cloud dependency, works offline (except YouTube fetch) |
| **Simple over complex** | Standalone script beats n8n orchestration |
| **Obsidian-native** | YAML frontmatter for Dataview, flat folder structure |
| **Honest about inference** | Mark uncertain data, set `needs_review` flag |
| **Graceful degradation** | Missing transcript → try Whisper → use description only |

### Constraints

- **Python 3.11** - Full f-string support including backslashes
- **Ollama local** - Must be running for extraction to work
- **YouTube API key required** - For metadata fetching
- **iCloud path** - Obsidian vault is in iCloud, path has spaces (escaped)

## Key Paths

| Path | Purpose |
|------|---------|
| `/Users/chaseeasterling/KitchenOS/` | Project root |
| `.venv/` | Python virtual environment |
| `Recipes/` in Obsidian vault | Main recipe files (title case, e.g., `Butter Biscuits.md`) |
| `Recipes/Cooking Mode/` in Obsidian vault | Simplified cooking view files (`.recipe.md`) |

**Obsidian Vault**: `/Users/chaseeasterling/Library/Mobile Documents/iCloud~md~obsidian/Documents/KitchenOS/`

## Running Commands

### Extract a Recipe (Primary Use)

```bash
cd /Users/chaseeasterling/KitchenOS
.venv/bin/python extract_recipe.py "https://www.youtube.com/watch?v=VIDEO_ID"

# Dry run (preview without saving)
.venv/bin/python extract_recipe.py --dry-run "VIDEO_URL"
```

### Fetch Video Data Only

```bash
.venv/bin/python main.py --json "VIDEO_ID_OR_URL"
```

### Migrate Recipes to New Schema

```bash
# Preview what would change
.venv/bin/python migrate_recipes.py --dry-run

# Apply migrations
.venv/bin/python migrate_recipes.py
```

### Batch Extract from Reminders

```bash
# Process all uncompleted reminders from "Recipies to Process" list
.venv/bin/python batch_extract.py

# Preview what would be processed
.venv/bin/python batch_extract.py --dry-run
```

### Generate Meal Plan

```bash
# Generate meal plan for 2 weeks ahead (normal operation)
.venv/bin/python generate_meal_plan.py

# Generate for specific week
.venv/bin/python generate_meal_plan.py --week 2026-W05

# Dry run (preview without creating)
.venv/bin/python generate_meal_plan.py --dry-run
```

### Generate Shopping List

```bash
# Auto-detect current week's plan
.venv/bin/python shopping_list.py

# Use specific week's plan
.venv/bin/python shopping_list.py --week 2026-W03

# Preview without adding to Reminders
.venv/bin/python shopping_list.py --dry-run

# Clear existing items first
.venv/bin/python shopping_list.py --clear
```

### Generate Shopping List (via API)

The Obsidian button calls this endpoint, but you can also test directly:

```bash
curl -X POST http://localhost:5001/generate-shopping-list \
  -H "Content-Type: application/json" \
  -d '{"week": "2026-W04"}'
```

### Send to Reminders (via API)

```bash
curl -X POST http://localhost:5001/send-to-reminders \
  -H "Content-Type: application/json" \
  -d '{"week": "2026-W04"}'
```

## Meal Plan Generator (LaunchAgent)

Auto-generates weekly meal plan templates 2 weeks in advance. Runs daily at 6am.

### Management

```bash
# Install the LaunchAgent
cp com.kitchenos.mealplan.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.kitchenos.mealplan.plist

# View logs
tail -f /Users/chaseeasterling/KitchenOS/meal_plan_generator.log

# Restart service
launchctl unload ~/Library/LaunchAgents/com.kitchenos.mealplan.plist
launchctl load ~/Library/LaunchAgents/com.kitchenos.mealplan.plist

# Test run manually
.venv/bin/python generate_meal_plan.py
```

### Meal Plan Location

Files are created in: `{Obsidian Vault}/Meal Plans/2026-W03.md`

Template includes Monday-Sunday with Breakfast/Lunch/Dinner/Notes sections.

## API Server (iOS Shortcut Integration)

The API server enables recipe extraction from iOS via Share Sheet. It runs as a LaunchAgent and is accessible via Tailscale from anywhere.

### Server Management

```bash
# Check if running
curl http://localhost:5001/health

# View logs
tail -f /Users/chaseeasterling/KitchenOS/server.log

# Restart service
launchctl unload ~/Library/LaunchAgents/com.kitchenos.api.plist
launchctl load ~/Library/LaunchAgents/com.kitchenos.api.plist

# Stop service
launchctl unload ~/Library/LaunchAgents/com.kitchenos.api.plist

# Start service
launchctl load ~/Library/LaunchAgents/com.kitchenos.api.plist
```

### Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/health` | GET | Health check |
| `/transcript` | GET/POST | Returns transcript + description (no extraction) |
| `/extract` | POST | Full extraction, saves to Obsidian |
| `/generate-shopping-list` | POST | Generate shopping list markdown from meal plan |
| `/send-to-reminders` | POST | Send unchecked items to Apple Reminders |
| `/reprocess?file=<name>` | GET | Full re-extraction from YouTube (preserves notes) |
| `/refresh?file=<name>` | GET | Template refresh only, keeps existing data |

### Configuration

- **Port**: 5001 (configured in LaunchAgent)
- **Tailscale IP**: `100.111.6.10`
- **LaunchAgent**: `~/Library/LaunchAgents/com.kitchenos.api.plist`

See `docs/setup/iOS_SHORTCUT_SETUP.md` for iOS Shortcut configuration.

## Architecture

### Pipeline Flow

```
YouTube URL → extract_recipe.py
    ↓
main.py (fetch metadata + transcript)
    ↓
recipe_sources.py:
  1. find_recipe_link() → scrape_recipe_from_url()
  2. parse_recipe_from_description()
  3. search_creator_website() → scrape_recipe_from_url()
  4. extract_recipe_with_ollama() (fallback)
    ↓
extract_cooking_tips() (if webpage/description source)
    ↓
validate_ingredients() (repair AI extraction errors)
    ↓
template → Obsidian
```

### Core Components

| File | Purpose |
|------|---------|
| `extract_recipe.py` | **Main entry point** - orchestrates entire pipeline |
| `main.py` | Video data fetcher (transcript, metadata, `--json` mode) |
| `api_server.py` | Flask API for iOS Shortcut integration |
| `batch_extract.py` | Batch processor - reads from iOS Reminders, extracts in bulk |
| `generate_meal_plan.py` | Creates weekly meal plan templates |
| `shopping_list.py` | Generates shopping list from meal plans |
| `prompts/recipe_extraction.py` | AI prompt templates for structured extraction |
| `templates/recipe_template.py` | Markdown formatter with YAML frontmatter |
| `templates/meal_plan_template.py` | Weekly meal plan template generator |
| `lib/ingredient_parser.py` | Parses ingredient strings into amount/unit/item |
| `lib/ingredient_validator.py` | Validates/repairs AI extraction errors in ingredients |
| `lib/ingredient_aggregator.py` | Combines like ingredients for shopping lists |
| `lib/shopping_list_generator.py` | Core logic for generating shopping lists from meal plans |
| `templates/shopping_list_template.py` | Markdown template for shopping list files |
| `scripts/kitchenos-uri-handler/` | macOS URI scheme handler for Obsidian buttons |

### Key Functions

**extract_recipe.py:**
- `extract_recipe_with_ollama()` - Sends data to Ollama, returns parsed JSON
- `save_recipe_to_obsidian()` - Formats and writes markdown file
- `main()` - CLI entry point with `--dry-run` support

**main.py:**
- `youtube_parser(url)` - Extracts video ID from various URL formats
- `get_video_metadata(video_id)` - Fetches title, channel, description
- `get_transcript(video_id)` - Gets transcript (YouTube or Whisper fallback)

**templates/recipe_template.py:**
- `format_recipe_markdown()` - Converts recipe JSON to Obsidian markdown
- `generate_filename()` - Creates `YYYY-MM-DD-recipe-slug.md` filename
- `generate_tools_callout()` - Generates Tools callout with reprocess buttons

**recipe_sources.py:**
- `find_recipe_link()` - Detects recipe URLs in video descriptions
- `scrape_recipe_from_url()` - Fetches and parses JSON-LD from recipe websites
- `parse_recipe_from_description()` - Extracts inline recipes from descriptions
- `extract_cooking_tips()` - Pulls practical tips from transcripts
- `load_creator_mapping()` - Loads channel → website mapping from config
- `search_for_recipe_url()` - Searches DuckDuckGo for recipe URL
- `search_creator_website()` - Orchestrates creator website search

**api_server.py:**
- `refresh_template()` - Regenerates recipe with current template, preserves data/notes
- `reprocess_recipe()` - Full re-extraction from YouTube, preserves My Notes section

**lib/backup.py:**
- `create_backup()` - Creates timestamped backup in .history/ folder
- `cleanup_old_backups()` - Removes backups older than 30 days

**lib/recipe_parser.py:**
- `parse_recipe_file()` - Parses frontmatter and body from recipe markdown
- `extract_my_notes()` - Extracts content from ## My Notes section
- `parse_recipe_body()` - Extracts ingredients/instructions from markdown body
- `find_existing_recipe()` - Finds recipe file by video ID

**migrate_recipes.py:**
- `migrate_recipe_file()` - Updates single recipe to current schema
- `run_migration()` - Batch migrates all recipes
- `has_tools_callout()` - Detects if recipe has Tools callout
- `add_tools_callout()` - Adds Tools callout to existing recipes

**lib/ingredient_parser.py:**
- `parse_ingredient()` - Splits ingredient string into amount, unit, item
- `normalize_unit()` - Standardizes unit abbreviations
- `is_informal_measurement()` - Detects "a pinch", "to taste", etc.
- `parse_amount()` - Parses fractions, ranges, word numbers

**lib/ingredient_validator.py:**
- `validate_ingredients()` - Validates/repairs list of ingredients from AI extraction
- `is_malformed_ingredient()` - Detects AI errors (unit in amount, empty item, etc.)
- `repair_ingredient()` - Re-parses malformed ingredient using ingredient_parser

## AI Configuration

### Ollama Settings

```python
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "mistral:7b"
```

### Recipe JSON Schema

The AI extracts this structure:

```json
{
  "recipe_name": "string",
  "description": "string",
  "prep_time": "string or null",
  "cook_time": "string or null",
  "servings": "number or null",
  "difficulty": "easy|medium|hard",
  "cuisine": "string",
  "protein": "string or null",
  "dish_type": "string",
  "dietary": ["array"],
  "equipment": ["array"],
  "ingredients": [{"amount": "number/string", "unit": "string", "item": "string", "inferred": boolean}],
  "instructions": [{"step": number, "text": "string", "time": "string or null"}],
  "storage": "string or null",
  "variations": ["array"],
  "needs_review": boolean,
  "confidence_notes": "string"
}
```

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

## Development Environment

- **Python Version**: 3.11
- **Virtual Environment**: `.venv/` (required for all Python operations)
- **API Keys**: In `.env` file
  - `YOUTUBE_API_KEY` - YouTube Data API
  - `OPENAI_API_KEY` - Whisper fallback

## Dependencies

```
youtube-transcript-api    # Fetch video transcripts
google-api-python-client  # YouTube Data API
yt-dlp                    # Audio download for Whisper
openai                    # Whisper API transcription
python-dotenv             # Environment variables
requests                  # HTTP requests to Ollama
duckduckgo-search         # Web search for creator websites
```

## Testing

Test with a cooking video that has captions:

```bash
# Dry run first
.venv/bin/python extract_recipe.py --dry-run "https://www.youtube.com/watch?v=bJUiWdM__Qw"

# Then full extraction
.venv/bin/python extract_recipe.py "https://www.youtube.com/watch?v=bJUiWdM__Qw"
```

## Common Issues

### Ollama not running
```bash
ollama serve  # Start in background
curl http://localhost:11434/api/tags  # Verify running
```

### Transcript unavailable
Falls back to Whisper (requires OpenAI key) or proceeds with description only.

## File Naming Convention

Recipe files use title case with spaces: `{Recipe Name}.md`

Example: `Pasta Aglio E Olio.md`

Cooking mode files are stored in a subdirectory: `Recipes/Cooking Mode/{Recipe Name}.recipe.md`

## Completing Work

When finishing a feature or fix, follow this checklist:

### 1. Verify
- [ ] Run `extract_recipe.py --dry-run` with a test video
- [ ] Check for Python errors or warnings
- [ ] Verify Ollama is responding correctly

### 2. Test End-to-End (if applicable)
- [ ] Run full extraction: `.venv/bin/python extract_recipe.py "VIDEO_URL"`
- [ ] Check recipe file was created in Obsidian vault
- [ ] Open in Obsidian - verify frontmatter and content look correct

### 3. Update Documentation (Required)

- [ ] Review changes against table below - identify which docs need updates
- [ ] Make required documentation updates
- [ ] If no docs need updating, confirm why (e.g., "refactor only, no API changes")

**Which doc to update:**

| Change Type | Update This |
|-------------|-------------|
| New feature/function | CLAUDE.md → "Key Functions" |
| Architecture change | CLAUDE.md → "Architecture" |
| New config option | CLAUDE.md → "AI Configuration" |
| New constraint/gotcha | CLAUDE.md → "Constraints" or "Common Issues" |
| New design principle | CLAUDE.md → "Design Principles" |
| User-facing change | README.md → relevant section |
| Major feature complete | Future Enhancements → mark done or remove |
| Lessons learned | docs/IMPLEMENTATION_SUMMARY.md → "Lessons Learned" |

**Documentation standards:**
- Keep CLAUDE.md concise - it's loaded every session
- Use tables for structured data
- Include code examples for commands
- Update the JSON schema if recipe structure changes

### 4. Commit

**Do not commit until step 3 is complete.**

```bash
git add -A
git commit -m "feat/fix/docs: description

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

### 5. Update Future Enhancements
- [ ] Mark completed features as done (move to "Completed" or remove)
- [ ] Add any new ideas discovered during implementation

## Future Enhancements

These features are planned but not yet implemented:

| Feature | Priority | Notes |
|---------|----------|-------|
| ~~Recipe link detection~~ | ~~High~~ | **Completed** - Priority chain: webpage → description → AI |
| ~~iOS Shortcut~~ | ~~Medium~~ | **Completed** - /extract endpoint + Tailscale, see docs/setup/iOS_SHORTCUT_SETUP.md |
| ~~Batch processing~~ | ~~Medium~~ | **Completed** - Processes URLs from iOS Reminders list |
| ~~YouTube Shorts support~~ | ~~Medium~~ | **Completed** - yt-dlp fetches metadata for /shorts/ URLs |
| ~~Recipe reprocess buttons~~ | ~~Medium~~ | **Completed** - Tools callout with Re-extract/Refresh buttons |
| Claude API fallback | Low | Use Claude when Ollama fails |
| Image extraction | Low | Get video thumbnails for recipes |

## Project Structure

```
KitchenOS/
├── extract_recipe.py      # Main entry point
├── main.py                # Video data fetcher
├── api_server.py          # Flask API for iOS
├── batch_extract.py       # Batch processor
├── recipe_sources.py      # Recipe extraction logic
├── migrate_recipes.py     # Schema migration
├── shopping_list.py       # Shopping list from meal plans
├── generate_meal_plan.py  # Weekly meal plan generator
│
├── lib/                   # Python library modules
├── prompts/               # AI prompt templates
├── templates/             # Recipe + meal plan templates
├── tests/                 # Test suite
├── scripts/               # Shell scripts
│
├── docs/                  # Documentation
│   ├── setup/             # Setup guides (iOS, HOW_TO_RUN)
│   ├── plans/             # Design documents
│   └── stories/           # User stories
│
├── com.kitchenos.mealplan.plist  # LaunchAgent for meal plan generation
└── KitchenOSApp/          # macOS menu bar app
```

## Documentation

| Document | Purpose |
|----------|---------|
| `README.md` | User guide - installation, usage, configuration |
| `docs/setup/iOS_SHORTCUT_SETUP.md` | iOS Shortcut configuration |
| `docs/setup/HOW_TO_RUN.md` | Quick start guide |
| `docs/IMPLEMENTATION_SUMMARY.md` | What was built vs planned, lessons learned |
| `docs/plans/` | Design documents and plans |

**Note:** The original design proposed n8n orchestration, but we built a simpler standalone Python solution. See `IMPLEMENTATION_SUMMARY.md` for details on this decision.
