"""Tests for lib.meal_nutrition — the read-time meal macro rollup.

The exclusion tests are the point of this file. A sub-recipe whose macros can't
be trusted must be *named and left out*, never silently counted as zero and
never counted at face value.
"""
from pathlib import Path

import pytest

from lib.meal_loader import Meal, SubRecipe
from lib.meal_nutrition import meal_nutrition


def write_recipe(
    recipes_dir: Path,
    name: str,
    calories=400,
    protein=30,
    carbs=40,
    fat=12,
    coverage=1.0,
    servings=4,
) -> None:
    """A recipe file with per-serving macros. Pass None to omit a field."""
    lines = ["---", f'title: "{name}"']
    if servings is not None:
        lines.append(f"servings: {servings}")
    if calories is not None:
        lines.append(f"nutrition_calories: {calories}")
        lines.append(f"nutrition_protein: {protein}")
        lines.append(f"nutrition_carbs: {carbs}")
        lines.append(f"nutrition_fat: {fat}")
    if coverage is not None:
        lines.append(f"nutrition_coverage: {coverage}")
    lines += ["---", "", "## Ingredients", ""]
    (recipes_dir / f"{name}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture
def recipes_dir(tmp_path: Path) -> Path:
    d = tmp_path / "Recipes"
    d.mkdir()
    return d


def test_totals_sum_eligible_sub_recipes(recipes_dir: Path):
    write_recipe(recipes_dir, "Turkey Chili", calories=300, protein=32, carbs=25, fat=9)
    write_recipe(recipes_dir, "Cornbread", calories=200, protein=5, carbs=30, fat=7)
    meal = Meal(name="Chili Bowl", sub_recipes=[
        SubRecipe(recipe="Turkey Chili"),
        SubRecipe(recipe="Cornbread"),
    ])

    result = meal_nutrition(meal, recipes_dir)

    assert result["calories"] == 500
    assert result["protein"] == 37
    assert result["carbs"] == 55
    assert result["fat"] == 16
    assert result["incomplete"] is False
    assert result["excluded"] == []
    assert [s["recipe"] for s in result["sub"]] == ["Turkey Chili", "Cornbread"]
    assert all(s["eligible"] for s in result["sub"])


def test_fractional_servings_scale_contributions(recipes_dir: Path):
    write_recipe(recipes_dir, "Turkey Chili", calories=300, protein=32, carbs=25, fat=9)
    write_recipe(recipes_dir, "Cornbread", calories=200, protein=5, carbs=30, fat=7)
    meal = Meal(name="Chili Bowl", sub_recipes=[
        SubRecipe(recipe="Turkey Chili", servings=1.5),
        SubRecipe(recipe="Cornbread", servings=0.5),
    ])

    result = meal_nutrition(meal, recipes_dir)

    assert result["calories"] == pytest.approx(300 * 1.5 + 200 * 0.5)
    assert result["protein"] == pytest.approx(32 * 1.5 + 5 * 0.5)
    assert result["sub"][0]["calories"] == pytest.approx(450)
    assert result["sub"][1]["calories"] == pytest.approx(100)


def test_servings_unknown_is_excluded_and_named(recipes_dir: Path):
    """A serving-less recipe's macros are whole-batch totals, not per-serving.

    Counting one at face value (let alone x1.5) would add thousands of phantom
    kcal — so it is excluded, not scaled.
    """
    write_recipe(recipes_dir, "Turkey Chili", calories=300, protein=32, carbs=25, fat=9)
    write_recipe(recipes_dir, "Greek Yogurt", calories=8000, protein=900, servings=None)
    meal = Meal(name="Chili Bowl", sub_recipes=[
        SubRecipe(recipe="Turkey Chili"),
        SubRecipe(recipe="Greek Yogurt", servings=1.5),
    ])

    result = meal_nutrition(meal, recipes_dir)

    assert result["calories"] == 300, "the untrusted sub-recipe must not contribute"
    assert result["incomplete"] is True
    assert result["excluded"] == ["Greek Yogurt"]
    row = result["sub"][1]
    assert row["eligible"] is False
    assert "servings_unknown" in row["reasons"]
    assert row["calories"] is None, "not zero — unknown"


def test_low_coverage_is_excluded_and_named(recipes_dir: Path):
    write_recipe(recipes_dir, "Turkey Chili", calories=300, protein=32, carbs=25, fat=9)
    write_recipe(recipes_dir, "Mystery Stew", calories=700, coverage=0.4)
    meal = Meal(name="Chili Bowl", sub_recipes=[
        SubRecipe(recipe="Turkey Chili"),
        SubRecipe(recipe="Mystery Stew"),
    ])

    result = meal_nutrition(meal, recipes_dir)

    assert result["calories"] == 300
    assert result["incomplete"] is True
    assert result["excluded"] == ["Mystery Stew"]
    assert "low_coverage" in result["sub"][1]["reasons"]


def test_no_nutrition_is_excluded_and_named(recipes_dir: Path):
    write_recipe(recipes_dir, "Turkey Chili", calories=300, protein=32, carbs=25, fat=9)
    write_recipe(recipes_dir, "Plain Rice", calories=None, coverage=None)
    meal = Meal(name="Chili Bowl", sub_recipes=[
        SubRecipe(recipe="Turkey Chili"),
        SubRecipe(recipe="Plain Rice"),
    ])

    result = meal_nutrition(meal, recipes_dir)

    assert result["calories"] == 300
    assert result["incomplete"] is True
    assert result["excluded"] == ["Plain Rice"]


def test_missing_recipe_file_is_excluded_and_named(recipes_dir: Path):
    write_recipe(recipes_dir, "Turkey Chili", calories=300, protein=32, carbs=25, fat=9)
    meal = Meal(name="Chili Bowl", sub_recipes=[
        SubRecipe(recipe="Turkey Chili"),
        SubRecipe(recipe="Deleted Recipe"),
    ])

    result = meal_nutrition(meal, recipes_dir)

    assert result["calories"] == 300
    assert result["incomplete"] is True
    assert result["excluded"] == ["Deleted Recipe"]
    assert result["sub"][1]["reasons"] == ["missing"]


def test_empty_meal_is_zero_and_complete(recipes_dir: Path):
    result = meal_nutrition(Meal(name="Nothing Yet"), recipes_dir)
    assert result == {
        "calories": 0.0, "protein": 0.0, "carbs": 0.0, "fat": 0.0,
        "sub": [], "incomplete": False, "excluded": [],
    }


def test_macro_cache_reads_each_recipe_once(recipes_dir: Path):
    """The cache is what keeps /api/meals from re-reading shared sub-recipes."""
    write_recipe(recipes_dir, "Turkey Chili", calories=300)
    cache: dict = {}
    meal_a = Meal(name="A", sub_recipes=[SubRecipe(recipe="Turkey Chili")])
    meal_b = Meal(name="B", sub_recipes=[SubRecipe(recipe="Turkey Chili")])

    meal_nutrition(meal_a, recipes_dir, macro_cache=cache)
    (recipes_dir / "Turkey Chili.md").unlink()
    result = meal_nutrition(meal_b, recipes_dir, macro_cache=cache)

    assert result["calories"] == 300, "second rollup served from cache, not disk"
    assert set(cache) == {"Turkey Chili"}
