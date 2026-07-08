# KitchenOS API Reference

The single canonical interface reference for KitchenOS: every Flask HTTP
route, every MCP tool, and the Siri/App Intents surface that sits on top of
them. Generated from the live code (`api_server.py`, `mcp_server.py`,
`lib/mcp_tools.py`, `KitchenOSKit/Sources/KitchenOSKit/Intents/`) — if a route
or tool is missing here, it's a bug in this doc, file a fix. For "what exists
and why" (pipeline flow, AI stack, background services) see
`docs/ARCHITECTURE.md`; for install/restart/deploy operations see
`docs/OPERATIONS.md`.

The API server is a synchronous Flask app (`api_server.py`), run as the
`com.kitchenos.api` LaunchAgent on port 5001, exposed over Tailscale at
`chases-mac-mini.taila69703.ts.net:5001`.

**Auth**: when `KITCHENOS_API_TOKEN` is set, remote (non-localhost) callers of
the token-gated routes below must send `Authorization: Bearer <token>`.
Localhost (the Mac app, local browser UI, MCP server, LaunchAgents) is always
exempt. Gated routes are marked **🔒** in the table.

## 1. HTTP endpoints

62 routes. Path | Method | Purpose.

| Path | Method | Purpose |
|------|--------|---------|
| `/transcript` | GET, POST | Fetch a YouTube video's transcript + description as one text blob (`{url}` body or `?url=`). Used by ad-hoc tooling, not the main pipeline. |
| `/health` | GET | Liveness check — `{"status": "ok"}`. |
| `/api/recipes` 🔒 | GET | Recipe metadata index for the meal-planner sidebar. `?ingredient=<term>` filters to recipes whose ingredient list contains the case-insensitive substring — backs the Siri "recipes with X" intent. Cached 5 min. |
| `/api/recipes/by-ingredients` 🔒 | POST | Rank recipes by ingredient overlap. Body `{ingredients: [str], limit?: int}` → `{matches: [{name, score, shared_ingredients}]}` (zero-overlap excluded). Reuses `meal_suggester` scoring. |
| `/api/recipes/save` | POST | Save a recipe from structured JSON (e.g. from a Claude conversation). Validates ingredients, matches seasonal produce, computes nutrition, writes the markdown file. Body must include `recipe_name`. |
| `/api/recipes/import-text` | POST | Parse a free-text recipe (`{text, title?, source?}`) with Ollama (un-gated) and save it like `/api/recipes/save`; original text preserved in a collapsible `## Import Source` block. Backs Selene's `/webhook/api/recipe` forward. |
| `/api/recipes/<name>` 🔒 | GET | Full recipe detail (frontmatter + parsed body) as JSON. |
| `/images/<path:filename>` | GET | Serve a recipe image from `Recipes/Images/` in the vault. |
| `/extract` | POST | Run full recipe extraction (`extract_recipe.py` subprocess) and save to Obsidian. Body `{url}`. **Returns `{"status": "success", "recipe": "<name>"}` on success — the key is `recipe`, not `recipe_name`.** |
| `/generate-shopping-list` | POST | Generate a shopping list markdown file from a meal plan. Body `{week}`. Preserves manually-added items already in the file. The Obsidian button calls this. |
| `/send-to-reminders` | POST | Push a week's unchecked shopping-list items to the Apple Reminders "Shopping" list. Body `{week}`. |
| `/calendar.ics` | GET | Serve the generated meal-plan ICS calendar file. |
| `/refresh-nutrition` | GET | Regenerate the nutrition dashboard for `?week=`. |
| `/refresh` | GET | Template refresh only — re-renders a recipe file (`?file=`) from its existing frontmatter/body against the current template. Does **not** re-fetch from YouTube; preserves `## My Notes`. |
| `/reprocess` | GET | Full re-extraction — re-fetches from YouTube via `source_url` and re-runs the whole pipeline (`?file=`). **Preserves the `## My Notes` section** by extracting it before re-extraction and re-injecting it into the new file. |
| `/api/meal-plan/<week>` 🔒 | GET | Meal plan as structured JSON (creates the week file from template if missing). |
| `/api/meal-plan/<week>` 🔒 | PUT | Save a meal plan from structured JSON `{days: [...]}`; round-trips through `rebuild_meal_plan_markdown`. |
| `/api/suggest-meal` 🔒 | POST | Suggest a recipe for an empty meal-plan slot by ingredient overlap (waste-aware — prioritizes at-risk inventory). Body `{week, day, meal, skip_index?}`. |
| `/add-to-meal-plan` | GET | Screen 1 of the recipe-button flow — renders the branch-picker form (`?recipe=`). |
| `/add-to-meal-plan` | POST | Screen 1 submit. Branches on `mode`: `direct` (schedule into a week/day/slot immediately), `existing` (append to an existing `vault/Meals/<name>.meal.md`), `new` (create a new meal), `schedule_meal` (screen 2 — schedule a just-created/updated meal). `existing`/`new` end on an optional schedule prompt. |
| `/meal-planner` | GET | Interactive drag-and-drop meal-planner board (HTML/JS UI). |
| `/current/meal-plan` | GET | Redirect to the current ISO week's meal plan note in Obsidian. |
| `/current/shopping-list` | GET | Redirect to the current ISO week's shopping list note in Obsidian. |
| `/api/meals` | GET | List composite meal bundles (`vault/Meals/*.meal.md`). |
| `/api/meals` | POST | Create a meal bundle. Body `{name, sub_recipes: [{recipe, servings}], description?, tags?}`. |
| `/api/meals/<name>` | GET | Get one meal bundle. |
| `/api/meals/<name>` | PUT | Update a meal bundle (rename, edit sub-recipes/description/tags). |
| `/api/meals/<name>` | DELETE | Delete a meal bundle. |
| `/api/pantry` | GET | Read the pantry adapter's item list (DB-backed, legacy JSON-shaped view). |
| `/api/pantry` | PUT | Overwrite the pantry item list. Body `{items: [...]}`. |
| `/api/shopping-list/preview` | POST | **Pantry-aware shopping list, step 1.** Body `{week, use_pantry?}` → per-line records split into `from_pantry` / `to_buy` against the current DB inventory. |
| `/api/shopping-list/confirm` | POST | **Pantry-aware shopping list, step 2.** Body `{week, items_to_buy, decisions?}` — saves the markdown shopping list and, if `decisions` present, decrements DB inventory accordingly (`pantry.apply_decisions`). |
| `/api/tasks/<week>` | GET | Cross-recipe prep-task sidecar payload (prep/active/passive classification) for the "Today's Prep" panel. `?force=1` bypasses the freshness cache. |
| `/api/tasks/<week>/<task_id>/done` | POST | Mark a prep task done/undone. Body `{done?: bool}` (default true). |
| `/api/inventory` | GET | List DB inventory items. `?category=&location=` filter. Each item carries a computed `expiry_status` (`expired`/`soon`/`ok`/`null`). Backs the native app's inventory cleanup screen. |
| `/api/use-it-up` | GET | Recipes ranked by how much expiring/at-risk inventory they use, to avoid waste. `?limit=` (default 10). Returns `{at_risk, suggestions}`; staples excluded, only the actionable expiry window considered. Backs the `use_it_up` MCP tool and the meal-planner "Use It Up" panel. |
| `/api/cook` | POST | Mark a recipe cooked: decrement its non-staple ingredients from inventory (true partial-package leftovers). Body `{recipe, servings?}` → consume summary. Optional/additive — inventory still self-cleans via expiry without it. Backs the `cook_recipe` MCP tool. |
| `/api/inventory/add` | POST | Add items to inventory. Body `{items: [...], trip?}`. Accepts optional per-item `unit_price`/`line_total` and an optional `trip` block (`{date, store, total, source_id, source}`) to also record into the price ledger. See "Receipt → Inventory Workflow" in `CLAUDE.md`. |
| `/api/inventory/paste` | POST | Bulk-add from a pasted markdown table. Body `{markdown, commit?}` — preview (default, no write) unless `commit: true`. |
| `/api/inventory/remove` | POST | Remove an item. Body `{name, location?}`. |
| `/api/inventory/update` | POST | Adjust an item's quantity. Body `{name, quantity, location?}`. |
| `/api/receipts/trips` 🔒 | GET | Recent shopping trips, newest first. |
| `/api/receipts/trips/<int:trip_id>` 🔒 | GET | One trip plus its purchase line items. |
| `/api/price/trends` 🔒 | GET | Structured price-tracker data (spending, by-category totals, item trends) — JSON projection of `Price Tracker.md`. |
| `/api/nutrition/<week>` 🔒 | GET | Structured nutrition dashboard for a week — JSON projection of `Nutrition Dashboard.md`. |
| `/api/system-health` | GET | System health JSON: Ollama, vault, recent recipes, run/failure logs, Reminders queue. |
| `/system-health` | GET | Interactive system health dashboard (HTML UI). |
| `/recipe/<name>` | GET | Interactive recipe detail page with live ingredient scaling (HTML UI). |
| `/nutrition-review` | GET | Human review UI for weak/unresolved nutrition matches (HTML). |
| `/api/nutrition-review/recipes` 🔒 | GET | Ranked queue of recipes needing nutrition review, worst first (lowest coverage, then lowest confidence). Frontmatter-only — fast. |
| `/api/nutrition-review/recipe/<name>` 🔒 | GET | Recompute one recipe's nutrition live (deterministic, no LLM) and return an audit-trail view with USDA candidates for weak/unresolved items. |
| `/api/nutrition-review/resolve` 🔒 | POST | Pin a human food match (or mark an item resolved-as-zero) so the nutrition engine's cache uses it on the next recompute. |
| `/api/nutrition-review/recompute` 🔒 | POST | Rerun the nutrition engine for one recipe file and persist + return the new summary. |
| `/api/week-board/<week>` 🔒 | GET | Serving-ledger board view of a week (`serving_ledger.week_board`) — cooks and their placements. |
| `/api/week-board/<week>/import-legacy` 🔒 | POST | One-time conversion of a hand-edited week into the serving ledger (`lib.week_view.import_legacy_week`). |
| `/api/cooks` 🔒 | POST | Create a cook — one preparation of a recipe at a fractional scale (serving ledger). |
| `/api/cooks/<int:cook_id>` 🔒 | PATCH | Update a cook (e.g. scale). |
| `/api/cooks/<int:cook_id>` 🔒 | DELETE | Delete a cook and its placements. |
| `/api/placements` 🔒 | POST | Create a placement — assign a cook's servings to a (destination, date, meal, count) slot. |
| `/api/placements/<int:pid>` 🔒 | PATCH | Update a placement. |
| `/api/placements/<int:pid>` 🔒 | DELETE | Delete a placement. |
| `/api/placements/<int:pid>/move` 🔒 | POST | Move a placement to a new destination/date/meal. |

