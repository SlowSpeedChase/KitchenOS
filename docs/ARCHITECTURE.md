# KitchenOS Architecture

KitchenOS is a local-first kitchen operating system: a synchronous Flask API
(port 5001, run as the `com.kitchenos.api` LaunchAgent on the Mac mini) sits in
front of an Obsidian vault and a SQLite database, with a native iOS 26 /
macOS 26 app (`KitchenOSKit` + `KitchenOSSiri`) as the on-device client. AI is
hybrid, not a single model: local Ollama (`mistral:7b`) handles recipe
extraction, nutrition resolution, and seasonal matching; the Claude API is
load-bearing for receipt parsing and meal suggestions/resolvers/tasks when
`ANTHROPIC_API_KEY` is set; OpenAI Whisper is the transcript fallback; and the
native app additionally uses on-device Apple Foundation Models. This document
is the "what exists" reference — for the full route/tool list see
`docs/API.md`, and for install/restart/deploy operations see
`docs/OPERATIONS.md`.

## Extraction pipeline

Recipe extraction is a synchronous, single-process pipeline invoked from the
CLI (`extract_recipe.py`) — the `/extract` and `/reprocess` API routes do
**not** run this in-process; they `subprocess` out to `extract_recipe.py` and
return once it exits. Flow:

```
YouTube/Instagram URL → extract_recipe.py
    ↓
main.py (fetch metadata + transcript + first comment; Instagram routes via
          instagram_parser to extract_single_instagram_recipe)
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
calculate_recipe_nutrition() (nutrition_engine: resolve food → grams → per_100g×grams/100)
    ↓
download_image() (website image or YouTube thumbnail → Recipes/Images/)
    ↓
template → Obsidian markdown file
```

Transcript fetch falls back YouTube captions → Whisper (`OPENAI_API_KEY`) →
description-only if both fail. Instagram Reels get metadata + audio via
`yt-dlp` and feed the caption + a Whisper transcript to the same pipeline.
`batch_extract.py` (the hourly LaunchAgent) drives this same pipeline in bulk
from an iOS Reminders list, not through the API.

## Web/API tier

The API is a **synchronous Flask app** (`api_server.py`) — roughly 50
`@app.route` handlers spanning recipe CRUD/extraction, meal plans, shopping
lists, inventory, receipts, and the meal planner UI, served synchronously
with no async framework or job-orchestration layer in front of it. It runs
as the `com.kitchenos.api` LaunchAgent on port 5001.
`/extract` and `/reprocess` subprocess out to `extract_recipe.py` (see
above) rather than running extraction in-process; most other routes read and
write the vault and `data/kitchenos.db` directly.

It is exposed off the Mac mini over **Tailscale**
(`chases-mac-mini.taila69703.ts.net:5001`) for remote callers — the iOS
Shortcut, MCP server, and the native app. When `KITCHENOS_API_TOKEN` is set,
remote (non-localhost) callers of the Siri-facing endpoints (`/api/recipes`,
`/api/recipes/<name>`, `/api/meal-plan/<week>`, `/api/suggest-meal`) must
send `Authorization: Bearer <token>`; localhost is always exempt.

For the full route list and per-route contracts, see `docs/API.md`.

## Background services

Seven LaunchAgents (`ops/com.kitchenos.*.plist`) run the recurring jobs, each
as its own scheduled Python (or shell) process — none of this is a
queue/worker system. Python services self-rename their process title via
`setproctitle`, so `pgrep -f <script>.py` no longer matches after startup;
search for `kitchenos-*` instead.

| LaunchAgent | Responsibility |
|---|---|
| `com.kitchenos.api` | Runs `api_server.py` — the always-on Flask API (port 5001) |
| `com.kitchenos.batch-extract` | Hourly (:10) — extracts YouTube/Instagram/web URLs from the "Recipies to Process" Reminders list |
| `com.kitchenos.calendar-sync` | Daily 6:05am — regenerates the ICS meal calendar from meal plans |
| `com.kitchenos.cleanup-icloud-old` | Housekeeping — prunes stale iCloud/backup artifacts |
| `com.kitchenos.dashboard-update` | Regenerates the nutrition/price dashboards |
| `com.kitchenos.mealplan` | Daily 6am — generates weekly meal plan templates 2 weeks ahead |
| `com.kitchenos.receipt-ingest` | Hourly (:25) — fetches receipt/CSA emails, parses, updates the inventory DB |

