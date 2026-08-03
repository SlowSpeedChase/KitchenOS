"""One Meal -> the cook rows that represent it on a week."""
import pytest

from lib import meal_bundle, serving_ledger as sl
from lib.meal_loader import Meal, SubRecipe
from lib.meal_nutrition import meal_nutrition

RECIPE_MD = """---
title: {name}
servings: {servings}
nutrition_calories: {cal}
nutrition_protein: {protein}
nutrition_carbs: 40
nutrition_fat: 20
nutrition_coverage: 0.95
---
"""


def _recipe(recipes, name, cal=500, protein=30, servings=4):
    recipes.mkdir(parents=True, exist_ok=True)
    (recipes / f"{name}.md").write_text(
        RECIPE_MD.format(name=name, servings=servings, cal=cal, protein=protein),
        encoding="utf-8")


def _plate(**over):
    kw = dict(name="Osso Buco Plate", sub_recipes=[
        SubRecipe(recipe="Osso Buco"),
        SubRecipe(recipe="Garlic Toast", servings=0.5),
    ])
    kw.update(over)
    return Meal(**kw)


class TestPlanBundle:
    def test_share_is_both_the_scale_and_the_servings_placed(self, tmp_vault):
        """Not a coincidence — it is what makes the two surfaces agree."""
        _recipe(tmp_vault / "Recipes", "Osso Buco")
        _recipe(tmp_vault / "Recipes", "Garlic Toast", servings=2)
        members = meal_bundle.plan_bundle(_plate())
        by_name = {m["recipe"]: m for m in members}
        assert by_name["Osso Buco"]["scale"] == 1.0
        assert by_name["Osso Buco"]["initial_placement_count"] == 1.0
        assert by_name["Garlic Toast"]["scale"] == 0.5
        assert by_name["Garlic Toast"]["initial_placement_count"] == 0.5

    def test_servings_produced_is_the_recipe_yield_times_scale(self, tmp_vault):
        _recipe(tmp_vault / "Recipes", "Osso Buco", servings=4)
        _recipe(tmp_vault / "Recipes", "Garlic Toast", servings=2)
        by_name = {m["recipe"]: m for m in meal_bundle.plan_bundle(_plate())}
        assert by_name["Osso Buco"]["servings_produced"] == 4.0     # 4 x 1.0
        assert by_name["Garlic Toast"]["servings_produced"] == 1.0  # 2 x 0.5

    def test_outer_scale_multiplies_through_sub_multiplier(self, tmp_vault):
        """A 1.5 sub at outer 2.0 is 3.0, not 2 — the int() truncation guard."""
        _recipe(tmp_vault / "Recipes", "Osso Buco")
        _recipe(tmp_vault / "Recipes", "Garlic Toast")
        plate = _plate(sub_recipes=[SubRecipe(recipe="Osso Buco", servings=1.5)])
        assert meal_bundle.plan_bundle(plate, 2.0)[0]["scale"] == 3.0

    def test_a_recipe_with_no_file_falls_back_to_four_servings(self, tmp_vault):
        """Pins week_view.recipe_base_servings' 4.0 fallback, previously untested."""
        (tmp_vault / "Recipes").mkdir(parents=True, exist_ok=True)
        plate = _plate(sub_recipes=[SubRecipe(recipe="Nonexistent")])
        assert meal_bundle.plan_bundle(plate)[0]["servings_produced"] == 4.0

    def test_a_nonsense_yield_does_not_produce_a_negative_batch(self, tmp_vault):
        """servings: -1 would make servings_produced negative and 400 the write."""
        _recipe(tmp_vault / "Recipes", "Osso Buco", servings=-1)
        plate = _plate(sub_recipes=[SubRecipe(recipe="Osso Buco")])
        assert meal_bundle.plan_bundle(plate)[0]["servings_produced"] > 0


class TestPlaceMeal:
    def test_it_creates_the_bundle(self, tmp_db, tmp_vault):
        _recipe(tmp_vault / "Recipes", "Osso Buco")
        _recipe(tmp_vault / "Recipes", "Garlic Toast")
        meals = tmp_vault / "Meals"
        meals.mkdir(parents=True, exist_ok=True)
        from lib import meal_loader
        meal_loader.save_meal(_plate(), meals_dir=meals)

        b = meal_bundle.place_meal("Osso Buco Plate", "2026-W28",
                                   "2026-07-07", "dinner", meals_dir=meals)
        assert [c["recipe"] for c in b["cooks"]] == ["Osso Buco", "Garlic Toast"]
        assert all(c["bundle_name"] == "Osso Buco Plate" for c in b["cooks"])

    def test_an_unknown_meal_raises(self, tmp_db, tmp_vault):
        meals = tmp_vault / "Meals"
        meals.mkdir(parents=True, exist_ok=True)
        with pytest.raises(ValueError):
            meal_bundle.place_meal("No Such Plate", "2026-W28",
                                   "2026-07-07", "dinner", meals_dir=meals)

    def test_a_meal_with_no_sub_recipes_raises(self, tmp_db, tmp_vault):
        meals = tmp_vault / "Meals"
        meals.mkdir(parents=True, exist_ok=True)
        from lib import meal_loader
        meal_loader.save_meal(_plate(sub_recipes=[]), meals_dir=meals)
        with pytest.raises(ValueError):
            meal_bundle.place_meal("Osso Buco Plate", "2026-W28",
                                   "2026-07-07", "dinner", meals_dir=meals)


