"""Refusing a food match that shares no word with the ingredient."""

import pytest

from lib.resolution_guard import shares_a_food_word, vet


class TestCatchesTheRealFailures:
    """Every case here was found in the live resolution cache."""

    @pytest.mark.parametrize("ingredient,description", [
        ("blueberries, fresh", "Basil, fresh"),
        ("cm piece of fresh ginger", "Basil, fresh"),
        ("chicken mince", "Ham, minced"),
        ("aleppo pepper (1 tsp for mild)", "Frankfurter, beef, heated"),
        ("breadcrumbs", "Abiyuch, raw"),
        ("collagen peptides", "Abiyuch, raw"),
        ("additional butter for frying", "Fish, pollock, Alaska, raw"),
        ("ayran", "Alfalfa seeds, sprouted, raw"),
    ])
    def test_rejected(self, ingredient, description):
        assert shares_a_food_word(ingredient, description) is False

    def test_a_shared_modifier_is_not_a_match(self):
        """"fresh" is the only word blueberries and basil have in common, and it
        describes treatment, not identity."""
        assert shares_a_food_word("blueberries, fresh", "Basil, fresh") is False
        assert shares_a_food_word("blueberries, fresh", "Blueberries, dried") is True


class TestKeepsGoodMatches:
    """The rule must never reject a correct match worded differently."""

    @pytest.mark.parametrize("ingredient,description", [
        ("greek yogurt", "Yogurt, Greek, plain, nonfat"),
        ("blueberries", "Blueberries, raw"),
        ("blueberry", "Blueberries, raw"),
        ("light brown sugar", "Sugars, brown"),
        ("olive oil", "Oil, olive, salad or cooking"),
        ("large eggs", "Eggs, Grade A, Large, egg whole"),
        ("unsweetened cocoa powder", "Cocoa, dry powder, unsweetened"),
        ("chicken breast", "Chicken, broilers or fryers, breast, meat only, raw"),
        ("cherry tomatoes, halved", "Tomatoes, cherry, raw"),
    ])
    def test_accepted(self, ingredient, description):
        assert shares_a_food_word(ingredient, description) is True

    def test_plurals_agree(self):
        assert shares_a_food_word("carrot", "Carrots, raw") is True


class TestEmptyIngredient:
    @pytest.mark.parametrize("ingredient", ["", "*(inferred)*", "(sweetener)", "optional"])
    def test_nothing_identifying_cannot_be_matched(self, ingredient):
        """These resolved to real foods at confidence 1.0. With no food word in
        the ingredient there is nothing a match could be justified against."""
        assert shares_a_food_word(ingredient, "Blueberries, dried, sweetened") is False


class TestVet:
    def test_a_good_match_passes_through_untouched(self):
        conf, resolver, note = vet("greek yogurt", "Yogurt, Greek, plain", 0.95, "llm-ollama")
        assert (conf, resolver, note) == (0.95, "llm-ollama", "")

    def test_a_bad_match_is_stripped_of_confidence_not_discarded(self):
        """An ingredient may genuinely have no USDA equivalent, so a weak number
        can beat none — it just must not pose as settled."""
        conf, resolver, note = vet("breadcrumbs", "Abiyuch, raw", 0.95, "llm-ollama")
        assert conf == 0.2
        assert resolver == "llm-ollama-unvetted"
        assert "shares no food word" in note

    def test_the_downgrade_falls_below_the_review_threshold(self):
        """Below REVIEW_CONFIDENCE the recipe gets flagged, which is the point."""
        from lib.nutrition_engine import REVIEW_CONFIDENCE
        assert vet("breadcrumbs", "Abiyuch, raw", 1.0, "llm-ollama")[0] < REVIEW_CONFIDENCE


class TestSingularizerWorkaround:
    """normalize_food_name mangles -oes/-ves plurals ("tomatoes" -> "tomatoe"),
    so plural ingredients never matched their singular USDA food."""

    @pytest.mark.parametrize("ingredient,description", [
        ("cherry tomatoes, halved", "Tomato, roma"),
        ("potatoes", "Potato, raw"),
        ("bay leaves", "Spices, bay leaf"),
    ])
    def test_plural_forms_still_match(self, ingredient, description):
        assert shares_a_food_word(ingredient, description) is True

    def test_folding_does_not_collapse_distinct_foods(self):
        assert shares_a_food_word("rice", "Ice, water") is False
