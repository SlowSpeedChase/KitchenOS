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

Two things this does **not** currently amount to, both worth knowing before you
rely on it:

- **Coverage is partial.** Some `/api/` routes remain ungated, including mutating
  ones (`/api/inventory/*`, `/api/pantry` PUT,
  `/api/recipes/save`). They are listed in `KNOWN_UNGATED` in
  `tests/test_api_auth.py`, which fails if a *new* ungated route appears — so
  the gap is pinned and visible, not closed.
- **No browser page sends the header.** Every `fetch()` in `templates/` is
  bare, so the moment `KITCHENOS_API_TOKEN` is set, every gated route 401s for a
  remote browser and the planner, freezer and board stop working from any
  machine but this one. `KitchenOSKit` does send it, so the native app is fine.
  The token is currently unset, which is the only reason this isn't biting.

## 1. HTTP endpoints

**Measured from current source:** 91 `@app.route` decorators register 82 unique
literal paths. Path | Method | Purpose.

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
| `/generate-shopping-list` | POST | Generate a shopping list markdown file from a meal plan. Body `{week, use_pantry?}`. **Compares with current inventory but never decrements it.** Unmatched demand becomes checkboxes under **Need to purchase** and is the only generated content sent to Reminders. Every broad or exact inventory match appears as a plain bullet under **Inventory matches — verify**, with the needed amount, matched inventory row, and match reason; these lines are excluded from Reminders. Expired rows are ignored, water/ice are omitted, and `use_pantry: false` returns raw demand. The response includes `inventory_match_count`, `inventory_credited_count`, and `inventory_review_count`; manually-added purchase items are preserved using an encoded generated-item snapshot, with semantic cleanup for legacy notes whose old generator changed quantities or names. `/api/shopping-list/preview` → `/confirm` remains the only path that spends stock. |
| `/send-to-reminders` 🔒 | POST | Body `{week}`. A configured native integration queues its shopping scope and returns `{success:true, native:true, queued, delivered:0, items_sent:0, sent:0}`; a missing native destination returns 409 and never falls back. Paused/disconnected native mode also never runs AppleScript. Otherwise pushes unchecked items to the legacy "Shopping" list and returns `{success, items_sent, items_skipped, queued:0, delivered:items_sent}`. Fired by the **Send to Reminders** button on `/current/shopping-list`. All items go over in **one** `osascript` call (~0.4s per Reminders round-trip, so the old item-at-a-time loop cost ~10s for a 24-item list), and the list is created if missing — no separate `create_reminders_list` call is needed. Item text is passed as `argv`, never interpolated into the AppleScript: these strings come from LLM-extracted ingredient lines, and a quote in one used to be able to close the string literal and get the remainder evaluated. |
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
| `/api/bundles` 🔒 | POST | Place a composite plate on a week. Body `{meal_name, week, date, meal, scale?}` — `meal_name` is the plate, `meal` is the slot. Creates **one ordinary cook per sub-recipe** sharing a `bundle_id`, each placed at its `sub_multiplier` share, so the plate's macros land in the day-totals row and every downstream consumer still sees one recipe per row. 201, or **200** with the existing bundle on a double-tap inside the dedupe window. 404 for an unknown plate. Converts a hand-edited legacy week (with a backup) before writing. |
| `/api/bundles/<id>/move` 🔒 | POST | Re-anchor a whole plate. Body `{date, meal}`. One transaction: a date outside the members' week refuses all of them, never some. |
| `/api/bundles/<id>` 🔒 | PATCH | Set a bundle-wide field on every member. Allowed: `cooked_at`, `make_again`, `cook_note` — anything else is a 400. `scale` is deliberately excluded: scaling a plate up usually means more protein, not more rice, so it stays a per-member PATCH on `/api/cooks/<id>`. Returns `{bundle_id, bundle_name, cooks, consumption}`; the bundle-wide verdict is what stops one plate generating a separate "was this worth making?" nudge per sub-recipe. |
| `/api/bundles/<id>` 🔒 | DELETE | Remove a whole plate from the week. Returns `{status, cooks}`. |
| `/api/meals` 🔒 | GET | List composite meal bundles (`vault/Meals/*.meal.md`). Each carries `slot` and a derived `nutrition` rollup (see below). |
| `/api/meals` 🔒 | POST | Create a meal bundle. Body `{name, sub_recipes: [{recipe, servings}], description?, tags?, slot?}`. `servings` is a **float** (1.5 splits a batch across meals) and must be > 0 — a non-positive or unparseable value is a 400. `slot` is one of `breakfast`/`lunch`/`snack`/`dinner`, defaulting to `dinner`; anything else is a 400. |
| `/api/meals/<name>` 🔒 | GET | Get one meal bundle, with `slot` and `nutrition`. |
| `/api/meals/<name>` 🔒 | PUT | Update a meal bundle (rename, edit sub-recipes/description/tags/slot). Same validation as POST, applied **before** a rename deletes the old file, so a rejected payload can't destroy the meal. Omitting `slot` keeps the stored one. |
| `/api/meals/<name>` 🔒 | DELETE | Delete a meal bundle. |
| `/api/macro-targets` | GET | The daily macro target plus how it splits across slots: `{daily: {calories, protein, carbs, fat} \| null, slot_shares: {breakfast, lunch, snack, dinner}, slot_shares_normalized}`. `daily` is null when there's no `My Macros.md` — clients should then show no reference line rather than invent one. Shares come from the optional flat `share_<slot>` keys (defaults 0.25/0.30/0.35/0.10); when they don't sum to 1.0 within 1% they're rescaled proportionally and `slot_shares_normalized` is true so the UI can say so. |
| `/api/pantry` | GET | Read the pantry adapter's item list (DB-backed, legacy JSON-shaped view). Expired rows remain stored for history but are omitted from this usable-stock view. |
| `/api/pantry` | PUT | Overwrite the pantry item list. Body `{items: [...]}`. |
| `/api/shopping-list/preview` | POST | **Pantry-aware shopping list, step 1.** Body `{week, use_pantry?}` → canonical purchase-only `items`/`purchase_items`, `inventory_matches`, and per-line records split into `from_pantry` / `to_buy`. Each line includes `status`, `matched_inventory`, and stable `needed_display`, `to_buy_display`, and `inventory_match_note` strings for confirmation clients. |
| `/api/shopping-list/confirm` 🔒 | POST | **Pantry-aware shopping list, step 2.** Body `{week, items_to_buy, inventory_matches?, decisions?}` — saves purchase checkboxes plus plain inventory-match bullets and, if `decisions` are present, decrements DB inventory accordingly (`pantry.apply_decisions`). Choosing “Buy fresh” sends the line's full `needed_display`, not a pantry-subtracted remainder. |
| `/api/tasks/<week>` | GET | Cross-recipe prep-task sidecar payload (prep/active/passive classification) for the "Today's Prep" panel. `?force=1` bypasses the freshness cache. |
| `/api/tasks/<week>/saved` 🔒 | GET | Read the saved, fresh task sidecar without extraction or recovery. Returns the existing tasks payload; 404 absent, 409 stale/unsafe, 400 malformed week, 503 I/O unavailable. |
| `/api/shopping-list/saved/<week>` 🔒 | GET | Read the saved shopping note: `{week,content_hash,rows:[{id,text,completed,issue}]}`. No identity migration or generation. Empty legacy IDs have `identity_missing`. 404 absent, 409 unsafe identity, 400 malformed week, 503 I/O unavailable. |
| `/api/shopping-list/saved/<week>/completion` 🔒 | POST | Exactly `{row_id,completed:bool,expected_hash:SHA256,operation_id:UUID}`; returns the current saved payload. Exact row-ID mutation with hash precondition and durable idempotent replay; stale hash/unsafe row is 409. No pantry, purchase, trip or cook mutation. Missing list is 404; malformed input 400; I/O unavailable 503. |
| `/api/tasks/<week>/<task_id>/done` 🔒 | POST | Mark a prep task done/undone. Body `{done?: bool}` (default true). |
| `/api/briefing/kitchen` 🔒 | GET | The kitchen block Selene's 06:00 morning digest carries. `?date=YYYY-MM-DD` overrides today (400 on an unparseable date). **Read-only and cheap by contract**: it parses the recipe library and reads inventory once for the whole payload, and it never regenerates the `/api/tasks` sidecar — a stale or missing sidecar just skips the two task-derived `next` rungs rather than blocking on an LLM classification pass. Response has exactly seven keys: `date`, `week`, `plate` (today's placed servings in meal order, each `{meal, recipe, leftover}` — a placement whose parent cook was made on any strictly earlier date is a leftover, with no lower bound: a cook from a month ago whose leftovers are eaten today still counts, and the cook can be from a different ISO week entirely, so long as one of its placements lands in today's week), `next` (the one thing to do today, or `null`; `{kind, text, detail}` where `kind` is one of `prep` (today's own sidecar step), `ahead` (a do-ahead step for the nearest future day this week), `verdict` (asking how a past cook went), or `plan-week` (nothing at all is planned)), `at_risk` (expiring inventory, most urgent first, `{item, status, expires}`), `look` (up to three suggestions, one per reason — `never-cooked`, `on-hand`, `seasonal` — `{reason, recipe, detail}`), and `degraded` (labels for any component that failed and fell back to empty/absent rather than taking the rest of the block down with it). |
| `/api/inventory` | GET | List DB inventory items. `?category=&location=` filter. Each item carries a computed `expiry_status` (`expired`/`soon`/`ok`/`null`), plus `location_source`, `last_used` and `use_count`. `location_source` records **how the row's `location` was decided**: `manual` (the user placed it, or supplied it explicitly in a request), `item` (a hand-curated `by_item` override matched), `category` (a `by_category` rule matched a real category), or `default` (nothing matched). Absent/NULL reads as `default`, and only `default` renders as unsure. `last_used`/`use_count` are written by consume-on-cook when a row is used but not safely decrementable. Backs the native app's inventory cleanup screen. |
| `/api/use-it-up` | GET | Recipes ranked by how much expiring/at-risk inventory they use, to avoid waste. `?limit=` (default 10). Returns `{at_risk, suggestions}`; staples excluded, only the actionable expiry window considered. Backs the `use_it_up` MCP tool and the meal-planner "Use It Up" panel. |
| `/api/cook-now` | GET | Recipes ranked by ingredient coverage against current inventory. `?limit=` (default 30) caps **each chip group**, not the whole list — the page filters this one payload client-side, and a global cap taken after the meal-tier weighting left the Desserts/Snacks/Drinks chips with nothing behind them. Returns `{"recipes": [{recipe, image, dish_type, group, have, total, coverage, missing, at_risk, meal_tier, protein, minutes, servings, banked, freezes_well, all_staples, score}]}`. `group` is the meal-type chip the recipe belongs to — one of `Mains`, `Breakfast`, `Sides`, `Snacks`, `Desserts`, `Drinks`. Filtering happens client-side on the `/cook-now` page; this endpoint never filters. `all_staples` marks a recipe whose every ingredient is a pantry staple; its score is demoted hard (never hidden) so perpetually-"ready" doughs and spice blends stop squatting at the top. |
| `/api/cook` 🔒 | POST | Mark a recipe cooked. Body `{recipe, servings?}` → `{recipe, consumed: [{item, unit, before, after, depleted}], use_recorded: [{item, unit}], not_tracked: [...], skipped_staples: [...]}`. Every ingredient lands in exactly one bucket. A row at quantity exactly `1.0` is a container: it is use-stamped (`last_used`, `use_count`) rather than decremented, so a recipe calling for three bay leaves cannot delete the jar. Optional/additive — inventory still self-cleans via expiry without it. Backs the `cook_recipe` MCP tool. |
| `/api/inventory/add` | POST | Add items to inventory. Body `{items: [...], trip?}`. Accepts optional per-item `unit_price`/`line_total` and an optional `trip` block (`{date, store, total, source_id, source}`) to also record into the price ledger; when supplied, `trip` must be an object with a nonempty string `source_id`. See "Receipt → Inventory Workflow" in `CLAUDE.md`. **`location` is how the caller declares provenance, so omit it unless the user actually chose the shelf.** A truthy `location` is taken as a placement the user confirmed and stamps `location_source: manual`; an absent (or falsy) one routes through `place_item` and records the real tier — `item`, `category`, or `default`, the last of which renders as unsure. A client that always sends a form default therefore records a confirmed placement that never happened and can never surface the `?` marker: the iOS app did exactly that until its Picker gained an **Auto** option (`NewInventoryItem.location` is `String?`, encoded by omission). Note the check is truthiness, not key presence, so `null` and `""` also route — but omit the key rather than leaning on that. |
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

