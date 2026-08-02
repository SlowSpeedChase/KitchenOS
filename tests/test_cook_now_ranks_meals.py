"""Cook Now must answer "what should I make", not "what can I bake".

Reported from a real week: the top five results were Blueberry Muffins, Gooey
Chocolate Brownies, Chewy Peanut Butter Cookies, Strawberry Brownies and
Strawberry Buttercream Frosting. All true — every ingredient was on hand — and
none of them is dinner.

The cause is that a pantry is mostly dry goods (flour, sugar, cocoa, baking
powder), so ranking on ingredient coverage alone systematically favours baking.
"What can I make" and "what should I make" are different questions on that
inventory, and the page was answering the first while being asked the second.
"""

from lib import cook_now


class _Item:
    """Minimal stand-in for an inventory row."""

    def __init__(self, name):
        self.name = name
        self.expires = None
        self.quantity = 1.0
        self.unit = "ct"


def _recipe(name, dish_type, ingredients, protein=None, coverage=0.95, servings=4):
    return {
        "name": name,
        "dish_type": dish_type,
        "ingredient_items": ingredients,
        "nutrition_protein": protein,
        "nutrition_calories": 500 if protein is not None else None,
        "nutrition_coverage": coverage,
        "servings": servings,
    }


PANTRY = [_Item(n) for n in
          ("flour", "sugar", "cocoa powder", "butter", "eggs", "chicken", "rice")]


def _ranked(recipes, **kw):
    out = cook_now.generate(items=PANTRY, recipe_index=recipes, **kw)
    return [r["recipe"] for r in out["recipes"]]


class TestMealsOutrankTreats:
    def test_a_main_beats_a_fully_covered_dessert(self):
        """The exact reported failure: brownies above dinner."""
        order = _ranked([
            _recipe("Brownies", "dessert", ["flour", "sugar", "cocoa powder"], protein=4),
            _recipe("Chicken and Rice", "main", ["chicken", "rice", "butter"], protein=38),
        ])
        assert order[0] == "Chicken and Rice"

    def test_a_near_miss_main_still_beats_a_complete_dessert(self):
        """Missing one ingredient for dinner beats having everything for cake.

        The card names what's missing, so this is honest rather than a tease —
        and "closest real meal" is the useful answer on a baking-heavy pantry.
        """
        order = _ranked([
            _recipe("Brownies", "dessert", ["flour", "sugar", "cocoa powder"], protein=4),
            _recipe("Chicken Bowl", "main",
                    ["chicken", "rice", "butter", "scallions"], protein=40),
        ])
        assert order[0] == "Chicken Bowl"

    def test_a_mostly_missing_main_does_not_outrank_a_complete_dessert(self):
        """The boost is a weighting, not a licence to show impossible meals."""
        order = _ranked([
            _recipe("Brownies", "dessert", ["flour", "sugar", "cocoa powder"], protein=4),
            _recipe("Elaborate Roast", "main",
                    ["chicken"] + [f"exotic {i}" for i in range(9)], protein=40),
        ])
        assert order[0] == "Brownies"

    def test_sides_sit_between_meals_and_desserts(self):
        order = _ranked([
            _recipe("Frosting", "dessert", ["sugar", "butter"], protein=0),
            _recipe("Garlic Butter", "sauce", ["butter", "flour"], protein=1),
            _recipe("Chicken Rice", "main", ["chicken", "rice"], protein=38),
        ])
        assert order == ["Chicken Rice", "Garlic Butter", "Frosting"]

    def test_breakfast_counts_as_a_meal(self):
        """Muffins are `breakfast` in this library; eggs are too. Protein splits them."""
        order = _ranked([
            _recipe("Blueberry Muffins", "breakfast",
                    ["flour", "sugar", "butter", "eggs"], protein=5),
            _recipe("Scrambled Eggs", "breakfast", ["eggs", "butter"], protein=22),
        ])
        assert order[0] == "Scrambled Eggs"


