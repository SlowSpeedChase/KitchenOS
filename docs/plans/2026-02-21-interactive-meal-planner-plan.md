# Interactive Meal Planner Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a drag-and-drop meal planner web UI served from the existing Flask API server, accessible on iPad via Tailscale.

**Architecture:** Single HTML file with vanilla JS + SortableJS (CDN) for touch drag-and-drop. Three new API endpoints read/write the same Obsidian markdown files. A new `lib/recipe_index.py` scans recipe frontmatter for the sidebar. A new `rebuild_meal_plan_markdown()` function converts JSON back to markdown.

**Tech Stack:** Python 3.11, Flask (existing), SortableJS (CDN), vanilla HTML/CSS/JS

**Design doc:** `docs/plans/2026-02-21-interactive-meal-planner-design.md`

---

### Task 1: Create recipe index module

**Files:**
- Create: `lib/recipe_index.py`
- Test: `tests/test_recipe_index.py`

**Step 1: Write the failing test**

Create `tests/test_recipe_index.py`:

```python
"""Tests for recipe index."""

import tempfile
from pathlib import Path

from lib.recipe_index import get_recipe_index


class TestGetRecipeIndex:
    """Test scanning recipes folder for metadata."""

    def test_extracts_name_from_filename(self):
        """Recipe name comes from filename (stem), not frontmatter title."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recipes_dir = Path(tmpdir)
            (recipes_dir / "Pasta Aglio E Olio.md").write_text(
                '---\ntitle: "Pasta Aglio E Olio"\ncuisine: "Italian"\nprotein: "none"\n---\n\n# Pasta'
            )
            result = get_recipe_index(recipes_dir)
            assert len(result) == 1
            assert result[0]["name"] == "Pasta Aglio E Olio"

    def test_extracts_filter_fields(self):
        """Should extract cuisine, protein, meal_occasion, difficulty."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recipes_dir = Path(tmpdir)
            (recipes_dir / "Butter Chicken.md").write_text(
                '---\ntitle: "Butter Chicken"\ncuisine: "Indian"\nprotein: "chicken"\n'
                'difficulty: "easy"\nmeal_occasion: ["weeknight-dinner", "meal-prep"]\n---\n\n# Butter Chicken'
            )
            result = get_recipe_index(recipes_dir)
            assert result[0]["cuisine"] == "Indian"
            assert result[0]["protein"] == "chicken"
            assert result[0]["difficulty"] == "easy"
            assert result[0]["meal_occasion"] == ["weeknight-dinner", "meal-prep"]

    def test_handles_null_fields(self):
        """Null/missing frontmatter fields become None."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recipes_dir = Path(tmpdir)
            (recipes_dir / "Simple Recipe.md").write_text(
                '---\ntitle: "Simple Recipe"\ncuisine: null\nprotein: null\n---\n\n# Simple'
            )
            result = get_recipe_index(recipes_dir)
            assert result[0]["cuisine"] is None
            assert result[0]["protein"] is None

    def test_skips_non_md_files(self):
        """Should only index .md files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recipes_dir = Path(tmpdir)
            (recipes_dir / "Recipe.md").write_text('---\ntitle: "Recipe"\n---\n\n# Recipe')
            (recipes_dir / ".DS_Store").write_text("junk")
            (recipes_dir / "notes.txt").write_text("notes")
            result = get_recipe_index(recipes_dir)
            assert len(result) == 1

    def test_skips_subdirectories(self):
        """Should not recurse into subdirectories like Cooking Mode/."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recipes_dir = Path(tmpdir)
            (recipes_dir / "Recipe.md").write_text('---\ntitle: "Recipe"\n---\n\n# Recipe')
            subdir = recipes_dir / "Cooking Mode"
            subdir.mkdir()
            (subdir / "Recipe.recipe.md").write_text('---\ntitle: "Recipe"\n---\n\n# Recipe')
            result = get_recipe_index(recipes_dir)
            assert len(result) == 1

    def test_sorts_alphabetically(self):
        """Results sorted by name A-Z."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recipes_dir = Path(tmpdir)
            (recipes_dir / "Zucchini Bread.md").write_text('---\ntitle: "Zucchini Bread"\n---\n')
            (recipes_dir / "Apple Pie.md").write_text('---\ntitle: "Apple Pie"\n---\n')
            (recipes_dir / "Mac And Cheese.md").write_text('---\ntitle: "Mac And Cheese"\n---\n')
            result = get_recipe_index(recipes_dir)
            names = [r["name"] for r in result]
            assert names == ["Apple Pie", "Mac And Cheese", "Zucchini Bread"]

    def test_handles_missing_frontmatter(self):
        """Files without frontmatter still get indexed with name only."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recipes_dir = Path(tmpdir)
            (recipes_dir / "Plain Recipe.md").write_text("# Plain Recipe\n\nJust some text.")
            result = get_recipe_index(recipes_dir)
            assert len(result) == 1
            assert result[0]["name"] == "Plain Recipe"
            assert result[0]["cuisine"] is None
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_recipe_index.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lib.recipe_index'`