`check_server_freshness` is the one assertion about the server itself: it compares source mtimes
(`api_server.py`, `lib/*.py`, `templates/*.html`) against `lib.boot.BOOT_TIME`, the moment the
process started. The LaunchAgent imports `lib/*` once and holds it, so every edit, branch switch
and rebase widens the gap between what the server runs and what the repo says — and that gap is
not merely a stale read: a three-day-old server placed a plate and wrote `scale=1.0` where
`plan_bundle` returns `0.5`, with no error anywhere. **Unlike every other check it is also
surfaced outside `/system-health`**, as a banner injected by `_serve_page` onto
every HTML page, because the corruption lands from whatever page you are on while everything
looks normal. `lib/boot.py` must stay imported at `api_server` module scope: capture that
timestamp lazily and it records the first health *request*, which is always newer than the code,
and every stale server reports as fresh.
| `/recipe/<name>` | GET | Interactive recipe detail page with live ingredient scaling (HTML UI). Ingredients you don't have are coloured and marked `•`, ones you do `✓` with the stocked amount in the tooltip, plus a summary line under the table. Colour is never the only signal (red/green is the common colour-blindness axis, and this is read at a glance in a kitchen). Nothing is marked when inventory is empty — the legend says so instead of leaving the list looking merely unstyled. |
| `/plan-week` | GET | The Sunday-planning command center: a glanceable per-day status (slots filled + protein vs target, from `print_week.build_week_packet`) and three big actions — fill the week (`/meal-planner?week=`), review nutrition (`/nutrition-review`), print the week (`/print/week?week=`). Defaults to **next** week (`plan_week.default_week`); `?week=` overrides; prev/next nav. Unplanned weeks render an empty-state (200, not 404). Bookmarkable. |
| `/print/week` | GET | Printable one-page "week packet": the plan grid, each day's macros vs targets, the consolidated shopping list, and the do-ahead prep. Defaults to the current ISO week; `?week=YYYY-WNN` overrides; `?tasks=1` regenerates prep (an LLM call) instead of the read-only cache. Branches ledger-vs-markdown off `generate_shopping_list`'s `source`. Recipe names link to their `/recipe-card/<name>`. Bookmarkable (in `SECTIONS`). |
| `/recipe-card/<name>` | GET | Printable "grid" (Cooking-for-Engineers matrix) recipe card: ingredients with gram weights down the left, a staircase of merged action cells (what combines with what, in order) on the right, macros/servings header, print CSS. The step grouping is AI-inferred (`lib/recipe_grid.py`, cached in a `<recipe>.grid.json` sidecar keyed by recipe mtime; `?force=1` recomputes) and flagged for review — it never rewrites the recipe's own steps. |
| `/nutrition-review` | GET | Human review UI for weak/unresolved nutrition matches (HTML). |
| `/review` | GET | Inventory scan/review UI — interactive list of items sorted soonest-expiring first, with in-place actions: Remove (with Undo), +3d, +7d quick-extend buttons, and Refresh. Per-row checkboxes plus a header Select All raise a sticky bulk bar mirroring the same actions across the whole selection via `/api/inventory/bulk`; the selection is keyed by `(name, unit, location)` so it survives a re-render. After an expiry change the list re-sorts in place and the changed rows flash, so an item you just rescued visibly leaves the expired block. A header **Expiry / Added** control switches the ordering — "Added" sorts newest-first on `purchased`, which doubles as the date-added stamp (`add_items` stamps today on new rows only, never on a merge); rows predating the stamp sort last and read `added unknown`. The choice persists in `localStorage`. Every row's subline leads with its **storage location** and glyph, marked `?` with a tooltip when `location_source` is `default` (nothing actually resolved it), and carries a `used <when>` stamp when the row has a `last_used` — the only place consume-on-cook's use-stamping is visible, since for a container row that is the entire effect of marking a recipe cooked. A third **Location** sort blocks rows under per-location headers carrying a count and an unsure tally, unresolved rows first within each block. Correcting a row's location teaches `config/storage_locations.json`, so the same wrong guess stops recurring. Linked from the top of `Inventory.md`. |
| `/cook-now` | GET | What you could cook right now, ranked by coverage against inventory, with meal-type chips filtering client-side off one `/api/cook-now?limit=60` payload. **Each row is an `<a>` to `/recipe/<name>`** — the whole row, not just the name, so it's a real tap target on a phone; a coverage percentage alone doesn't tell you whether you want to eat the thing. Names are `encodeURIComponent`'d, which matters for real ones like `Ham Cheddar + Chive Protein Biscuits`. Rows keep `data-group` because the filter e2e tests select on it. |
| `/receipt-paste` | GET | Phone-friendly HTML page: copy the Claude-app prompt, paste the receipt JSON it returns, preview (routed items + reconciliation), then confirm to ingest. Backed by `/api/receipt/paste`. |
| `/` | GET | The web home page — **Kitchen Today**: four live cards from `lib/kitchen_today.py` (cookable-now count, recipes added this week, what's expiring, the week's plan), each a workflow entry point, over the full `SECTIONS` registry folded into a collapsed "All pages". The cards lead because the page's job is recall: a list of page names can't remind you a feature exists, but "9 recipes need nothing you don't have" does. Loads the inventory and recipe index **once** and injects them into `cook_now`/`use_it_up`, which would otherwise each re-parse the whole library. Every card degrades to a plain link if its query fails — no single card can 500 the page. |
| `/recent` | GET | Recipes newest-first by when they arrived, grouped under Today / Yesterday / weekday / date, linking to `/recipe/<name>`. Ordered by **file birth time, not mtime** — the nutrition resolver rewrites recipe files long after they land, so an mtime ordering would reshuffle on every backfill. Surfaces `recipe_index`'s `added` field. |
| `/api/recipes/<name>/servings` 🔒 | POST | Set a recipe's servings count and recompute its nutrition. Body `{servings}` (whole number, 1–200). **This is what turns whole-batch macros into per-serving ones:** the engine derives per-serving as `total / servings`, and with `servings` missing it divides by 1 and publishes the batch total. Writes frontmatter, clears any `servings_inferred` / `servings_needs_review` flag (a typed count is a measurement, not an estimate — same rule `backfill_servings.py` uses for a stated yield), then recomputes **after** the write, since the engine reads `servings` back off the file. Backs the file up first. Fired by the "How many servings does it make?" form on `/recipe/<name>`. |
| `/api/nutrition-review/recipes` 🔒 | GET | Ranked queue of recipes needing nutrition review, worst first (lowest coverage, then lowest confidence). Frontmatter-only — fast. |
| `/api/nutrition-review/recipe/<name>` 🔒 | GET | Recompute one recipe's nutrition live (deterministic, no LLM) and return an audit-trail view with USDA candidates for weak/unresolved items. |
| `/api/nutrition-review/resolve` 🔒 | POST | Pin a human food match (or mark an item resolved-as-zero) so the nutrition engine's cache uses it on the next recompute. |
| `/api/nutrition-review/recompute` 🔒 | POST | Rerun the nutrition engine for one recipe file and persist + return the new summary. |
| `/api/week-board/<week>` 🔒 | GET | Serving-ledger board view of a week (`serving_ledger.week_board`) — cooks and their placements. |
| `/api/week-board/<week>/import-legacy` 🔒 | POST | One-time conversion of a hand-edited week into the serving ledger (`lib.week_view.import_legacy_week`). |
| `/api/cooks` 🔒 | POST | Create a cook — one preparation of a recipe at a fractional scale (serving ledger). |
| `/api/cooks/<int:cook_id>` 🔒 | GET | Return the raw current ledger cook, including placements, unassigned servings, cooked state and bundle identity; 404 absent. Resolves typed native cook IDs without title matching, generation or mutation. |
| `/api/cooks/<int:cook_id>/schedule` 🔒 | POST | `{date,meal,start,timezone,duration_minutes,servings_to_eat,expected_unplaced?:bool}` → `{cook,schedule}`. Schedule an eligible uncooked single-recipe cook through the ledger. Offset-bearing start, IANA timezone, same week, 15-minute steps, 15–360-minute duration and finish by midnight are required. First placement requires positive servings; existing anchor servings and unrelated leftovers are preserved. Optional `expected_unplaced` is checked inside the write transaction: mismatch/nonboolean is 400. Native omitted anchored servings are explicit null, accepted only with `expected_unplaced:false` and a current anchor; absent precondition retains legacy positive-serving validation. |
| `/api/cooks/<int:cook_id>/schedule` 🔒 | DELETE | Remove only the timed reservation; preserve cook, meal/serving placements, scale, inventory and cooked state. Repeated unscheduling is a no-op; absent cook is 404. |
| `/api/cooks/<int:cook_id>` 🔒 | PATCH | Update a cook. Body accepts any of `scale`, `servings_produced`, `date`, `meal`, `notes`, `cooked_at`, plus the post-eating verdict: `make_again` (`true`/`false`/`null`) and `cook_note` (free text). `make_again` is strictly binary — anything other than a bool or null is a `400`, since a stray `4` would store as truthy. `null` means *not judged*, which is deliberately distinct from `false`. Writing a verdict or yield also refreshes `cook_count` / `observed_servings` / `make_again_count` / `verdict_count` / `last_cooked` on the recipe note (best-effort; a missing note never fails the write). |
| `/api/cooks/<int:cook_id>` 🔒 | DELETE | Delete a cook and its placements. |
| `/api/cooks/<int:cook_id>/move` 🔒 | POST | Move a scheduled cook to another slot. Body `date` + `meal`. Re-anchors the cook **and** re-points the slot placements sitting at its old anchor, merging into any placement already at the destination; placements in other cells (planned leftovers) are left alone. Rejects a `date` outside the cook's `week` with a `400` — `cooks.week` is not updatable and `week_board()` filters on it, so such a cook would render on no board at all. |
| `/api/cooks/<int:cook_id>/freeze-rest` 🔒 | POST | Bank the cook's `unassigned` servings in the freezer in one call. No body. A no-op returning `200` when nothing is left over, so a double-tap neither errors nor double-banks. Previously the only route into the freezer was dragging a serving chip onto the planner's sidebar tray — a gesture needing board mode, an open sidebar and a mouse. |
| `/api/freezer` 🔒 | GET | What's banked, grouped by recipe and **oldest first** (a freezer is FIFO). Returns `{freezer: [{recipe, servings, banked_on, placement_ids, protein, calories, total_protein, total_calories}], totals: {servings, protein, calories}}`. `banked_on` prefers `cooked_at` over the planned `date` over `created_at` — only the first means "this exists". Macros pass the `implausible` **bounds** only — deliberately looser than `day_totals`, which applies the full `eligible_macros` gate: the day row is a claim about what you ate, while the freezer is an inventory of real food and a low-coverage portion is still a portion. An unpriced or implausible recipe reports `null` macros while still contributing its **servings**. |
| `/api/placements` 🔒 | POST | Create a placement — assign a cook's servings to a (destination, date, meal, count) slot. |
| `/api/placements/<int:pid>` 🔒 | PATCH | Update a placement. |
| `/api/placements/<int:pid>` 🔒 | DELETE | Delete a placement. |
| `/api/placements/<int:pid>/move` 🔒 | POST | Move a placement to a new destination/date/meal. |

