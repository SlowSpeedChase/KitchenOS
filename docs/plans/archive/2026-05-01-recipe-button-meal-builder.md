# Recipe Button — Meal Builder Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Branch the recipe "Add to Meal Plan" button into three flows — schedule directly, add to an existing meal, or start a new meal seeded with this recipe — with an optional schedule prompt at the end. Editing meals stays in Obsidian markdown.

**Architecture:** Server-rendered Flask form with three radio options that progressively reveal fields via tiny JS. One unified `POST /add-to-meal-plan` endpoint that branches on `mode={direct,existing,new,schedule_meal}`. One new helper in `lib/meal_loader.py` for idempotent sub-recipe append. The composite-meal data model and CRUD API already exist; the meal-planner sidebar Meals tab is already implemented and out of scope.

**Tech Stack:** Python 3.11, Flask, pytest. Reuses `lib/meal_loader` (composite meal I/O), `lib/meal_plan_parser.insert_recipe_into_meal_plan` (slot insertion), and existing CSS palette / `error_page` helper from `api_server.py`.

**Design doc:** `docs/plans/2026-05-01-recipe-button-meal-builder-design.md`

**Important context:**
- Surface 2 from the design doc (Meals tab in `/meal-planner` sidebar) is already shipped — `templates/meal_planner.html` already has the tab toggle, meals list, drag-drop, and a meal editor modal. Do not re-implement it.
- The current single-screen form lives at `api_server.py:825-935`. The `mode=direct` branch must be byte-identical to today's behavior — preserve it via a private helper, not a rewrite.
- Run the API server tests with `.venv/bin/python -m pytest tests/test_api_server.py -v` (no extra config needed).
- Run all of the meal-loader tests with `.venv/bin/python -m pytest tests/test_meal_loader.py -v`.

---

## Phase 1 — `lib/meal_loader.append_sub_recipe` helper

### Task 1.1: Write the failing tests

**Files:**
- Modify: `tests/test_meal_loader.py` — append at the end of the file.

**Step 1: Write the failing tests**

Append to `tests/test_meal_loader.py`:

```python
from lib.meal_loader import append_sub_recipe


def test_append_sub_recipe_to_empty_meal():
    meal = Meal(name="Empty", sub_recipes=[])
    result = append_sub_recipe(meal, recipe_name="Pan-Seared Salmon")
    assert result is meal  # in-place mutation returns same object
    assert meal.sub_recipes == [SubRecipe(recipe="Pan-Seared Salmon", servings=1)]


def test_append_sub_recipe_to_existing_meal():
    meal = Meal(
        name="Salmon Dinner",
        sub_recipes=[SubRecipe(recipe="Pan-Seared Salmon", servings=1)],
    )
    append_sub_recipe(meal, recipe_name="Lemon Asparagus")
    assert meal.sub_recipes == [
        SubRecipe(recipe="Pan-Seared Salmon", servings=1),
        SubRecipe(recipe="Lemon Asparagus", servings=1),
    ]


def test_append_sub_recipe_idempotent_on_duplicate():
    meal = Meal(
        name="Dinner",
        sub_recipes=[SubRecipe(recipe="Pan-Seared Salmon", servings=1)],
    )
    append_sub_recipe(meal, recipe_name="Pan-Seared Salmon")
    append_sub_recipe(meal, recipe_name="Pan-Seared Salmon")
    assert meal.sub_recipes == [SubRecipe(recipe="Pan-Seared Salmon", servings=1)]


def test_append_sub_recipe_custom_servings():
    meal = Meal(name="Dinner", sub_recipes=[])
    append_sub_recipe(meal, recipe_name="Wild Rice Pilaf", servings=2)
    assert meal.sub_recipes == [SubRecipe(recipe="Wild Rice Pilaf", servings=2)]
```

**Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_meal_loader.py -v -k append_sub_recipe`

Expected: 4 errors with `ImportError: cannot import name 'append_sub_recipe' from 'lib.meal_loader'`.

### Task 1.2: Implement `append_sub_recipe`

**Files:**
- Modify: `lib/meal_loader.py` — add the helper after the `Meal` dataclass (around line 50).

**Step 1: Add the helper**

Insert after the `Meal` dataclass `to_dict` method in `lib/meal_loader.py`:

```python
def append_sub_recipe(meal: Meal, recipe_name: str, servings: int = 1) -> Meal:
    """Append a SubRecipe to ``meal.sub_recipes`` in place.

    No-op if a SubRecipe with the same ``recipe`` name is already present —
    callers should treat the operation as idempotent. Returns the same Meal
    instance to allow chaining.
    """
    if any(s.recipe == recipe_name for s in meal.sub_recipes):
        return meal
    meal.sub_recipes.append(SubRecipe(recipe=recipe_name, servings=servings))
    return meal
```

**Step 2: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_meal_loader.py -v`

Expected: ALL meal_loader tests pass (existing + 4 new). Confirm no regressions on the existing tests.

### Task 1.3: Commit

