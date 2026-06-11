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
- **Obsidian Sync** - Vault uses Obsidian Sync (not iCloud); no spaces in path

## Key Paths

| Path | Purpose |
|------|---------|
| `/Users/chaseeasterling/KitchenOS/` | Project root |
| `.venv/` | Python virtual environment |
| `Recipes/` in Obsidian vault | Main recipe files (title case, e.g., `Butter Biscuits.md`) |
| `Recipes/Images/` in Obsidian vault | Recipe images (downloaded from source or YouTube thumbnail) |

**Obsidian Vault**: `~/KitchenOS/KitchenOS_Vault/` (configurable via `KITCHENOS_VAULT` env var; resolved by `lib/paths.py`)

## Running Commands

### Extract a Recipe (Primary Use)

```bash
cd /Users/chaseeasterling/KitchenOS
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

### Ingest Receipt Emails

```bash
# Fetch HEB receipt emails from Gmail, parse, record trip + inventory
.venv/bin/python ingest_receipts.py

# Preview without DB/inventory writes
.venv/bin/python ingest_receipts.py --dry-run

# Look further back than the default 14 days
.venv/bin/python ingest_receipts.py --since-days 30

# Parse a single local file instead of Gmail
.venv/bin/python ingest_receipts.py --file receipt.eml   # or .html
```

### Generate Price Dashboard

```bash
# Write Price Tracker.md to the vault root
.venv/bin/python generate_price_dashboard.py

# Print markdown without saving
.venv/bin/python generate_price_dashboard.py --dry-run
```

### Migrate Inventory to SQLite (One-Time)

```bash
# Preview legacy Inventory.md import
.venv/bin/python migrate_inventory_db.py --dry-run

# Import into data/kitchenos.db (refuses if inventory table already has rows)
.venv/bin/python migrate_inventory_db.py
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
3. `/api/shopping-list/confirm` saves the markdown and decrements the DB inventory (`data/kitchenos.db`).
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

## Receipt Ingest (LaunchAgent)

Ingests HEB receipt emails from Gmail hourly (at :25 past each hour). Parses with Ollama, records trips/purchases in `data/kitchenos.db`, updates inventory, then regenerates `Inventory.md` and `Price Tracker.md`.

### Management