### Request and persistence contracts

- Flask has already decoded request values. `/refresh` and `/reprocess` validate
  each `file` once with `contained_markdown`, which resolves the Markdown path
  beneath the configured recipes root; the server does not decode it again.
- The four shopping-list mutation/preview handlers — `/generate-shopping-list`,
  `/send-to-reminders`, `/api/shopping-list/preview`, and
  `/api/shopping-list/confirm` — accept only real canonical ISO weeks
  (`YYYY-WNN`). `parse_iso_week` rejects noncanonical and impossible weeks, and
  `shopping_list_path` builds the resulting filename beneath the configured root.
- Ordinary inventory additions merge matching case-insensitive
  `(name, unit, location)` keys inside one `BEGIN IMMEDIATE` transaction. Whole-set
  reconciliations take that write lock before reading their snapshot, then replace
  the set in the same transaction.
- On `POST /api/inventory/add`, a supplied `trip` must be an object with a
  nonempty string `source_id`; malformed trip payloads return 400 before any
  inventory, trip, or purchase write.
- Receipt ingestion treats a duplicate `source_id` as a successful no-op. A
  valid receipt commits its trip, purchases, and non-fee inventory merge together;
  a needs-review receipt intentionally persists only its trip and purchases.
  Inventory and Cook Now views refresh only after a valid stock commit, under a
  serialized full read-and-render lock. Every ordinary exception at that public
  post-commit boundary is caught and logged, so it never makes a durable receipt
  retryable.

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
| `add_to_inventory` | `(items: list[dict], trip: dict = None)` | Batch add — items may carry optional `unit_price`/`line_total`; optional `trip` `{date, store, total, source_id, source}` records into the price ledger, but a supplied trip needs a nonempty string `source_id`. Calls `POST /api/inventory/add`. |
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