```bash
git add lib/meal_loader.py tests/test_meal_loader.py
git commit -m "$(cat <<'EOF'
feat(meal_loader): add idempotent append_sub_recipe helper

Used by the recipe-button add-to-meal flow to add a recipe to an
existing meal definition without duplicating sub_recipes.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 2 — Refactor existing `/add-to-meal-plan` (preserve `mode=direct`)

The existing `add_to_meal_plan_form` (GET, `api_server.py:825-882`) and `add_to_meal_plan` (POST, `api_server.py:885-935`) both need to be split into helpers so the branching can be added without touching the direct path. **No behavior change in this phase.**

### Task 2.1: Write a regression test for the current direct flow

**Files:**
- Modify: `tests/test_api_server.py` — append a new test class.

**Step 1: Write the test**

Append to `tests/test_api_server.py`:

```python
class TestAddToMealPlanDirect:
    """Regression guard for the existing direct schedule flow."""

    def test_direct_schedules_recipe(self, client, tmp_path, monkeypatch):
        plans_dir = tmp_path / "Meal Plans"
        plans_dir.mkdir()
        monkeypatch.setattr('api_server.MEAL_PLANS_PATH', plans_dir)

        response = client.post('/add-to-meal-plan', data={
            'recipe': 'Pan-Seared Salmon',
            'mode': 'direct',
            'week': '2026-W18',
            'day': 'Monday',
            'meal': 'Dinner',
        })

        assert response.status_code == 200
        assert b'Added!' in response.data
        plan_file = plans_dir / "2026-W18.md"
        assert plan_file.exists()
        assert '[[Pan-Seared Salmon]]' in plan_file.read_text()

    def test_direct_without_mode_param_still_works(self, client, tmp_path, monkeypatch):
        """Backwards compat: forms posted without 'mode' default to direct."""
        plans_dir = tmp_path / "Meal Plans"
        plans_dir.mkdir()
        monkeypatch.setattr('api_server.MEAL_PLANS_PATH', plans_dir)

        response = client.post('/add-to-meal-plan', data={
            'recipe': 'Pan-Seared Salmon',
            'week': '2026-W18',
            'day': 'Monday',
            'meal': 'Dinner',
        })

        assert response.status_code == 200
        assert b'Added!' in response.data
```

**Step 2: Run the tests to verify they pass on the current code**

Run: `.venv/bin/python -m pytest tests/test_api_server.py -v -k AddToMealPlanDirect`

Expected: Both tests PASS (the second one may fail if the current handler rejects unknown form fields — if so, mark this expectation in step 3).

If the second test fails because the current code does not accept missing `mode`, that is fine for now — the refactor in Task 2.2 will add the `mode` default. Update the test docstring to note this if needed.

### Task 2.2: Refactor — extract `_render_add_form` and `_schedule_recipe_directly`

**Files:**
- Modify: `api_server.py:825-935` — replace the two existing route handlers with the refactored versions.

**Step 1: Replace the two handlers**

In `api_server.py`, replace lines 825-935 with the following. Take care to preserve the exact HTML, CSS, and copy from the original (success page included).

```python
# ----- Add to Meal Plan (recipe button) -----

def _list_meal_names() -> list[str]:
    """Sorted meal names from vault/Meals/, used by the form."""
    return [m.name for m in meal_loader.list_meals()]


def _generate_week_options(weeks_ahead: int = 4) -> list[str]:
    from datetime import date
    today = date.today()
    weeks: list[str] = []
    for i in range(weeks_ahead):
        d = today + timedelta(days=7 * i)
        iso = d.isocalendar()
        weeks.append(f"{iso[0]}-W{iso[1]:02d}")
    return weeks


