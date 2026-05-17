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
| `/Users/chaseeasterling/GitHub/KitchenOS/` | Project root |
| `.venv/` | Python virtual environment |
| `Recipes/` in Obsidian vault | Main recipe files (title case, e.g., `Butter Biscuits.md`) |
| `Recipes/Cooking Mode/` in Obsidian vault | Simplified cooking view files (`.recipe.md`) |
| `Recipes/Images/` in Obsidian vault | Recipe images (downloaded from source or YouTube thumbnail) |

**Obsidian Vault**: `~/KitchenOS/vault/` (configurable via `KITCHENOS_VAULT` env var; resolved by `lib/paths.py`)

## Running Commands

### Extract a Recipe (Primary Use)

```bash
cd /Users/chaseeasterling/GitHub/KitchenOS
.venv/bin/python extract_recipe.py "https://www.youtube.com/watch?v=VIDEO_ID"

# Dry run (preview without saving)
.venv/bin/python extract_recipe.py --dry-run "VIDEO_URL"
```

### Import from Crouton

```bash
# Import all .crumb files from a Crouton export folder
.venv/bin/python import_crouton.py "/path/to/Crouton Recipes"

# Preview without importing
.venv/bin/python import_crouton.py --dry-run "/path/to/Crouton Recipes"

# Import without Ollama enrichment (faster, metadata will be null)
.venv/bin/python import_crouton.py --no-enrich "/path/to/Crouton Recipes"
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

### Clean Up Cuisine Data, Normalize Tags & Populate Seasonal

```bash
# Preview all corrections (cuisine, tags, seasonal)
.venv/bin/python migrate_cuisine.py --dry-run

# Apply all fixes
.venv/bin/python migrate_cuisine.py

# Cuisine + tags only (skip seasonal matching)
.venv/bin/python migrate_cuisine.py --no-seasonal

# Tags only (skip cuisine and seasonal)
.venv/bin/python migrate_cuisine.py --no-seasonal

# Force re-match seasonal data (ignore existing)
.venv/bin/python migrate_cuisine.py --no-tags --force-seasonal
```

### Batch Extract from Reminders

```bash
# Process all uncompleted reminders from "Recipies to Process" list
.venv/bin/python batch_extract.py

# Preview what would be processed
.venv/bin/python batch_extract.py --dry-run
```

### Meal Planner UI (iPad)

```
Open in browser: http://localhost:5001/meal-planner
iPad via Tailscale: http://100.103.114.106:5001/meal-planner
```

Drag-and-drop board for planning weekly meals. Recipe sidebar with search and filter chips. Reads/writes the same Obsidian markdown files.

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

### Sync Calendar

```bash
# Generate meal calendar ICS file
.venv/bin/python sync_calendar.py

# Preview without writing
.venv/bin/python sync_calendar.py --dry-run
```

### Generate Nutrition Dashboard

```bash
# Generate for current week
.venv/bin/python generate_nutrition_dashboard.py

# Generate for specific week
.venv/bin/python generate_nutrition_dashboard.py --week 2026-W03

# Preview without saving
.venv/bin/python generate_nutrition_dashboard.py --dry-run
```

## Meal Plan Generator (LaunchAgent)

Auto-generates weekly meal plan templates 2 weeks in advance. Runs daily at 6am.

### Management

```bash
# Install the LaunchAgent
cp ops/com.kitchenos.mealplan.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.kitchenos.mealplan.plist

# View logs
tail -f ~/GitHub/KitchenOS/logs/meal_plan_generator.log

# Restart service
launchctl unload ~/Library/LaunchAgents/com.kitchenos.mealplan.plist
launchctl load ~/Library/LaunchAgents/com.kitchenos.mealplan.plist