Shared Siri and Shortcuts entry points are defined in
`KitchenOSKit/Sources/KitchenOSKit/Intents/` and use `KitchenOSClient`.
Its defaults connect iOS over Tailscale and macOS over localhost; both are
configurable via `UserDefaults["kitchenos.baseURL"]`. A configured bearer from
`CredentialStore` is attached automatically, matching the server's optional
`KITCHENOS_API_TOKEN` policy. Existing add-to-plan/assistant writes retain their
confirmation gates. The five Mac Apple actions below use the shared serialized
Apple integration service and execute the explicitly configured action; they do
not add a universal confirmation step to every mutation.

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

### Mac Apple actions

These five actions are in `KitchenOSSiri/Sources/Intents/AppleIntegrationIntents.swift`,
compiled only on macOS. Buttons and intents share `AppleIntegrationCoordinator`.
They require the designated Mac's local server; missing connection, permission or
destination continues in the foreground to setup and asks the caller to rerun.

| Action / metadata identifier | Parameters | Semantics |
|---|---|---|
| Send Shopping List to Reminders / `SendShoppingListToRemindersIntent` | Date in week (default today) | Activate the selected shopping week using its chosen writable list, then sync active scopes. |
| Send Prep Tasks to Reminders / `SendPrepTasksToRemindersIntent` | Date in week (default today) | Activate the selected prep week using its chosen writable list, then sync active scopes. |
| Sync Cooking Calendar / `SyncCookingCalendarIntent` | Date in week (default today) | Activate the selected cooking week/calendar; export eligible existing schedules. |
| Schedule Cooking / `ScheduleCookingIntent` | Week date, exact planned cook entity, start, duration (default 60), meal (default dinner), optional servings | Refetch cook by ledger ID, validate and POST its schedule. First placement requires servings. Existing portions stay unchanged. Reconcile only if this cooking week is already active; otherwise report the KitchenOS save and direct the caller to Sync Cooking Calendar. |
| Sync KitchenOS / `SyncKitchenOSIntent` | None | Reconcile already active weeks; does not activate historical scopes. |