def _render_add_form(recipe_display: str, error: str | None = None) -> str:
    """Screen 1: branch picker + conditional fields."""
    weeks = _generate_week_options()
    days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    meals = ['Breakfast', 'Lunch', 'Snack', 'Dinner']
    meal_names = _list_meal_names()

    week_options = ''.join(f'<option value="{w}">{w}</option>' for w in weeks)
    day_options = ''.join(f'<option value="{d}">{d}</option>' for d in days)
    meal_options = ''.join(f'<option value="{m}">{m}</option>' for m in meals)
    meal_name_options = ''.join(f'<option value="{n}">{n}</option>' for n in meal_names)

    has_meals = bool(meal_names)
    existing_disabled = '' if has_meals else 'disabled'
    existing_label = 'Add to an existing meal' if has_meals else 'Add to an existing meal (none yet)'

    error_html = (
        f'<div class="error">{error}</div>' if error else ''
    )

    return f'''<!DOCTYPE html>
<html><head>
<title>Add to Meal Plan</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
    body {{ font-family: system-ui; padding: 1.5rem; max-width: 480px; margin: 0 auto; background: #fafafa; }}
    h2 {{ margin-top: 0; }}
    .recipe-name {{ background: #f0f0f0; padding: 0.75rem; border-radius: 8px; margin-bottom: 1.5rem; font-weight: 600; }}
    .error {{ background: #fee; border: 1px solid #c00; color: #c00; padding: 0.75rem; border-radius: 8px; margin-bottom: 1rem; }}
    .branch {{ display: block; padding: 0.75rem; margin-bottom: 0.5rem; border: 1px solid #ddd; border-radius: 8px; cursor: pointer; background: white; }}
    .branch input[type="radio"] {{ margin-right: 0.5rem; }}
    .branch.disabled {{ opacity: 0.5; cursor: not-allowed; }}
    .fields {{ display: none; margin-top: 1rem; }}
    .fields.active {{ display: block; }}
    label {{ display: block; font-weight: 600; margin-bottom: 0.25rem; margin-top: 1rem; }}
    select, input[type="text"] {{ width: 100%; padding: 0.75rem; font-size: 16px; border: 1px solid #ccc; border-radius: 8px; background: white; -webkit-appearance: none; box-sizing: border-box; }}
    button {{ width: 100%; padding: 1rem; font-size: 18px; font-weight: 600; background: #2563eb; color: white; border: none; border-radius: 8px; margin-top: 1.5rem; cursor: pointer; }}
    button:active {{ background: #1d4ed8; }}
</style>
</head>
<body>
<h2>Add to Meal Plan</h2>
<div class="recipe-name">{recipe_display}</div>
{error_html}
<form method="POST" action="/add-to-meal-plan">
    <input type="hidden" name="recipe" value="{recipe_display}">

    <label class="branch"><input type="radio" name="mode" value="direct" checked onchange="toggleFields(this.value)">Schedule directly</label>
    <label class="branch {('disabled' if not has_meals else '')}"><input type="radio" name="mode" value="existing" {existing_disabled} onchange="toggleFields(this.value)">{existing_label}</label>
    <label class="branch"><input type="radio" name="mode" value="new" onchange="toggleFields(this.value)">Start a new meal</label>

    <div id="fields-direct" class="fields active">
        <label for="week">Week</label>
        <select name="week" id="week">{week_options}</select>
        <label for="day">Day</label>
        <select name="day" id="day">{day_options}</select>
        <label for="meal">Meal</label>
        <select name="meal" id="meal">{meal_options}</select>
    </div>

    <div id="fields-existing" class="fields">
        <label for="meal_name_existing">Meal</label>
        <select name="meal_name" id="meal_name_existing" form="ignored">{meal_name_options}</select>
    </div>

    <div id="fields-new" class="fields">
        <label for="meal_name_new">New meal name</label>
        <input type="text" name="meal_name" id="meal_name_new" placeholder="e.g. Salmon Dinner" form="ignored">
    </div>

    <button type="submit">Submit</button>
</form>

<script>
    function toggleFields(mode) {{
        ['direct', 'existing', 'new'].forEach(function(m) {{
            var el = document.getElementById('fields-' + m);
            if (!el) return;
            el.classList.toggle('active', m === mode);
            // Re-attach the active panel's name=meal_name input to the form,
            // and detach the inactive ones (so only one meal_name is posted).
            el.querySelectorAll('[form]').forEach(function(input) {{
                if (m === mode) input.removeAttribute('form');
                else input.setAttribute('form', 'ignored');
            }});
        }});
    }}
    // Sync on initial load (covers back-button restoration).
    document.addEventListener('DOMContentLoaded', function() {{
        var checked = document.querySelector('input[name="mode"]:checked');
        if (checked) toggleFields(checked.value);
    }});
</script>
</body></html>'''


def _success_page_for_wikilink(wikilink_target: str, day: str, meal: str, week: str) -> str:
    """Green confirmation card after a slot insert. Works for [[Recipe]] or [[Meal: X]]."""
    from urllib.parse import quote
    encoded_file = quote(f"Meal Plans/{week}", safe='')
    return f'''<!DOCTYPE html>
<html><head><title>KitchenOS</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
</head>
<body style="font-family: system-ui; padding: 2rem; max-width: 600px; margin: 0 auto;">
<div style="background: #efe; border: 1px solid #0a0; padding: 1rem; border-radius: 8px;">
<strong style="color: #0a0;">Added!</strong><br>
[[{wikilink_target}]] &rarr; {day} {meal} ({week})
</div>
<p><a href="obsidian://open?vault=KitchenOS&file={encoded_file}">View Meal Plan</a></p>
<p><a href="obsidian://open?vault=KitchenOS">Back to Obsidian</a></p>
</body></html>'''


def _schedule_recipe_directly(recipe: str, week: str, day: str, meal: str):
    """The original direct flow, extracted unchanged."""
    try:
        parts = week.split('-W')
        year = int(parts[0])
        week_num = int(parts[1])
    except (ValueError, IndexError):
        return error_page(f"Error: Invalid week format: {week}"), 400

    MEAL_PLANS_PATH.mkdir(parents=True, exist_ok=True)
    plan_file = MEAL_PLANS_PATH / f"{week}.md"

    if not plan_file.exists():
        content = generate_meal_plan_markdown(year, week_num)
        plan_file.write_text(content, encoding='utf-8')

    content = plan_file.read_text(encoding='utf-8')
    try:
        new_content = insert_recipe_into_meal_plan(content, day, meal, recipe)
    except ValueError as e:
        return error_page(f"Error: {str(e)}"), 400

    plan_file.write_text(new_content, encoding='utf-8')
    return _success_page_for_wikilink(recipe, day, meal, week)


@app.route('/add-to-meal-plan', methods=['GET'])
def add_to_meal_plan_form():
    """Screen 1 — branch picker."""
    from urllib.parse import unquote
    recipe = request.args.get('recipe')
    if not recipe:
        return error_page("Error: recipe parameter required"), 400
    recipe_display = unquote(recipe).replace('.md', '')
    return _render_add_form(recipe_display)


@app.route('/add-to-meal-plan', methods=['POST'])
def add_to_meal_plan():
    """Branches on `mode`. Modes: direct, existing, new, schedule_meal."""
    recipe = request.form.get('recipe')
    mode = request.form.get('mode', 'direct')

    if not recipe:
        return error_page("Error: recipe parameter required"), 400

    if mode == 'direct':
        week = request.form.get('week')
        day = request.form.get('day')
        meal = request.form.get('meal')
        if not all([week, day, meal]):
            return error_page("Error: recipe, week, day, and meal are all required"), 400
        return _schedule_recipe_directly(recipe, week, day, meal)

    return error_page(f"Unknown mode: {mode}"), 400