# Test run manually
.venv/bin/python generate_meal_plan.py
```

### Meal Plan Location

Files are created in: `{Obsidian Vault}/Meal Plans/2026-W03.md`

Template includes Monday-Sunday with Breakfast/Lunch/Dinner/Notes sections.

**Servings multiplier:** Use `[[Recipe Name]] x2` to indicate multiple servings. The `xN` goes outside the wiki link so Obsidian links still resolve. Affects nutrition dashboard calculations and shopping list ingredient scaling.

**Composite meals:** Reference a meal bundle with `[[Meal: Salmon Dinner]]` (the `Meal:` prefix is the parser discriminator). Meal definitions live in `vault/Meals/<Name>.meal.md` with frontmatter listing `sub_recipes`. The parser keeps the meal name in the markdown; `flatten_to_recipes()` expands meals downstream for shopping lists, nutrition, and tasks. Outer `xN` multipliers stack with each sub-recipe's `servings` override.

**Pantry-aware shopping list flow:**
1. `/api/shopping-list/preview` returns per-line records split into `from_pantry` / `to_buy`.
2. UI shows a confirmation modal for any pantry-overlapping line.
3. `/api/shopping-list/confirm` saves the markdown and decrements `config/pantry.json`.
The CLI (`shopping_list.py`) implements the same flow with `[a]ll / [s]ome / [n]one` prompts when stdin is a tty (`--no-interactive` skips, `--no-pantry` ignores inventory entirely).

**Cross-recipe prep tasks (Today's Prep panel):** `lib/task_extractor.py` runs once per week, classifying each scheduled recipe's instructions into prep / active / passive with do-ahead and dependency flags. Cached in a `<week>.tasks.json` sidecar next to the meal plan. The meal-planner UI shows today's tasks plus a "Get ahead" section for upcoming `can_do_ahead` items. Done flags persist across plan edits via stable task IDs.

## Calendar Sync (LaunchAgent)

Syncs meal plans to ICS calendar file daily at 6:05am (after meal plan generator).

### Management

```bash
# Install the LaunchAgent
cp ops/com.kitchenos.calendar-sync.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.kitchenos.calendar-sync.plist

# View logs
tail -f ~/GitHub/KitchenOS/logs/calendar_sync.log

# Test run manually
.venv/bin/python sync_calendar.py
```

### Output

ICS file is written to: `{Obsidian Vault}/meal_calendar.ics`

Accessible via API at: `http://localhost:5001/calendar.ics` (or Tailscale IP)

## Batch Extract (LaunchAgent)

Processes YouTube URLs from the "Recipies to Process" iOS Reminders list hourly (at :10 past each hour).

### Management

```bash
# Install the LaunchAgent
cp ops/com.kitchenos.batch-extract.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.kitchenos.batch-extract.plist

# View logs
tail -f ~/GitHub/KitchenOS/logs/batch_extract.log

# Restart service
launchctl unload ~/Library/LaunchAgents/com.kitchenos.batch-extract.plist
launchctl load ~/Library/LaunchAgents/com.kitchenos.batch-extract.plist

# Test run manually
.venv/bin/python batch_extract.py
```

## Failure Analysis Agent

When batch extract encounters failures, it writes a structured JSON log to `failures/` and triggers `scripts/analyze_failures.sh` in the background. The script invokes `claude -p` to:

1. Analyze the failure log
2. Skip transient (network) errors
3. Reproduce and fix code bugs
4. Open a PR for review

### Failure Log Location

Files: `failures/YYYY-MM-DD-HHMMSS.json` (auto-cleaned after 30 days)

### Error Categories

| Category | Meaning | Agent Action |
|----------|---------|--------------|
| `network` | Transient connectivity | Skip |
| `ollama` | Ollama infrastructure | Check config |
| `youtube` | Video/transcript issue | Improve fallbacks |
| `parsing` | Code bug | Create fix |
| `io` | File/permission issue | Flag for review |
| `unknown` | Unrecognized | Investigate |

### Manual Trigger

```bash
# Run analysis on a specific failure log
scripts/analyze_failures.sh failures/2026-02-13-061000.json
```

## API Server (iOS Shortcut Integration)

The API server enables recipe extraction from iOS via Share Sheet. It runs as a LaunchAgent and is accessible via Tailscale from anywhere.

### Server Management

```bash
# Check if running
curl http://localhost:5001/health

# View logs
tail -f ~/GitHub/KitchenOS/logs/server.log

# Restart service
launchctl unload ~/Library/LaunchAgents/com.kitchenos.api.plist
launchctl load ~/Library/LaunchAgents/com.kitchenos.api.plist

# Stop service
launchctl unload ~/Library/LaunchAgents/com.kitchenos.api.plist

# Start service
launchctl load ~/Library/LaunchAgents/com.kitchenos.api.plist
```

### Endpoints

For the full route list, grep `@app.route` in `api_server.py`. Endpoints with non-obvious contracts:

| Endpoint | Notes |
|----------|-------|
| `/reprocess?file=<name>` (GET) | Full re-extraction from YouTube. **Preserves the `## My Notes` section.** |
| `/refresh?file=<name>` (GET) | Template refresh only — keeps existing extracted data, just re-renders. |
| `/meal-planner` (GET) | Interactive drag-and-drop meal planner board (HTML). |
| `/api/meal-plan/<week>` (GET/PUT) | Programmatic meal plan as JSON; PUT round-trips through `rebuild_meal_plan_markdown`. |
| `/api/meals` (POST) | Create meal — frontmatter saved to `vault/Meals/<name>.meal.md`. |
| `/api/shopping-list/preview` `/confirm` | See "Pantry-aware shopping list flow" above. |
| `/api/tasks/<week>` (GET, `?force=1`) | Prep-task sidecar payload; cached in `<week>.tasks.json`. |
| `/add-to-meal-plan` (GET/POST) | Recipe-button entry. POST branches on `mode={direct,existing,new,schedule_meal}`. `existing`/`new` mutate `vault/Meals/<name>.meal.md` and end on an optional schedule prompt. |

### Configuration

- **Port**: 5001 (configured in LaunchAgent)
- **Tailscale IP**: `100.103.114.106`
- **LaunchAgent**: `~/Library/LaunchAgents/com.kitchenos.api.plist`

See `docs/setup/iOS_SHORTCUT_SETUP.md` for iOS Shortcut configuration.

## MCP Server (Claude Desktop Integration)

Claude Desktop can interact with KitchenOS directly via MCP tools.

### Setup

Configured in `~/Library/Application Support/Claude/claude_desktop_config.json`. Requires the API server to be running.

### Available Tools

| Tool | Purpose |
|------|---------|
| `extract_recipe` | Extract recipe from YouTube URL |
| `save_recipe` | Save recipe from conversation |
| `search_recipes` | Search recipe library |
| `get_recipe` | Read full recipe details |
| `get_meal_plan` | View week's meal plan |
| `update_meal_plan` | Modify meal plan |
| `generate_shopping_list` | Generate shopping list |
| `send_to_reminders` | Push to Apple Reminders |
| `add_to_inventory` | Add items to pantry inventory (from receipt photo/email) |
| `list_inventory` | List inventory items with category/location filters |
| `remove_from_inventory` | Remove an item from inventory (used up) |
| `update_inventory_item` | Adjust an item's quantity |
| `create_things_task` | Create Things 3 task |

### Prerequisites

- KitchenOS API server running (`com.kitchenos.api.plist`)
- Things 3 installed (for task creation)
- "KitchenOS" project created in Things

## Receipt → Inventory Workflow

KitchenOS tracks pantry inventory in a single `Inventory.md` at the vault root. New items enter via Claude Desktop:

