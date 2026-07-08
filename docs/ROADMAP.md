# KitchenOS Roadmap

**ROADMAP = what's next.** Shipped design history lives in `docs/superpowers/specs`
(per-feature design docs) and `docs/plans/archive` (frozen pre-superpowers plans).
Build/deploy history (the Siri/App-Intents build log, origin-story rationale) lives
in `docs/history`. This file tracks only: what shipped since the last update (for
context) and what's genuinely still open.

Audited 2026-07-01 against `main` (post-convergence). Original 2026-06-24 audit
covered the salvaged-branch Python backlog below; this pass adds the native/Siri
tier that shipped since and corrects two stale statuses.

---

## Done / Shipped

The native tier — entirely undocumented here until now — is built and merged to
`main` (both forked app branches, `siri-app-intents` and `ingredient-cleaning`,
converged via `docs/superpowers/plans/2026-06-24-convergence-plan.md`; both
branches are gone, both surfaces coexist in one app):

- **`KitchenOSSiri`** — single XcodeGen target building **iOS 26 + macOS 26**
  (bundle `com.kitchenos.siri`), multiplatform: macOS gets the `AppShell` sidebar
  (Cook / Plan / Stock / System sections), iOS/iPadOS gets the tab-based
  Assistant/Plan/Cook/Search/Settings surface. Both platforms share
  `KitchenOSKit`.
- **`KitchenOSKit`** — shared Swift package: async `KitchenOSClient`, Codable
  models, Keychain-backed credential store, `WeekDate` helpers.
- **App Intents + `AppShortcutsProvider`** — 9 intents: `FindRecipesByIngredient`,
  `GetMealPlan`, `SuggestForMealPlan`, `AddRecipeToMealPlan` (gated behind
  `requestConfirmation`), `GetRecipeNutrition`, `SummarizeRecipe`, `OpenRecipe`,
  `SmartFindRecipes`, `AskKitchenOS`. All Swift-side relay/format only — recipe,
  AI, and nutrition logic stays server-side in Python.
- **On-device Apple Foundation Models** (Subsystem C, phases C1/C2):
  `RecipeAI` (single Foundation Models gateway; `@Generable RecipeQuery` filter;
  backs `SummarizeRecipeIntent`) and `MealPlanAssistant` + three `Tool`
  conformances (`FindRecipesTool`, `MealPlanTool`, `SuggestMealTool`) powering the
  in-app chat assistant.
- **CoreSpotlight / `IndexedEntity` semantic search** (Subsystem C, phase C3):
  `RecipeEntity: IndexedEntity` with a `CSSearchableItemAttributeSet`
  (title/cuisine/protein), `RecipeIndexer.reindexAll`, indexed on launch + a
  manual "Reindex for search" Settings button. Spotlight/Siri can match recipes
  by meaning, not just exact name. (`AssistantSchemas`/`@AssistantEntity` were
  evaluated and correctly skipped — no matching Apple domain exists for
  food/recipe/meal.)
- **Backend Phase 0** (`docs/superpowers/plans/2026-06-21-siri-backend-phase0.md`):
  `GET /api/recipes?ingredient=<term>` server-side filter, and optional
  `KITCHENOS_API_TOKEN` bearer-token auth (no-op when unset, localhost always
  exempt) gating the Siri-facing endpoints for the iPad-over-Tailscale case.
  `/api/recipes/by-ingredients` also shipped as part of the merged backend work.
- **Inventory cleanup screen** (`docs/superpowers/plans/2026-06-26-inventory-cleanup-screen.md`):
  `GET /api/inventory` now returns a computed `expiry_status`
  (`expired`/`soon`/`ok`/`null`, from `lib/expiry.py` — same thresholds as
  `Inventory.md`). The native `InventoryView` shows an "Added … · Exp … 🔴/🟡"
  secondary line, sorts each category worst-first by expiry, and stepping
  quantity to 0 removes the item.
- **Convergence merge**: `siri-app-intents` and `ingredient-cleaning` are merged
  to `main` and deleted; the app is one multiplatform target, not two forks.

---

## Native / Siri — pending polish

Genuinely open items surfaced by the superpowers specs/plans, not yet built:

- **CoreSpotlight ingredient-keyword enrichment + reindex cadence** (C3
  follow-up). C3 v1 indexes title/cuisine/protein only — ingredient keywords
  need a backend "all recipes with ingredients" endpoint that doesn't exist yet.
  Reindexing today is launch-time + a manual Settings button; no background/
  periodic cadence.
- **`AppShell` `ComingSoonView` fallback** (`KitchenOSSiri/Sources/Shell/AppShell.swift`):
  a placeholder view still exists for any `SidebarSection` the `detail(for:)`
  switch doesn't explicitly handle. As of this audit every current section
  (Search, Recipes, Meals, Nutrition, Meal Plan, Planner Board, Shopping List,
  Tasks, Inventory, Pantry, Receipts, Extraction (macOS), System Health,
  Settings) routes to a real screen — so this is currently dead code / a safety
  net, not an active gap. Worth removing or re-purposing next time a new section
  is added rather than leaving it as a silent fallback.

## Native inventory: zone + shelf layout (next concrete step)

