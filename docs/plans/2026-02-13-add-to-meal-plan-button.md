# Add to Meal Plan Button — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add an "Add to Meal Plan" button to recipe pages that opens a mobile-friendly form to pick a week/day/meal slot, then appends the recipe as a wikilink to that meal plan file.

**Architecture:** New Flask endpoint serves an HTML picker form (GET) and handles submission (POST). The insertion logic lives in `lib/meal_plan_parser.py`. All recipe button URLs migrate from `localhost:5001` to Tailscale IP `100.111.6.10:5001` for iPhone compatibility.

**Tech Stack:** Python/Flask, HTML form, existing meal plan template generator

---

### Task 1: Add `insert_recipe_into_meal_plan()` to meal plan parser

**Files:**
- Modify: `lib/meal_plan_parser.py`
- Test: `tests/test_meal_plan_parser.py`

**Step 1: Write the failing tests**

Add to `tests/test_meal_plan_parser.py`:

```python
from lib.meal_plan_parser import insert_recipe_into_meal_plan


class TestInsertRecipeIntoMealPlan:
    """Test inserting recipe links into meal plan markdown."""

    def test_inserts_into_empty_slot(self):
        content = """# Meal Plan - Week 07

## Monday (Feb 9)
### Breakfast

### Lunch

### Dinner

### Notes

"""
        result = insert_recipe_into_meal_plan(content, "Monday", "Dinner", "Pasta Aglio E Olio")
        assert "### Dinner\n[[Pasta Aglio E Olio]]" in result

    def test_appends_to_existing_recipe(self):
        content = """# Meal Plan - Week 07

## Monday (Feb 9)
### Breakfast

### Lunch

### Dinner
[[Existing Recipe]]
### Notes

"""
        result = insert_recipe_into_meal_plan(content, "Monday", "Dinner", "New Recipe")
        assert "[[Existing Recipe]]" in result
        assert "[[New Recipe]]" in result

    def test_inserts_into_correct_day(self):
        content = """# Meal Plan - Week 07

## Monday (Feb 9)
### Breakfast

### Lunch

### Dinner

### Notes

## Tuesday (Feb 10)
### Breakfast

### Lunch

### Dinner

### Notes

"""
        result = insert_recipe_into_meal_plan(content, "Tuesday", "Breakfast", "Pancakes")
        # Tuesday breakfast should have the recipe
        assert "## Tuesday" in result
        # Monday dinner should still be empty
        monday_section = result.split("## Tuesday")[0]
        assert "[[Pancakes]]" not in monday_section

    def test_case_insensitive_day_and_meal(self):
        content = """# Meal Plan - Week 07

## Monday (Feb 9)
### Breakfast

### Lunch

### Dinner

### Notes

"""
        result = insert_recipe_into_meal_plan(content, "monday", "dinner", "Test Recipe")
        assert "[[Test Recipe]]" in result

    def test_raises_on_invalid_day(self):
        content = "# Meal Plan\n## Monday (Feb 9)\n### Breakfast\n\n### Lunch\n\n### Dinner\n\n### Notes\n"
        with pytest.raises(ValueError, match="Day .* not found"):
            insert_recipe_into_meal_plan(content, "Funday", "Dinner", "Test")

    def test_raises_on_invalid_meal(self):
        content = "# Meal Plan\n## Monday (Feb 9)\n### Breakfast\n\n### Lunch\n\n### Dinner\n\n### Notes\n"
        with pytest.raises(ValueError, match="Meal .* not found"):
            insert_recipe_into_meal_plan(content, "Monday", "Brunch", "Test")
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_meal_plan_parser.py::TestInsertRecipeIntoMealPlan -v`
Expected: FAIL with `ImportError: cannot import name 'insert_recipe_into_meal_plan'`

**Step 3: Write the implementation**

Add to `lib/meal_plan_parser.py`:

```python
def insert_recipe_into_meal_plan(content: str, day: str, meal: str, recipe_name: str) -> str:
    """Insert a recipe wikilink into a meal plan at the specified day and meal slot.

    Args:
        content: Full markdown content of meal plan file
        day: Day name (e.g. "Monday") - case insensitive
        meal: Meal type (e.g. "Dinner") - case insensitive
        recipe_name: Recipe name to insert as [[wikilink]]

    Returns:
        Updated markdown content

    Raises:
        ValueError: If day or meal section not found
    """
    day_title = day.strip().title()
    meal_title = meal.strip().title()

    # Find the day section
    day_pattern = rf'(## {day_title}\s+\([^)]+\))'
    day_match = re.search(day_pattern, content, re.IGNORECASE)
    if not day_match:
        raise ValueError(f"Day '{day_title}' not found in meal plan")

    # Find the meal subsection within the day section
    # We need to find ### {meal} after the day header, then insert before the next ### or ##
    day_start = day_match.start()

    # Find the meal header after this day
    meal_pattern = rf'(### {meal_title})\s*\n'
    meal_match = re.search(meal_pattern, content[day_start:], re.IGNORECASE)
    if not meal_match:
        raise ValueError(f"Meal '{meal_title}' not found under {day_title}")

    # Absolute position of the end of the meal header line
    insert_pos = day_start + meal_match.end()

    # Find the next section header (### or ##) after the meal header
    next_section = re.search(r'^###?\s', content[insert_pos:], re.MULTILINE)
    if next_section:
        section_end = insert_pos + next_section.start()
    else:
        section_end = len(content)

    # Get existing content in this slot
    existing = content[insert_pos:section_end].strip()

    # Build the new content for this slot
    if existing:
        new_slot = f"{existing}\n[[{recipe_name}]]\n"
    else:
        new_slot = f"[[{recipe_name}]]\n"

    # Replace the slot content
    return content[:insert_pos] + new_slot + content[section_end:]
```

**Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_meal_plan_parser.py::TestInsertRecipeIntoMealPlan -v`
Expected: All 6 tests PASS

**Step 5: Commit**

```bash
git add lib/meal_plan_parser.py tests/test_meal_plan_parser.py
git commit -m "feat: add insert_recipe_into_meal_plan() for adding recipes to meal plan slots"
```

---

### Task 2: Update recipe template to use Tailscale IP and add meal plan button

**Files:**
- Modify: `templates/recipe_template.py:10,105-127`
- Test: `tests/test_recipe_template.py`

**Step 1: Write the failing tests**

Add to `tests/test_recipe_template.py`:

```python
from templates.recipe_template import generate_tools_callout, API_BASE_URL


def test_api_base_url_uses_tailscale():
    assert API_BASE_URL == "http://100.111.6.10:5001"


def test_tools_callout_contains_add_to_meal_plan():
    result = generate_tools_callout("Test Recipe.md")
    assert "Add to Meal Plan" in result
    assert "add-to-meal-plan" in result
    assert "recipe=Test%20Recipe.md" in result


def test_tools_callout_uses_tailscale_ip():
    result = generate_tools_callout("Test.md")
    assert "100.111.6.10:5001" in result
    assert "localhost" not in result
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_recipe_template.py::test_api_base_url_uses_tailscale tests/test_recipe_template.py::test_tools_callout_contains_add_to_meal_plan tests/test_recipe_template.py::test_tools_callout_uses_tailscale_ip -v`
Expected: FAIL (URL is still localhost, no meal plan button)

**Step 3: Write the implementation**

In `templates/recipe_template.py`:

1. Change line 10:
```python
API_BASE_URL = "http://100.111.6.10:5001"
```

2. Update `generate_tools_callout()` (lines 105-127) to add the new button:
```python
def generate_tools_callout(filename: str) -> str:
    """Generate the Tools callout block with reprocess buttons."""
    encoded_filename = quote(filename, safe='')
    return f'''> [!tools]- Tools
> ```button
> name Re-extract
> type link
> url {API_BASE_URL}/reprocess?file={encoded_filename}
> ```
> ```button
> name Refresh Template
> type link
> url {API_BASE_URL}/refresh?file={encoded_filename}
> ```
> ```button
> name Add to Meal Plan
> type link
> url {API_BASE_URL}/add-to-meal-plan?recipe={encoded_filename}
> ```

'''
```

**Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_recipe_template.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add templates/recipe_template.py tests/test_recipe_template.py
git commit -m "feat: add meal plan button and migrate URLs to Tailscale IP"
```

---

### Task 3: Add `/add-to-meal-plan` endpoint to API server

**Files:**
- Modify: `api_server.py`
- Test: `tests/test_api_server.py`

**Step 1: Write the failing tests**

Add to `tests/test_api_server.py`:

```python
class TestAddToMealPlan:
    """Tests for the add-to-meal-plan endpoint."""

    def test_get_returns_form_html(self, client):
        """GET should return an HTML form."""
        response = client.get('/add-to-meal-plan?recipe=Test%20Recipe.md')
        assert response.status_code == 200
        assert b'Test Recipe' in response.data
        assert b'<form' in response.data
        assert b'Breakfast' in response.data

    def test_get_missing_recipe_returns_error(self, client):
        """GET without recipe param should return 400."""
        response = client.get('/add-to-meal-plan')
        assert response.status_code == 400

    def test_post_adds_recipe_to_meal_plan(self, tmp_path):
        """POST should append recipe wikilink to meal plan file."""
        from templates.meal_plan_template import generate_meal_plan_markdown

        meal_plans_path = tmp_path / "Meal Plans"
        meal_plans_path.mkdir()
        plan_file = meal_plans_path / "2026-W07.md"
        plan_file.write_text(generate_meal_plan_markdown(2026, 7))

        with patch('api_server.MEAL_PLANS_PATH', meal_plans_path):
            with app.test_client() as client:
                response = client.post('/add-to-meal-plan', data={
                    'recipe': 'Pasta Aglio E Olio',
                    'week': '2026-W07',
                    'day': 'Monday',
                    'meal': 'Dinner'
                })

        assert response.status_code == 200
        assert b'Success' in response.data
        content = plan_file.read_text()
        assert '[[Pasta Aglio E Olio]]' in content

    def test_post_creates_meal_plan_if_missing(self, tmp_path):
        """POST should create meal plan file if it doesn't exist."""
        meal_plans_path = tmp_path / "Meal Plans"
        meal_plans_path.mkdir()

        with patch('api_server.MEAL_PLANS_PATH', meal_plans_path):
            with app.test_client() as client:
                response = client.post('/add-to-meal-plan', data={
                    'recipe': 'Test Recipe',
                    'week': '2026-W07',
                    'day': 'Wednesday',
                    'meal': 'Lunch'
                })

        assert response.status_code == 200
        plan_file = meal_plans_path / "2026-W07.md"
        assert plan_file.exists()
        content = plan_file.read_text()
        assert '[[Test Recipe]]' in content

    def test_post_missing_fields_returns_error(self, client):
        """POST without required fields should return 400."""
        response = client.post('/add-to-meal-plan', data={
            'recipe': 'Test',
            # missing week, day, meal
        })
        assert response.status_code == 400
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_api_server.py::TestAddToMealPlan -v`
Expected: FAIL with 404 (endpoint doesn't exist)

**Step 3: Write the implementation**

Add to `api_server.py`:

1. Add import at top:
```python
from templates.meal_plan_template import generate_meal_plan_markdown
```

2. Add `MEAL_PLANS_PATH` constant after `OBSIDIAN_RECIPES_PATH`:
```python
MEAL_PLANS_PATH = Path("/Users/chaseeasterling/Library/Mobile Documents/iCloud~md~obsidian/Documents/KitchenOS/Meal Plans")
```

3. Add the two route handlers before the `if __name__` block:

```python
@app.route('/add-to-meal-plan', methods=['GET'])
def add_to_meal_plan_form():
    """Serve HTML form for picking meal plan slot."""
    from urllib.parse import unquote
    from datetime import date

    recipe = request.args.get('recipe')
    if not recipe:
        return error_page("Error: recipe parameter required"), 400

    recipe = unquote(recipe)
    # Strip .md extension for display
    recipe_display = recipe.replace('.md', '')

    # Generate week options: current week + next 3
    today = date.today()
    weeks = []
    for i in range(4):
        d = today + timedelta(days=7 * i)
        iso = d.isocalendar()
        week_id = f"{iso[0]}-W{iso[1]:02d}"
        weeks.append(week_id)

    days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    meals = ['Breakfast', 'Lunch', 'Dinner']

    week_options = ''.join(f'<option value="{w}">{w}</option>' for w in weeks)
    day_options = ''.join(f'<option value="{d}">{d}</option>' for d in days)
    meal_options = ''.join(f'<option value="{m}">{m}</option>' for m in meals)

    return f'''<!DOCTYPE html>
<html><head>
<title>Add to Meal Plan</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
    body {{ font-family: system-ui; padding: 1.5rem; max-width: 480px; margin: 0 auto; background: #fafafa; }}
    h2 {{ margin-top: 0; }}
    .recipe-name {{ background: #f0f0f0; padding: 0.75rem; border-radius: 8px; margin-bottom: 1.5rem; font-weight: 600; }}
    label {{ display: block; font-weight: 600; margin-bottom: 0.25rem; margin-top: 1rem; }}
    select {{ width: 100%; padding: 0.75rem; font-size: 16px; border: 1px solid #ccc; border-radius: 8px; background: white; -webkit-appearance: none; }}
    button {{ width: 100%; padding: 1rem; font-size: 18px; font-weight: 600; background: #2563eb; color: white; border: none; border-radius: 8px; margin-top: 1.5rem; cursor: pointer; }}
    button:active {{ background: #1d4ed8; }}
</style>
</head>
<body>
<h2>Add to Meal Plan</h2>
<div class="recipe-name">{recipe_display}</div>
<form method="POST" action="/add-to-meal-plan">
    <input type="hidden" name="recipe" value="{recipe_display}">
    <label for="week">Week</label>
    <select name="week" id="week">{week_options}</select>
    <label for="day">Day</label>
    <select name="day" id="day">{day_options}</select>
    <label for="meal">Meal</label>
    <select name="meal" id="meal">{meal_options}</select>
    <button type="submit">Add to Meal Plan</button>
</form>
</body></html>'''


@app.route('/add-to-meal-plan', methods=['POST'])
def add_to_meal_plan():
    """Add recipe to a meal plan slot."""
    from lib.meal_plan_parser import insert_recipe_into_meal_plan

    recipe = request.form.get('recipe')
    week = request.form.get('week')
    day = request.form.get('day')
    meal = request.form.get('meal')

    if not all([recipe, week, day, meal]):
        return error_page("Error: recipe, week, day, and meal are all required"), 400

    # Parse week string (e.g. "2026-W07")
    try:
        parts = week.split('-W')
        year = int(parts[0])
        week_num = int(parts[1])
    except (ValueError, IndexError):
        return error_page(f"Error: Invalid week format: {week}"), 400

    # Find or create meal plan file
    MEAL_PLANS_PATH.mkdir(parents=True, exist_ok=True)
    plan_file = MEAL_PLANS_PATH / f"{week}.md"

    if not plan_file.exists():
        content = generate_meal_plan_markdown(year, week_num)
        plan_file.write_text(content, encoding='utf-8')

    # Read current content and insert recipe
    content = plan_file.read_text(encoding='utf-8')
    try:
        new_content = insert_recipe_into_meal_plan(content, day, meal, recipe)
    except ValueError as e:
        return error_page(f"Error: {str(e)}"), 400

    plan_file.write_text(new_content, encoding='utf-8')

    # Success page with link to meal plan in Obsidian
    from urllib.parse import quote
    encoded_file = quote(f"Meal Plans/{week}", safe='')
    return f'''<!DOCTYPE html>
<html><head><title>KitchenOS</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
</head>
<body style="font-family: system-ui; padding: 2rem; max-width: 600px; margin: 0 auto;">
<div style="background: #efe; border: 1px solid #0a0; padding: 1rem; border-radius: 8px;">
<strong style="color: #0a0;">Added!</strong><br>
[[{recipe}]] → {day} {meal} ({week})
</div>
<p><a href="obsidian://open?vault=KitchenOS&file={encoded_file}">View Meal Plan</a></p>
<p><a href="obsidian://open?vault=KitchenOS">Back to Obsidian</a></p>
</body></html>'''
```

4. Add `timedelta` import at top of file:
```python
from datetime import timedelta
```

**Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_api_server.py::TestAddToMealPlan -v`
Expected: All 5 tests PASS

**Step 5: Run all tests**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: All tests PASS

**Step 6: Commit**

```bash
git add api_server.py tests/test_api_server.py
git commit -m "feat: add /add-to-meal-plan endpoint with mobile-friendly form"
```

---

### Task 4: Add migration for existing recipes (Tailscale IP + new button)

**Files:**
- Modify: `migrate_recipes.py`
- Test: `tests/test_migrate.py`

**Step 1: Write the failing test**

Add to `tests/test_migrate.py`:

```python
from migrate_recipes import migrate_recipe_content


def test_migration_updates_localhost_to_tailscale():
    """Migration should replace localhost URLs with Tailscale IP."""
    content = '''---
title: "Test"
---

> [!tools]- Tools
> ```button
> name Re-extract
> type link
> url http://localhost:5001/reprocess?file=Test.md
> ```
> ```button
> name Refresh Template
> type link
> url http://localhost:5001/refresh?file=Test.md
> ```

# Test
'''
    result, changes = migrate_recipe_content(content, "Test.md")
    assert "100.111.6.10:5001" in result
    assert "localhost:5001" not in result


def test_migration_adds_meal_plan_button():
    """Migration should add Add to Meal Plan button if missing."""
    content = '''---
title: "Test"
---

> [!tools]- Tools
> ```button
> name Re-extract
> type link
> url http://localhost:5001/reprocess?file=Test.md
> ```
> ```button
> name Refresh Template
> type link
> url http://localhost:5001/refresh?file=Test.md
> ```

# Test
'''
    result, changes = migrate_recipe_content(content, "Test.md")
    assert "Add to Meal Plan" in result
    assert "add-to-meal-plan" in result
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_migrate.py::test_migration_updates_localhost_to_tailscale tests/test_migrate.py::test_migration_adds_meal_plan_button -v`
Expected: FAIL

**Step 3: Write the implementation**

In `migrate_recipes.py`, update `migrate_recipe_content()` to add two new migration steps after the existing ones:

```python
def migrate_recipe_content(content: str, filename: str = None) -> Tuple[str, List[str]]:
    """..."""
    changes = []
    new_content = content

    # ... existing table migration code ...

    # Add Tools callout if missing
    if filename and not has_tools_callout(new_content):
        new_content = add_tools_callout(new_content, filename)
        changes.append("Added Tools callout with reprocess buttons")

    # Migrate localhost URLs to Tailscale IP
    if "localhost:5001" in new_content:
        new_content = new_content.replace("http://localhost:5001", "http://100.111.6.10:5001")
        changes.append("Updated button URLs from localhost to Tailscale IP")

    # Add "Add to Meal Plan" button if Tools callout exists but button is missing
    if has_tools_callout(new_content) and "Add to Meal Plan" not in new_content and filename:
        from urllib.parse import quote
        encoded_filename = quote(filename, safe='')
        meal_plan_button = (
            f'> ```button\n'
            f'> name Add to Meal Plan\n'
            f'> type link\n'
            f'> url http://100.111.6.10:5001/add-to-meal-plan?recipe={encoded_filename}\n'
            f'> ```\n'
        )
        # Insert before the closing of the tools callout (before the blank line after last ```)
        # Find the last "> ```" line in the tools callout and insert after it
        last_button_end = new_content.rfind('> ```\n')
        if last_button_end != -1:
            insert_pos = last_button_end + len('> ```\n')
            new_content = new_content[:insert_pos] + meal_plan_button + new_content[insert_pos:]
            changes.append("Added 'Add to Meal Plan' button")

    return new_content, changes
```

Also update `needs_content_migration()`:

```python
def needs_content_migration(content: str) -> bool:
    if '| Amount | Ingredient |' in content:
        return True
    if not has_tools_callout(content):
        return True
    if "localhost:5001" in content:
        return True
    if has_tools_callout(content) and "Add to Meal Plan" not in content:
        return True
    return False
```

**Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_migrate.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add migrate_recipes.py tests/test_migrate.py
git commit -m "feat: migration for Tailscale IP URLs and Add to Meal Plan button"
```

---

### Task 5: Run migration, update docs, final commit

**Files:**
- Run: `migrate_recipes.py --dry-run` then `migrate_recipes.py`
- Update: `CLAUDE.md` (new endpoint, key function)

**Step 1: Dry-run migration**

Run: `.venv/bin/python migrate_recipes.py --dry-run`
Expected: Lists all recipes that would be updated with "Would update button URLs" and "Would add Add to Meal Plan button"

**Step 2: Run migration**

Run: `.venv/bin/python migrate_recipes.py`
Expected: All recipes updated, backups created

**Step 3: Verify a recipe file**

Pick any recipe file and check:
- All button URLs use `100.111.6.10:5001`
- "Add to Meal Plan" button is present
- No `localhost:5001` remaining

**Step 4: Update CLAUDE.md**

Add to the Endpoints table:
```
| `/add-to-meal-plan` | GET/POST | Pick meal plan slot and add recipe |
```

Add to Key Functions under `api_server.py`:
```
- `add_to_meal_plan_form()` - Serves mobile-friendly form to pick week/day/meal
- `add_to_meal_plan()` - Inserts recipe wikilink into meal plan file
```

Add to Key Functions under `lib/meal_plan_parser.py`:
```
- `insert_recipe_into_meal_plan()` - Inserts `[[recipe]]` wikilink into meal plan markdown at specified day/meal slot
```

**Step 5: Run full test suite**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: All tests PASS

**Step 6: Commit everything**

```bash
git add -A
git commit -m "feat: add-to-meal-plan button with mobile support

- Add to Meal Plan button in recipe Tools callout
- Mobile-friendly HTML form to pick week/day/meal
- Auto-creates meal plan file if it doesn't exist
- Appends recipe as wikilink (supports multiple per slot)
- Migrate all button URLs from localhost to Tailscale IP
- Migrated all existing recipes"
```
