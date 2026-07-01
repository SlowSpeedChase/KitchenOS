# End-to-End Workflow

How KitchenOS actually works today, stage by stage. Written as a snapshot of the wired-up system — if you change something, update this doc.

Stages: **Capture → Plan → Shop → Prep → Cook → Review.**

---

## Before you start: make sure the server is up

Everything routes through the API server. Confirm it's alive:

```bash
curl http://localhost:5001/health
```

If it doesn't respond, restart it:

```bash
launchctl load ~/Library/LaunchAgents/com.kitchenos.api.plist
```

---

## 0. The vault

Everything is markdown in the Obsidian vault (`~/Dev/KitchenOS/vault/KitchenOS/`, set via `KITCHENOS_VAULT` in `.env`). Folders that matter:

| Folder / file | What lives here |
|---|---|
| `Recipes/` | One markdown file per recipe (frontmatter + body) |
| `Recipes/Images/` | Recipe images (downloaded thumbnails or scraped hero shots) |
| `Meals/` | Composite-meal definitions (`<Name>.meal.md` — frontmatter lists `sub_recipes`) |
| `Meal Plans/` | One file per ISO week (`2026-W18.md`) |
| `Meal Plans/<week>.tasks.json` | Sidecar cache for the prep-task panel |
| `Shopping Lists/` | One markdown checklist per week |
| `Nutrition Dashboard/` | One per week |
| `Inventory.md` | Generated read-only view of the inventory DB (`data/kitchenos.db`) |
| `meal_calendar.ics` | All weeks merged into one calendar feed |

Plus repo data/config:
- `data/kitchenos.db` — unified inventory + price ledger (single source of truth for pantry stock; see Stage 3)
- `config/seasonal_ingredients.json` — Texas seasonal calendar
- `config/creator_websites.json` — YouTube channel → recipe site mapping

---

## 1. Capture — getting recipes into the vault

Five entry points, all converge on `extract_recipe.py` (or `import_crouton.py` for legacy imports). Output is always a recipe markdown file in `Recipes/`.

### 1a. iOS Share Sheet → API
- On iPhone, share a YouTube URL to the **KitchenOS Shortcut**.
- Shortcut hits the API server at `http://chases-mac-mini.taila69703.ts.net:5001/extract` (Tailscale).
- API spawns `extract_recipe.py` as a subprocess (5-min timeout) and returns `{status, recipe}` on success.
- Shortcut shows a success card linking to the new recipe in Obsidian.