```

**Step 2: Run the regression tests + meal_loader tests**

Run: `.venv/bin/python -m pytest tests/test_api_server.py tests/test_meal_loader.py -v`

Expected: All previously-passing tests still pass. New `TestAddToMealPlanDirect` tests pass. The new `_render_add_form` is wired up but only the `direct` mode submits cleanly — the other modes return "Unknown mode" until later phases.

**Step 3: Manual smoke test**

Start the API server (or restart the LaunchAgent):
```bash
launchctl unload ~/Library/LaunchAgents/com.kitchenos.api.plist
launchctl load ~/Library/LaunchAgents/com.kitchenos.api.plist
```

Open in browser: `http://localhost:5001/add-to-meal-plan?recipe=Pan-Seared%20Salmon`

Verify:
- Three radios visible, "Schedule directly" is checked.
- Clicking "Start a new meal" hides week/day/meal and shows the name input.
- If `vault/Meals/` is empty, the "existing" radio is disabled.
- Submitting in `direct` mode still inserts the wikilink and shows the green success card.

### Task 2.3: Commit

```bash
git add api_server.py tests/test_api_server.py
git commit -m "$(cat <<'EOF'
refactor(api): split add-to-meal-plan into branched form + handler

Pulls the form HTML and direct-schedule flow into private helpers so
upcoming meal-builder branches can share them without touching the
shipped behavior. No user-visible change beyond the new (currently
inert) radio buttons for "existing meal" and "new meal".

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 3 — `mode=existing` branch

### Task 3.1: Write the failing tests

**Files:**
- Modify: `tests/test_api_server.py` — append.

**Step 1: Write the tests**

```python
class TestAddToMealPlanExisting:
    """mode=existing — append a recipe to an existing meal."""

    def test_appends_recipe_to_existing_meal(self, client, tmp_path, monkeypatch):
        meals_dir = tmp_path / "Meals"
        meals_dir.mkdir()
        # Seed a meal with one sub-recipe.
        from lib import meal_loader as ml
        ml.save_meal(
            ml.Meal(name="Salmon Dinner",
                    sub_recipes=[ml.SubRecipe(recipe="Pan-Seared Salmon", servings=1)]),
            meals_dir=meals_dir,
        )
        monkeypatch.setattr('lib.meal_loader.paths.meals_dir', lambda: meals_dir)

        response = client.post('/add-to-meal-plan', data={
            'recipe': 'Lemon Asparagus',
            'mode': 'existing',
            'meal_name': 'Salmon Dinner',
        })

        assert response.status_code == 200
        # Schedule prompt is rendered after success.
        assert b'Schedule it now?' in response.data
        # File now has 2 sub-recipes.
        loaded = ml.load_meal('Salmon Dinner', meals_dir=meals_dir)
        assert [s.recipe for s in loaded.sub_recipes] == ['Pan-Seared Salmon', 'Lemon Asparagus']

    def test_idempotent_when_recipe_already_in_meal(self, client, tmp_path, monkeypatch):
        meals_dir = tmp_path / "Meals"
        meals_dir.mkdir()
        from lib import meal_loader as ml
        ml.save_meal(
            ml.Meal(name="Dinner",
                    sub_recipes=[ml.SubRecipe(recipe="Pan-Seared Salmon", servings=1)]),
            meals_dir=meals_dir,
        )
        monkeypatch.setattr('lib.meal_loader.paths.meals_dir', lambda: meals_dir)

        response = client.post('/add-to-meal-plan', data={
            'recipe': 'Pan-Seared Salmon',
            'mode': 'existing',
            'meal_name': 'Dinner',
        })

        assert response.status_code == 200
        assert b'already in' in response.data.lower()
        loaded = ml.load_meal('Dinner', meals_dir=meals_dir)
        assert len(loaded.sub_recipes) == 1  # no duplicate

    def test_meal_not_found_re_renders_form_with_error(self, client, tmp_path, monkeypatch):
        meals_dir = tmp_path / "Meals"
        meals_dir.mkdir()
        monkeypatch.setattr('lib.meal_loader.paths.meals_dir', lambda: meals_dir)

        response = client.post('/add-to-meal-plan', data={
            'recipe': 'Lemon Asparagus',
            'mode': 'existing',
            'meal_name': 'Does Not Exist',
        })

        # Re-rendered Screen 1 with an inline error.
        assert b'Add to Meal Plan' in response.data
        assert b'Meal not found' in response.data
```

**Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_api_server.py -v -k AddToMealPlanExisting`

Expected: All three FAIL — the handler currently returns "Unknown mode: existing" → 400.

### Task 3.2: Implement `mode=existing`

**Files:**
- Modify: `api_server.py` — extend the `add_to_meal_plan` POST handler with the `existing` branch and add `_render_schedule_prompt`.

**Step 1: Add the schedule-prompt renderer**

Insert above the `_schedule_recipe_directly` function in `api_server.py`:

```python
def _render_schedule_prompt(recipe: str, meal_name: str, action: str, info: str | None = None) -> str:
    """Screen 2 — hybrid optional schedule prompt after meal save."""
    from urllib.parse import quote
    weeks = _generate_week_options()
    days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    meals = ['Breakfast', 'Lunch', 'Snack', 'Dinner']
    week_options = ''.join(f'<option value="{w}">{w}</option>' for w in weeks)
    day_options = ''.join(f'<option value="{d}">{d}</option>' for d in days)
    meal_options = ''.join(f'<option value="{m}">{m}</option>' for m in meals)
    encoded_meal = quote(f"Meals/{meal_name}", safe='')

    if action == 'created':
        banner = f'Created meal &ldquo;{meal_name}&rdquo; with {recipe}.'
    elif action == 'added':
        banner = f'Added {recipe} to &ldquo;{meal_name}&rdquo;.'
    else:
        banner = f'Saved &ldquo;{meal_name}&rdquo;.'

    info_html = f'<div class="info">{info}</div>' if info else ''

    return f'''<!DOCTYPE html>
<html><head>
<title>Schedule Meal</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
    body {{ font-family: system-ui; padding: 1.5rem; max-width: 480px; margin: 0 auto; background: #fafafa; }}
    .ok {{ background: #efe; border: 1px solid #0a0; color: #060; padding: 0.75rem; border-radius: 8px; margin-bottom: 1rem; }}
    .info {{ background: #eef; border: 1px solid #66c; color: #336; padding: 0.5rem 0.75rem; border-radius: 8px; margin-bottom: 1rem; font-size: 14px; }}
    h3 {{ margin-top: 0.5rem; }}
    label {{ display: block; font-weight: 600; margin-bottom: 0.25rem; margin-top: 1rem; }}
    select {{ width: 100%; padding: 0.75rem; font-size: 16px; border: 1px solid #ccc; border-radius: 8px; background: white; -webkit-appearance: none; }}
    button {{ width: 100%; padding: 1rem; font-size: 18px; font-weight: 600; background: #2563eb; color: white; border: none; border-radius: 8px; margin-top: 1.5rem; cursor: pointer; }}
    .skip {{ display: block; text-align: center; margin-top: 1rem; color: #666; }}
</style>
</head>
<body>
<div class="ok"><strong>&#10003;</strong> {banner}</div>
{info_html}
<h3>Schedule it now? <span style="font-weight: 400; color: #888;">(optional)</span></h3>
<form method="POST" action="/add-to-meal-plan">
    <input type="hidden" name="recipe" value="{recipe}">
    <input type="hidden" name="mode" value="schedule_meal">
    <input type="hidden" name="meal_name" value="{meal_name}">
    <label for="week">Week</label>
    <select name="week" id="week">{week_options}</select>
    <label for="day">Day</label>
    <select name="day" id="day">{day_options}</select>
    <label for="meal">Slot</label>
    <select name="meal" id="meal">{meal_options}</select>
    <button type="submit">Schedule meal</button>
</form>
<a class="skip" href="obsidian://open?vault=KitchenOS&file={encoded_meal}">Skip &mdash; open in Obsidian</a>
</body></html>'''
```

**Step 2: Add the `existing` branch to `add_to_meal_plan`**

Insert the following block in `add_to_meal_plan`, immediately before the final `return error_page(f"Unknown mode: {mode}"), 400`:

```python
    if mode == 'existing':
        meal_name = (request.form.get('meal_name') or '').strip()
        if not meal_name:
            recipe_display = recipe.replace('.md', '')
            return _render_add_form(recipe_display, error="Pick a meal."), 400
        meal = meal_loader.load_meal(meal_name)
        if meal is None:
            recipe_display = recipe.replace('.md', '')
            return _render_add_form(recipe_display, error=f'Meal not found: "{meal_name}".'), 404
        already_present = any(s.recipe == recipe for s in meal.sub_recipes)
        meal_loader.append_sub_recipe(meal, recipe_name=recipe)
        meal_loader.save_meal(meal)
        info = f'{recipe} is already in this meal.' if already_present else None
        return _render_schedule_prompt(recipe, meal_name, action='added', info=info)
```

**Step 3: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_api_server.py -v -k AddToMealPlanExisting`

Expected: All three PASS.

### Task 3.3: Commit

```bash
git add api_server.py tests/test_api_server.py
git commit -m "$(cat <<'EOF'
feat(api): add to existing meal from recipe button

POST /add-to-meal-plan with mode=existing appends the recipe to the
named meal (idempotent) and renders the optional schedule prompt.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 4 — `mode=new` branch (create new meal)

### Task 4.1: Write the failing tests

**Files:**
- Modify: `tests/test_api_server.py` — append.

**Step 1: Write the tests**