The week parameter resolves through the local timezone's ISO week-year. Entities
use ledger integer IDs, never recipe/display titles. Reports distinguish setup,
paused, queued, conflicts, unavailable and acknowledged delivery; counts are
**overall sync across active weeks**, not proof that one chosen cook was delivered.
A successful schedule followed by failed sync is reported as saved in KitchenOS
with Apple delivery unconfirmed.

Build metadata must contain all five discoverable action identifiers in
`Contents/Resources/Metadata.appintents/extract.actionsdata`. This does not prove
installed discovery or execution. Create named Mac Shortcuts from the action
library; no new automatic Mac phrases are registered. iOS has no Apple writer or
these five Mac actions.

## Native Apple integration (model version 1)

`lib/apple_integration/routes.py` registers every route below under
`/api/apple-integration`. All use the existing optional bearer policy: localhost
is exempt; with `KITCHENOS_API_TOKEN` configured, remote callers need its bearer
value. **Local writer** routes additionally require the actual remote address to
be `127.0.0.1` or `::1`, even with a valid bearer or when the token is unset.
Forwarding headers do not grant local authority. Settings/status may be used by
iOS; iOS never becomes a second EventKit writer.

Errors are `{error: string}`: 400 malformed/unknown/missing fields, 401 bad remote
bearer, 403 nonlocal writer/stale owner/paused writer, 409 stale revision or
conflicting lifecycle, 413 oversized complete batch. Source IO/recovery failures
return 503 `{error:"Source recovery unavailable; retry", retryable:true,
report:SyncReport}`. The bridge accepts at most 2 MiB JSON, 5,000 observations,
and no duplicate observation tokens. Complete work output is also bounded to
2 MiB and 5,000 combined items, retained items, operations and retry observations.
Overflow fails; no array is truncated or interpreted as deleted membership.
No endpoint accepts a file path.

### Shared JSON types

All keys are snake_case. UUIDs are canonical lowercase UUID strings. ISO weeks
are exact `YYYY-Www` keys, not display labels. Types below list every wire key;
`?` means nullable, not an omitted required property.