1. **Photo receipt or email** — share with Claude in a conversation (Claude Desktop, the web app, or via the iOS app's Share Sheet).
2. **Claude parses** the items, normalizes the cryptic receipt strings (e.g. `GV WHL MLK 1G` → `Whole milk, 1 gal`), assigns a category and storage location, and calls the `add_to_inventory` MCP tool.
3. **The tool** posts to `/api/inventory/add`, which writes to `Inventory.md` (merging duplicates by `name+unit+location`).

### Item Schema

| Field | Required | Vocab |
|-------|----------|-------|
| `name` | yes | Free text, normalized |
| `quantity` | yes | Numeric (default 1) |
| `unit` | yes | Free text (`gal`, `lb`, `oz`, `ct`, …) |
| `category` | no | `produce`, `dairy`, `meat`, `seafood`, `pantry`, `frozen`, `bakery`, `beverages`, `household`, `other` |
| `location` | no | `fridge`, `freezer`, `pantry`, `counter`, `other` (default `pantry`) |
| `purchased` | no | `YYYY-MM-DD` |
| `source` | no | `receipt`, `manual`, `claude` |
| `notes` | no | Free text (often the raw receipt line) |

### MCP Tools

| Tool | Purpose |
|------|---------|
| `add_to_inventory(items)` | Batch add — Claude calls this after parsing a receipt |
| `list_inventory(category?, location?)` | List items, with optional filters |
| `remove_from_inventory(name, location?)` | Remove an item (used up) |
| `update_inventory_item(name, quantity, location?)` | Adjust quantity (e.g., 0.5 for half-used) |

### Storage

`Inventory.md` is a markdown table: human-editable in Obsidian, machine-parseable. Items sort by category then name on every write. Duplicate `(name, unit, location)` rows merge — quantities sum.

## QuickAdd Setup (Obsidian)

The "Add Ingredients" button in shopping lists requires QuickAdd plugin configuration:

1. Settings → QuickAdd → Add Choice → name: `Add Ingredients to Shopping List` → type: Capture
2. Configure the Capture:
   - **Capture To:** Active file
   - **Insert at:** Bottom of file
   - **Capture format:** Enabled
3. Format template: `{{VALUE:Paste ingredients (one per line):}}`
4. Add format function to transform lines to checkboxes:
   ```javascript
   return value
     .split('\n')
     .map(line => line.trim())
     .filter(line => line.length > 0)
     .map(line => `- [ ] ${line}`)
     .join('\n');
   ```

## Architecture

### Pipeline Flow

```
YouTube URL → extract_recipe.py
    ↓
main.py (fetch metadata + transcript + first comment)
    ↓
recipe_sources.py:
  1. find_recipe_link() → scrape_recipe_from_url()
  2. parse_recipe_from_description()
  2.5a. find_recipe_link(comment) → scrape_recipe_from_url()
  2.5b. parse_recipe_from_description(comment)
  3. search_creator_website() → scrape_recipe_from_url()
  4. extract_recipe_with_ollama() (fallback, includes comment as context)
    ↓
extract_cooking_tips() (if webpage/description/comment source)
    ↓
validate_ingredients() (repair AI extraction errors)
    ↓
match_ingredients_to_seasonal() (Ollama fuzzy match → seasonal_ingredients, peak_months)
    ↓
calculate_recipe_nutrition() (Nutritionix → USDA → AI fallback)
    ↓
download_image() (website image or YouTube thumbnail → Recipes/Images/)
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
| `import_crouton.py` | Imports Crouton .crumb files into Obsidian vault |
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
| `lib/image_downloader.py` | Downloads recipe images from URLs |
| `lib/crouton_parser.py` | Parses Crouton .crumb JSON format |
| `prompts/crouton_enrichment.py` | AI prompt for classifying imported recipes |
| `lib/failure_logger.py` | Error classification and structured failure logging |
| `scripts/analyze_failures.sh` | Invokes Claude Code CLI to analyze failures and create fix PRs |
| `sync_calendar.py` | Generates ICS calendar from meal plans |
| `lib/meal_plan_parser.py` | Parses meal plan markdown files |
| `lib/ics_generator.py` | Creates ICS calendar format |
| `generate_nutrition_dashboard.py` | Creates nutrition dashboard from meal plans |
| `lib/nutrition.py` | NutritionData dataclass |
| `lib/nutrition_lookup.py` | API clients for Nutritionix, USDA, AI fallback |
| `lib/macro_targets.py` | Parses My Macros.md targets |
| `lib/nutrition_dashboard.py` | Dashboard generation logic |
| `lib/recipe_index.py` | Scans recipe files, returns frontmatter metadata for filtering |
| `lib/inventory.py` | Pantry inventory storage in `Inventory.md` (read/write/merge items) |
| `lib/seasonality.py` | Seasonal ingredient matching and scoring |
| `prompts/seasonal_matching.py` | Ollama prompt for fuzzy matching ingredients to seasonal produce |
| `config/seasonal_ingredients.json` | Texas seasonal produce calendar (~60 items) |
| `templates/meal_planner.html` | Interactive meal planner board (HTML/CSS/JS + SortableJS) |
| `mcp_server.py` | MCP server for Claude Desktop integration |
| `lib/mcp_tools.py` | MCP tool implementations (HTTP + Things) |
| `migrate_cuisine.py` | Cuisine cleanup, tag normalization & seasonal population |
| `lib/normalizer.py` | Controlled vocabularies and tag normalization |
| `lib/meal_suggester.py` | Ingredient overlap scoring + Claude/Ollama suggestion |
| `prompts/meal_suggestion.py` | Prompt templates for ingredient normalization and meal selection |
| `config/pantry_staples.json` | Flat keyword list — staples excluded from seasonal overlap scoring (NOT inventory) |
| `lib/meal_loader.py` | Read/write composite **meal** definitions (`vault/Meals/<Name>.meal.md`) |
| `lib/pantry.py` | Structured pantry inventory (`config/pantry.json`); split shopping demand against pantry; decrement on confirm |
| `lib/task_extractor.py` | Cross-recipe prep/active/passive task classification with sidecar cache (`<week>.tasks.json`) |
| `prompts/task_classification.py` | Prompt template for the task classifier |
| `config/pantry.json` | Structured pantry inventory: `[{item, amount, unit}, ...]` |

### Function Reference

There is no maintained function index — it drifts. To find a function, `grep -rn "def name" .` or read the module docstring. Most modules in `lib/` have docstrings explaining their role.

A few non-obvious invariants worth knowing:

- **Vault paths**: always go through `lib/paths.py` helpers (`vault_root()`, `recipes_dir()`, `meal_plans_dir()`, `meals_dir()`). Never hardcode.
- **Task IDs** (`lib/task_extractor.py`): `sha1(recipe|day|slot|step)[:12]` — stable across plan edits so `done` flags survive regeneration.
- **Pantry split** (`lib/pantry.py`): `split_against_pantry()` auto-converts within a unit family (e.g. tsp↔tbsp↔cup) but returns a `warning` on cross-family mismatch rather than guessing.
- **Composite meals** (`lib/meal_plan_parser.py`): `[[Meal: X]]` entries keep the meal name in the markdown; `flatten_to_recipes()` expands them downstream. Outer `xN` stacks with per-sub-recipe `servings` overrides.
- **Tasks cache freshness** (`lib/task_extractor.py`): sidecar is fresh when `sidecar_mtime >= plan_mtime`. Pass `force=True` to recompute.

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
  "meal_occasion": ["up to 3 strings - e.g. weeknight-dinner, grab-and-go-breakfast, meal-prep"],
  "dietary": ["array"],
  "equipment": ["array"],
  "ingredients": [{"amount": "number/string", "unit": "string", "item": "string", "inferred": boolean}],
  "instructions": [{"step": number, "text": "string", "time": "string or null"}],
  "storage": "string or null",
  "variations": ["array"],
  "seasonal_ingredients": ["array of matched seasonal produce names"],
  "peak_months": [1, 2, 3],
  "needs_review": boolean,
  "confidence_notes": "string"
}
```

### Seasonal Produce Config

**File:** `config/seasonal_ingredients.json`

Maps ~60 Texas produce items to peak month numbers (1-12). Used by `lib/seasonality.py` to score recipes by seasonal freshness. Region is Texas.

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
  - `NUTRITIONIX_APP_ID` - Nutritionix API app ID
  - `NUTRITIONIX_API_KEY` - Nutritionix API key
  - `ANTHROPIC_API_KEY` - Claude API for meal suggestions

## Dependencies

```
youtube-transcript-api    # Fetch video transcripts
google-api-python-client  # YouTube Data API
yt-dlp                    # Audio download for Whisper
openai                    # Whisper API transcription
python-dotenv             # Environment variables
requests                  # HTTP requests to Ollama
duckduckgo-search         # Web search for creator websites
anthropic                     # Claude API for meal suggestions
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
| New non-obvious invariant | CLAUDE.md → "Function Reference" bullets (only if it's load-bearing across modules; otherwise put it in the module docstring) |
| New `lib/` convention | `lib/CLAUDE.md` |
| Architecture change | CLAUDE.md → "Architecture" |
| New config option / model / API key | CLAUDE.md → "AI Configuration" or "Development Environment" |
| New constraint/gotcha | CLAUDE.md → "Constraints" or "Common Issues" |
| New API endpoint with non-obvious contract | CLAUDE.md → "Endpoints" (otherwise just add the route — `grep` will find it) |
| User-facing change | README.md → relevant section |
| Major feature complete | Future Enhancements → remove the row |
| Lessons learned | docs/IMPLEMENTATION_SUMMARY.md → "Lessons Learned" |

**Documentation standards:**
- Keep CLAUDE.md concise — it's loaded every session. **Do not add a function index.** Function listings drift; rely on docstrings + `grep`.
- Use tables for structured data.
- Include code examples for commands.
- Update the JSON schema if recipe structure changes.

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

| Feature | Priority | Notes |
|---------|----------|-------|
| Claude API fallback | Low | Use Claude when Ollama fails |
| Non-YouTube recipe URLs in `batch_extract` | Medium | Route non-YouTube URLs in "Recipies to Process" through `scrape_recipe_from_url()` (Serious Eats, NYT Cooking, etc.). Currently `batch_extract.py:212` rejects anything without youtube.com/youtu.be. Decide handling for plain-text notes (skip vs flag). |
| Inventory ↔ shopping list integration | Medium | Subtract on-hand inventory from generated shopping lists; add a "Restock" pass that auto-adds low-stock staples. |
| Email IMAP polling for receipts | Low | Currently the user pastes/forwards receipt content into Claude. IMAP would auto-ingest from HEB/Whole Foods/Instacart inboxes. |

## Documentation

| Document | Purpose |
|----------|---------|
| `README.md` | User guide - installation, usage, configuration |
| `docs/setup/iOS_SHORTCUT_SETUP.md` | iOS Shortcut configuration |
| `docs/setup/HOW_TO_RUN.md` | Quick start guide |
| `docs/IMPLEMENTATION_SUMMARY.md` | What was built vs planned, lessons learned |
| `docs/plans/` | Design documents and plans |

**Note:** The original design proposed n8n orchestration, but we built a simpler standalone Python solution. See `IMPLEMENTATION_SUMMARY.md` for details on this decision.