```python
class TestAddToMealPlanNew:
    """mode=new — create a new meal seeded with the current recipe."""

    def test_creates_new_meal_with_seed_recipe(self, client, tmp_path, monkeypatch):
        meals_dir = tmp_path / "Meals"
        meals_dir.mkdir()
        monkeypatch.setattr('lib.meal_loader.paths.meals_dir', lambda: meals_dir)

        response = client.post('/add-to-meal-plan', data={
            'recipe': 'Pan-Seared Salmon',
            'mode': 'new',
            'meal_name': 'Salmon Dinner',
        })

        assert response.status_code == 200
        assert b'Schedule it now?' in response.data
        from lib import meal_loader as ml
        loaded = ml.load_meal('Salmon Dinner', meals_dir=meals_dir)
        assert loaded is not None
        assert [s.recipe for s in loaded.sub_recipes] == ['Pan-Seared Salmon']

    def test_empty_meal_name_re_renders_with_error(self, client, tmp_path, monkeypatch):
        meals_dir = tmp_path / "Meals"
        meals_dir.mkdir()
        monkeypatch.setattr('lib.meal_loader.paths.meals_dir', lambda: meals_dir)

        response = client.post('/add-to-meal-plan', data={
            'recipe': 'Pan-Seared Salmon',
            'mode': 'new',
            'meal_name': '   ',
        })

        assert b'Meal name is required' in response.data
        assert response.status_code == 400

    def test_collision_re_renders_with_error(self, client, tmp_path, monkeypatch):
        meals_dir = tmp_path / "Meals"
        meals_dir.mkdir()
        from lib import meal_loader as ml
        ml.save_meal(
            ml.Meal(name="Salmon Dinner",
                    sub_recipes=[ml.SubRecipe(recipe="Pan-Seared Salmon")]),
            meals_dir=meals_dir,
        )
        monkeypatch.setattr('lib.meal_loader.paths.meals_dir', lambda: meals_dir)

        response = client.post('/add-to-meal-plan', data={
            'recipe': 'Lemon Asparagus',
            'mode': 'new',
            'meal_name': 'Salmon Dinner',
        })

        assert response.status_code == 409
        assert b'already exists' in response.data

    def test_filesystem_unsafe_name_re_renders_with_error(self, client, tmp_path, monkeypatch):
        meals_dir = tmp_path / "Meals"
        meals_dir.mkdir()
        monkeypatch.setattr('lib.meal_loader.paths.meals_dir', lambda: meals_dir)

        response = client.post('/add-to-meal-plan', data={
            'recipe': 'Pan-Seared Salmon',
            'mode': 'new',
            'meal_name': 'Bad/Name',
        })

        assert response.status_code == 400
        assert b"can't contain" in response.data or b'can&#39;t contain' in response.data
```

**Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_api_server.py -v -k AddToMealPlanNew`

Expected: All four FAIL.

### Task 4.2: Implement `mode=new` (with name validation)

**Files:**
- Modify: `api_server.py` — add a validator and the `new` branch.

**Step 1: Add a name validator**

Insert above `_render_add_form` in `api_server.py`:

```python
_INVALID_MEAL_NAME_CHARS = ('/', ':', '\\')


def _validate_meal_name(name: str) -> str | None:
    """Return an error message if the name is invalid, else None."""
    name = name.strip()
    if not name:
        return "Meal name is required."
    if name.startswith('.'):
        return "Meal name can't start with a dot."
    for ch in _INVALID_MEAL_NAME_CHARS:
        if ch in name:
            return "Meal name can't contain / : or \\."
    return None
```

**Step 2: Add the `new` branch**

Insert in `add_to_meal_plan`, immediately before the existing `Unknown mode` return:

```python
    if mode == 'new':
        meal_name = (request.form.get('meal_name') or '').strip()
        recipe_display = recipe.replace('.md', '')
        err = _validate_meal_name(meal_name)
        if err:
            return _render_add_form(recipe_display, error=err), 400
        if meal_loader.load_meal(meal_name) is not None:
            return _render_add_form(
                recipe_display,
                error=f'A meal called "{meal_name}" already exists.'
            ), 409
        meal = meal_loader.Meal(
            name=meal_name,
            sub_recipes=[meal_loader.SubRecipe(recipe=recipe, servings=1)],
        )
        meal_loader.save_meal(meal)
        return _render_schedule_prompt(recipe, meal_name, action='created')
```

**Step 3: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_api_server.py -v -k AddToMealPlanNew`

Expected: All four PASS.

### Task 4.3: Commit

```bash
git add api_server.py tests/test_api_server.py
git commit -m "$(cat <<'EOF'
feat(api): create new meal from recipe button

POST /add-to-meal-plan with mode=new creates a vault/Meals/<name>.meal.md
seeded with the current recipe and renders the optional schedule prompt.
Validates meal name (non-empty, no path separators, no leading dot) and
fails with 409 on collision.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 5 — `mode=schedule_meal` (Screen 2 submit)

### Task 5.1: Write the failing tests

**Files:**
- Modify: `tests/test_api_server.py` — append.

**Step 1: Write the tests**

```python
class TestScheduleMeal:
    """mode=schedule_meal — Screen 2 submit. Inserts [[Meal: X]] into the plan."""

    def test_inserts_meal_token_into_plan(self, client, tmp_path, monkeypatch):
        plans_dir = tmp_path / "Meal Plans"
        plans_dir.mkdir()
        monkeypatch.setattr('api_server.MEAL_PLANS_PATH', plans_dir)

        response = client.post('/add-to-meal-plan', data={
            'recipe': 'Pan-Seared Salmon',  # carried through, not used here
            'mode': 'schedule_meal',
            'meal_name': 'Salmon Dinner',
            'week': '2026-W19',
            'day': 'Tuesday',
            'meal': 'Dinner',
        })

        assert response.status_code == 200
        assert b'Added!' in response.data
        plan_text = (plans_dir / "2026-W19.md").read_text()
        assert '[[Meal: Salmon Dinner]]' in plan_text
        # The wikilink is NOT a plain recipe link.
        assert '[[Pan-Seared Salmon]]' not in plan_text

    def test_invalid_week_returns_error(self, client, tmp_path, monkeypatch):
        plans_dir = tmp_path / "Meal Plans"
        plans_dir.mkdir()
        monkeypatch.setattr('api_server.MEAL_PLANS_PATH', plans_dir)

        response = client.post('/add-to-meal-plan', data={
            'recipe': 'X',
            'mode': 'schedule_meal',
            'meal_name': 'Salmon Dinner',
            'week': 'not-a-week',
            'day': 'Tuesday',
            'meal': 'Dinner',
        })

        assert response.status_code == 400
        assert b'Invalid week format' in response.data