```text
BridgeContext = {owner_id:UUID, owner_generation:int>0}
Locator = {calendar_id:string, item_id:string, external_id:string?}
DueValue = null | {date:"YYYY-MM-DD", time:"HH:MM"?, timezone:IANA-name?}
SourceItem = {logical_id:string, domain:"shopping"|"prep"|"cooking",
  week:ISO-week, title:string, fields:object, source_revision:SHA256,
  state:"active"|"retired"|"history"|"conflict"}
SyncItem = SourceItem + {revision:int>0, generation:int>0, token:UUID,
  destination_id:string, locator:Locator?, common_fields:object?}
  (SyncItem.state also permits "suppressed".)
Observation = {token:UUID, generation:int>0, revision:int>0,
  availability:"present"|"missing"|"unavailable", locator:Locator?,
  title:string?, fields:object, absence_confirmed:bool,
  issue:null|"unsupported_all_day"|"unsupported_recurrence"|"identity_ambiguous",
  has_user_notes:bool?}
AppleOperation = {operation_id:UUID, token:UUID, generation:int>0,
  revision:int>0, action:"upsert"|"delete", destination_id:string,
  locator:Locator?, title:string, fields:object, expected_apple_hash:SHA256?}
SyncReport = {created:int, updated:int, deleted:int, queued:int,
  conflicts:int, unavailable:int, last_success:offset-ISO-timestamp?}
Scope = {domain, week, destination_id, status:"active"|"paused"|"archived",
  revision:int>0}
ConflictSummary = {conflict_id:UUID, token:UUID, field:string, revision:int>0}
ObservationRetry = {request_id:UUID, observations:[Observation]}
OwnedRemovalItem = {token:UUID, expected_revision:int>0, observation:Observation}
```

Reminder fields are exactly `{completed:bool, due:DueValue}`. Date-only due has
null `time` and `timezone`; a timed due requires both. Cooking fields are exactly
`{start:offset-ISO-timestamp, timezone:IANA-name, duration_minutes:int}`. Use the
specified timezone's local offset representation consistently. An ordinary
present observation requires a non-null title and all domain fields. Unsupported
all-day/recurring/ambiguous objects use `issue`; never coerce them into valid
cooking fields. Unavailable/missing observations may use `{}`. Only complete,
readable native reconciliation may set `absence_confirmed:true` on `missing`.

The Apple hash is SHA-256 of UTF-8 canonical JSON **`{"title":title,"fields":fields}`**:
lexicographically sorted object keys, no whitespace, unescaped Unicode, finite
JSON values. The native adapter must verify the object's exact ownership marker
`kitchenos-native://item/<token>`, generation/identity and this hash immediately
before every mutation. A locator alone is not ownership. Search all readable
relevant stores to disambiguate moved/reidentified objects. A null expected hash
permits first creation only after the adapter's available identifier/marker
searches find no owned object; finding one requires observation/recovery.
Public EventKit cannot prove global Calendar absence. A previously linked,
unlocatable Calendar event stays unavailable. For a never-linked first export,
finite recovery windows leave a residual duplicate risk if an interrupted save
was moved beyond every searched window before its locator was acknowledged. Never
adopt old AppleScript reminders, clear a list/calendar, or mutate foreign objects.

### Exact endpoint envelopes

| Method and suffix | Request | Successful response |
|---|---|---|
| POST `/owner` (**local writer**) | `{owner_id:UUID, permissions?:{domain:Permission}, destinations?:{domain:[{id:string,title:string}]}}` | `{model_version:1, context:BridgeContext, status:IntegrationStatus}` |
| DELETE `/owner` (**local writer**) | `{context:BridgeContext}` | `IntegrationStatus` |
| PUT `/settings` | `{paused:bool, expected_revision:int>0}` | `IntegrationStatus` |
| PUT `/scopes/<domain>/<week>` | `{domain, week, destination_id:string, state:"active"|"paused"|"archived", expected_revision:int>=0}` | `{scope:Scope, report:SyncReport}` |
| GET `/status` | No body | `IntegrationStatus` |
| GET `/work` (**local writer**) | Query `owner_id=<UUID>&owner_generation=<positive integer>`; no body | `WorkBatch` |
| POST `/observations` (**local writer**) | `{context:BridgeContext, request_id:UUID, complete:true, observations:[Observation]}` | `{operations:[AppleOperation], report:SyncReport}` |
| POST `/operations/<uuid>/ack` (**local writer**) | `{context:BridgeContext, operation_id:UUID, outcome:"saved"|"deleted"|"changed"|"failed", locator:Locator?, observed_fields:object, observed_hash:SHA256?}` | `{report:SyncReport}` |
| POST `/operations/<uuid>/recover-saved` (**local writer**) | `{context:BridgeContext, ack:OperationAck, observation:Observation}`; saved ack operation ID matches path | `{report:SyncReport}` |
| POST `/sync/complete` (**local writer**) | `{context:BridgeContext, scopes:[Scope], request_ids:[UUID]}`; exact scopes from fresh work and completed observation request IDs covering its current items | `{report:SyncReport}` |
| POST `/conflicts/<uuid>/resolve` | `{choice:"keep_kitchenos"|"keep_apple"|"keep_manual"|"restore", expected_revision:int>0}` | `{report:SyncReport}` |
| POST `/items/<token>/restore` | `{expected_revision:int>0}` | `{item:SyncItem, report:SyncReport}` |
| POST `/items/remove-owned` (**local writer**) | `{context:BridgeContext, request_id:UUID, items:[OwnedRemovalItem]}` | `{operations:[AppleOperation]}` |
| GET `/links/<token>` | No body | `{domain, week, source_id:string, state:string}` |
| GET `/items` | Exactly query `domain=<domain>&week=<ISO-week>` | `{items:[SyncItem + {has_due_override:bool,due_override:DueValue}]}` including retained generations; maximum 5,000 items / 2 MiB. No refresh or recovery. |
| GET `/conflicts/<uuid>` | No body | `{conflict_id,token,field,revision,source,apple,choices}` for an open conflict; 409 closed/missing. Recorded source/Apple evidence, not a fresh Apple scan. |

