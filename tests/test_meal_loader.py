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


# --- Fractional servings + slot binding ---

from lib.meal_loader import DEFAULT_SLOT, normalize_slot


def test_fractional_servings_round_trip(tmp_path: Path):
    """1.5 survives parse -> render -> parse, and 2.0 renders as `2`."""
    meal = Meal(
        name="Chili Bowl Lunch",
        sub_recipes=[
            SubRecipe(recipe="Turkey Chili", servings=1.5),
            SubRecipe(recipe="Cornbread", servings=0.5),
            SubRecipe(recipe="Side Salad", servings=2.0),
            SubRecipe(recipe="Roll", servings=1.0),
        ],
    )
    save_meal(meal, meals_dir=tmp_path)

    raw = (tmp_path / "Chili Bowl Lunch.meal.md").read_text()
    assert "servings: 1.5" in raw
    assert "servings: 0.5" in raw
    assert "servings: 2\n" in raw, "a whole number must not render as 2.0"
    assert "2.0" not in raw
    # servings of exactly 1 stays omitted, as before
    assert raw.count("servings:") == 3

    loaded = load_meal("Chili Bowl Lunch", meals_dir=tmp_path)
    assert [s.servings for s in loaded.sub_recipes] == [1.5, 0.5, 2.0, 1.0]


def test_parses_fractional_servings_from_file(tmp_path: Path):
    (tmp_path / "Split.meal.md").write_text(
        '---\ntype: meal\nname: "Split"\nsub_recipes:\n'
        '  - recipe: "Chili"\n    servings: 1.5\n---\n'
    )
    meal = load_meal("Split", meals_dir=tmp_path)
    assert meal.sub_recipes[0].servings == 1.5


def test_bad_servings_falls_back_to_one_without_raising(tmp_path: Path):
    """A garbage value must not make the meal vanish — list_meals swallows raises."""
    (tmp_path / "Bad.meal.md").write_text(
        '---\ntype: meal\nname: "Bad"\nsub_recipes:\n'
        '  - recipe: "Zero"\n    servings: 0\n'
        '  - recipe: "Negative"\n    servings: -2\n'
        '  - recipe: "Words"\n    servings: lots\n'
        '  - recipe: "Empty"\n    servings:\n---\n'
    )
    meal = load_meal("Bad", meals_dir=tmp_path)
    assert [s.servings for s in meal.sub_recipes] == [1.0, 1.0, 1.0, 1.0]
    assert [m.name for m in list_meals(meals_dir=tmp_path)] == ["Bad"]


def test_slot_defaults_to_dinner_and_is_not_written_back(tmp_path: Path):
    (tmp_path / "Legacy.meal.md").write_text(
        '---\ntype: meal\nname: "Legacy"\nsub_recipes:\n  - recipe: "Chili"\n---\n'
    )
    meal = load_meal("Legacy", meals_dir=tmp_path)
    assert meal.slot == "dinner"

    save_meal(meal, meals_dir=tmp_path)
    assert "slot:" not in (tmp_path / "Legacy.meal.md").read_text()


def test_slot_round_trip(tmp_path: Path):
    meal = Meal(name="Chili Bowl Lunch", slot="lunch",
                sub_recipes=[SubRecipe(recipe="Chili")])
    save_meal(meal, meals_dir=tmp_path)
    assert "slot: lunch" in (tmp_path / "Chili Bowl Lunch.meal.md").read_text()
    assert load_meal("Chili Bowl Lunch", meals_dir=tmp_path).slot == "lunch"


def test_unrecognised_slot_falls_back_to_dinner(tmp_path: Path):
    (tmp_path / "Brunchy.meal.md").write_text(
        '---\ntype: meal\nname: "Brunchy"\nslot: brunch\n'
        'sub_recipes:\n  - recipe: "Eggs"\n---\n'
    )
    assert load_meal("Brunchy", meals_dir=tmp_path).slot == "dinner"


def test_normalize_slot():
    assert normalize_slot("lunch") == "lunch"
    assert normalize_slot("  DINNER ") == "dinner"
    assert normalize_slot("snack") == "snack"
    assert normalize_slot("brunch") == DEFAULT_SLOT
    assert normalize_slot(None) == DEFAULT_SLOT
    assert normalize_slot(3) == DEFAULT_SLOT


def test_to_dict_includes_slot():
    meal = Meal(name="Lunchy", slot="lunch",
                sub_recipes=[SubRecipe(recipe="Chili", servings=1.5)])
    d = meal.to_dict()
    assert d["slot"] == "lunch"
    assert d["sub_recipes"] == [{"recipe": "Chili", "servings": 1.5}]