```

**Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_api_server.py -v -k ScheduleMeal`

Expected: Both FAIL.

### Task 5.2: Implement `mode=schedule_meal`

**Files:**
- Modify: `api_server.py` — add the branch.

**Step 1: Add a small helper that inserts a meal token**

Insert above `_schedule_recipe_directly`:

```python
def _schedule_meal_token(meal_name: str, week: str, day: str, meal: str):
    """Insert ``[[Meal: <meal_name>]]`` into the plan slot. Mirrors _schedule_recipe_directly."""
    try:
        parts = week.split('-W')
        year = int(parts[0])
        week_num = int(parts[1])
    except (ValueError, IndexError):
        return error_page(f"Error: Invalid week format: {week}"), 400

    MEAL_PLANS_PATH.mkdir(parents=True, exist_ok=True)
    plan_file = MEAL_PLANS_PATH / f"{week}.md"
    if not plan_file.exists():
        content = generate_meal_plan_markdown(year, week_num)
        plan_file.write_text(content, encoding='utf-8')

    content = plan_file.read_text(encoding='utf-8')
    token = f"Meal: {meal_name}"
    try:
        new_content = insert_recipe_into_meal_plan(content, day, meal, token)
    except ValueError as e:
        return error_page(f"Error: {str(e)}"), 400

    plan_file.write_text(new_content, encoding='utf-8')
    return _success_page_for_wikilink(token, day, meal, week)
```

**Step 2: Add the branch in `add_to_meal_plan`**

Insert in `add_to_meal_plan`, immediately before the `Unknown mode` return:

```python
    if mode == 'schedule_meal':
        meal_name = (request.form.get('meal_name') or '').strip()
        week = request.form.get('week')
        day = request.form.get('day')
        meal = request.form.get('meal')
        if not all([meal_name, week, day, meal]):
            return error_page("Error: meal_name, week, day, and meal are all required"), 400
        return _schedule_meal_token(meal_name, week, day, meal)
```

**Step 3: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_api_server.py -v -k ScheduleMeal`

Expected: Both PASS.

### Task 5.3: Run the full suite

Run: `.venv/bin/python -m pytest tests/test_api_server.py tests/test_meal_loader.py -v`

Expected: All tests pass — direct, existing, new, schedule_meal, plus the original tests.

### Task 5.4: Commit

```bash
git add api_server.py tests/test_api_server.py
git commit -m "$(cat <<'EOF'
feat(api): schedule built meal from the schedule prompt

POST /add-to-meal-plan with mode=schedule_meal inserts [[Meal: <name>]]
into the chosen day/slot and reuses the existing green confirmation
card. Wraps up the recipe-button meal-builder flow.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 6 — Form-render assertions + manual smoke

### Task 6.1: Test the form render

**Files:**
- Modify: `tests/test_api_server.py` — append.

**Step 1: Write the tests**

```python
class TestAddToMealPlanFormRender:
    """GET /add-to-meal-plan — branch picker form."""

    def test_form_lists_three_radios(self, client, tmp_path, monkeypatch):
        meals_dir = tmp_path / "Meals"
        meals_dir.mkdir()
        monkeypatch.setattr('lib.meal_loader.paths.meals_dir', lambda: meals_dir)

        response = client.get('/add-to-meal-plan?recipe=Pan-Seared%20Salmon')
        body = response.data
        assert response.status_code == 200
        assert b'Pan-Seared Salmon' in body
        assert b'value="direct"' in body
        assert b'value="existing"' in body
        assert b'value="new"' in body
        # Default selection
        assert b'value="direct" checked' in body

    def test_existing_disabled_when_no_meals(self, client, tmp_path, monkeypatch):
        meals_dir = tmp_path / "Meals"
        meals_dir.mkdir()
        monkeypatch.setattr('lib.meal_loader.paths.meals_dir', lambda: meals_dir)

        response = client.get('/add-to-meal-plan?recipe=X')
        # The existing radio is rendered with `disabled`.
        assert b'value="existing" disabled' in response.data
        assert b'(none yet)' in response.data

    def test_existing_enabled_when_meals_exist(self, client, tmp_path, monkeypatch):
        meals_dir = tmp_path / "Meals"
        meals_dir.mkdir()
        from lib import meal_loader as ml
        ml.save_meal(
            ml.Meal(name="Salmon Dinner",
                    sub_recipes=[ml.SubRecipe(recipe="Pan-Seared Salmon")]),
            meals_dir=meals_dir,
        )
        monkeypatch.setattr('lib.meal_loader.paths.meals_dir', lambda: meals_dir)

        response = client.get('/add-to-meal-plan?recipe=X')
        assert b'value="existing" disabled' not in response.data
        assert b'<option value="Salmon Dinner">' in response.data
```