Path domain/week and operation ID must match their payload. Initial scope creation
uses `expected_revision:0`; later edits use `Scope.revision`. Owner settings start
at revision 1; use `IntegrationStatus.settings_revision`. Item restoration/removal
uses **item** revision, while conflict resolution uses **conflict** revision.
Conflict detail advertises only currently supported choices; revalidation still
occurs on POST. `source_recovery` offers manual separation, plus restore only for
a suppressed item; present Apple evidence alone cannot make an unreadable source
safe to import. Opening `kitchenos-native://item/<token>` resolves the exact source
and displays it without mutation; missing, historical or retired sources explain
their state without creating replacements.

`Permission` is one of `unknown`, `not_determined`, `denied`, `restricted`,
`authorized`, `write_only`, or `unavailable`. Owner registration optionally replaces
the full reported permission/destination maps; omitted maps are preserved. It is
also the permission/status refresh call. One owner UUID reconnects idempotently.
Replacement requires explicit quiescent disconnection; pending operations,
imports, requests or resolutions prevent it. Disconnection leaves Apple objects
and source data in place, increments owner generation, and invalidates old clients.

```text
IntegrationStatus = {
  model_version:1, configured:bool, connected:bool, paused:bool,
  settings_revision:int>=0, report:SyncReport,
  permissions:{domain:Permission}, destinations:{domain:[{id,title}]},
  scopes:[Scope], conflicts:[ConflictSummary] (maximum 100 summaries)
}
WorkBatch = {
  model_version:1, context:BridgeContext, items:[SyncItem],
  operations:[AppleOperation], scopes:[Scope], report:SyncReport,
  paused:bool, retry_requests:[ObservationRetry], retained_items:[SyncItem]
}
```

`report.conflicts` counts all open conflicts even when the summary list reaches
100. `queued` counts durable pending operations/recovery work; it never means
Apple delivery. Permission reports reflect the native owner's latest report.
`unavailable` in a work/observation response includes unreadable source scopes or
uncertain observations from that reconciliation. Source failures do not imply
Apple deletion. Status does not perform source inference or native IO.
`has_user_notes` is true when Apple notes contain user prose beyond exact
ownership-marker lines; omitted means false for older replay payloads. Retirement
opens review instead of deleting such an item, and EventKit rechecks notes just
before deletion.
`last_success` records a complete converged pass, including an unchanged or empty
active scope. The native owner freshly checks Apple permissions/destinations and
observes current work after all writes; the completion endpoint revalidates owner,
scopes, current item coverage and source availability. At least one active scope
is required, with no pending work or open conflicts. An empty pass submits a
completed empty observation request. Work/status reads and individual write acks
do not advance the timestamp. An identical valid completion proof reuses its
SQLite receipt timestamp rather than recording another success.

Work `items` contains the latest generations in active scopes, excluding detached
history and already-cleaned retirement rows. Suppressed/conflicted rows remain
visible as such and must not be exported. `retained_items` contains old incomplete
owned generations with locators in active scopes, plus retained rows with explicit
pending cleanup. It is separate recovery UI data: **do not include it in ordinary
observations**. Archived/paused scopes stop normal work. Archiving or changing a
scope default preserves existing tokens, common state and locators. Existing
objects keep their user-selected list/calendar; a default selects destinations
only for new identities. Reactivation resumes those same objects.

### Reconciliation and recovery order

1. Register/reconnect the localhost owner and obtain its current context. Foreground
   permission/destination selection remains in the native app.
2. Fetch work. The server first recovers exact note edits, source imports, generated
   cooking views and explicit resolutions, then refreshes sources. Polling never
   runs prep inference. Missing/stale/unmigrated source data requires an explicit
   normal source refresh/save and is unavailable in the meantime.
3. If `retry_requests` is nonempty, resend that exact request ID and observation
   array with the current matching context and `complete:true`. The server permits
   at most one unfinished request and rejects new IDs until it finishes. Completed
   retries are inert; changed UUID payloads are 409. Semantic drift becomes a
   visible conflict and finishes that observation, so the request is not permanently
   stuck. IO failures retain durable progress for retry.
4. **After replay, fetch fresh server work AND fresh Apple observations again before
   applying any outbound operation.** Apple edits made during downtime must not be
   overwritten by operations derived from an old replay. Work returns no operations
   while retry work remains. Native operations run in one serialized writer service.
5. Submit a complete bounded observation array. All incoming identities, generations,
   revisions and field shapes validate before any import. Recoverable multi-note
   imports are journaled per item (not a cross-file atomic transaction). Invalid or
   truncated batches never partially import or imply absence. The shared Python
   merge engine owns field decisions; the Swift adapter does not add a second merge.
6. Before each returned operation, freshly verify unique ownership and expected hash.
   Drift returns `changed` and a **new full Observation** through the observations
   endpoint, rather than overwriting. Permission/save failure returns `failed`.
   Neither advances common state. `saved` requires the final locator, all saved
   fields and the title/fields hash; `deleted` requires null locator, `{}` fields,
   and null hash. Ack operation UUID must match the path.
7. After writes or source imports, repeat the fresh work/Apple observation pass.
   Once every active scope is readable and converged with no pending work or
   conflicts, POST `/sync/complete`. Partial, stale and unavailable passes cannot
   record success.

An already committed acknowledgement can be retried with the same payload under
the same owner generation even after later item/scope revisions. It returns no
additional delivery count and does not change `last_success`. Changed payloads
remain rejected.

If a save completes in Apple after its server operation was superseded, retain
that saved acknowledgement and the original item identity. Fetch fresh work and
verify the same generation's unique owned marker with a fresh Apple observation,
even if active work no longer includes the item. The saved ack must match the
original operation title/fields/hash; the current Apple title and fields may have
changed. POST `/recover-saved` to record the receipt, link only the observed
locator, and open `recovery`, `retirement`, or `retained_generation` review
according to the current source state. No old save is imported into the newer
source. A verified moved/reidentified object may have a different locator from
the saved ack; an unreadable or missing result cannot establish recovery.
Transient/lost responses retry the exact proof. A definitive 409 discards only
that observation proof, retaining the saved acknowledgement for a fresh scan.
Uncertain deletion keeps its acknowledgement pending for explicit review; no
fresh scan invents deletion proof.

