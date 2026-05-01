"""Tests for lib.meal_loader."""
from pathlib import Path

from lib.meal_loader import (
    Meal,
    SubRecipe,
    delete_meal,
    list_meals,
    load_meal,
    parse_meal_file,
    save_meal,
)


SAMPLE_MEAL = """---
type: meal
name: "Salmon Dinner"
description: "Weeknight pan-seared salmon with sides"
tags: ["weeknight", "fish"]
sub_recipes:
  - recipe: "Pan-Seared Salmon"
    servings: 1
  - recipe: "Lemon Asparagus"
  - recipe: "Wild Rice Pilaf"
    servings: 2
---

Notes about the meal go here.
"""


def test_parse_meal_file_extracts_frontmatter_and_body():
    parsed = parse_meal_file(SAMPLE_MEAL)
    fm = parsed["frontmatter"]
    assert fm["name"] == "Salmon Dinner"
    assert fm["description"] == "Weeknight pan-seared salmon with sides"
    assert fm["tags"] == ["weeknight", "fish"]
    assert len(fm["sub_recipes"]) == 3
    assert fm["sub_recipes"][0] == {"recipe": "Pan-Seared Salmon", "servings": 1}
    assert fm["sub_recipes"][1] == {"recipe": "Lemon Asparagus"}
    assert fm["sub_recipes"][2] == {"recipe": "Wild Rice Pilaf", "servings": 2}
    assert "Notes about the meal" in parsed["body"]


def test_load_meal_returns_meal_object(tmp_path: Path):
    (tmp_path / "Salmon Dinner.meal.md").write_text(SAMPLE_MEAL)
    meal = load_meal("Salmon Dinner", meals_dir=tmp_path)
    assert isinstance(meal, Meal)
    assert meal.name == "Salmon Dinner"
    assert meal.tags == ["weeknight", "fish"]
    assert len(meal.sub_recipes) == 3
    assert meal.sub_recipes[0] == SubRecipe(recipe="Pan-Seared Salmon", servings=1)
    assert meal.sub_recipes[1] == SubRecipe(recipe="Lemon Asparagus", servings=1)
    assert meal.sub_recipes[2] == SubRecipe(recipe="Wild Rice Pilaf", servings=2)


def test_load_meal_missing_returns_none(tmp_path: Path):
    assert load_meal("Nope", meals_dir=tmp_path) is None


def test_list_meals_sorted_and_skips_other_files(tmp_path: Path):
    (tmp_path / "Salmon Dinner.meal.md").write_text(SAMPLE_MEAL)
    (tmp_path / "Avocado Toast.meal.md").write_text(
        '---\ntype: meal\nname: "Avocado Toast"\nsub_recipes:\n  - recipe: "Avocado Toast"\n---\n'
    )
    (tmp_path / "Notes.md").write_text("# Not a meal")
    meals = list_meals(meals_dir=tmp_path)
    assert [m.name for m in meals] == ["Avocado Toast", "Salmon Dinner"]


def test_save_meal_round_trip(tmp_path: Path):
    meal = Meal(
        name="Tacos Tuesday",
        description="Quick weeknight tacos",
        tags=["mexican", "weeknight"],
        sub_recipes=[
            SubRecipe(recipe="Beef Tacos", servings=2),
            SubRecipe(recipe="Pico de Gallo"),
        ],
        body="Make pico the day before.",
    )
    save_meal(meal, meals_dir=tmp_path)
    loaded = load_meal("Tacos Tuesday", meals_dir=tmp_path)
    assert loaded is not None
    assert loaded.name == meal.name
    assert loaded.description == meal.description
    assert loaded.tags == meal.tags
    assert loaded.sub_recipes == meal.sub_recipes
    assert "Make pico the day before." in loaded.body


def test_delete_meal(tmp_path: Path):
    (tmp_path / "Trash.meal.md").write_text(
        '---\ntype: meal\nname: "Trash"\nsub_recipes:\n  - recipe: "Junk"\n---\n'
    )
    assert delete_meal("Trash", meals_dir=tmp_path) is True
    assert delete_meal("Trash", meals_dir=tmp_path) is False
    assert not (tmp_path / "Trash.meal.md").exists()


def test_list_meals_handles_missing_dir(tmp_path: Path):
    missing = tmp_path / "does_not_exist"
    assert list_meals(meals_dir=missing) == []


def test_save_meal_creates_dir(tmp_path: Path):
    target = tmp_path / "fresh"
    meal = Meal(name="Cereal", sub_recipes=[SubRecipe(recipe="Cornflakes")])
    save_meal(meal, meals_dir=target)
    assert (target / "Cereal.meal.md").exists()