## 2. MCP tools

15 tools, registered once in `mcp_server.py` (implementations in
`lib/mcp_tools.py`, which wraps the HTTP API above plus the Things 3 URL
scheme). All tools except `create_things_task` require the API server to be
running (`localhost:5001/health`); they return a fixed "API server is not
running" message otherwise.

### Recipes

| Tool | Signature | Purpose |
|------|-----------|---------|
| `extract_recipe` | `(url: str)` | Extract a recipe from a YouTube URL and save it. Calls `POST /extract`. |
| `save_recipe` | `(recipe_name, ingredients: list[dict], instructions: list[dict], description="", servings=4, cuisine=None, protein=None, dish_type=None, difficulty=None, prep_time=None, cook_time=None)` | Save a recipe that came up in conversation (not from YouTube). Calls `POST /api/recipes/save`. |
| `search_recipes` | `(query=None, cuisine=None, protein=None)` | Search the recipe library by name/cuisine/protein. Calls `GET /api/recipes` and filters client-side. |
| `get_recipe` | `(name: str)` | Full recipe details. Calls `GET /api/recipes/<name>`. |

### Meal plans

| Tool | Signature | Purpose |
|------|-----------|---------|
| `get_meal_plan` | `(week: str)` | View a week's meal plan. Calls `GET /api/meal-plan/<week>`. |
| `update_meal_plan` | `(week: str, days: list[dict])` | Modify a week's meal plan; each day has `breakfast`/`lunch`/`dinner`, each meal is `null` or `{name, servings}`. Calls `PUT /api/meal-plan/<week>`. |
| `generate_shopping_list` | `(week: str)` | Generate a shopping list from a meal plan. Calls `POST /generate-shopping-list`. |
| `send_to_reminders` | `(week: str)` | Push a shopping list to Apple Reminders. Calls `POST /send-to-reminders`. |

