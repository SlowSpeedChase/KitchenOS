# KitchenOS Planner v2 — Serving Ledger, Daily Macros, Grocery Scaling, Nutrition Backfill v2, Recipe Detail

**Date:** 2026-07-06
**Status:** Approved by user (sections 1–5), pending spec review

## Problem

The meal planner is a mature drag-and-drop grid, but four things the user needs are missing or untrustworthy:

1. **No daily nutrition totals.** `/api/nutrition/<week>` exists but the planner never calls it; no macro totals appear anywhere on the board.
2. **No serving accounting.** A recipe makes N servings; today nothing tracks where they go. "Cook" (`lib/cook.py`) is a fire-and-forget raw-ingredient decrement. Freezer is only an inventory location string for groceries — cooked servings can't be frozen, eaten later, or trashed.
3. **Scaling is integer-only and disconnected.** The `xN` link suffix only accepts integers; the grocery list is derived from `[[links]]`, not from what's actually being cooked at what scale.
4. **Nutrition data is untrusted.** 229/233 recipes have per-serving macros, but 225 sit at confidence 0.0 and 230 are flagged `needs_review` because `min()` confidence lets one unmatched ingredient zero the recipe, unresolved lines silently contribute 0 kcal (undercounting), and there is no surface to review/fix bad USDA matches. Vault max is 20,883 kcal/serving — no sanity guard.

Additionally (from UX research across Mealie, Plan to Eat, Crouton, CookBook, and a 2026 JMIR study): the app lacks a **recipe detail page** — recipes exist only as sidebar cards; there is no full in-app view with scaled ingredients and macros. (A step-by-step cooking mode is confirmed valuable but **deferred** to the backlog.)

## Decisions made with user