Install/restart/log commands and full detail live in `docs/OPERATIONS.md`.

## Data model — SQLite as single source of truth

`data/kitchenos.db` (SQLite, WAL mode; override with `KITCHENOS_DB`; accessed
only through `lib/inventory_db.py`) is the **single source of truth** for
inventory and price history. `config/pantry.json` is gone — it does not
exist anymore. Three core tables:

| Table | Notes |
|---|---|
| `trips` | One row per receipt (email, photo, manual, CSA). `source_id` UNIQUE drives ingest dedup. |
| `purchases` | Append-only price ledger, one row per line item, integer-cents money columns. `category='fee'` rows (tax, totes, tips) count toward spending but never touch inventory. |
| `inventory` | Current on-hand stock. Merge key is `(name, unit, location)` — case-insensitive UNIQUE; duplicate adds merge by summing quantity. |

`Inventory.md`, `Price Tracker.md`, and `Use It Up.md` at the vault root are
**generated, read-only views** rewritten from the DB on every relevant
change (do-not-edit banners included) — the DB, not the markdown, is
authoritative. Hand edits to those files are silently overwritten on the
next regeneration.

## Receipt → inventory

Items enter inventory via five paths, condensed from `CLAUDE.md`'s
"Receipt → Inventory Workflow":

1. **Email (automatic)** — hourly `receipt-ingest` LaunchAgent fetches HEB
   receipt emails over IMAP, parses with the Claude API
   (`lib/receipt_parser.py`, Opus when `ANTHROPIC_API_KEY` is set else
   Ollama fallback), validates line totals, records trip + purchases, and
   updates inventory. Dedup by Gmail Message-ID.
2. **CSA newsletter (automatic)** — `ingest_csa.py` (run at the tail of the
   hourly receipt ingest) parses the weekly Central Texas Farmers Co-op
   "Week N(A/B)" newsletter deterministically and adds the subscriber's
   tier/week produce with `source="csa"`, `purchased` rolled to the
   Wednesday pickup.
3. **Photo receipt (Claude)** — a shared receipt photo is parsed by Claude,
   normalized, and posted through `add_to_inventory` — optionally with a
   `trip` block so photo receipts feed the same price ledger.
4. **Manual** — `add_to_inventory` via MCP, or `POST /api/inventory/add`
   directly.
5. **Markdown paste** — a pasted markdown table is preview-then-committed via
   `lib/receipt_paster.py` / `POST /api/inventory/paste`.

**Design principle — additive, not another chore.** Inventory must never
become something the user has to maintain:
- **Auto-add, auto-age-out.** Items enter automatically from receipts;
  expired perishables prune themselves on the daily meal-plan run (assumed
  used/tossed) — no manual "I used this" step.
- **Staples are assumed, never tracked.** `config/pantry_staples.json` items
  are treated as always-on-hand and excluded from waste flagging.
- **Consume-on-cook is optional.** `lib/cook.py` / `POST /api/cook` can
  decrement a cooked recipe's non-staple ingredients for true
  partial-package leftover tracking, but inventory self-cleans on expiry
  with or without it.
- **The plan itself fights waste.** The interactive suggester
  (`lib/meal_suggester.py`) ranks recipes by how much at-risk (expiring)
  inventory they use first, so waste-relevant recipes surface without an
  LLM tiebreak.

## Vault taxonomy

The Obsidian vault is resolved via `lib/paths.py` (`vault_root()` and
friends), driven by the `KITCHENOS_VAULT` environment variable — every path
in the codebase must go through these helpers, never a hardcoded path.
`lib/paths.py` ships a fallback default for the case where `KITCHENOS_VAULT`
is unset, but that default is not meaningful for this deployment; treat
`KITCHENOS_VAULT` as required in practice. Vault structure:

| Path | Contents |
|---|---|
| `Recipes/` | Recipe markdown files, title-case filenames |
| `Recipes/Images/` | Downloaded recipe images (source page or YouTube thumbnail) |
| `Meals/` | Composite meal definitions (`<Name>.meal.md`) |
| `Meal Plans/` | Weekly plan files (`YYYY-Www.md`) + generated `Meal Plans Index.md` |
| `My Macros.md` | User's nutrition targets, parsed by `lib/macro_targets.py` |
| `Inventory.md` | Generated, read-only view of `data/kitchenos.db` inventory |
| `Use It Up.md` | Generated, read-only waste-reduction suggestions |
| `Price Tracker.md` | Generated, read-only spending/price-trend dashboard |

## MCP server

`mcp_server.py` (tool implementations in `lib/mcp_tools.py`) exposes
KitchenOS to Claude Desktop over MCP, calling the same Flask API rather than
touching the vault/DB directly — so it requires `com.kitchenos.api` to be
running. Tool list and contracts live in `docs/API.md`.

## Native app tier

The native client is a single Xcode project (`project.yml`, XcodeGen)
building two products from shared code:

- **`KitchenOSKit`** — a shared Swift Package (`Sources/KitchenOSKit`) with
  `Intents/` (App Intents surfacing recipes, meal plans, inventory, etc. to
  the system) and `AI/` (Apple Foundation Models integration: `RecipeAI`,
  `MealPlanAssistant`, and tool-calling wrappers like `SuggestMealTool`,
  `FindRecipesTool`, `AddToMealPlanTool`, `CookWithIngredientsTool`), plus
  the API client and models.
- **`KitchenOSSiri`** — the app target, feature-organized under `Sources/`
  (`Recipes`, `MealPlan`, `Shopping`, `Inventory`, `Nutrition`, `Tasks`,
  `Receipts`, `Meals`, `SystemHealth`, `Extraction`, `Shell`, `Components`).
  `Shell/AppShell.swift` branches `#if os(macOS)` for a sidebar layout vs.
  `#else` for an iOS `TabView`.

`supportedDestinations: [macOS, iOS]` with `deploymentTarget` iOS 26 /
macOS 26. The app registers `AppShortcutsProvider` (`KitchenOSShortcuts`)
for Siri/Shortcuts, uses on-device Foundation Models for the AI layer, and
indexes content via CoreSpotlight (`RecipeIndexer`). This tier is converged
on `main` (the historical iOS-Siri vs. macOS-extraction branch split has
been merged).

Build/sign/deploy commands live in `docs/OPERATIONS.md`; how the app
connects to the Mac mini API (base URL, Tailscale, bearer token) is covered
in `docs/setup/`.

## Feature semantics

- **Servings multiplier** — `[[Recipe Name]] x2` in a meal plan; the `xN`
  sits outside the wiki-link so Obsidian resolution still works. Scales
  nutrition dashboard calculations and shopping-list ingredient quantities.
- **Composite meals** — `[[Meal: Salmon Dinner]]` references a bundle
  defined in `vault/Meals/<Name>.meal.md` (frontmatter `sub_recipes`).
  `flatten_to_recipes()` expands meals downstream for shopping lists,
  nutrition, and tasks; outer `xN` stacks with each sub-recipe's own
  `servings` override.
- **Pantry-aware shopping list** — `POST /api/shopping-list/preview` splits
  each shopping-list line into `from_pantry` / `to_buy`; the UI confirms
  any pantry-overlapping line; `POST /api/shopping-list/confirm` saves the
  markdown and decrements DB inventory accordingly.
- **Cross-recipe prep tasks** — `lib/task_extractor.py` classifies each
  scheduled recipe's instructions into prep/active/passive with
  do-ahead/dependency flags, cached in a `<week>.tasks.json` sidecar. The
  meal-planner UI surfaces today's tasks plus a "Get ahead" section for
  upcoming do-ahead items, with `done` state stable across plan edits via
  hashed task IDs.