### Inventory

| Tool | Signature | Purpose |
|------|-----------|---------|
| `add_to_inventory` | `(items: list[dict], trip: dict = None)` | Batch add — items may carry optional `unit_price`/`line_total`; optional `trip` `{date, store, total, source_id, source}` records into the price ledger. Calls `POST /api/inventory/add`. |
| `list_inventory` | `(category: str = None, location: str = None)` | List items, with optional filters. Calls `GET /api/inventory`. |
| `remove_from_inventory` | `(name: str, location: str = None)` | Remove an item (used up). Calls `POST /api/inventory/remove`. |
| `update_inventory_item` | `(name: str, quantity: float, location: str = None)` | Adjust quantity (e.g. 0.5 for half-used). Calls `POST /api/inventory/update`. |

### Waste reduction / cooking

| Tool | Signature | Purpose |
|------|-----------|---------|
| `use_it_up` | `(limit: int = 10)` | Suggest recipes that use up food about to expire ("what can I make to use up what's expiring?"). Staples excluded. Calls `GET /api/use-it-up`. |
| `cook_recipe` | `(recipe: str, servings: float = 1.0)` | Mark a recipe cooked — subtracts its non-staple ingredients from inventory so partial-package leftovers stay accurate. Calls `POST /api/cook`. |