- **Platform:** local web app (existing Flask server) over the Obsidian vault; Markdown stays human-readable.
- **Data model:** SQLite ledger + Markdown view. Cook events and serving placements live in `data/kitchenos.db`; the weekly meal-plan `.md` is regenerated as a readable view. DB is authoritative for serving state (freezer state spans weeks; Markdown can't hold it cleanly).
- **Serving model:** a scheduled cook of a recipe at a fractional scale produces N servings; every serving is placed in a day/meal slot, the freezer, or the trash. Frozen servings persist as inventory and can be dragged onto future days.
- **Grocery list:** computed from the week's cook events × scale. Freezer-sourced meals add nothing.
- **Nutrition backfill:** USDA-based (keep `lib/nutrition_engine.py`) with a human review step; coverage-based honesty instead of silent undercounting.
- **Scope:** recipe detail page included; cooking mode deferred.

## 1. Serving ledger (data model)

New tables in `data/kitchenos.db` (created via `lib/inventory_db.py` migration pattern):

```sql
CREATE TABLE cooks (
    id INTEGER PRIMARY KEY,
    recipe TEXT NOT NULL,            -- recipe note name
    week TEXT NOT NULL,              -- ISO week the cook is planned in, e.g. '2026-W28'
    date TEXT,                       -- anchor day (YYYY-MM-DD)
    meal TEXT,                       -- anchor slot: breakfast|lunch|snack|dinner
    scale REAL NOT NULL DEFAULT 1.0, -- 0.5–4.0 in 0.5 steps
    servings_produced REAL NOT NULL, -- recipe frontmatter servings × scale, user-editable
    cooked_at TEXT,                  -- set when marked cooked (triggers inventory decrement)
    notes TEXT
);

CREATE TABLE placements (
    id INTEGER PRIMARY KEY,
    cook_id INTEGER NOT NULL REFERENCES cooks(id) ON DELETE CASCADE,
    destination TEXT NOT NULL CHECK (destination IN ('slot','freezer','trash')),
    date TEXT,                       -- required when destination='slot'
    meal TEXT,                       -- required when destination='slot'
    count REAL NOT NULL DEFAULT 1.0  -- servings placed here
);
```

**Invariant (API-enforced):** `SUM(placements.count) <= cooks.servings_produced`; the difference is shown as "unassigned" in the UI. Deleting a cook cascades its placements. Moving a frozen serving to a future slot = decrement the freezer placement, insert/increment a slot placement (same `cook_id`, so recipe identity and macros travel with it).

**Markdown view:** `rebuild_meal_plan_markdown` (lib/meal_plan_parser.py) renders, per slot, `[[Recipe]] x1.5` for the anchor cook plus a placements summary line (e.g. `↳ 2 servings here · 3 frozen · 1 unassigned`); leftover slot placements render as `[[Recipe]] (leftover)`. Parser treats these lines as view-only decoration — hand-edits to links still work via the existing fallback (see §3).

**API:** `POST/PATCH/DELETE /api/cooks`, `POST/PATCH/DELETE /api/placements`, `GET /api/week-board/<week>` returning cooks + placements + freezer contents for the planner. Marking a cook cooked calls the existing `lib/cook.py` consume path with the cook's `scale`.

## 2. Planner UI (`templates/meal_planner.html`)

- **Drop = cook event.** Dropping a sidebar recipe on a grid cell creates a cook anchored there. Card gains a **scale stepper** (0.5–4.0 × in 0.5 steps) replacing the ×1/×2/×3 cycle button (`setCardServings`/`cycleCardServings`, ~:1520–1531). Changing scale recomputes `servings_produced`.
- **Serving chips.** Each cook card fans out one chip per serving (SortableJS group, same pattern as recipe cards at :1411–1419). Chips drag to: another grid cell (leftover placement), the **Freezer tray**, or a **Trash** drop target. Fractional remainders render as a partial chip.
- **Freezer tray.** Persistent panel (sidebar tab next to Recipes/Meals) listing frozen servings grouped by recipe with count and age (days since cook). Chips drag out onto any day/slot — including in a different week.
- **Unassigned badge** on each cook card (e.g. "2 unassigned") until every serving is placed.
- **Daily totals row.** An 8th grid row appended in `buildGrid()` (after :1394), one cell per day column: **kcal · P · C · F**, summed as Σ(per-serving macros × chip count) over that day's slot placements. Data from `/api/nutrition/<week>` extended to compute from placements. A ⚠ marker appears when any contributing recipe has `nutrition_coverage < 0.8` or missing macros — totals are never silently wrong.
- Composite `[[Meal:]]` bundles keep current behavior (out of scope for serving chips in this build; each sub-recipe can be promoted to a cook later).

## 3. Grocery list from cooks

- `lib/shopping_list_generator.py`: new primary source — the week's `cooks` rows (`ingredients × scale`, floats allowed in `multiply_ingredients`, :91). The existing `[[link]] xN` regex scan (`extract_recipe_links`, :38) remains as fallback for hand-edited plans with no DB cooks that week; when both exist, DB wins and hand-added links absent from the DB are included with a note.
- Freezer-sourced slot placements contribute nothing to the list.
- Aggregation (`lib/ingredient_aggregator.py`), pantry subtraction (`lib/pantry.py`), Shopping Lists note output, and Reminders push are unchanged.

## 4. Nutrition backfill v2

Keep the USDA-first engine (`lib/nutrition_engine.py`); fix trust and matching:

- **(a) Coverage, not min().** New per-recipe `nutrition_coverage` = fraction of resolvable ingredient **grams** resolved (lines with no gram estimate count by line). Written to frontmatter alongside existing fields; `nutrition_confidence` becomes the mean of resolved-line confidences. `needs_review` = coverage < 0.8 or any sanity flag. Unmatched ingredient names are written to a `nutrition_unmatched: [...]` frontmatter list so partial data is visible, never silent.
- **(b) Pre-match text cleanup ("Phase B" of `lib/ingredient_cleaner.py`).** Strip parentheticals, prep phrases ("spooned and leveled", "plus more for serving"), `*(inferred)*` markers, and duplicate words before USDA search. Add a small alias table (`config/food_aliases.yml`, e.g. "evoo → olive oil") consulted before search; user-taught fixes land here or in the `food_resolution` cache.
- **(c) Nutrition Review page.** New surface `/nutrition-review`: recipes ranked worst-coverage-first; each row expands to per-ingredient lines showing grams + matched USDA food + the other candidates as a picker. Picking a candidate (or marking "negligible") writes to the existing `food_resolution` cache and recomputes that recipe live — every fix teaches the matcher vault-wide. Batch "re-run backfill" button.
- **(d) Sanity flags.** Per-serving kcal outside [50, 2500] (configurable) or a single line > 50% of recipe grams ⇒ `needs_review: true` + shown atop the review page. Backfill never writes silently absurd numbers again.

## 5. Recipe detail page

New route `/recipe/<name>` (server-rendered template, linked from sidebar cards and review page): image, source link, tags/meta, servings, a **scale control** that live-recomputes the ingredient table amounts (client-side, same unit formatting as `format_amount`), instructions, per-serving macro table with coverage/confidence footer, and actions: *add to this week's plan* (creates a cook) and *open in Obsidian* (`obsidian://` URI). Read-only in this build — editing stays in Obsidian.

## Backlog (explicitly deferred)

- Step-by-step cooking mode (large-type, hands-free navigation) — research-confirmed valuable.
- Serving chips for `[[Meal:]]` composite bundles.
- Waste analytics from the trash ledger (data accrues from day one via `placements`).

## Error handling

- Placement writes are transactional; the invariant check rejects over-placement with a 409 the UI surfaces.
- A recipe missing macros never blocks placement — the day total shows ⚠ and the review page surfaces the recipe.
- Grocery generation with zero cooks for the week falls back to the link scan (current behavior) rather than an empty list.
- USDA API failures (rate limit/network) leave lines unresolved and reduce coverage — they must not zero out existing data on re-runs.

## Testing

- Unit: placement invariant (over-place rejected; freezer→slot move conserves counts), fractional `multiply_ingredients`, coverage math (all-resolved=1.0; one unresolved line lowers coverage but not others' macros), sanity flags, alias/parenthetical stripping.
- Integration: `GET /api/week-board` round-trip (create cook → place servings → totals reflect placements); grocery list from a week with 1.5× cook + one freezer meal (freezer meal absent from list); backfill dry-run on the 20,883 kcal recipe flags instead of writing.
- Manual: drag chips slot↔freezer↔trash on iPad (SortableJS touch path); daily totals match hand-computed macros for one real week; fix one bad match on the review page and confirm the recipe recomputes and the fix persists in `food_resolution`.

## Verification

Run `python api_server.py`, open `http://localhost:5001/meal-planner`: drop a recipe at 1.5×, place its servings across two days + freezer + trash, confirm the day totals row updates and the ⚠ appears for a low-coverage recipe; generate the shopping list and confirm 1.5× quantities and no freezer-meal ingredients; open `/nutrition-review`, fix a match, confirm coverage rises; open `/recipe/<name>` and scale it.
