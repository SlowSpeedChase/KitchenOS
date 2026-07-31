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
YouTube/Instagram/web URL → extract_recipe.py
    ↓
main.py: route_url() picks the pipeline — 'instagram' → extract_single_instagram_recipe,
          'web' → extract_single_web_recipe, 'youtube' (also bare video IDs) →
          extract_single_recipe, which fetches metadata + transcript + first comment
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

The API is a **synchronous Flask app** (`api_server.py`) — roughly 60
`@app.route` handlers spanning recipe CRUD/extraction, meal plans, shopping
lists, inventory, receipts, the meal planner UI, the serving-ledger board
(`/api/cooks`, `/api/placements`, `/api/week-board/<week>`), the interactive
recipe detail page (`/recipe/<name>`, live ingredient scaling), and the
nutrition review UI (`/nutrition-review`, `/api/nutrition-review/*`), served
synchronously with no async framework or job-orchestration layer in front of
it. It runs as the `com.kitchenos.api` LaunchAgent on port 5001.
`/extract` and `/reprocess` subprocess out to `extract_recipe.py` (see
above) rather than running extraction in-process; most other routes read and
write the vault and `data/kitchenos.db` directly.

It is exposed off the Mac mini over **Tailscale**
(`chases-mac-mini.taila69703.ts.net:5001`) for remote callers — the iOS
Shortcut, MCP server, and the native app. When `KITCHENOS_API_TOKEN` is set,
remote (non-localhost) callers of the Siri-facing endpoints (`/api/recipes`,
`/api/recipes/<name>`, `/api/meal-plan/<week>`, `/api/suggest-meal`) must
send `Authorization: Bearer <token>`; localhost is always exempt.

The browsable pages are phone-first, reached over the tailnet from an iPhone.
Two modules serve that:

- **`lib/kitchen_today.py`** — the `/` home page's live state. It computes four
  cards (cookable now, recently added, expiring, the week's plan), each a fact
  that doubles as a workflow entry point. It exists because the home page's job
  is *recall*: a directory of page names cannot remind you a feature exists.
  It loads the inventory and recipe index once and injects them into `cook_now`
  and `use_it_up`, which each re-parse the whole recipe library when called
  bare. Every card is computed under a `_safe` wrapper and degrades to a plain
  link, so no single failing query can take the home page down.
- **`lib/note_view.py`** — renders the generated meal-plan and shopping-list
  notes as HTML for `/current/*`. Deliberately **not** a general Markdown
  renderer: it handles only the syntax those two generators emit, because
  adding a Markdown dependency to display two files we write ourselves is a bad
  trade in a project with one runtime dependency. Unknown syntax falls through
  as escaped text rather than vanishing.

Styling comes from `static/tokens.css`, a **copy** of the personal design
language in `~/Dev/design-system` (Ink dark / Dawn light, KitchenOS's accent is
coral). Vendored, like everything in `static/`, because these pages are opened
over a private tailnet from devices that may have no route to the internet.

For the full route list and per-route contracts, see `docs/API.md`.

## Background services

Nine LaunchAgents (`ops/com.kitchenos.*.plist`) run the recurring jobs, each
as its own scheduled Python (or shell) process — none of this is a
queue/worker system. Each plist's `ProgramArguments[0]` is a descriptively
named launcher shim in `ops/agents/` rather than the interpreter itself, so
macOS's Background App Activity list identifies them individually instead of
showing nine rows called `python` (see `docs/OPERATIONS.md` §2).
Python services self-rename their process title via
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
exist anymore. Core tables:

| Table | Notes |
|---|---|
| `trips` | One row per receipt (email, photo, manual, CSA). `source_id` UNIQUE drives ingest dedup. |
| `purchases` | Append-only price ledger, one row per line item, integer-cents money columns. `category='fee'` rows (tax, totes, tips) count toward spending but never touch inventory. |
| `inventory` | Current on-hand stock. Merge key is `(name, unit, location)` — case-insensitive UNIQUE; duplicate adds merge by summing quantity. |
| `cooks` | Serving-ledger (`lib/serving_ledger.py`): one *cook* = one preparation of a recipe at a fractional `scale`, producing `servings_produced` servings. Also carries the post-eating verdict — `make_again` (NULL = not judged, distinct from 0 = never again) and `cook_note`. Verdicts attach to the cook, not the recipe: the same dish goes well one week and badly the next. |
| `placements` | Where a cook's servings went — `(cook_id, destination, date, meal, count)` rows. Invariant: `SUM(placements.count) <= servings_produced`; the remainder is unplaced/leftover. |

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

**All five route through one placement router.**
`lib/storage_locations.place_item(name, category)` returns a `Placement` of
`(location, source)` — the location *and* which tier decided it: a hand-curated
`by_item` override, a `by_category` rule, or nothing (`default`).
`resolve_location()` is a thin wrapper for the callers that only want the
location. The tier is stored per row as `inventory.location_source`, so a
machine guess stays distinguishable from a placement the user confirmed; both
`/review` and the generated `Inventory.md` mark a `default` row as unsure. A
hand-correction (`move_item`, or a bulk move) stamps the row `manual` *and*
teaches `config/storage_locations.json`, so the same wrong guess stops
recurring — freezing deliberately teaches nothing, since it rescues one item
rather than declaring where that food lives. The table's path honours
`KITCHENOS_STORAGE_TABLE`, which is how the out-of-process e2e server avoids
writing the real config. Longest matching `by_item` key wins, because teaching
grows that table and a first-match would let a taught `milk` capture
`milk chocolate chips`.

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
  with or without it. Every ingredient lands in exactly one of four buckets —
  `consumed`, `use_recorded`, `not_tracked`, `skipped_staples`. Because
  inventory rows are *packages* rather than measured quantities, a cook may
  reduce a row but never delete one: a row at quantity `1.0`, a row summed
  across locations, or a weight/volume decrement that would zero the row out
  is use-stamped (`last_used`, `use_count`) instead. `use_recorded` is the
  dominant outcome by an order of magnitude, which is why every client must
  report all four buckets and not just `consumed`.
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
| `My Meal System.md` | Personal food/habit profile — health drivers, craving lanes, buffer menu, building blocks. Parsed by `lib/profile.py`; the prose is also fed verbatim to LLM prompts so new sections need no code change. |
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
- **Serving ledger & board mode** — `lib/serving_ledger.py` models a week as
  *cooks* (one preparation of a recipe at a fractional scale) and *placements*
  (where each cook's servings go: a date/meal slot, freezer, etc.), stored in
  the `cooks`/`placements` tables. The ledger is authoritative; `lib/week_view.py`
  regenerates the week's Markdown as a read-only Obsidian view after every
  mutation (weeks the ledger has never owned are left alone so legacy
  hand-edited plans still work). `import-legacy` converts a hand-edited week
  into the ledger once. Exposed via `/api/cooks`, `/api/placements`, and
  `/api/week-board/<week>`; driven by the planner board's serving chips,
  scale stepper, and freezer/trash targets.
- **Recipe detail page** — `/recipe/<name>` serves an interactive page with
  live ingredient scaling; the planner and Use-It-Up suggestions link into it.
- **Nutrition review** — `/nutrition-review` + `/api/nutrition-review/*` is a
  human review UI for weak/unresolved nutrition matches: a ranked queue
  (worst coverage/confidence first), live deterministic recompute with USDA
  candidates, and human match pinning that the engine's cache honors on the
  next recompute.
