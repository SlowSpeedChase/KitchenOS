"""Tests for meal plan parser."""

import pytest
from datetime import date
from lib.meal_plan_parser import parse_meal_plan, extract_meals_for_day, insert_recipe_into_meal_plan, MealEntry, rebuild_meal_plan_markdown


class TestParseMealPlan:
    """Test parsing full meal plan files."""

    def test_extracts_week_dates(self):
        content = """# Meal Plan - Week 04 (Jan 19 - Jan 25, 2026)

## Monday (Jan 19)
### Breakfast
[[Pancakes]]
### Lunch

### Dinner
[[Pasta]]
### Notes
"""
        result = parse_meal_plan(content, 2026, 4)

        assert len(result) == 7
        assert result[0]['date'] == date(2026, 1, 19)
        assert result[0]['day'] == 'Monday'

    def test_extracts_recipe_links(self):
        content = """# Meal Plan - Week 04 (Jan 19 - Jan 25, 2026)

## Monday (Jan 19)
### Breakfast
[[Rich Fudgy Chocolate Cake]]
### Lunch
[[Caesar Salad]]
### Dinner
[[Pasta Aglio E Olio]]
### Notes
"""
        result = parse_meal_plan(content, 2026, 4)

        assert result[0]['breakfast'] == MealEntry('Rich Fudgy Chocolate Cake', 1)
        assert result[0]['lunch'] == MealEntry('Caesar Salad', 1)
        assert result[0]['dinner'] == MealEntry('Pasta Aglio E Olio', 1)

    def test_handles_empty_meals(self):
        content = """# Meal Plan - Week 04 (Jan 19 - Jan 25, 2026)

## Monday (Jan 19)
### Breakfast

### Lunch

### Dinner
[[Pasta]]
### Notes
"""
        result = parse_meal_plan(content, 2026, 4)

        assert result[0]['breakfast'] is None
        assert result[0]['lunch'] is None
        assert result[0]['dinner'] == MealEntry('Pasta', 1)

    def test_handles_multiple_recipes_uses_first(self):
        content = """# Meal Plan - Week 04 (Jan 19 - Jan 25, 2026)

## Monday (Jan 19)
### Breakfast
[[Eggs]]
[[Toast]]
### Lunch

### Dinner

### Notes
"""
        result = parse_meal_plan(content, 2026, 4)

        # Use first recipe only for simplicity
        assert result[0]['breakfast'] == MealEntry('Eggs', 1)

    def test_extracts_servings_multiplier(self):
        content = """# Meal Plan - Week 04 (Jan 19 - Jan 25, 2026)

## Monday (Jan 19)
### Breakfast
[[Pancakes]] x2
### Lunch
[[Caesar Salad]]
### Dinner
[[Pasta]] x3
### Notes
"""
        result = parse_meal_plan(content, 2026, 4)

        assert result[0]['breakfast'] == MealEntry('Pancakes', 2)
        assert result[0]['lunch'] == MealEntry('Caesar Salad', 1)
        assert result[0]['dinner'] == MealEntry('Pasta', 3)


class TestExtractMealsForDay:
    """Test extracting meals from a day section."""

    def test_extracts_all_meals(self):
        section = """## Monday (Jan 19)
### Breakfast
[[Pancakes]]
### Lunch
[[Salad]]
### Dinner
[[Steak]]
### Notes
Some notes here
"""
        result = extract_meals_for_day(section)

        assert result['breakfast'] == MealEntry('Pancakes', 1)
        assert result['lunch'] == MealEntry('Salad', 1)
        assert result['dinner'] == MealEntry('Steak', 1)

    def test_extracts_multiplier(self):
        section = """## Monday (Jan 19)
### Breakfast
[[Pancakes]] x2
### Lunch
[[Salad]]
### Dinner
[[Steak]] x3
### Notes
"""
        result = extract_meals_for_day(section)

        assert result['breakfast'] == MealEntry('Pancakes', 2)
        assert result['lunch'] == MealEntry('Salad', 1)
        assert result['dinner'] == MealEntry('Steak', 3)

    def test_returns_none_for_empty(self):
        section = """## Monday (Jan 19)
### Breakfast

### Lunch

### Dinner

### Notes
"""
        result = extract_meals_for_day(section)

        assert result['breakfast'] is None
        assert result['lunch'] is None
        assert result['dinner'] is None


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


class TestRebuildMealPlanMarkdown:
    """Test converting structured meal plan data back to markdown."""

    def test_empty_plan_matches_template(self):
        """Empty plan (all nulls) produces valid format."""
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
        assert "[[" not in result

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
        days_json = []
        for day_data in parsed:
            day_json = {
                "day": day_data["day"],
                "date": day_data["date"].isoformat(),
                "breakfast": None, "lunch": None, "dinner": None,
            }
            for meal in ("breakfast", "lunch", "dinner"):
                entry = day_data[meal]
                if entry is not None:
                    day_json[meal] = {"name": entry.name, "servings": entry.servings}
            days_json.append(day_json)

        rebuilt = rebuild_meal_plan_markdown("2026-W09", days_json)
        reparsed = parse_meal_plan(rebuilt, 2026, 9)
        assert reparsed[0]["breakfast"] == MealEntry("Pancakes", 2)
        assert reparsed[0]["lunch"] == MealEntry("Caesar Salad", 1)
        assert reparsed[0]["dinner"] == MealEntry("Butter Chicken", 1)
        assert reparsed[1]["dinner"] == MealEntry("Pasta Aglio E Olio", 1)
        assert reparsed[2]["breakfast"] is None