class TestTheIdentity:
    """day_totals[date] == meal_nutrition(meal) x outer.

    The keystone. The card figure and the day total are the same arithmetic over
    the same gate — if this drifts, one of the two surfaces is lying.
    """

    @pytest.mark.parametrize("outer", [1.0, 1.5, 2.0])
    def test_a_placed_plate_contributes_exactly_its_card_figure(
            self, tmp_db, tmp_vault, outer):
        recipes = tmp_vault / "Recipes"
        _recipe(recipes, "Osso Buco", cal=640, protein=62, servings=4)
        _recipe(recipes, "Garlic Toast", cal=210, protein=6, servings=2)
        _recipe(recipes, "Beans", cal=180, protein=11, servings=6)
        plate = _plate(sub_recipes=[
            SubRecipe(recipe="Osso Buco"),
            SubRecipe(recipe="Garlic Toast", servings=0.5),
            SubRecipe(recipe="Beans", servings=0.25),
        ])
        sl.create_bundle("Osso Buco Plate",
                         meal_bundle.plan_bundle(plate, outer), "2026-W28",
                         date="2026-07-07", meal="dinner")

        card = meal_nutrition(plate, recipes)
        day = sl.day_totals("2026-W28", recipes)["2026-07-07"]
        for k in ("calories", "protein", "carbs", "fat"):
            assert day[k] == pytest.approx(card[k] * outer), \
                f"{k}: day row and plate card disagree"

    def test_both_surfaces_name_the_same_exclusion(self, tmp_db, tmp_vault):
        recipes = tmp_vault / "Recipes"
        _recipe(recipes, "Osso Buco")
        _recipe(recipes, "Garlic Toast")
        # Below the coverage threshold: excluded by the shared gate.
        (recipes / "Garlic Toast.md").write_text(
            RECIPE_MD.format(name="Garlic Toast", servings=2, cal=210, protein=6)
            .replace("nutrition_coverage: 0.95", "nutrition_coverage: 0.3"),
            encoding="utf-8")
        plate = _plate()
        sl.create_bundle("Osso Buco Plate", meal_bundle.plan_bundle(plate),
                         "2026-W28", date="2026-07-07", meal="dinner")

        card = meal_nutrition(plate, recipes)
        day = sl.day_totals("2026-W28", recipes)["2026-07-07"]
        assert card["excluded"] == ["Garlic Toast"]
        assert day["excluded"] == ["Garlic Toast"]
        assert day["calories"] == pytest.approx(card["calories"])


class TestGroupBundles:
    def test_it_groups_by_bundle_date_and_slot(self, tmp_db, tmp_vault):
        _recipe(tmp_vault / "Recipes", "Osso Buco")
        _recipe(tmp_vault / "Recipes", "Garlic Toast")
        plate = _plate()
        sl.create_bundle("Osso Buco Plate", meal_bundle.plan_bundle(plate),
                         "2026-W28", date="2026-07-07", meal="dinner")
        sl.create_cook(recipe="Chili", week="2026-W28", servings_produced=4.0,
                       date="2026-07-08", meal="dinner")

        groups = meal_bundle.group_bundles(sl.cooks_for_week("2026-W28"))
        plates = [g for g in groups if g["bundle_id"]]
        singles = [g for g in groups if not g["bundle_id"]]
        assert len(plates) == 1 and len(plates[0]["cooks"]) == 2
        assert len(singles) == 1 and singles[0]["cooks"][0]["recipe"] == "Chili"

    def test_a_member_moved_away_becomes_its_own_group(self, tmp_db, tmp_vault):
        """Grouping is (bundle_id, date, meal) — rendering it in a cell it is
        not in would be a lie."""
        _recipe(tmp_vault / "Recipes", "Osso Buco")
        _recipe(tmp_vault / "Recipes", "Garlic Toast")
        b = sl.create_bundle("Osso Buco Plate",
                             meal_bundle.plan_bundle(_plate()), "2026-W28",
                             date="2026-07-07", meal="dinner")
        sl.move_cook(b["cooks"][1]["id"], "2026-07-08", "lunch")
        groups = meal_bundle.group_bundles(sl.cooks_for_week("2026-W28"))
        assert len(groups) == 2
        assert {len(g["cooks"]) for g in groups} == {1}