### Other

| Tool | Signature | Purpose |
|------|-----------|---------|
| `create_things_task` | `(title: str, notes: str = None)` | Create a Things 3 task via the `things:///add` URL scheme. Local-only, no API call. |

## 3. Siri / App Intents surface

Siri and Shortcuts entry points into KitchenOS, defined in
`KitchenOSKit/Sources/KitchenOSKit/Intents/`. Every intent routes through the
single shared `KitchenOSClient` (`KitchenOSKit/Sources/KitchenOSKit/KitchenOSClient.swift`
+ `+Meals`/`+Search`/`+MealPlanEdit`/`+Inventory`/`+Receipts`/`+System`
extensions) — iOS talks to the Tailscale hostname, macOS talks to localhost,
both overridable via `UserDefaults["kitchenos.baseURL"]`. When a bearer token
is configured (`CredentialStore`) it's attached automatically, matching the
`KITCHENOS_API_TOKEN` gating (🔒) on the server routes above. Write-capable
intents always call `requestConfirmation(actionName: .add, ...)` before
hitting a mutating endpoint — the app never writes to the meal plan without
an explicit Siri confirmation.

| Intent | Parameters | Backing endpoint(s) | Purpose |
|--------|-----------|----------------------|---------|
| `FindRecipesByIngredientIntent` | `ingredient: String` | `GET /api/recipes?ingredient=<term>` | "Find recipes with chicken" — substring match against each recipe's ingredient list. |
| `SmartFindRecipesIntent` | `query: String` (free-text mood/craving) | On-device `RecipeAI.parseQuery` (when Apple Intelligence is ready) then `GET /api/recipes?ingredient=`; falls back to the same endpoint directly (no smart parse) otherwise | "What can I make that's spicy and quick" — natural-language recipe search. |
| `GetMealPlanIntent` | `day: DayOfWeek?` (optional) | `GET /api/meal-plan/<week>` (current ISO week) | "What's for dinner this week / on Tuesday?" |
| `SuggestForMealPlanIntent` | `day: DayOfWeek?`, `meal: MealSlot?` (both optional — first empty slot if omitted) | `GET /api/meal-plan/<week>` then `POST /api/suggest-meal` | "Suggest something for Tuesday dinner" — waste-aware recipe suggestion for an empty slot. |
| `AddRecipeToMealPlanIntent` | `recipe: RecipeEntity`, `day: DayOfWeek`, `meal: MealSlot` | Read-modify-write: `GET /api/meal-plan/<week>` then `PUT /api/meal-plan/<week>` (no dedicated add endpoint) | "Add X to Thursday's dinner" — schedules a recipe into a plan slot, behind a Siri confirmation. |
| `GetRecipeNutritionIntent` | `recipe: RecipeEntity` | `GET /api/recipes/<name>` | "How many calories are in X" — reads `nutrition_calories`/`nutrition_protein`/etc. off the recipe detail response. |
| `SummarizeRecipeIntent` | `recipe: RecipeEntity` | `GET /api/recipes/<name>`, then on-device `RecipeAI.summarize` | On-device summary of a recipe's steps/ingredients — no separate summarization endpoint. |
| `AskKitchenOSIntent` | `request: String` (free-text, open-ended) | Indirect — delegates to `MealPlanAssistant`/`RecipeAI` (on-device LLM + tools), which itself calls into `KitchenOSClient`; any proposed write goes through the same read-modify-write `addRecipe`/`putMealPlan` path after a confirmation gate | Freeform natural-language entry point ("what should I make tonight", "add pasta to Friday"). |
| `OpenRecipeIntent` | `target: RecipeEntity` | None — pure in-app navigation via `RecipeRouter`, no HTTP endpoint | Opens a recipe directly in the app (e.g. tapping the indexed entity in Spotlight). |

`KitchenOSClient` also exposes `recipesByIngredients(_:limit:)` →
`POST /api/recipes/by-ingredients` and `inventoryItems()` → `GET /api/inventory`,
used by in-app UI (not currently wired to a dedicated Siri intent).

See `docs/superpowers/specs/2026-06-21-siri-app-intents-voice-design.md` for
the original design rationale and phrase catalogue.
