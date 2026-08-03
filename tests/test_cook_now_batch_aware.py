"""Cook Now on a week with no time: batch size and what's already banked.

Reported from a real week — "I'm not going to eat the same meal three days in a
row; that's why freezing is an option to help with variety." The suggester was
blind to both halves of that. It never read `servings`, so a one-serving oatmeal
competed on equal terms with a recipe that feeds five, and it never read the
freezer, so it kept recommending dinners already sitting cooked in a container.

Both factors are deliberately weak — a batch of something you can't eat is still
the wrong answer, and coverage and nutrition remain the load-bearing terms.
"""
import pytest

from lib import cook_now


class _Item:
    def __init__(self, name):
        self.name = name
        self.expires = None
        self.quantity = 1.0
        self.unit = "ct"


PANTRY = [_Item(n) for n in ("chicken", "rice", "butter", "flour", "eggs")]


def _recipe(name, servings=4, protein=40, dish_type="main",
            ingredients=("chicken", "rice")):
    return {
        "name": name,
        "dish_type": dish_type,
        "ingredient_items": list(ingredients),
        "nutrition_protein": protein,
        "nutrition_calories": 500,
        "nutrition_coverage": 1.0,
        "servings": servings,
    }


def _ranked(recipes, **kw):
    kw.setdefault("banked", set())
    out = cook_now.generate(items=PANTRY, recipe_index=recipes, **kw)
    return [r["recipe"] for r in out["recipes"]]


class TestBatchSize:
    def test_a_batch_outranks_a_single_serving(self):
        """One cooking session that feeds you four times beats one that feeds you once."""
        order = _ranked([
            _recipe("Single Bowl", servings=1),
            _recipe("Big Batch", servings=5),
        ])
        assert order[0] == "Big Batch"

    def test_the_benefit_saturates_rather_than_running_away(self):
        """A 20-serving recipe is not five times better than a 4-serving one."""
        out = cook_now.generate(items=PANTRY, banked=set(), recipe_index=[
            _recipe("Four", servings=4), _recipe("Twenty", servings=20)])
        scores = {r["recipe"]: r["score"] for r in out["recipes"]}
        assert scores["Twenty"] == scores["Four"]

    def test_unknown_servings_is_neutral_not_penalised(self):
        """Same rule as unknown macros and unknown time: absence isn't evidence."""
        out = cook_now.generate(items=PANTRY, banked=set(), recipe_index=[
            _recipe("Unknown", servings=None)])
        r = out["recipes"][0]
        assert r["servings"] is None
        assert r["score"] > 0

    def test_batch_size_cannot_promote_a_dessert_over_a_meal(self):
        """The weakest factor stays the weakest factor."""
        order = _ranked([
            _recipe("Giant Cake", servings=16, protein=5, dish_type="dessert"),
            _recipe("Small Dinner", servings=2, protein=40, dish_type="main"),
        ])
        assert order[0] == "Small Dinner"

    def test_a_junk_servings_value_does_not_crash_the_page(self):
        """`servings` has been a string, a range and null in this corpus."""
        for bad in ("6-8", "", [], {}, -3, 0):
            out = cook_now.generate(items=PANTRY, banked=set(),
                                    recipe_index=[_recipe("Odd", servings=bad)])
            assert out["recipes"][0]["score"] > 0


class TestAlreadyInTheFreezer:
    def test_a_banked_recipe_sinks(self):
        """You don't need to cook what's already cooked."""
        order = _ranked([
            _recipe("In The Freezer"),
            _recipe("Not Yet Made"),
        ], banked={"In The Freezer"})
        assert order[0] == "Not Yet Made"

    def test_it_is_demoted_not_hidden(self):
        """Still an answer to "what can I eat" — the tray links to it."""
        out = cook_now.generate(items=PANTRY, banked={"Chili"},
                                recipe_index=[_recipe("Chili")])
        assert [r["recipe"] for r in out["recipes"]] == ["Chili"]
        assert out["recipes"][0]["banked"] is True

    def test_an_unbanked_recipe_says_so(self):
        out = cook_now.generate(items=PANTRY, banked=set(),
                                recipe_index=[_recipe("Chili")])
        assert out["recipes"][0]["banked"] is False


class TestProteinTargetComesFromTheVault:
    """The hardcoded 30 g was calibrated to a 120 g/day target, not the real one.

    Its own comment said "against a 190 g/day target across roughly four eating
    occasions" — but 4 x 30 is 120. The effect was that the nutrition factor
    saturated at 30 g, so a 30 g dish and a 68 g dish scored identically and the
    ranking could not tell a light meal from a heavy one.
    """

    def test_it_reads_the_daily_target_from_my_macros(self, tmp_vault):
        (tmp_vault / "My Macros.md").write_text(
            "---\ncalories: 2300\nprotein: 190\ncarbs: 228\nfat: 70\n---\n",
            encoding="utf-8")
        assert cook_now.meal_protein_target() == pytest.approx(47.5)

    def test_a_vault_without_targets_keeps_the_old_behaviour(self, tmp_vault):
        assert cook_now.meal_protein_target() == pytest.approx(30.0)

    def test_a_heavier_meal_now_outranks_a_merely_adequate_one(self):
        """At the old saturating 30 g these two were indistinguishable."""
        order = _ranked([
            _recipe("Adequate", protein=30),
            _recipe("Substantial", protein=68),
        ], protein_target=47.5)
        assert order[0] == "Substantial"

    def test_the_target_is_never_zero_or_negative(self, tmp_vault):
        """A zeroed target would divide by zero on every render."""
        (tmp_vault / "My Macros.md").write_text(
            "---\ncalories: 0\nprotein: 0\ncarbs: 0\nfat: 0\n---\n", encoding="utf-8")
        assert cook_now.meal_protein_target() > 0