**Step 2: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_api_server.py -v -k AddToMealPlanFormRender`

Expected: All three PASS (no implementation change needed — Phase 2 already wired this up).

If they fail because of HTML quirks (attribute order etc.), adjust the assertions to substrings that match what `_render_add_form` actually emits — do NOT change the renderer to match the test.

### Task 6.2: Manual end-to-end smoke

Restart the API server:
```bash
launchctl unload ~/Library/LaunchAgents/com.kitchenos.api.plist
launchctl load ~/Library/LaunchAgents/com.kitchenos.api.plist
curl -s http://localhost:5001/health
```

Open in Obsidian: any recipe → click **Add to Meal Plan**. Walk these scenarios:

1. **Direct path** — pick "Schedule directly", choose a week / day / slot, submit. Verify the green "Added!" page, then confirm the wikilink appears in `Meal Plans/<week>.md`.
2. **Create new meal** — pick "Start a new meal", enter "Test Meal Builder", submit. Verify:
    - The schedule prompt shows the banner "Created meal …".
    - `vault/Meals/Test Meal Builder.meal.md` exists with the recipe in `sub_recipes`.
    - Click **Skip — open in Obsidian** → Obsidian opens the meal file.
3. **Add to existing meal** — from a *different* recipe, pick "Add to an existing meal", select "Test Meal Builder", submit. Verify:
    - Schedule prompt banner reads "Added X to …".
    - The meal file now has 2 sub-recipes.
4. **Idempotent existing** — repeat step 3 with the same recipe. Verify the blue info chip "X is already in this meal" appears and the file still has 2 sub-recipes.
5. **Schedule the meal** — from one of the schedule prompts, pick a week / day / slot and submit. Verify `[[Meal: Test Meal Builder]]` appears in the plan file (not `[[Test Meal Builder]]`).
6. **Downstream sanity** — generate the shopping list for that week and confirm the meal's sub-recipes are aggregated:
    ```bash
    .venv/bin/python shopping_list.py --week <YYYY-WNN> --dry-run
    ```
7. **Cleanup** — delete `vault/Meals/Test Meal Builder.meal.md` and remove the `[[Meal: Test Meal Builder]]` line from the plan.

### Task 6.3: Commit (only if Task 6.1 needed an assertion tweak)

```bash
git add tests/test_api_server.py
git commit -m "$(cat <<'EOF'
test(api): assertions for add-to-meal-plan form rendering

Verifies the three-branch radio layout, the disabled/enabled state of
the existing-meal option, and meal options being rendered.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 7 — Documentation

### Task 7.1: Update `CLAUDE.md`

**Files:**
- Modify: `CLAUDE.md` — Key Functions section under `lib/meal_loader.py` and `api_server.py`.

**Step 1: Add the new helper to `lib/meal_loader.py` Key Functions**

Find the `**lib/meal_loader.py:**` section in `CLAUDE.md` and append:

```markdown
- `append_sub_recipe(meal, recipe_name, servings=1)` - Idempotently append a SubRecipe; no-op if the recipe is already present in the meal.
```

**Step 2: Update the `add_to_meal_plan` Key Function entries under `api_server.py`**

Find the `**api_server.py:**` Key Functions section and replace the two existing meal-plan entries:

Current:
```markdown
- `add_to_meal_plan_form()` - Serves mobile-friendly form to pick week/day/meal
- `add_to_meal_plan()` - Inserts recipe wikilink into meal plan file
```

Replace with:
```markdown
- `add_to_meal_plan_form()` - Serves the mobile-friendly branch picker (Schedule directly / Add to existing meal / Start a new meal).
- `add_to_meal_plan()` - Branches on `mode` (`direct`, `existing`, `new`, `schedule_meal`). Direct/schedule_meal insert wikilinks via `insert_recipe_into_meal_plan`; existing/new mutate `vault/Meals/<name>.meal.md` and render the optional schedule prompt.
```

**Step 3: Note the endpoint contract under "Endpoints"**

Find the table under "Endpoints" in `CLAUDE.md` and add:

```markdown
| `/add-to-meal-plan` (GET/POST) | Recipe-button entry. POST branches on `mode={direct,existing,new,schedule_meal}`. `existing`/`new` end on a hybrid schedule prompt. |
```

### Task 7.2: Verify the dry-run extraction still works

The "Completing Work" checklist requires this. Run:

```bash
.venv/bin/python extract_recipe.py --dry-run "https://www.youtube.com/watch?v=bJUiWdM__Qw"
```

Expected: completes without Python errors. (We haven't touched the extraction pipeline, so this is a regression guard.)

### Task 7.3: Commit

```bash
git add CLAUDE.md
git commit -m "$(cat <<'EOF'
docs(CLAUDE): document the four-mode add-to-meal-plan endpoint

Documents the new branched flow (direct / existing / new / schedule_meal)
and the new meal_loader.append_sub_recipe helper.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Out of Scope (verify before starting)

- The Meals tab in `templates/meal_planner.html` is **already implemented** (sidebar tabs at line 901-904, meals list, drag-drop, meal editor modal at line 944). Do not touch it as part of this plan.
- Editing/removing/reordering sub-recipes — user does this by hand in Obsidian.
- Renaming or deleting meals from KitchenOS UI.
- A `/meals` manager page.

## Files Touched (Summary)

| File | Change |
|------|--------|
| `lib/meal_loader.py` | +`append_sub_recipe()` helper. |
| `api_server.py` | Replace `add_to_meal_plan_form`/`add_to_meal_plan` (lines 825-935) with branched versions; add `_render_add_form`, `_render_schedule_prompt`, `_success_page_for_wikilink`, `_schedule_recipe_directly`, `_schedule_meal_token`, `_validate_meal_name`, `_list_meal_names`, `_generate_week_options` helpers. |
| `tests/test_meal_loader.py` | +4 tests for `append_sub_recipe`. |
| `tests/test_api_server.py` | +4 test classes (`TestAddToMealPlanDirect`, `TestAddToMealPlanExisting`, `TestAddToMealPlanNew`, `TestScheduleMeal`, `TestAddToMealPlanFormRender`). |
| `CLAUDE.md` | Update Key Functions and Endpoints. |