### 1b. iOS Reminders → batch extract (LaunchAgent)
- Drop YouTube links into the **"Recipies to Process"** Reminders list (typo intentional — that's the actual list name).
- `com.kitchenos.batch-extract` runs every hour at :10, polls Reminders, extracts each link, and marks the reminder complete on success. An uncompleted reminder means the extraction failed — check `failures/` for details.
- Failures land in `failures/YYYY-MM-DD-HHMMSS.json`; `scripts/analyze_failures.sh` triggers a Claude Code background analysis for non-transient errors.

### 1c. Claude Desktop / web → MCP
- In a Claude conversation, paste a recipe (or a screenshot, or "save this from our chat").
- Claude calls the `save_recipe` MCP tool → `POST /api/recipes/save` writes the markdown.
- Same path for `extract_recipe(url)` — Claude asks the API to run extraction.

### 1d. CLI (manual)
```bash
.venv/bin/python extract_recipe.py "https://youtube.com/watch?v=..."
.venv/bin/python extract_recipe.py --dry-run "..."   # preview, no write
```

### 1e. Native app (Siri / App Intents)
- The native `KitchenOSSiri` app (iOS 26 / macOS 26 — `KitchenOSKit` + `KitchenOSSiri`) is a first-class capture *and* query surface, not just a Shortcut wrapper. Its own **Extraction** screens let you capture a recipe directly in-app, and its registered `AppShortcutsProvider` exposes Siri/App Intents for hands-free capture and lookup ("find recipes with chicken," "what's for dinner Tuesday," "add X to Thursday's dinner").
- Every intent routes through the shared `KitchenOSClient` to the same Flask API (Tailscale hostname on iOS, localhost on macOS), with a bearer token attached automatically when `KITCHENOS_API_TOKEN` is configured. Write-capable intents require an explicit Siri confirmation before mutating the meal plan.
- Full intent table and backing endpoints: `docs/API.md` § 3.

### What extraction actually does
For each URL: fetch metadata + transcript + first comment → try recipe-link in description → try description-as-recipe → try comment → try creator's website → fall back to Ollama (`mistral:7b`) on the transcript. Then validate ingredients, match against the seasonal calendar, look up nutrition (Nutritionix → USDA → AI), download a hero image, render the template. The recipe markdown gets three Obsidian Buttons baked into the body: **Reprocess** (`/reprocess`), **Refresh template** (`/refresh`), and **Add to Meal Plan** (`/add-to-meal-plan` — see Stage 2c).

---

## 2. Plan — putting recipes onto a week

Three ways meals land on a meal plan. Output is always `Meal Plans/<week>.md` with `[[Recipe Name]]` wikilinks under each day's slots.

### 2a. Auto-generated empty template (LaunchAgent)
- `com.kitchenos.mealplan` runs daily at 6:00 AM.
- Creates an **empty** `Meal Plans/<week>.md` two weeks ahead so a blank slot is always waiting.
- Template has Mon–Sun rows with Breakfast / Lunch / Snack / Dinner / Notes.

### 2b. Meal planner web UI (the main interface)
- Open `http://localhost:5001/meal-planner` (or `100.103.114.106:5001` from iPad over Tailscale).
- Layout: **left sidebar** = recipe library with search box + filter chips (cuisine, protein, dietary, seasonal); **right grid** = 7-day × 4-slot board for the selected ISO week.
- Drag a recipe from the sidebar onto a slot → auto-saves via `PUT /api/meal-plan/<week>`.
- Week selector buttons jump weeks; URL is `?week=2026-W18` so refreshes stick.
- Empty slots have a **"suggest"** affordance → `POST /api/suggest-meal` ranks recipes by ingredient overlap with what's already on the plan + what's seasonal.
- Composite meals (`[[Meal: Salmon Dinner]]`) render as a single block; the parser keeps the meal name, and downstream consumers (shopping, nutrition, prep) flatten via `flatten_to_recipes()`.
- **Servings multiplier:** type `[[Recipe Name]] x2` to scale (the `xN` lives outside the wikilink so Obsidian links still resolve).

### 2c. Recipe-page button (Obsidian)
Each recipe markdown contains an **Add to Meal Plan** button (Obsidian Buttons plugin) that opens `http://chases-mac-mini.taila69703.ts.net:5001/add-to-meal-plan?recipe=<file>` in the browser. The form has three branches:

1. **Schedule directly** → pick week / day / slot → API inserts the wikilink into the meal plan.
2. **Add to existing meal** → pick a meal from `vault/Meals/` → API appends this recipe to that meal's `sub_recipes` and offers an optional "now schedule it" prompt.
3. **Create new meal** → name + recipes → API writes `vault/Meals/<Name>.meal.md` and offers the same schedule prompt.

This is the primary way to go from "I'm reading a recipe" to "this is in next week's plan" without leaving Obsidian.

---

## 3. Shop — week's plan to groceries

Always starts from a meal plan; ends in a `Shopping Lists/<week>.md` checklist plus (optionally) Apple Reminders.

### Pantry and Inventory — one unified store
- **`data/kitchenos.db`** — the single source of truth for what's in the kitchen. Receipts (email ingest or Claude photo parse, Stage 6) **increment** it; confirming a shopping list **decrements** it.
- **`Inventory.md`** — generated read-only view of the DB, rewritten on every inventory change. Hand edits are overwritten.

### The flow (UI)
1. From the meal planner, click **Shopping List** for the active week.
2. UI calls `POST /api/shopping-list/preview` → `lib/shopping_list_generator.py` collects all recipe ingredients across the week, aggregates likes, and splits each line against the inventory in `data/kitchenos.db`.
3. If any line has overlap with pantry, a **confirmation modal** appears: per line, "Use pantry" or "Buy fresh." Cross-unit-family conflicts surface as a `warning` instead of guessing (e.g. "need 2 cups, pantry has 8 oz").
4. Submit → `POST /api/shopping-list/confirm` → writes `Shopping Lists/<week>.md` and decrements the DB inventory for the items the user chose to pull from pantry.
5. Optional: click **Send to Reminders** → `POST /send-to-reminders` → AppleScript pushes unchecked items into the macOS "Shopping" Reminders list, which syncs to phone.

### The flow (CLI)
```bash
.venv/bin/python shopping_list.py                 # auto-detect current week
.venv/bin/python shopping_list.py --week 2026-W18
.venv/bin/python shopping_list.py --dry-run       # preview only
.venv/bin/python shopping_list.py --no-pantry     # ignore pantry split
.venv/bin/python shopping_list.py --clear         # clear Reminders first
```
When stdin is a TTY, the CLI prompts `[a]ll / [s]ome / [n]one` for each pantry-overlapping line. `--no-interactive` skips the prompt (assumes "buy fresh").

---

## 4. Prep — what to do today (and what to get ahead on)

The meal planner UI has a **Today's Prep** panel that shows up when the loaded week contains today's date.

- Source: `lib/task_extractor.py` walks every recipe in the week's plan and runs each instruction step through Claude (Haiku) — classified as **prep** / **active** / **passive**, with `time_minutes`, `can_do_ahead`, and `depends_on`.
- Cached as `Meal Plans/<week>.tasks.json` next to the plan; regenerated when the plan's mtime moves past the sidecar's. Force a rebuild with `?force=1` on `/api/tasks/<week>`.
- Task IDs are `sha1(recipe|day|slot|step)[:12]` — stable across plan edits, so the **done** checkbox state survives regeneration.
- The panel splits into two sections:
  - **Today** — tasks where `task.day == today's weekday`.
  - **Get ahead** — tasks for other days where `can_do_ahead == true`.
- Marking done → `POST /api/tasks/<week>/<task_id>/done` writes back to the sidecar.

Calendar reminders for prep ride along with the meal-plan calendar (Stage 5).

---

## 5. Cook — at the stove

- **Calendar** — `com.kitchenos.calendar-sync` runs daily at 6:05 AM, regenerating `meal_calendar.ics` from every meal plan. Apple Calendar (or Obsidian Full Calendar plugin) subscribes to `http://localhost:5001/calendar.ics`.
- **Re-render or re-extract** — the per-recipe buttons:
  - **Refresh template** (`/refresh`) — re-renders from existing extracted data. Use after editing the template.
  - **Reprocess** (`/reprocess`) — full re-extraction from YouTube. **Preserves the `## My Notes` section.** Use when the AI got something wrong.

---

## 6. Inventory & receipts (parallel track)

Not part of the linear cook flow, but feeds back into Stage 3 eventually.

1. Take a photo of a grocery receipt (or forward an HEB/Whole Foods email) and share with Claude Desktop.
2. Claude parses the receipt, normalizes cryptic line items (`GV WHL MLK 1G` → `Whole milk, 1 gal`), assigns category + location, and calls the `add_to_inventory` MCP tool.
3. MCP → `POST /api/inventory/add` → `lib/inventory.py` merges into the DB inventory by `(name, unit, location)`. Quantities sum on duplicates.
4. Inspect in Obsidian (`Inventory.md`, the generated view), or edit via MCP tools (`list_inventory`, `update_inventory_item`, `remove_from_inventory`).

`Inventory.md` is regenerated from `data/kitchenos.db` on every write — don't hand-edit it.

---

## 7. Review — nutrition dashboard

- `com.kitchenos.dashboard-update` runs daily (6:15 AM) and writes `Nutrition Dashboard/<week>.md`: per-day calorie/macro totals from the recipes on that week's plan, weighted by servings multipliers and meal expansion.
- Targets come from `My Macros.md` in the vault (parsed by `lib/macro_targets.py`).
- Manual rebuild: `.venv/bin/python generate_nutrition_dashboard.py --week 2026-W18`.

---

## Background services (reference)

All in `~/Library/LaunchAgents/` (copied from `ops/*.plist`).

| LaunchAgent | Schedule | What it does |
|---|---|---|
| `com.kitchenos.api` | Always on | Flask server on port 5001 — every UI, the Shortcut, and the native app's Siri/App Intents hit this |
| `com.kitchenos.batch-extract` | Hourly at :10 | Pulls YouTube URLs from "Recipies to Process" Reminders list, extracts each |
| `com.kitchenos.mealplan` | 06:00 daily | Creates the empty meal-plan template two weeks out |
| `com.kitchenos.calendar-sync` | 06:05 daily | Regenerates `meal_calendar.ics` |
| `com.kitchenos.dashboard-update` | 06:15 daily | Regenerates current week's nutrition dashboard |
| `com.kitchenos.cleanup-icloud-old` | Monthly | iCloud housekeeping (low-importance) |

Logs: `~/Dev/KitchenOS/logs/<service>.log`. Reload all: `scripts/reload_launch_agents.sh`.

---

## A typical week (the happy path)

1. **Sun evening** — open meal planner, drag 5–6 recipes onto the upcoming week from the sidebar (or use **suggest** for blank slots). Auto-saves as you go.
2. Click **Shopping List** → confirm pantry pulls in the modal → click **Send to Reminders**. Phone now has the grocery list.
3. **Mon morning** — receipt photo from Sunday's shop → share with Claude → `Inventory.md` updates.
4. **Each morning** — meal planner shows **Today's Prep** (e.g., "marinate chicken — 5 min, can do ahead"). Check off as you go.
5. **At the stove** — open the recipe on iPad. Calendar subscription has already put dinner on the calendar.
6. **End of week** — glance at the Nutrition Dashboard to see how the week landed against macro targets.

---

## When something is wrong

| Symptom | First thing to check |
|---|---|
| Recipe didn't extract | `failures/` for the latest JSON; `tail -f logs/batch_extract.log` |
| iOS Shortcut hangs | `curl http://localhost:5001/health`; restart `com.kitchenos.api` |
| Meal planner won't save | DevTools network tab — is `PUT /api/meal-plan/<week>` 200? |
| Shopping list missing items | Check `Meal Plans/<week>.md` parses cleanly via `lib/meal_plan_parser.py`; composite-meal expansion silent-fails on missing `Meals/<Name>.meal.md` |
| Today's Prep empty | Sidecar might be stale — append `?force=1` to `/api/tasks/<week>` |
| Reminders push did nothing | macOS Reminders permission for the API process; check `logs/server.log` |
| Server not responding | `launchctl load ~/Library/LaunchAgents/com.kitchenos.api.plist` |