class TestProteinBreaksTies:
    def test_the_higher_protein_meal_wins_an_equal_match(self):
        order = _ranked([
            _recipe("Plain Rice", "main", ["rice", "butter"], protein=4),
            _recipe("Chicken Rice", "main", ["rice", "chicken"], protein=38),
        ])
        assert order[0] == "Chicken Rice"

    def test_implausible_protein_is_not_ranked_on(self):
        """The 244 g-protein smoothie must not win this the way it won suggest.

        Phase 1's plausibility gate is what makes protein safe to sort by at
        all; without consulting it this would reintroduce the same failure in a
        new place.
        """
        order = _ranked([
            _recipe("Fake Protein Bomb", "main", ["flour", "sugar"], protein=244),
            _recipe("Chicken Rice", "main", ["rice", "chicken"], protein=38),
        ])
        assert order[0] == "Chicken Rice"

    def test_missing_protein_data_does_not_crash_or_win(self):
        order = _ranked([
            _recipe("Unknown Macros", "main", ["rice", "chicken"], protein=None),
            _recipe("Chicken Rice", "main", ["rice", "chicken"], protein=38),
        ])
        assert order[0] == "Chicken Rice"


class TestPayload:
    def test_each_result_reports_why_it_ranked(self):
        out = cook_now.generate(items=PANTRY, recipe_index=[
            _recipe("Chicken Rice", "main", ["rice", "chicken"], protein=38)])
        r = out["recipes"][0]
        assert r["meal_tier"] == "meal"
        assert r["protein"] == 38
        assert 0 < r["score"] <= 1.0

    def test_an_unknown_dish_type_is_treated_as_a_meal(self):
        """Same rule as group_for: a data gap must not hide a cookable recipe."""
        out = cook_now.generate(items=PANTRY, recipe_index=[
            _recipe("Mystery", None, ["rice", "chicken"], protein=20)])
        assert out["recipes"][0]["meal_tier"] == "meal"

    def test_coverage_is_still_reported_unchanged(self):
        out = cook_now.generate(items=PANTRY, recipe_index=[
            _recipe("Chicken Rice", "main", ["rice", "chicken"], protein=38)])
        assert out["recipes"][0]["coverage"] == 1.0


class TestNutritionCarriesRealWeight:
    """Dish type alone wasn't enough — muffins are `breakfast`.

    On the real pantry, tier-only ranking still returned Blueberry Muffins at
    #2. They classify as a meal because the library files them under breakfast,
    which is true and not the point: they are a meal the way a scone is a meal.
    """

    def test_a_muffin_does_not_outrank_a_real_dinner(self):
        order = _ranked([
            _recipe("Blueberry Muffins", "breakfast",
                    ["flour", "sugar", "butter", "eggs"], protein=10),
            _recipe("Steak Skillet", "main", ["chicken", "rice", "butter"], protein=42),
        ])
        assert order[0] == "Steak Skillet"

    def test_a_muffin_loses_even_with_better_coverage(self):
        """Fully stocked for muffins, one item short for dinner: dinner wins."""
        order = _ranked([
            _recipe("Blueberry Muffins", "breakfast",
                    ["flour", "sugar", "butter"], protein=10),
            _recipe("Chicken Bowl", "main",
                    ["chicken", "rice", "butter", "scallions"], protein=40),
        ])
        assert order[0] == "Chicken Bowl"

    def test_unknown_macros_land_mid_range_not_at_the_bottom(self):
        """Missing data isn't evidence of poor nutrition."""
        out = cook_now.generate(items=PANTRY, recipe_index=[
            _recipe("No Macros", "main", ["rice", "chicken"], protein=None),
            _recipe("Low Protein", "main", ["rice", "chicken"], protein=0),
            _recipe("High Protein", "main", ["rice", "chicken"], protein=40),
        ])
        order = [r["recipe"] for r in out["recipes"]]
        assert order == ["High Protein", "No Macros", "Low Protein"]