```bash
# Install the LaunchAgent
cp ops/com.kitchenos.receipt-ingest.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.kitchenos.receipt-ingest.plist

# View logs
tail -f ~/GitHub/KitchenOS/logs/receipt_ingest.log

# Restart service
launchctl unload ~/Library/LaunchAgents/com.kitchenos.receipt-ingest.plist
launchctl load ~/Library/LaunchAgents/com.kitchenos.receipt-ingest.plist

# Test run manually
.venv/bin/python ingest_receipts.py
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
| `/api/inventory/add` (POST) | Accepts optional `trip` `{date, store, total, source_id, source}` + per-item `unit_price`/`line_total` → records into the price ledger. See "Receipt → Inventory Workflow". |
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

Inventory and price history live in one SQLite database: `data/kitchenos.db` (`lib/inventory_db.py`). `Inventory.md` at the vault root is a **generated read-only view** with a do-not-edit banner — it is rewritten on every inventory change; hand edits are overwritten.

Items enter via three paths:

1. **Email (automatic)** — the hourly receipt-ingest LaunchAgent fetches HEB receipt emails over IMAP (`GMAIL_ADDRESS` + `GMAIL_APP_PASSWORD` in `.env`; sender domains in `config/receipt_senders.json`), parses them with Ollama, and validates line totals against the receipt total (tolerance: max($1, 2%)). Pass → trip + purchases recorded, inventory updated. Fail → trip stored with `needs_review` + raw text, **no** inventory update; failures also logged via `lib/failure_logger`. Dedup is by Gmail Message-ID (`trips.source_id` UNIQUE; content-hash fallback). Raw receipt strings are canonicalized through `config/item_aliases.json` — a saved alias always wins over the model's suggestion, and the file is hand-correctable.
2. **Photo receipt (Claude)** — share a receipt photo with Claude (Desktop, web, or iOS Share Sheet). Claude parses the items, normalizes the cryptic receipt strings (e.g. `GV WHL MLK 1G` → `Whole milk, 1 gal`), assigns category/location, and calls `add_to_inventory` — optionally with per-item `unit_price`/`line_total` and a `trip` block so photo receipts feed the same price ledger.
3. **Manual** — `add_to_inventory` via MCP, or POST `/api/inventory/add` directly.

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
| `add_to_inventory(items, trip?)` | Batch add — items may carry optional `unit_price`/`line_total`; optional `trip` `{date, store, total, source_id, source}` records into the price ledger |
| `list_inventory(category?, location?)` | List items, with optional filters |
| `remove_from_inventory(name, location?)` | Remove an item (used up) |
| `update_inventory_item(name, quantity, location?)` | Adjust quantity (e.g., 0.5 for half-used) |

### Storage

`data/kitchenos.db` (SQLite, WAL mode; override path with `KITCHENOS_DB`). Money columns are integer cents. Tables:

| Table | Notes |
|-------|-------|
| `trips` | One row per receipt; `source_id` UNIQUE drives ingest dedup |
| `purchases` | Append-only price ledger; `category='fee'` rows (tax, totes, tips) count toward spending but never touch inventory |
| `inventory` | Current stock; duplicate `(name, unit, location)` rows merge — quantities sum |

`Inventory.md` is regenerated from the DB on every write — items sorted by category then name.

### Price Tracker

`generate_price_dashboard.py` writes `Price Tracker.md` at the vault root: spending for the last 4 weeks, by-category totals for the last 12 months, average trip cost, top-20 item price trends vs 90-day average (▲/▼), collapsible per-item price history, and a needs-review list. Regenerated automatically after each successful email ingest.

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
| `lib/inventory.py` | DB-backed inventory operations; regenerates the read-only `Inventory.md` view |
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
| `lib/pantry.py` | Pantry adapter over the DB inventory table; split shopping demand against pantry; decrement on confirm |
| `lib/task_extractor.py` | Cross-recipe prep/active/passive task classification with sidecar cache (`<week>.tasks.json`) |
| `prompts/task_classification.py` | Prompt template for the task classifier |
| `ingest_receipts.py` | Hourly email receipt ingestion (IMAP fetch → Ollama parse → ledger + inventory) |
| `lib/inventory_db.py` | SQLite store (`data/kitchenos.db`): trips, purchases ledger, inventory |
| `lib/receipt_parser.py` | Receipt email HTML → text → Ollama extraction → line-total validation |
| `lib/email_fetcher.py` | Gmail IMAP fetcher for receipt emails (read-only mailbox) |
| `lib/item_aliases.py` | Raw receipt string → canonical item name cache |
| `lib/price_dashboard.py` | Price Tracker dashboard generation from the purchases ledger |
| `generate_price_dashboard.py` | CLI — writes `Price Tracker.md` to the vault root |
| `prompts/receipt_extraction.py` | Ollama prompt for structured receipt extraction |
| `config/receipt_senders.json` | Receipt sender domains per store (HEB) |
| `config/item_aliases.json` | Saved receipt-string aliases (hand-correctable; alias wins over model) |
| `migrate_inventory_db.py` | One-time import of legacy `Inventory.md` into the DB |

### Function Reference

There is no maintained function index — it drifts. To find a function, `grep -rn "def name" .` or read the module docstring. Most modules in `lib/` have docstrings explaining their role.

A few non-obvious invariants worth knowing:

- **Vault paths**: always go through `lib/paths.py` helpers (`vault_root()`, `recipes_dir()`, `meal_plans_dir()`, `meals_dir()`). Never hardcode.
- **Task IDs** (`lib/task_extractor.py`): `sha1(recipe|day|slot|step)[:12]` — stable across plan edits so `done` flags survive regeneration.
- **Pantry split** (`lib/pantry.py`): `split_against_pantry()` auto-converts within a unit family (e.g. tsp↔tbsp↔cup) but returns a `warning` on cross-family mismatch rather than guessing.
- **Composite meals** (`lib/meal_plan_parser.py`): `[[Meal: X]]` entries keep the meal name in the markdown; `flatten_to_recipes()` expands them downstream. Outer `xN` stacks with per-sub-recipe `servings` overrides.
- **Tasks cache freshness** (`lib/task_extractor.py`): sidecar is fresh when `sidecar_mtime >= plan_mtime`. Pass `force=True` to recompute.
- **Inventory/pantry truth** (`lib/inventory_db.py`): lives in `data/kitchenos.db` — `Inventory.md` is a generated view and `config/pantry.json` is gone. Money columns are integer cents; `trips.source_id` UNIQUE drives ingest dedup; DB path overridable via `KITCHENOS_DB` (tests use this).

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
  - `GMAIL_ADDRESS` - Gmail account for receipt-email ingestion
  - `GMAIL_APP_PASSWORD` - Google app password for IMAP (requires 2-step verification)

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
| Auto-restock for low staples | Medium | Pantry subtraction from shopping lists now works via the unified inventory DB; remaining idea is a "Restock" pass that auto-adds low-stock staples. |
| Serving size correction | Medium | Workflow to correct `servings: null` on existing recipes; affects per-serving accuracy of backfilled nutrition. |

## Documentation

| Document | Purpose |
|----------|---------|
| `README.md` | User guide - installation, usage, configuration |
| `docs/setup/iOS_SHORTCUT_SETUP.md` | iOS Shortcut configuration |
| `docs/setup/HOW_TO_RUN.md` | Quick start guide |
| `docs/IMPLEMENTATION_SUMMARY.md` | What was built vs planned, lessons learned |
| `docs/plans/` | Design documents and plans |

**Note:** The original design proposed n8n orchestration, but we built a simpler standalone Python solution. See `IMPLEMENTATION_SUMMARY.md` for details on this decision.
