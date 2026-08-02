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

76 routes. Path | Method | Purpose.

| Path | Method | Purpose |
|------|--------|---------|
| `/transcript` | GET, POST | Fetch a YouTube video's transcript + description as one text blob (`{url}` body or `?url=`). Used by ad-hoc tooling, not the main pipeline. |
| `/health` | GET | Liveness check — `{"status": "ok"}`. |
| `/api/recipes` 🔒 | GET | Recipe metadata index for the meal-planner sidebar. `?ingredient=<term>` filters to recipes whose ingredient list contains the case-insensitive substring — backs the Siri "recipes with X" intent. Cached 5 min. |
| `/api/recipes/by-ingredients` 🔒 | POST | Rank recipes by ingredient overlap. Body `{ingredients: [str], limit?: int}` → `{matches: [{name, score, shared_ingredients}]}` (zero-overlap excluded). Reuses `meal_suggester` scoring. |
| `/api/recipes/save` | POST | Save a recipe from structured JSON (e.g. from a Claude conversation). Validates ingredients, matches seasonal produce, computes nutrition, writes the markdown file. Body must include `recipe_name`. |
| `/api/recipes/import-text` | POST | Parse a free-text recipe (`{text, title?, source?}`) with Ollama (un-gated) and save it like `/api/recipes/save`; original text preserved in a collapsible `## Import Source` block. Backs Selene's `/webhook/api/recipe` forward. |
| `/api/recipes/<name>` 🔒 | GET | Full recipe detail (frontmatter + parsed body) as JSON. Each ingredient also carries `in_stock` and `have`: **`in_stock` is tri-state** — `true`/`false`, or **`null` when there was no inventory to check against** (empty pantry, or the DB wouldn't open), which clients must render as *unmarked* rather than as "you don't have it". `have` is the matched row (`"3 lb"`) or null. Matching is `pantry.find_match`, the same matcher the shopping list uses, so the two can't disagree. It reports **presence, not sufficiency** — the page scales 1x-4x, so a server-side "enough" would be wrong the moment the reader scales up. |
| `/images/<path:filename>` | GET | Serve a recipe image from `Recipes/Images/` in the vault. |
| `/extract` | POST | Run full recipe extraction (`extract_recipe.py` subprocess) and save to Obsidian. Body `{url}`. **Returns `{"status": "success", "recipe": "<name>"}` on success — the key is `recipe`, not `recipe_name`.** |
| `/generate-shopping-list` | POST | Generate a shopping list markdown file from a meal plan. Body `{week, use_pantry?}`. **Credits current inventory but never decrements it** — items you already own are kept off the buy list and named under an "Already have" section (plain bullets, never checkboxes: `parse_shopping_list_file` collects every `- [ ]` line in the file regardless of section, so a checkbox there would reach Reminders as something to buy and return as a phantom manual item). This is the one-shot trigger — the `/current/shopping-list` button, the only one reachable from a phone — so there's no confirmation step to authorise inventory writes; `/api/shopping-list/preview` → `/confirm` stays the only path that spends stock. `use_pantry: false` returns raw demand. Preserves manually-added items already in the file. The Obsidian button calls this. |
| `/send-to-reminders` | POST | Push a week's unchecked shopping-list items to the Apple Reminders "Shopping" list. Body `{week}`. Returns `{success, items_sent, items_skipped}`. Fired by the **Send to Reminders** button on `/current/shopping-list`. All items go over in **one** `osascript` call (~0.4s per Reminders round-trip, so the old item-at-a-time loop cost ~10s for a 24-item list), and the list is created if missing — no separate `create_reminders_list` call is needed. Item text is passed as `argv`, never interpolated into the AppleScript: these strings come from LLM-extracted ingredient lines, and a quote in one used to be able to close the string literal and get the remainder evaluated. |
| `/calendar.ics` | GET | Serve the generated meal-plan ICS calendar file. |
| `/refresh-nutrition` | GET | Regenerate the nutrition dashboard for `?week=`. |
| `/refresh` | GET | Template refresh only — re-renders a recipe file (`?file=`) from its existing frontmatter/body against the current template. Does **not** re-fetch from YouTube; preserves `## My Notes`. |
| `/reprocess` | GET | Full re-extraction — re-fetches from YouTube via `source_url` and re-runs the whole pipeline (`?file=`). **Preserves the `## My Notes` section** by extracting it before re-extraction and re-injecting it into the new file. |
| `/api/meal-plan/<week>` 🔒 | GET | Meal plan as structured JSON (creates the week file from template if missing). A `kind: "meal"` slot also carries `sub_recipes`, `slot` and a derived `nutrition` rollup **per 1× the bundle** — shipped here rather than left to the client's `/api/meals` fetch, because the planner loads meals and the plan concurrently and a card built from the plan can't assume the meal index is populated. |
| `/api/meal-plan/<week>` 🔒 | PUT | Save a meal plan from structured JSON `{days: [...]}`; round-trips through `rebuild_meal_plan_markdown`. |
| `/api/suggest-meal` 🔒 | POST | Suggest a recipe for an empty meal-plan slot. Ranks by, in priority order: at-risk inventory (waste), macro-gap fit (when `My Macros.md` targets exist — protein-weighted), then ingredient overlap. Body `{week, day, meal, skip_index?}`. A planned `[[Meal: X]]` bundle is flattened to its sub-recipes before ranking, so its ingredients and macros count toward the day (they used to count as zero).  Response `{suggestion, macro_context}`: `suggestion` carries `nutrition` (per-serving macros or null), `macro_fit` (0–1) and `nutrition_unknown` (true when the recipe's macros aren't trustworthy); `macro_context` is `{target, current, remaining, projected_with_suggestion}` for the day, or null when no targets are set. |
| `/add-to-meal-plan` | GET | Screen 1 of the recipe-button flow — renders the branch-picker form (`?recipe=`). |
| `/add-to-meal-plan` | POST | Screen 1 submit. Branches on `mode`: `direct` (schedule into a week/day/slot immediately), `existing` (append to an existing `vault/Meals/<name>.meal.md`), `new` (create a new meal), `schedule_meal` (screen 2 — schedule a just-created/updated meal). `existing`/`new` end on an optional schedule prompt. |
| `/meal-planner` | GET | Interactive drag-and-drop meal-planner board (HTML/JS UI). |
| `/current/meal-plan` | GET | The current ISO week's meal plan, rendered as HTML by `lib/note_view.py`. `?week=` overrides. Wikilinks become `/recipe/<name>` links; the note's dead `kitchenos://` button becomes a working HTTP one. Keeps an "Open in Obsidian" footer link. Was a 302 to `obsidian://`, which dead-ended on a phone. |
| `/current/shopping-list` | GET | The current ISO week's shopping list, rendered as HTML. `?week=` overrides. When no list exists yet, offers a **Generate shopping list** button that POSTs to `/generate-shopping-list` — the workflow's only phone-reachable trigger. Checkbox state is rendered read-only; the vault note stays the single source of truth. |
| `/api/meals` | GET | List composite meal bundles (`vault/Meals/*.meal.md`). Each carries `slot` and a derived `nutrition` rollup (see below). |
| `/api/meals` | POST | Create a meal bundle. Body `{name, sub_recipes: [{recipe, servings}], description?, tags?, slot?}`. `servings` is a **float** (1.5 splits a batch across meals) and must be > 0 — a non-positive or unparseable value is a 400. `slot` is one of `breakfast`/`lunch`/`snack`/`dinner`, defaulting to `dinner`; anything else is a 400. |
| `/api/meals/<name>` | GET | Get one meal bundle, with `slot` and `nutrition`. |
| `/api/meals/<name>` | PUT | Update a meal bundle (rename, edit sub-recipes/description/tags/slot). Same validation as POST, applied **before** a rename deletes the old file, so a rejected payload can't destroy the meal. Omitting `slot` keeps the stored one. |
| `/api/meals/<name>` | DELETE | Delete a meal bundle. |
| `/api/macro-targets` | GET | The daily macro target plus how it splits across slots: `{daily: {calories, protein, carbs, fat} \| null, slot_shares: {breakfast, lunch, snack, dinner}, slot_shares_normalized}`. `daily` is null when there's no `My Macros.md` — clients should then show no reference line rather than invent one. Shares come from the optional flat `share_<slot>` keys (defaults 0.25/0.30/0.35/0.10); when they don't sum to 1.0 within 1% they're rescaled proportionally and `slot_shares_normalized` is true so the UI can say so. |
| `/api/pantry` | GET | Read the pantry adapter's item list (DB-backed, legacy JSON-shaped view). |
| `/api/pantry` | PUT | Overwrite the pantry item list. Body `{items: [...]}`. |
| `/api/shopping-list/preview` | POST | **Pantry-aware shopping list, step 1.** Body `{week, use_pantry?}` → per-line records split into `from_pantry` / `to_buy` against the current DB inventory. |
| `/api/shopping-list/confirm` | POST | **Pantry-aware shopping list, step 2.** Body `{week, items_to_buy, decisions?}` — saves the markdown shopping list and, if `decisions` present, decrements DB inventory accordingly (`pantry.apply_decisions`). |
| `/api/tasks/<week>` | GET | Cross-recipe prep-task sidecar payload (prep/active/passive classification) for the "Today's Prep" panel. `?force=1` bypasses the freshness cache. |
| `/api/tasks/<week>/<task_id>/done` | POST | Mark a prep task done/undone. Body `{done?: bool}` (default true). |
| `/api/inventory` | GET | List DB inventory items. `?category=&location=` filter. Each item carries a computed `expiry_status` (`expired`/`soon`/`ok`/`null`), plus `location_source`, `last_used` and `use_count`. `location_source` records **how the row's `location` was decided**: `manual` (the user placed it, or supplied it explicitly in a request), `item` (a hand-curated `by_item` override matched), `category` (a `by_category` rule matched a real category), or `default` (nothing matched). Absent/NULL reads as `default`, and only `default` renders as unsure. `last_used`/`use_count` are written by consume-on-cook when a row is used but not safely decrementable. Backs the native app's inventory cleanup screen. |
| `/api/use-it-up` | GET | Recipes ranked by how much expiring/at-risk inventory they use, to avoid waste. `?limit=` (default 10). Returns `{at_risk, suggestions}`; staples excluded, only the actionable expiry window considered. Backs the `use_it_up` MCP tool and the meal-planner "Use It Up" panel. |
| `/api/cook-now` | GET | Recipes ranked by ingredient coverage against current inventory. `?limit=` (default 30). Returns `{"recipes": [{recipe, image, dish_type, group, have, total, coverage, missing, at_risk}]}`. `group` is the meal-type chip the recipe belongs to — one of `Mains`, `Breakfast`, `Sides`, `Snacks`, `Desserts`, `Drinks`. Filtering happens client-side on the `/cook-now` page; this endpoint never filters. |
| `/api/cook` 🔒 | POST | Mark a recipe cooked. Body `{recipe, servings?}` → `{recipe, consumed: [{item, unit, before, after, depleted}], use_recorded: [{item, unit}], not_tracked: [...], skipped_staples: [...]}`. Every ingredient lands in exactly one bucket. A row at quantity exactly `1.0` is a container: it is use-stamped (`last_used`, `use_count`) rather than decremented, so a recipe calling for three bay leaves cannot delete the jar. Optional/additive — inventory still self-cleans via expiry without it. Backs the `cook_recipe` MCP tool. |
| `/api/inventory/add` | POST | Add items to inventory. Body `{items: [...], trip?}`. Accepts optional per-item `unit_price`/`line_total` and an optional `trip` block (`{date, store, total, source_id, source}`) to also record into the price ledger. See "Receipt → Inventory Workflow" in `CLAUDE.md`. **`location` is how the caller declares provenance, so omit it unless the user actually chose the shelf.** A truthy `location` is taken as a placement the user confirmed and stamps `location_source: manual`; an absent (or falsy) one routes through `place_item` and records the real tier — `item`, `category`, or `default`, the last of which renders as unsure. A client that always sends a form default therefore records a confirmed placement that never happened and can never surface the `?` marker: the iOS app did exactly that until its Picker gained an **Auto** option (`NewInventoryItem.location` is `String?`, encoded by omission). Note the check is truthiness, not key presence, so `null` and `""` also route — but omit the key rather than leaning on that. |
| `/api/inventory/paste` | POST | Bulk-add from a pasted markdown table. Body `{markdown, commit?}` — preview (default, no write) unless `commit: true`. |
| `/api/receipt/paste` | POST | Ingest a photographed HEB receipt as pasted schema JSON (from the Claude iOS app). Body `{json, commit?}` — preview (default, no write) unless `commit: true`. Runs the full receipt pipeline via `lib/receipt_ingest.py` (trip + priced purchases + non-fee inventory, meal-plan recipe assignment); dedups on a content hash of the receipt. Response carries `mode` (`preview`/`committed`) and the engine `status` (`ingested`/`needs_review`/`skipped`). 400 on unparseable JSON. Un-gated (private tailnet, browser page sends no token) — matches `/api/inventory/paste`. |
| `/api/receipt/prompt` | GET | Plain-text prompt to paste (with a receipt photo) into the Claude iOS app; derived from `RECEIPT_SCHEMA` so it can't drift. Backs the "Copy prompt" button on `/receipt-paste`. |
| `/api/inventory/remove` | POST | Remove an item. Body `{name, location?}`. |
| `/api/inventory/update` | POST | Adjust an item's quantity. Body `{name, quantity, location?}`. |
| `/api/inventory/extend` | POST | Extend an item's expiry date. Body `{name, days, location?}` → **adds** `days` to the row's own expiry, so repeated calls accumulate. A row whose expiry has already lapsed (or is unset, or unparseable) counts from today instead, since adding to a stale date would leave it expired. Ungated. Returns `{status: "extended", item: {..., expiry_status}}` on success; `400` if name/days missing or days not int-coercible; `404` if no matching row. |
| `/api/inventory/set-expiry` | POST | Set an item's expiry to an absolute date, or clear it. Body `{name, expires: "YYYY-MM-DD" \| null, location?}`. Ungated. Returns `{status: "expiry_set", item: {..., expiry_status}}`; `400` if `name`/`expires` missing (send `expires: null` to clear) or `expires` is neither string nor null; `404` if no matching row. |
| `/api/inventory/set-category` | POST | Change an item's category. Body `{name, category, location?}` — `category` is normalized against the `CATEGORIES` vocab (unknown → `other`). Ungated. Returns `{status: "category_set", item}`; `400` if `name`/`category` missing; `404` if no matching row. |
| `/api/inventory/move` | POST | Move an item to a new location. Body `{name, to_location, location?}` — `location` is the current-row match filter, `to_location` the destination (normalized against `LOCATIONS`). If a row already exists at the destination with the same `(name, unit)`, quantities are summed and the source row dropped. Ungated. Returns `{status: "moved", item}`; `400` if `name`/`to_location` missing; `404` if no matching row. |
| `/api/inventory/freeze` | POST | Mark an item as frozen — moves it to the `freezer` location, sets `category=frozen`, and clears its expiry (freezing stops the clock). Body `{name, location?}`. Merges into an existing freezer row like `/move`. Ungated. Returns `{status: "frozen", item}`; `400` if `name` missing; `404` if no matching row. |
| `/api/inventory/bulk` | POST | Apply one action to many items in a single read-modify-write, instead of N round trips. Body `{action, refs, days?, expires?, category?, to_location?}` — `action` is one of `remove`, `extend`, `set-expiry`, `set-category`, `move`, `freeze`; `refs` a non-empty list of `{name, unit, location}`; action params are `days` (extend), `expires` (set-expiry, nullable), `category`, `to_location`. `extend` is cumulative and computed **per row** — each selected row advances from its own expiry (or from today if lapsed/unset), so a staggered selection stays staggered rather than collapsing onto one shared date. **Addresses rows by the true `(name, unit, location)` uniqueness key**, unlike the single-item routes above, which match on `(name, location)` and can therefore hit the wrong row when one name repeats across units. Ungated. Returns `{status: "applied", applied, items, removed, not_found}` — `applied` is how many refs matched a row, `items` the resulting rows (empty for `remove`, each shaped like the single-item routes' `item` including `expiry_status`), `removed` the full pre-delete rows (empty except for `remove`; replayable into `/api/inventory/add` as an undo), `not_found` the refs that matched nothing. A non-empty `not_found` does **not** fail the call — a client working from a stale list must not lose the edits that did land. `400` on unknown/missing `action`, empty `refs`, a ref missing any of `name`/`unit`/`location`, or a missing action parameter. `move` and `freeze` may merge rows: a colliding `(name, unit)` at the destination sums quantities, and two *selected* rows moving to the same destination merge into each other — so `items` can be shorter than `applied`. |
| `/api/claude-notes` | GET | Read the shared `Claude Notes.md` (vault root) that seeds a `claude` launch. Returns `{notes: "<body>"}` (empty string if the file doesn't exist yet). Ungated — backs the notes textarea in the launch bar on every web page. |
| `/api/claude-notes` | POST | Save the shared `Claude Notes.md`. Body `{notes: str}` → writes it atomically (trailing-newline normalized; empty/whitespace → empty file) and returns `{status: "saved", notes: "<normalized body>"}`. `400` if `notes` is missing or not a string. Ungated. **Security:** like the other ungated routes, anyone on the tailnet can set this text — and it becomes the opening prompt of a `claude` session that runs with your permissions on the mini. Same threat model as the ungated inventory/receipt routes (private Tailscale network). |
| `/api/receipts/trips` 🔒 | GET | Recent shopping trips, newest first. |
| `/api/receipts/trips/<int:trip_id>` 🔒 | GET | One trip plus its purchase line items. |
| `/api/price/trends` 🔒 | GET | Structured price-tracker data (spending, by-category totals, item trends) — JSON projection of `Price Tracker.md`. |
| `/api/nutrition/<week>` 🔒 | GET | Structured nutrition dashboard for a week — JSON projection of `Nutrition Dashboard.md`. |
| `/api/system-health` | GET | System health JSON: Ollama, vault, recent recipes, run/failure logs, Reminders queue, plus `assertions` (see below). |
| `/system-health` | GET | Interactive system health dashboard (HTML UI). |

**`assertions`** — `{checks: [...], ok, failing, unknown}` from `lib/health_assertions.run_all()`.
Everything else in this payload reports whether a component is *running*; these report whether
it is *working*. Each check is `{id, label, status, detail, consequence, fix}` where `status` is
`ok` / `failing` / `unknown`, `detail` carries the current numbers, `consequence` names what
silently stops working, and `fix` names the next action (sometimes a user action, like a Full
Disk Access grant, which no code path can perform).

Checks never raise — a probe that throws becomes `unknown`, because a health page that 500s on a
failed probe is the same class of bug the page exists to catch. Note that
`check_share_sheet_capture` reads `logs/batch_extract.log` rather than probing the Reminders
store: TCC grants are per-executable, so probing from inside the API server would answer a
question about the API server, not about the job that actually fails.
| `/recipe/<name>` | GET | Interactive recipe detail page with live ingredient scaling (HTML UI). Ingredients you don't have are coloured and marked `•`, ones you do `✓` with the stocked amount in the tooltip, plus a summary line under the table. Colour is never the only signal (red/green is the common colour-blindness axis, and this is read at a glance in a kitchen). Nothing is marked when inventory is empty — the legend says so instead of leaving the list looking merely unstyled. |
| `/plan-week` | GET | The Sunday-planning command center: a glanceable per-day status (slots filled + protein vs target, from `print_week.build_week_packet`) and three big actions — fill the week (`/meal-planner?week=`), review nutrition (`/nutrition-review`), print the week (`/print/week?week=`). Defaults to **next** week (`plan_week.default_week`); `?week=` overrides; prev/next nav. Unplanned weeks render an empty-state (200, not 404). Bookmarkable. |
| `/print/week` | GET | Printable one-page "week packet": the plan grid, each day's macros vs targets, the consolidated shopping list, and the do-ahead prep. Defaults to the current ISO week; `?week=YYYY-WNN` overrides; `?tasks=1` regenerates prep (an LLM call) instead of the read-only cache. Branches ledger-vs-markdown off `generate_shopping_list`'s `source`. Recipe names link to their `/recipe-card/<name>`. Bookmarkable (in `SECTIONS`). |
| `/recipe-card/<name>` | GET | Printable "grid" (Cooking-for-Engineers matrix) recipe card: ingredients with gram weights down the left, a staircase of merged action cells (what combines with what, in order) on the right, macros/servings header, print CSS. The step grouping is AI-inferred (`lib/recipe_grid.py`, cached in a `<recipe>.grid.json` sidecar keyed by recipe mtime; `?force=1` recomputes) and flagged for review — it never rewrites the recipe's own steps. |
| `/nutrition-review` | GET | Human review UI for weak/unresolved nutrition matches (HTML). |
| `/review` | GET | Inventory scan/review UI — interactive list of items sorted soonest-expiring first, with in-place actions: Remove (with Undo), +3d, +7d quick-extend buttons, and Refresh. Per-row checkboxes plus a header Select All raise a sticky bulk bar mirroring the same actions across the whole selection via `/api/inventory/bulk`; the selection is keyed by `(name, unit, location)` so it survives a re-render. After an expiry change the list re-sorts in place and the changed rows flash, so an item you just rescued visibly leaves the expired block. A header **Expiry / Added** control switches the ordering — "Added" sorts newest-first on `purchased`, which doubles as the date-added stamp (`add_items` stamps today on new rows only, never on a merge); rows predating the stamp sort last and read `added unknown`. The choice persists in `localStorage`. Every row's subline leads with its **storage location** and glyph, marked `?` with a tooltip when `location_source` is `default` (nothing actually resolved it), and carries a `used <when>` stamp when the row has a `last_used` — the only place consume-on-cook's use-stamping is visible, since for a container row that is the entire effect of marking a recipe cooked. A third **Location** sort blocks rows under per-location headers carrying a count and an unsure tally, unresolved rows first within each block. Correcting a row's location teaches `config/storage_locations.json`, so the same wrong guess stops recurring. Linked from the top of `Inventory.md`. |
| `/cook-now` | GET | What you could cook right now, ranked by coverage against inventory, with meal-type chips filtering client-side off one `/api/cook-now?limit=60` payload. **Each row is an `<a>` to `/recipe/<name>`** — the whole row, not just the name, so it's a real tap target on a phone; a coverage percentage alone doesn't tell you whether you want to eat the thing. Names are `encodeURIComponent`'d, which matters for real ones like `Ham Cheddar + Chive Protein Biscuits`. Rows keep `data-group` because the filter e2e tests select on it. |
| `/receipt-paste` | GET | Phone-friendly HTML page: copy the Claude-app prompt, paste the receipt JSON it returns, preview (routed items + reconciliation), then confirm to ingest. Backed by `/api/receipt/paste`. |
| `/` | GET | The web home page — **Kitchen Today**: four live cards from `lib/kitchen_today.py` (cookable-now count, recipes added this week, what's expiring, the week's plan), each a workflow entry point, over the full `SECTIONS` registry folded into a collapsed "All pages". The cards lead because the page's job is recall: a list of page names can't remind you a feature exists, but "9 recipes need nothing you don't have" does. Loads the inventory and recipe index **once** and injects them into `cook_now`/`use_it_up`, which would otherwise each re-parse the whole library. Every card degrades to a plain link if its query fails — no single card can 500 the page. Every page's Claude bar links back here. |
| `/recent` | GET | Recipes newest-first by when they arrived, grouped under Today / Yesterday / weekday / date, linking to `/recipe/<name>`. Ordered by **file birth time, not mtime** — the nutrition resolver rewrites recipe files long after they land, so an mtime ordering would reshuffle on every backfill. Surfaces `recipe_index`'s `added` field. |
| `/api/recipes/<name>/servings` 🔒 | POST | Set a recipe's servings count and recompute its nutrition. Body `{servings}` (whole number, 1–200). **This is what turns whole-batch macros into per-serving ones:** the engine derives per-serving as `total / servings`, and with `servings` missing it divides by 1 and publishes the batch total. Writes frontmatter, clears any `servings_inferred` / `servings_needs_review` flag (a typed count is a measurement, not an estimate — same rule `backfill_servings.py` uses for a stated yield), then recomputes **after** the write, since the engine reads `servings` back off the file. Backs the file up first. Fired by the "How many servings does it make?" form on `/recipe/<name>`. |
| `/api/nutrition-review/recipes` 🔒 | GET | Ranked queue of recipes needing nutrition review, worst first (lowest coverage, then lowest confidence). Frontmatter-only — fast. |
| `/api/nutrition-review/recipe/<name>` 🔒 | GET | Recompute one recipe's nutrition live (deterministic, no LLM) and return an audit-trail view with USDA candidates for weak/unresolved items. |
| `/api/nutrition-review/resolve` 🔒 | POST | Pin a human food match (or mark an item resolved-as-zero) so the nutrition engine's cache uses it on the next recompute. |
| `/api/nutrition-review/recompute` 🔒 | POST | Rerun the nutrition engine for one recipe file and persist + return the new summary. |
| `/api/week-board/<week>` 🔒 | GET | Serving-ledger board view of a week (`serving_ledger.week_board`) — cooks and their placements. |
| `/api/week-board/<week>/import-legacy` 🔒 | POST | One-time conversion of a hand-edited week into the serving ledger (`lib.week_view.import_legacy_week`). |
| `/api/cooks` 🔒 | POST | Create a cook — one preparation of a recipe at a fractional scale (serving ledger). |
| `/api/cooks/<int:cook_id>` 🔒 | PATCH | Update a cook. Body accepts any of `scale`, `servings_produced`, `date`, `meal`, `notes`, `cooked_at`, plus the post-eating verdict: `make_again` (`true`/`false`/`null`) and `cook_note` (free text). `make_again` is strictly binary — anything other than a bool or null is a `400`, since a stray `4` would store as truthy. `null` means *not judged*, which is deliberately distinct from `false`. Writing a verdict or yield also refreshes `cook_count` / `observed_servings` / `make_again_count` / `verdict_count` / `last_cooked` on the recipe note (best-effort; a missing note never fails the write). |
| `/api/cooks/<int:cook_id>` 🔒 | DELETE | Delete a cook and its placements. |
| `/api/cooks/<int:cook_id>/move` 🔒 | POST | Move a scheduled cook to another slot. Body `date` + `meal`. Re-anchors the cook **and** re-points the slot placements sitting at its old anchor, merging into any placement already at the destination; placements in other cells (planned leftovers) are left alone. Rejects a `date` outside the cook's `week` with a `400` — `cooks.week` is not updatable and `week_board()` filters on it, so such a cook would render on no board at all. |
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
