# Recipe Button — Meal Builder Design

**Date**: 2026-05-01
**Status**: Design (approved, ready for implementation plan)
**Topic**: Extending the recipe "Add to Meal Plan" button to also build composite meals (recipe playlists), and surfacing those meals in the meal-planner board sidebar.

---

## Problem

The composite-meal data model already exists:

- `vault/Meals/<Name>.meal.md` files with a `sub_recipes` frontmatter list
- `[[Meal: X]]` tokens in meal plans, parsed by `lib/meal_plan_parser.py`
- `flatten_to_recipes()` expanding meals downstream for shopping lists, nutrition, prep tasks
- CRUD API at `/api/meals` (GET, POST) and `/api/meals/<name>` (GET, PUT, DELETE)

What's missing is the **user-facing flow** to actually build meals and tie them to the existing recipe button. Today, clicking "Add to Meal Plan" on a recipe opens a single-screen form with week/day/slot dropdowns. There is no way to start a meal, no way to add a recipe to an existing meal, and meals are invisible in the drag-drop planner board.

## Goals

1. From any recipe, the user can **schedule directly** (today's behaviour, unchanged), **add the recipe to an existing meal**, or **start a new meal seeded with the current recipe**.
2. Building a meal is **incremental** — visit a recipe, click the button, add it to the meal. No giant "browse 100+ recipes inside a modal" picker.
3. After adding/creating a meal, the user can **optionally schedule it** in the same flow (skippable).
4. The **meal-planner board sidebar** has a Meals tab that lists meals as draggable cards.
5. All meal **editing** (remove sub-recipe, reorder, edit servings, rename, delete) happens by hand-editing the `.meal.md` in Obsidian. No editor UI.

## Non-Goals

- Recipe browser/picker for stacking multiple sub-recipes in one shot (rejected explicitly — the user does not want to browse 100+ recipes in a modal).
- A `/meals` manager page.
- Inline reorder/remove/servings UI.
- Renaming or deleting meals from KitchenOS UI.
- Filter chips on the Meals tab in the planner sidebar.

## Architecture

Two surfaces, built independently:

### Surface 1 — Recipe button → form flow

Replaces the existing single-screen form at `GET /add-to-meal-plan` with a 2-screen flow.

- **Screen 1**: One HTML page with three radio options that reveal different fields via tiny JS (toggle `display: none`). One POST to a unified endpoint.
- **Screen 2**: Result page rendered by the POST handler. For meal-creation/append paths, shows a hybrid "Saved. Schedule now?" prompt with optional pickers and a Skip link.

Touches: `api_server.py` (`/add-to-meal-plan` GET + POST), `lib/meal_loader.py` (one new helper).

### Surface 2 — Meal-planner board sidebar Meals tab

Adds a tab toggle in the existing recipe sidebar. Calls `GET /api/meals` (already exists), renders cards, makes them draggable. Drop handler inserts `[[Meal: <Name>]]` (vs `[[Recipe]]` for recipes).

Touches: `templates/meal_planner.html` only.

### Data model

Unchanged. `vault/Meals/<Name>.meal.md` already stores everything needed. New sub-recipes default to `servings: 1`. Editing happens via Obsidian markdown.

### State semantics

- "Add to existing meal" appends a `SubRecipe(recipe=<current>, servings=1)` to the meal's `sub_recipes` list. Idempotent — already-present recipes are no-ops.
- "Create new meal" saves a new `<name>.meal.md` seeded with the current recipe. Fails on name collision.
- Optional schedule step inserts `[[Meal: <name>]]` (not `[[Recipe]]`). The unit being scheduled is the meal.

## Screen 1 — Branch Picker Form

`GET /add-to-meal-plan?recipe=<encoded>`

```
┌─────────────────────────────────────┐
│ Add to Meal Plan                    │
│ ┌─────────────────────────────────┐ │
│ │ Pasta Aglio E Olio              │ │
│ └─────────────────────────────────┘ │
│                                     │
│ ◉ Schedule directly                 │
│ ○ Add to an existing meal           │
│ ○ Start a new meal                  │
│                                     │
│ ─── (conditional fields) ───        │
│ [Week ▾] [Day ▾] [Meal ▾]   (direct)│
│ [Pick meal ▾]            (existing) │
│ [Meal name: __________]      (new)  │
│                                     │
│ [        Submit         ]           │
└─────────────────────────────────────┘
```

- Default radio: **Schedule directly** (preserves muscle memory).
- Inline `<script>` toggles three `<div>` containers' visibility on radio change. No fetch calls.
- "Pick meal" dropdown populated server-side via `meal_loader.list_meals()`. Empty list → option rendered with `disabled` and label "Add to existing meal (none yet)".
- Single `<form method="POST" action="/add-to-meal-plan">` with hidden `recipe` field.

Posted fields by mode:

| Mode | Required fields |
|------|-----------------|
| `direct` | `recipe`, `mode=direct`, `week`, `day`, `meal` |
| `existing` | `recipe`, `mode=existing`, `meal_name` |
| `new` | `recipe`, `mode=new`, `meal_name` |

## POST Handler Logic

`POST /add-to-meal-plan` branches on `mode`:

```python
@app.route('/add-to-meal-plan', methods=['POST'])
def add_to_meal_plan():
    recipe = request.form.get('recipe')
    mode = request.form.get('mode', 'direct')
    if not recipe:
        return error_page("recipe parameter required"), 400

    if mode == 'direct':
        return _schedule_recipe_directly(recipe, week, day, meal)

    if mode == 'existing':
        meal_name = request.form.get('meal_name', '').strip()
        meal = meal_loader.load_meal(meal_name)
        if meal is None:
            return _render_form(recipe, error="Meal not found.")
        meal_loader.append_sub_recipe(meal, recipe_name=recipe)
        meal_loader.save_meal(meal)
        return _render_schedule_prompt(recipe, meal_name, action="added")

    if mode == 'new':
        meal_name = request.form.get('meal_name', '').strip()
        if not meal_name:
            return _render_form(recipe, error="Meal name is required.")
        if meal_loader.load_meal(meal_name) is not None:
            return _render_form(recipe, error=f'A meal called "{meal_name}" already exists.')
        meal = meal_loader.Meal(
            name=meal_name,
            sub_recipes=[meal_loader.SubRecipe(recipe=recipe, servings=1)],
        )
        meal_loader.save_meal(meal)
        return _render_schedule_prompt(recipe, meal_name, action="created")

    if mode == 'schedule_meal':
        return _schedule_meal(meal_name, week, day, meal)

    return error_page(f"Unknown mode: {mode}"), 400
```

### New helper in `lib/meal_loader.py`

```python
def append_sub_recipe(meal: Meal, recipe_name: str, servings: int = 1) -> Meal:
    """Append a SubRecipe to meal.sub_recipes in place. No-op if already present."""
    if any(s.recipe == recipe_name for s in meal.sub_recipes):
        return meal
    meal.sub_recipes.append(SubRecipe(recipe=recipe_name, servings=servings))
    return meal
```

### Notes

- `direct` branch is byte-identical to current code, wrapped in a private helper. Zero regression risk.
- All meal mutation goes through `meal_loader.save_meal()` which writes atomically.
- No `lib/backup.py` calls — backups are for recipe overwrites, not small YAML sidecar files.
- Filesystem case-insensitivity (macOS APFS): "Salmon Dinner" and "salmon dinner" collide via `load_meal()` returning the existing file. This is the right behaviour; integration test should cover it.

## Screen 2 — Schedule Prompt (Hybrid)

Rendered after a successful `existing`/`new` POST. Skipped for `direct` (existing flow already lands on its own success page).

```
┌─────────────────────────────────────┐
│ ✓ Created meal "Salmon Dinner"      │
│   with Pan-Seared Salmon            │
│                                     │
│ Schedule it now? (optional)         │
│                                     │
│ [Week ▾] [Day ▾] [Slot ▾]           │
│                                     │
│ [   Schedule meal   ]               │
│ [ Skip — open in Obsidian ]         │
└─────────────────────────────────────┘
```

- Banner reflects `action`: "Added X to Y" or "Created Y with X".
- Dropdowns identical to current form (current week + 3 ahead, Mon–Sun, Breakfast/Lunch/Snack/Dinner).
- Primary button POSTs to `/add-to-meal-plan` with `mode=schedule_meal, meal_name, week, day, meal`. Server:
  1. Find-or-create the meal-plan file (existing logic).
  2. Call `insert_recipe_into_meal_plan(content, day, slot, f"Meal: {meal_name}")`. The helper wraps the value in `[[...]]`, producing `[[Meal: Salmon Dinner]]`.
  3. Render the existing green success page (generalized to take a `wikilink_target` param so it works for both recipe and meal outcomes — ~5-line refactor).
- Skip link: `obsidian://open?vault=KitchenOS&file=Meals/<name>` — lands on the canonical edit surface.

## Meal-Planner Sidebar Meals Tab

`templates/meal_planner.html` only.

```
┌─────────────────────────┐
│ [ Recipes | Meals ]     │
│ ─────────────────────── │
│ [ search...        ]    │
│ [chip] [chip] [chip]    │   (Recipes only)
│ ─────────────────────── │
│ ╔═══════════════════╗   │
│ ║ Salmon Dinner     ║   │
│ ║ MEAL · 3 recipes  ║   │
│ ╚═══════════════════╝   │
│ ╔═══════════════════╗   │
│ ║ Taco Tuesday      ║   │
│ ║ MEAL · 2 recipes  ║   │
│ ╚═══════════════════╝   │
└─────────────────────────┘
```

- Tab toggle: CSS segmented control. Click "Meals" → hide recipe list & filter chips, show meal list. State held in JS module variable.
- Meals fetched via `GET /api/meals` on `DOMContentLoaded` (in parallel with the recipe index fetch). Cached client-side for the session.
- Each meal card: name, "MEAL" pill, sub-recipe count. Hover tooltip shows sub-recipe names.
- Search filters meal names (case-insensitive substring) when on the Meals tab.
- Filter chips hidden on the Meals tab. Meals don't share the recipe tag taxonomy.
- Drop handler: dragged item's `data-kind === 'meal'` → wikilink token is `Meal: <name>`. PUT to `/api/meal-plan/<week>` round-trips through `rebuild_meal_plan_markdown` which already supports the `Meal:` prefix.
- Empty state: "No meals yet. Create one from any recipe's 'Add to Meal Plan' → 'Start a new meal'."
- API failure: Meals tab shows error, Recipes tab still works.

## Edge Cases

| Case | Behaviour |
|------|-----------|
| Recipe already in target meal | `append_sub_recipe` no-op. Schedule prompt banner: "X is already in Y." Save still happens (no-op write is harmless). |
| New meal name collision | Re-render Screen 1 with collision error. Form keeps user's prior choices. |
| Filesystem-unsafe meal name (`/`, `:`, `\`, leading `.`) | Reject on Screen 1 with explicit error. |
| Empty/whitespace meal name | Re-render Screen 1: "Meal name is required." |
| Existing-meal radio with no meals yet | Option `disabled` at render time, label: "(none yet)". |
| Schedule step: meal-plan file missing for week | Auto-create from template (existing behaviour, unchanged). |
| Schedule step: day/slot already has a recipe | Append, don't replace (existing `insert_recipe_into_meal_plan` behaviour). |
| Race: meal deleted between Screen 1 render and POST | `mode=existing` POST: `load_meal()` is `None` → re-render Screen 1 with "Meal not found." |
| Planner sidebar `/api/meals` failure | Meals tab shows error, Recipes tab unaffected. |
| Meal name with quotes/backslashes | `_yaml_quote` escapes both. Test: `Mac & Cheese "Special"` round-trips. |

## Testing

### Unit tests (in `tests/`)

- `test_meal_loader_append_sub_recipe.py` — append to empty, append with one existing, idempotent on duplicate, custom servings, in-place mutation.
- Filename safety — reject `/ : \ .leading`. Round-trip quotes/backslashes via `save_meal` → `load_meal`.

### Integration tests (Flask test client)

- `test_add_to_meal_plan_direct_unchanged` — regression guard for current behaviour.
- `test_add_to_meal_plan_create_new_meal` — POST `mode=new` → file exists, has recipe as sub-recipe, response is schedule prompt.
- `test_add_to_meal_plan_existing_meal` — pre-create meal → POST `mode=existing` → file has 2 sub-recipes.
- `test_add_to_meal_plan_existing_meal_idempotent` — same recipe twice → still 1 sub-recipe.
- `test_add_to_meal_plan_name_collision` — POST `mode=new` with existing name → form re-rendered with error.
- `test_schedule_meal_inserts_meal_token` — meal-plan file has `[[Meal: X]]`, not `[[X]]`.
- `test_screen_1_disables_existing_when_no_meals` — empty `vault/Meals/` → response HTML has `disabled` on existing-meal radio.

### Manual verification (per CLAUDE.md "Completing Work" checklist)

1. Recipe button → form renders with three radios, default "Schedule directly".
2. "Start a new meal" → name input → submit → schedule prompt → Skip → Obsidian opens the meal file with the recipe in `sub_recipes`.
3. Different recipe → "Add to existing meal" → dropdown lists the new meal → submit → file has 2 sub-recipes.
4. Schedule prompt → fill week/day/slot → submit → meal plan file at `Meal Plans/<week>.md` has `[[Meal: <name>]]`.
5. `/meal-planner` → toggle Meals tab → cards visible → drag a meal into a slot → `[[Meal: X]]` token saved.
6. Downstream: shopping list aggregates ingredients from all sub-recipes; nutrition dashboard sums sub-recipe macros into the day total.

### Test fixtures

Add one minimal `.meal.md` fixture under `tests/fixtures/` for the existing-meal flow.

## Out of Scope (Explicit)

- Removing/reordering/editing sub-recipes — edit `.meal.md` directly.
- Renaming or deleting meals from UI.
- Filter chips on the Meals tab.
- Recipe browser inside the form.

## Files Touched

| File | Change |
|------|--------|
| `api_server.py` | Refactor `/add-to-meal-plan` GET + POST into branched flow; new `mode=schedule_meal` branch; small generalization of success-page renderer to take a `wikilink_target`. |
| `lib/meal_loader.py` | One new helper: `append_sub_recipe(meal, recipe_name, servings=1)`. |
| `templates/meal_planner.html` | Tab toggle, Meals tab rendering, parallel `/api/meals` fetch, meal-aware drag handler. |
| `tests/test_meal_loader.py` (or new file) | Unit tests for the new helper. |
| `tests/test_api_server.py` (or new file) | Integration tests for the four POST branches. |
| `tests/fixtures/` | One sample `.meal.md`. |
| `CLAUDE.md` | Update "Key Functions" with the new helper and the four-mode endpoint behaviour. |

No backend changes for the planner sidebar — `/api/meals` and `/api/meal-plan/<week>` PUT already do what's needed.