The protocol maps confirmed missing reminders to suppression and confirmed missing
cooking events to unscheduling only. The current native adapter never confirms a
missing Calendar event from failed lookup: public EventKit lacks global tombstones,
so that case stays unavailable for review. Reminder absence needs prior in-process
ownership/visibility evidence and a complete readable local scan; a cold restart
cannot manufacture that evidence. Neither path logs cooking or changes inventory. Restore
requires the current suppressed item revision and creates a new token/generation.
Explicit restore retains its displayed due choice; normal retirement/reappearance
starts fresh per-generation metadata. A reappearing source whose old incomplete
Apple object still has a locator gets `retained_generation` recovery and cannot
create a duplicate until the old object is explicitly detached or removed.
Suppressed exports are terminal for ordinary work and successful-pass coverage;
they do not need an Apple observation until explicit restore or owned cleanup.
Regenerated shopping demand after a retired historical row starts incomplete.

Generated v3 shopping snapshots must keep the target text in the row's ingredient bucket, and conflict markers must use the declared amount/identity
values. Invalid metadata makes the source unavailable before any conflict rows
are published; it never offers an unsafe Keep KitchenOS choice.

Explicit shopping activation prepares a missing or unmigrated note through the
existing pantry-aware generator and canonical save writer. It never confirms
pantry spending. Ordinary work/status reads leave missing and legacy notes
untouched and report them unavailable until an explicit activation or normal save.

### Explicit choices and deletion

- Ordinary field/recovery conflicts with a valid present observation and
  matching current source revision support Keep choices only while the item
  and scope are active. Archived or inactive items offer manual separation;
  reactivation can expose the other choices. A later Apple observation
  refreshes an open recovery conflict's evidence and revision before import.
  Active choices are
  `keep_kitchenos` (reserve a verified outbound update), `keep_apple` (import the
  selected field/full recovery snapshot), or `keep_manual` (detach the Apple object,
  leave it untouched, and suppress the source export). Unsupported shapes accept
  detachment; they are never coerced. A pending Keep KitchenOS correction survives
  a fresh scan of the same Apple evidence; newer Apple edits require review again.
  Common values advance only after acknowledgement or verified equality.
  `restore` applies only to a suppressed source;
  the dedicated restore endpoint is the normal UI action.
- Shopping conflict detail includes optional `shopping_demand` evidence:
  `{state:"active",text:"3 lime"}` identifies the generated acceptance target;
  `{state:"removed",text:null}` identifies demand that disappeared. `source.title`
  retains the visible edited row. Reading this evidence never regenerates the note.
  The generated target participates in the source revision, so a changed target
  invalidates a choice presented earlier even when the edited row text is unchanged.
  Each row has one open shopping source conflict: regeneration updates its evidence
  and revision, including amount-to-ingredient changes. Superseded duplicate records
  are closed without changing the note or Apple object. Missing, nonstring, empty
  or multiline generated snapshot text makes the source unavailable instead of
  publishing an unusable acceptance target; malformed metadata is never repaired
  implicitly by reading it.
  Older conflict records without this evidence offer only manual separation until
  a refresh records the current target.
- `shopping_amount_changed`: for active demand, `keep_kitchenos` accepts the shown
  generated amount, reopens its checkbox and removes the explicit amount conflict.
  For removed demand, it removes the exact shopping row and retires its Apple link;
  the UI labels this **Remove item from shopping list**. `keep_manual`
  keeps the visible line under a genuinely new manual row ID and detaches the old
  Apple object. An ingredient identity edit uses the same choices, but
  `keep_kitchenos` restores the recorded original ingredient. These edits use the
  adapter's exact hash and durable note journal; the service never edits encoded
  metadata directly. Apple text is never sent to an LLM.
- `retirement`: a removed source has an Apple title or supported field changed since
  the acknowledged common snapshot. Automatic deletion is blocked; `keep_manual`
  separates the object, or explicit remove-owned can delete it after fresh review.
  Completed reminders remain history without deletion. Completion first observed
  after source retirement freezes that journal generation as history and cancels
  pending mutations. Later Apple reopening cannot resume deletion; reappearing
  source demand receives a new incomplete generation without a retained-item block.
- `retained_generation`: `keep_manual` leaves the old Apple object as a manual copy,
  clears only its bridge locator and unblocks the new generation. Alternatively,
  invoke remove-owned with the retained item's token and **its own** expected
  revision plus a freshly verified present observation. The returned cleanup UUID
  and callback can clear only that retained row, never the replacement generation.
- Remove-owned uses a nonempty bounded list with no duplicate tokens. Selection
  alone is insufficient: the native service must freshly verify each object's unique
  ownership, then submit its matching generation/revision and observed hash inputs.
  The server binds the entire cleanup request UUID/payload and reserves all operations
  in one short transaction. Existing Apple objects are preserved until each verified
  per-object delete completes. Ordinary old-generation callbacks remain rejected.

`/api/prep/reminders` is token-gated too. In native mode its optional `week` (default
current ISO week) queues the configured prep scope and returns the native sender
fields plus `{list:"Prep",scope:"today"|"ahead"}`. Native sync follows the selected
week's structured task membership. With no native configuration, the prior today/
ahead AppleScript behavior remains and adds `{queued:0,delivered:sent}`.
`shopping_list.py` similarly saves the canonical shopping note and queues its native
scope; native `--clear` is rejected. Paused/offline native mode never invokes the
legacy fallback. Shopping-confirm and task-done now use the same token gate as
these sender paths. Existing MCP send calls preserve the full JSON response.
A native sender's `queued` counts that scope's durable pending operations, source
patches, resolutions and unfinished observation requests containing its tokens;
already synchronized items contribute zero. Requests without item tokens cannot
be attributed to a selected scope and remain visible in the global status.
Sending an archived scope returns 409; reactivate it explicitly in the Mac app.