**Step 3: Write minimal implementation**

Create `lib/recipe_index.py`:

```python
"""Recipe index — scan recipe files and extract frontmatter metadata."""

from pathlib import Path

from lib.recipe_parser import parse_recipe_file

FILTER_FIELDS = ("cuisine", "protein", "difficulty", "meal_occasion", "dish_type")


def get_recipe_index(recipes_dir: Path) -> list[dict]:
    """Scan all recipe .md files and return metadata for filtering.

    Args:
        recipes_dir: Path to the Recipes folder in Obsidian vault

    Returns:
        List of dicts sorted by name, each with keys:
            name, cuisine, protein, difficulty, meal_occasion, dish_type
    """
    recipes = []

    for filepath in recipes_dir.iterdir():
        if not filepath.is_file() or filepath.suffix != ".md":
            continue

        name = filepath.stem
        entry = {"name": name}

        try:
            content = filepath.read_text(encoding="utf-8")
            parsed = parse_recipe_file(content)
            fm = parsed["frontmatter"]
            for field in FILTER_FIELDS:
                entry[field] = fm.get(field)
        except Exception:
            for field in FILTER_FIELDS:
                entry.setdefault(field, None)

        recipes.append(entry)

    recipes.sort(key=lambda r: r["name"])
    return recipes
```

**Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_recipe_index.py -v`
Expected: PASS (7 tests)

**Step 5: Commit**

```bash
git add lib/recipe_index.py tests/test_recipe_index.py
git commit -m "feat: add recipe index module for scanning recipe metadata"
```

---

### Task 2: Add `rebuild_meal_plan_markdown()` to meal plan parser

**Files:**
- Modify: `lib/meal_plan_parser.py:147` (append new function)
- Test: `tests/test_meal_plan_parser.py` (add new test class)

**Step 1: Write the failing test**

Append to `tests/test_meal_plan_parser.py`:

```python
from lib.meal_plan_parser import rebuild_meal_plan_markdown