**Status:** the flat-category cleanup screen (dates + expiry badges, worst-first
sort) shipped — see Done/Shipped above. `main` still routes every item to one of
five flat locations (`fridge/freezer/pantry/counter/other` in `lib/inventory.py`);
the richer zone → shelf → group hierarchy from the salvaged
`claude/kitchen-inventory-system-EdBZI` branch (below) was never built.

The concrete next step is **not** a new screen from scratch — it's reconciling
the shipped flat `storage_location`/`for_recipe` router
(`lib/storage_locations.py:resolve_location`) with the branch's richer
`Location/Shelf/Group` model into **one** item → `(zone, shelf, location)`
router, then surfacing shelf grouping in both `Inventory.md` and the native
`InventoryView`. See the salvaged-branch entry below for the original design
(`config/storage_locations.json` schema, `route_item()`).

---

## Salvaged Python-side backlog

Unbuilt feature ideas worth keeping. These were salvaged from stale feature
branches before those branches were deleted — each entry records the source
branch + commit so the original implementation is recoverable from git's
reflog / object store (`git show <sha>`) until garbage-collected.

Branches whose every idea was already built (`refine-local-plan`,
`recipe-link-detection`, `recipe-update-system`, `reprocess-button`) were
deleted with nothing to preserve.

### Inventory: spatial zone + shelf layout

**Source:** `claude/kitchen-inventory-system-EdBZI` @ `f19dcec` (2026-04-25)
**Status today:** GAP, and now the concrete next inventory step — see
"Native inventory: zone + shelf layout" above. `main` has flat location
categories only (`fridge/freezer/pantry/counter/other` in `lib/inventory.py`).

Model the kitchen as a zone → shelf → group hierarchy instead of flat
categories. Items route to a specific shelf; `Inventory.md` and the UI group by
shelf. Branch introduced `config/storage_locations.json` (declarative layout +
per-group defaults), `Location/Shelf/Group` dataclasses, and `route_item()`.

- Declarative kitchen-layout schema (zones, shelves, item groups)
- Per-shelf grouping in the rendered inventory + a sidebar zone picker
- Native equivalent: the shipped `InventoryView` (see Done/Shipped) organized
  by zone/shelf instead of flat category

### Inventory: markdown receipt-paste ingestion

**Source:** `claude/kitchen-inventory-system-EdBZI` @ `f19dcec`
**Status today:** DONE via a different path. `lib/receipt_paster.py` +
`POST /api/inventory/paste` (preview-then-commit) + `paste_inventory.py` CLI
already ship this on `main` — see `CLAUDE.md` / `docs/API.md`. Kept here only
for branch-provenance completeness; no further work needed.

### Inventory: expiry tracking + default expiry windows

**Source:** `claude/kitchen-inventory-system-EdBZI` @ `f19dcec`
**Status today:** DONE. `config/expiry_windows.json` (`by_item`/`by_category`
default windows) + `lib/expiry.py:compute_expires`/`expiry_status` ship on
`main`, and the native inventory cleanup screen (Done/Shipped above) surfaces
the UI warnings this item asked for. Kept for branch-provenance completeness.

### Inventory: printable kitchen labels

**Source:** `claude/kitchen-inventory-system-EdBZI` @ `f19dcec`
**Status today:** GAP. No label generation in `main`.

Generate a printable `Kitchen Labels.md` (shelf/zone labels) from the layout
config. Branch had `templates/labels_template.py`, `manage_inventory.py
--labels`, and `scripts/generate_labels.py`. Lowest priority of the set — blocked
on the zone+shelf layout landing first (labels need real shelf/zone data).

---

### Ingredients: ML parser with confidence scoring

**Source:** `feature/ingredient-parsing` @ `9247a01` (2026-01-08)
**Status today:** **Done / opt-in.** `main` ships `lib/ingredient_ml.py`
(`ingredient-parser-nlp`, needs Python 3.11+, `requirements-ml.txt`) as an
optional fast-path returning `{amount, unit, item, preparation, confidence}`.
`lib/ingredient_parser.py:parse_ingredient_best()` uses it only when
`KITCHENOS_ML_INGREDIENTS=1` and confident, falling back to the rule-based
parser + cleaner otherwise (which already emits explicit `needs_review` flags
for low-confidence / edge cases). Off by default. This closes the branch idea —
no further work needed; the "optional fast-path, not a replacement" framing the
branch recommended is exactly how it shipped.

---

### Meal plan: timed calendar events

**Source:** `feature/timed-meal-events` @ `bbb5ec1` (2026-01-10)
**Status today:** **Done.** `main`'s calendar sync (`lib/ics_generator.py`,
`sync_calendar.py`) emits a separate 30-minute timed event per meal slot
(breakfast 8:00, lunch 12:00, snack 15:00, dinner 19:30 — see `MEAL_TIMES` in
`lib/ics_generator.py`), marked `TRANSP:TRANSPARENT` (shown as free). Matches
what the branch proposed; no further work needed.

> Note: the branch also *removed* `MealEntry` / `flatten_to_recipes()` from the
> parser — that dropped composite `[[Meal: Bundle]]` expansion and was a
> regression that was correctly **not** ported. `main` keeps composite-meal
> expansion.