class TestRebuildMealPlanMarkdown:
    """Test converting structured meal plan data back to markdown."""

    def test_empty_plan_matches_template(self):
        """Empty plan (all nulls) produces same format as template generator."""
        days = [
            {"day": "Monday", "date": "2026-02-23", "breakfast": None, "lunch": None, "dinner": None},
            {"day": "Tuesday", "date": "2026-02-24", "breakfast": None, "lunch": None, "dinner": None},
            {"day": "Wednesday", "date": "2026-02-25", "breakfast": None, "lunch": None, "dinner": None},
            {"day": "Thursday", "date": "2026-02-26", "breakfast": None, "lunch": None, "dinner": None},
            {"day": "Friday", "date": "2026-02-27", "breakfast": None, "lunch": None, "dinner": None},
            {"day": "Saturday", "date": "2026-02-28", "breakfast": None, "lunch": None, "dinner": None},
            {"day": "Sunday", "date": "2026-03-01", "breakfast": None, "lunch": None, "dinner": None},
        ]
        result = rebuild_meal_plan_markdown("2026-W09", days)
        assert "# Meal Plan - Week 09" in result
        assert "## Monday (Feb 23)" in result
        assert "## Sunday (Mar 1)" in result
        assert "### Breakfast" in result
        assert "[[" not in result  # No recipes

    def test_inserts_recipe_links(self):
        """Filled slots get [[wikilink]] format."""
        days = [
            {"day": "Monday", "date": "2026-02-23",
             "breakfast": {"name": "Pancakes", "servings": 1},
             "lunch": None,
             "dinner": {"name": "Pasta Aglio E Olio", "servings": 1}},
        ] + [
            {"day": d, "date": "2026-02-24", "breakfast": None, "lunch": None, "dinner": None}
            for d in ["Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        ]
        result = rebuild_meal_plan_markdown("2026-W09", days)
        assert "### Breakfast\n[[Pancakes]]" in result
        assert "### Dinner\n[[Pasta Aglio E Olio]]" in result

    def test_includes_servings_multiplier(self):
        """Servings > 1 adds xN suffix outside wikilink."""
        days = [
            {"day": "Monday", "date": "2026-02-23",
             "breakfast": {"name": "Pancakes", "servings": 2},
             "lunch": None, "dinner": None},
        ] + [
            {"day": d, "date": "2026-02-24", "breakfast": None, "lunch": None, "dinner": None}
            for d in ["Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        ]
        result = rebuild_meal_plan_markdown("2026-W09", days)
        assert "[[Pancakes]] x2" in result

    def test_servings_1_no_suffix(self):
        """Servings == 1 has no xN suffix."""
        days = [
            {"day": "Monday", "date": "2026-02-23",
             "breakfast": {"name": "Pancakes", "servings": 1},
             "lunch": None, "dinner": None},
        ] + [
            {"day": d, "date": "2026-02-24", "breakfast": None, "lunch": None, "dinner": None}
            for d in ["Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        ]
        result = rebuild_meal_plan_markdown("2026-W09", days)
        assert "[[Pancakes]]" in result
        assert "[[Pancakes]] x" not in result

    def test_roundtrip_parse_then_rebuild(self):
        """Parsing then rebuilding should preserve recipe assignments."""
        original = """# Meal Plan - Week 09 (Feb 23 - Mar 1, 2026)

```button
name Generate Shopping List
type link
action kitchenos://generate-shopping-list?week=2026-W09
```

## Monday (Feb 23)
### Breakfast
[[Pancakes]] x2
### Lunch
[[Caesar Salad]]
### Dinner
[[Butter Chicken]]
### Notes


## Tuesday (Feb 24)
### Breakfast

### Lunch

### Dinner
[[Pasta Aglio E Olio]]
### Notes


## Wednesday (Feb 25)
### Breakfast

### Lunch

### Dinner

### Notes


## Thursday (Feb 26)
### Breakfast

### Lunch

### Dinner

### Notes


## Friday (Feb 27)
### Breakfast

### Lunch

### Dinner

### Notes


## Saturday (Feb 28)
### Breakfast

### Lunch

### Dinner

### Notes


## Sunday (Mar 1)
### Breakfast

### Lunch

### Dinner

### Notes

"""
        parsed = parse_meal_plan(original, 2026, 9)
        # Convert parsed data to the JSON format
        days_json = []
        for day_data in parsed:
            day_json = {
                "day": day_data["day"],
                "date": day_data["date"].isoformat(),
                "breakfast": None,
                "lunch": None,
                "dinner": None,
            }
            for meal in ("breakfast", "lunch", "dinner"):
                entry = day_data[meal]
                if entry is not None:
                    day_json[meal] = {"name": entry.name, "servings": entry.servings}
            days_json.append(day_json)

        rebuilt = rebuild_meal_plan_markdown("2026-W09", days_json)

        # Re-parse the rebuilt markdown
        reparsed = parse_meal_plan(rebuilt, 2026, 9)
        assert reparsed[0]["breakfast"] == MealEntry("Pancakes", 2)
        assert reparsed[0]["lunch"] == MealEntry("Caesar Salad", 1)
        assert reparsed[0]["dinner"] == MealEntry("Butter Chicken", 1)
        assert reparsed[1]["dinner"] == MealEntry("Pasta Aglio E Olio", 1)
        assert reparsed[2]["breakfast"] is None
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_meal_plan_parser.py::TestRebuildMealPlanMarkdown -v`
Expected: FAIL — `ImportError: cannot import name 'rebuild_meal_plan_markdown'`

**Step 3: Write minimal implementation**

Append to `lib/meal_plan_parser.py`:

```python
def rebuild_meal_plan_markdown(week: str, days: list[dict]) -> str:
    """Rebuild meal plan markdown from structured data.

    Args:
        week: Week identifier like '2026-W09'
        days: List of 7 day dicts, each with keys:
            day, date (ISO string), breakfast, lunch, dinner
            Meal values are None or {"name": str, "servings": int}

    Returns:
        Complete meal plan markdown string
    """
    from datetime import date as date_type

    # Parse week string
    parts = week.split("-W")
    year = int(parts[0])
    week_num = int(parts[1])

    # Build date objects from ISO strings
    day_dates = []
    for d in days:
        day_dates.append(date_type.fromisoformat(d["date"]))

    start_date = day_dates[0]
    end_date = day_dates[6]

    def fmt_date(d):
        return d.strftime("%b %-d")

    def fmt_meal(meal_data):
        if meal_data is None:
            return ""
        name = meal_data["name"]
        servings = meal_data.get("servings", 1)
        if servings > 1:
            return f"[[{name}]] x{servings}"
        return f"[[{name}]]"

    lines = [
        f"# Meal Plan - Week {week_num:02d} ({fmt_date(start_date)} - {fmt_date(end_date)}, {year})",
        "",
        "```button",
        "name Generate Shopping List",
        "type link",
        f"action kitchenos://generate-shopping-list?week={week}",
        "```",
        "",
    ]

    for day_data in days:
        d = date_type.fromisoformat(day_data["date"])
        day_name = day_data["day"]

        lines.append(f"## {day_name} ({fmt_date(d)})")
        lines.append("### Breakfast")
        lines.append(fmt_meal(day_data.get("breakfast")))
        lines.append("### Lunch")
        lines.append(fmt_meal(day_data.get("lunch")))
        lines.append("### Dinner")
        lines.append(fmt_meal(day_data.get("dinner")))
        lines.append("### Notes")
        lines.append("")
        lines.append("")

    return "\n".join(lines)
```

**Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_meal_plan_parser.py -v`
Expected: ALL PASS (existing + new tests)

**Step 5: Commit**

```bash
git add lib/meal_plan_parser.py tests/test_meal_plan_parser.py
git commit -m "feat: add rebuild_meal_plan_markdown for JSON-to-markdown conversion"
```

---

### Task 3: Add `/api/recipes` endpoint

**Files:**
- Modify: `api_server.py` (add import + route + caching)
- Test: `tests/test_api_server.py` (add test class)

**Step 1: Write the failing test**

Append to `tests/test_api_server.py`:

```python
class TestApiRecipes:
    """Tests for GET /api/recipes endpoint."""

    def test_returns_recipe_list(self, tmp_path):
        """Should return JSON list of recipe metadata."""
        import api_server

        recipes_path = tmp_path / "Recipes"
        recipes_path.mkdir()
        (recipes_path / "Pasta.md").write_text(
            '---\ntitle: "Pasta"\ncuisine: "Italian"\nprotein: null\n'
            'difficulty: "easy"\nmeal_occasion: ["weeknight-dinner"]\n---\n\n# Pasta'
        )

        with patch.object(api_server, 'OBSIDIAN_RECIPES_PATH', recipes_path), \
             patch.object(api_server, '_recipe_cache', {"data": None, "timestamp": 0}):
            with app.test_client() as c:
                response = c.get('/api/recipes')

        assert response.status_code == 200
        data = response.get_json()
        assert len(data) == 1
        assert data[0]["name"] == "Pasta"
        assert data[0]["cuisine"] == "Italian"

    def test_returns_empty_list_for_no_recipes(self, tmp_path):
        """Should return empty list if no recipe files."""
        import api_server

        recipes_path = tmp_path / "Recipes"
        recipes_path.mkdir()

        with patch.object(api_server, 'OBSIDIAN_RECIPES_PATH', recipes_path), \
             patch.object(api_server, '_recipe_cache', {"data": None, "timestamp": 0}):
            with app.test_client() as c:
                response = c.get('/api/recipes')

        assert response.status_code == 200
        assert response.get_json() == []
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_api_server.py::TestApiRecipes -v`
Expected: FAIL — 404 (route doesn't exist)

**Step 3: Write minimal implementation**

In `api_server.py`, add import at top (after existing imports):

```python
import time
from lib.recipe_index import get_recipe_index
```

Add module-level cache dict (after `app = Flask(__name__)` on line 34):

```python
_recipe_cache = {"data": None, "timestamp": 0}
RECIPE_CACHE_TTL = 300  # 5 minutes
```

Add route (before `if __name__ == '__main__':` on line 634):

```python
@app.route('/api/recipes', methods=['GET'])
def api_recipes():
    """Return recipe metadata for meal planner sidebar."""
    now = time.time()
    if _recipe_cache["data"] is None or (now - _recipe_cache["timestamp"]) > RECIPE_CACHE_TTL:
        _recipe_cache["data"] = get_recipe_index(OBSIDIAN_RECIPES_PATH)
        _recipe_cache["timestamp"] = now
    return jsonify(_recipe_cache["data"])
```

**Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_api_server.py::TestApiRecipes -v`
Expected: PASS (2 tests)

**Step 5: Commit**

```bash
git add api_server.py tests/test_api_server.py
git commit -m "feat: add GET /api/recipes endpoint with caching"
```

---

### Task 4: Add `/api/meal-plan/<week>` GET endpoint

**Files:**
- Modify: `api_server.py` (add route)
- Test: `tests/test_api_server.py` (add test class)

**Step 1: Write the failing test**

Append to `tests/test_api_server.py`:

```python
class TestApiMealPlanGet:
    """Tests for GET /api/meal-plan/<week> endpoint."""

    def test_returns_parsed_meal_plan(self, tmp_path):
        """Should return structured JSON from existing meal plan."""
        from templates.meal_plan_template import generate_meal_plan_markdown

        meal_plans_path = tmp_path / "Meal Plans"
        meal_plans_path.mkdir()
        plan_file = meal_plans_path / "2026-W09.md"
        content = generate_meal_plan_markdown(2026, 9)
        # Insert a recipe manually
        content = content.replace("## Monday (Feb 23)\n### Breakfast\n",
                                  "## Monday (Feb 23)\n### Breakfast\n[[Pancakes]] x2\n")
        plan_file.write_text(content)

        with patch('api_server.MEAL_PLANS_PATH', meal_plans_path):
            with app.test_client() as c:
                response = c.get('/api/meal-plan/2026-W09')

        assert response.status_code == 200
        data = response.get_json()
        assert data["week"] == "2026-W09"
        assert len(data["days"]) == 7
        assert data["days"][0]["day"] == "Monday"
        assert data["days"][0]["breakfast"]["name"] == "Pancakes"
        assert data["days"][0]["breakfast"]["servings"] == 2
        assert data["days"][0]["lunch"] is None

    def test_creates_plan_if_missing(self, tmp_path):
        """Should auto-create meal plan file and return empty plan."""
        meal_plans_path = tmp_path / "Meal Plans"
        meal_plans_path.mkdir()

        with patch('api_server.MEAL_PLANS_PATH', meal_plans_path):
            with app.test_client() as c:
                response = c.get('/api/meal-plan/2026-W09')

        assert response.status_code == 200
        data = response.get_json()
        assert data["week"] == "2026-W09"
        assert all(d["breakfast"] is None for d in data["days"])
        # File should now exist
        assert (meal_plans_path / "2026-W09.md").exists()

    def test_invalid_week_format(self, client):
        """Should return 400 for invalid week format."""
        response = client.get('/api/meal-plan/bad-format')
        assert response.status_code == 400
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_api_server.py::TestApiMealPlanGet -v`
Expected: FAIL — 404 (route doesn't exist)

**Step 3: Write minimal implementation**

Add import at top of `api_server.py` (update existing import from `lib.meal_plan_parser`):

```python
from lib.meal_plan_parser import insert_recipe_into_meal_plan, parse_meal_plan
```

Add route in `api_server.py` (before `if __name__ == '__main__':`):

```python
@app.route('/api/meal-plan/<week>', methods=['GET'])
def api_meal_plan_get(week):
    """Return meal plan as structured JSON."""
    # Validate week format
    match = re.match(r'^(\d{4})-W(\d{2})$', week)
    if not match:
        return jsonify({"error": "Invalid week format. Expected YYYY-WNN"}), 400

    year = int(match.group(1))
    week_num = int(match.group(2))

    # Find or create meal plan file
    MEAL_PLANS_PATH.mkdir(parents=True, exist_ok=True)
    plan_file = MEAL_PLANS_PATH / f"{week}.md"

    if not plan_file.exists():
        content = generate_meal_plan_markdown(year, week_num)
        plan_file.write_text(content, encoding="utf-8")
    else:
        content = plan_file.read_text(encoding="utf-8")

    # Parse into structured data
    parsed = parse_meal_plan(content, year, week_num)

    # Convert to JSON-serializable format
    days = []
    for day_data in parsed:
        day_json = {
            "day": day_data["day"],
            "date": day_data["date"].isoformat(),
            "breakfast": None,
            "lunch": None,
            "dinner": None,
        }
        for meal in ("breakfast", "lunch", "dinner"):
            entry = day_data[meal]
            if entry is not None:
                day_json[meal] = {"name": entry.name, "servings": entry.servings}
        days.append(day_json)

    return jsonify({"week": week, "days": days})
```

**Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_api_server.py::TestApiMealPlanGet -v`
Expected: PASS (3 tests)

**Step 5: Commit**

```bash
git add api_server.py tests/test_api_server.py
git commit -m "feat: add GET /api/meal-plan/<week> endpoint"
```

---

### Task 5: Add `/api/meal-plan/<week>` PUT endpoint

**Files:**
- Modify: `api_server.py` (add PUT handler)
- Test: `tests/test_api_server.py` (add test class)

**Step 1: Write the failing test**

Append to `tests/test_api_server.py`:

```python
class TestApiMealPlanPut:
    """Tests for PUT /api/meal-plan/<week> endpoint."""

    def test_saves_meal_plan(self, tmp_path):
        """Should write meal plan markdown from JSON."""
        from templates.meal_plan_template import generate_meal_plan_markdown

        meal_plans_path = tmp_path / "Meal Plans"
        meal_plans_path.mkdir()
        # Pre-create an empty plan
        plan_file = meal_plans_path / "2026-W09.md"
        plan_file.write_text(generate_meal_plan_markdown(2026, 9))

        payload = {
            "week": "2026-W09",
            "days": [
                {"day": "Monday", "date": "2026-02-23",
                 "breakfast": {"name": "Pancakes", "servings": 2},
                 "lunch": None,
                 "dinner": {"name": "Butter Chicken", "servings": 1}},
                {"day": "Tuesday", "date": "2026-02-24",
                 "breakfast": None, "lunch": None, "dinner": None},
                {"day": "Wednesday", "date": "2026-02-25",
                 "breakfast": None, "lunch": None, "dinner": None},
                {"day": "Thursday", "date": "2026-02-26",
                 "breakfast": None, "lunch": None, "dinner": None},
                {"day": "Friday", "date": "2026-02-27",
                 "breakfast": None, "lunch": None, "dinner": None},
                {"day": "Saturday", "date": "2026-02-28",
                 "breakfast": None, "lunch": None, "dinner": None},
                {"day": "Sunday", "date": "2026-03-01",
                 "breakfast": None, "lunch": None, "dinner": None},
            ]
        }

        with patch('api_server.MEAL_PLANS_PATH', meal_plans_path):
            with app.test_client() as c:
                response = c.put('/api/meal-plan/2026-W09',
                                 json=payload,
                                 content_type='application/json')

        assert response.status_code == 200
        content = plan_file.read_text()
        assert "[[Pancakes]] x2" in content
        assert "[[Butter Chicken]]" in content

    def test_creates_file_if_missing(self, tmp_path):
        """Should create meal plan file if it doesn't exist."""
        meal_plans_path = tmp_path / "Meal Plans"
        meal_plans_path.mkdir()

        payload = {
            "week": "2026-W09",
            "days": [
                {"day": "Monday", "date": "2026-02-23",
                 "breakfast": {"name": "Toast", "servings": 1},
                 "lunch": None, "dinner": None},
                {"day": "Tuesday", "date": "2026-02-24",
                 "breakfast": None, "lunch": None, "dinner": None},
                {"day": "Wednesday", "date": "2026-02-25",
                 "breakfast": None, "lunch": None, "dinner": None},
                {"day": "Thursday", "date": "2026-02-26",
                 "breakfast": None, "lunch": None, "dinner": None},
                {"day": "Friday", "date": "2026-02-27",
                 "breakfast": None, "lunch": None, "dinner": None},
                {"day": "Saturday", "date": "2026-02-28",
                 "breakfast": None, "lunch": None, "dinner": None},
                {"day": "Sunday", "date": "2026-03-01",
                 "breakfast": None, "lunch": None, "dinner": None},
            ]
        }

        with patch('api_server.MEAL_PLANS_PATH', meal_plans_path):
            with app.test_client() as c:
                response = c.put('/api/meal-plan/2026-W09',
                                 json=payload,
                                 content_type='application/json')

        assert response.status_code == 200
        assert (meal_plans_path / "2026-W09.md").exists()
        content = (meal_plans_path / "2026-W09.md").read_text()
        assert "[[Toast]]" in content

    def test_invalid_week_format(self, client):
        """Should return 400 for invalid week format."""
        response = client.put('/api/meal-plan/bad', json={"days": []},
                              content_type='application/json')
        assert response.status_code == 400

    def test_roundtrip_get_put_get(self, tmp_path):
        """GET → PUT → GET should preserve data."""
        meal_plans_path = tmp_path / "Meal Plans"
        meal_plans_path.mkdir()

        with patch('api_server.MEAL_PLANS_PATH', meal_plans_path):
            with app.test_client() as c:
                # GET creates empty plan
                r1 = c.get('/api/meal-plan/2026-W09')
                data = r1.get_json()

                # Add a recipe
                data["days"][0]["dinner"] = {"name": "Steak", "servings": 1}

                # PUT it back
                c.put('/api/meal-plan/2026-W09', json=data,
                      content_type='application/json')

                # GET again
                r2 = c.get('/api/meal-plan/2026-W09')
                data2 = r2.get_json()

        assert data2["days"][0]["dinner"]["name"] == "Steak"
        assert data2["days"][0]["dinner"]["servings"] == 1
        assert data2["days"][0]["breakfast"] is None
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_api_server.py::TestApiMealPlanPut -v`
Expected: FAIL — 405 Method Not Allowed (PUT not defined)

**Step 3: Write minimal implementation**

Add import at top of `api_server.py`:

```python
from lib.meal_plan_parser import insert_recipe_into_meal_plan, parse_meal_plan, rebuild_meal_plan_markdown
```

Add PUT route in `api_server.py` (right after the GET route):

```python
@app.route('/api/meal-plan/<week>', methods=['PUT'])
def api_meal_plan_put(week):
    """Save meal plan from structured JSON."""
    match = re.match(r'^(\d{4})-W(\d{2})$', week)
    if not match:
        return jsonify({"error": "Invalid week format. Expected YYYY-WNN"}), 400

    data = request.get_json(force=True, silent=True)
    if not data or "days" not in data:
        return jsonify({"error": "Request body must include 'days' array"}), 400

    # Rebuild markdown from JSON
    content = rebuild_meal_plan_markdown(week, data["days"])

    # Write to file
    MEAL_PLANS_PATH.mkdir(parents=True, exist_ok=True)
    plan_file = MEAL_PLANS_PATH / f"{week}.md"
    plan_file.write_text(content, encoding="utf-8")

    # Invalidate recipe cache (meal plan change may affect views)
    _recipe_cache["data"] = None

    return jsonify({"status": "saved", "week": week})
```

**Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_api_server.py::TestApiMealPlanPut -v`
Expected: PASS (4 tests)

**Step 5: Run all existing tests to check for regressions**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: ALL PASS

**Step 6: Commit**

```bash
git add api_server.py tests/test_api_server.py
git commit -m "feat: add PUT /api/meal-plan/<week> endpoint"
```

---

### Task 6: Add `/meal-planner` route and create the HTML board

**Files:**
- Modify: `api_server.py` (add route to serve HTML)
- Create: `templates/meal_planner.html`

This is the largest task. No automated tests — this is a UI file tested manually on iPad.

**Step 1: Add Flask route to serve the HTML file**

In `api_server.py`, add this route (before `if __name__ == '__main__':`):

```python
@app.route('/meal-planner', methods=['GET'])
def meal_planner():
    """Serve the interactive meal planner board."""
    return send_file('templates/meal_planner.html', mimetype='text/html')
```

Also add at the top of `api_server.py` if not already imported:

```python
from flask import Flask, request, jsonify, send_file
```

(`send_file` is already imported on line 4.)

**Step 2: Create `templates/meal_planner.html`**

Create the full HTML file. This is a single self-contained file with embedded CSS and JS. SortableJS loaded from CDN.

The HTML structure should implement the design doc:
- **Header:** Week title + left/right navigation arrows
- **Left sidebar:** Search input, filter chips (protein, cuisine, meal_occasion), scrollable recipe card list
- **Main grid:** 7 columns (Mon-Sun) x 3 rows (B/L/D), each cell is a SortableJS drop zone
- **Toast area:** Bottom notification for save status

Key JS behaviors:
1. On page load: fetch `GET /api/recipes` and `GET /api/meal-plan/<week>` (week from URL param or current week)
2. Render recipe cards in sidebar as SortableJS list with `group: {name: 'recipes', pull: 'clone', put: false}`
3. Render grid cells as SortableJS lists with `group: {name: 'recipes', pull: true, put: true}`
4. On any drop/remove: collect all grid state → `PUT /api/meal-plan/<week>`
5. Search input: filter sidebar cards by name (case-insensitive `includes`)
6. Filter chips: generated from unique values in recipe data; toggle active state; filter sidebar
7. Week navigation: update URL param and re-fetch meal plan
8. Remove button (X) on filled cells: clear the recipe, save
9. Servings picker: tap filled cell to toggle x1/x2/x3 dropdown, save on change

CSS should be:
- System font stack (`system-ui, -apple-system, ...`)
- CSS Grid for the 7-column layout
- Responsive: sidebar collapses on narrow screens
- Touch-friendly: minimum 44px tap targets
- Clean colors: white cards, light gray background, blue accent for active filters

**Step 3: Test manually**

Start the server:
```bash
.venv/bin/python api_server.py
```

Open in browser:
```
http://localhost:5001/meal-planner
```

Verify:
- Recipe sidebar loads with recipe names
- Filter chips appear based on actual recipe metadata
- Search filters the list
- Dragging a recipe to a slot works
- Removing a recipe from a slot works
- Week navigation loads different weeks
- Servings multiplier works
- Changes persist (refresh page, data still there)

Then test on iPad via Tailscale:
```
http://100.111.6.10:5001/meal-planner
```

Verify touch drag-and-drop works on iPad Safari.

**Step 4: Commit**

```bash
git add api_server.py templates/meal_planner.html
git commit -m "feat: add interactive meal planner board UI"
```

---

### Task 7: Update CLAUDE.md documentation

**Files:**
- Modify: `CLAUDE.md`

**Step 1: Add to CLAUDE.md**

1. **Endpoints table** (in "API Server" section): Add `/meal-planner`, `/api/recipes`, `/api/meal-plan/<week>` GET/PUT rows

2. **Core Components table**: Add:
   - `lib/recipe_index.py` — Scans recipe files, returns frontmatter metadata for filtering
   - `templates/meal_planner.html` — Interactive meal planner board (HTML/CSS/JS + SortableJS)

3. **Key Functions section**: Add:
   - `lib/recipe_index.py`:
     - `get_recipe_index()` — Scans recipes folder, returns sorted list of recipe metadata dicts
   - `lib/meal_plan_parser.py`:
     - `rebuild_meal_plan_markdown()` — Converts structured JSON meal plan back to markdown

4. **Running Commands section**: Add "Meal Planner UI" subsection:
   ```
   ### Meal Planner UI
   Open in browser: http://localhost:5001/meal-planner
   iPad via Tailscale: http://100.111.6.10:5001/meal-planner
   ```

5. **Future Enhancements**: If "interactive meal planner" or similar is listed, mark it as completed

**Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add interactive meal planner to CLAUDE.md"
```

---

### Task 8: End-to-end verification

**Step 1: Run all tests**

```bash
.venv/bin/python -m pytest tests/ -v
```

Expected: ALL PASS

**Step 2: Start server and test workflow**

```bash
.venv/bin/python api_server.py
```

1. Open `http://localhost:5001/meal-planner` in browser
2. Verify recipes load in sidebar
3. Drag a recipe to Monday Dinner
4. Open the meal plan file in Obsidian — verify `[[Recipe Name]]` is there
5. Edit the meal plan in Obsidian (add a recipe to Tuesday Lunch)
6. Refresh the web UI — verify Tuesday Lunch shows the recipe
7. Navigate to a new week — verify empty plan is created
8. Test servings multiplier — verify `x2` appears in markdown

**Step 3: Test on iPad via Tailscale**

```
http://100.111.6.10:5001/meal-planner
```

Verify touch drag-and-drop works.

**Step 4: Final commit if fixes needed**

```bash
git add -A
git commit -m "fix: address e2e test findings for meal planner"
```
