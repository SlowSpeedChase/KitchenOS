"""The short-title validator — the part that has to be right.

An LLM asked to shorten a recipe name will, given three attempts and a rejection,
start reaching into the ingredient list for words. Every case in
:class:`TestRejectsWhatTheModelActuallyDid` was produced by mistral:7b or Claude
against this repo's own recipes, not invented for the test.
"""
from __future__ import annotations

import pytest

from lib import short_title
from lib.short_title import display_name, needs_shortening, validate_short_title


class TestDisplayName:
    def test_the_name_is_the_fallback(self):
        assert display_name("Beef Birria", None) == "Beef Birria"
        assert display_name("Beef Birria", "") == "Beef Birria"
        assert display_name("Beef Birria", "   ") == "Beef Birria"

    def test_a_short_title_wins_when_present(self):
        assert display_name("Maple Sweet Potato Salad - With Whipped Tahini",
                            "Maple Sweet Potato Salad") == "Maple Sweet Potato Salad"


class TestNeedsShortening:
    def test_only_over_the_threshold(self):
        assert not needs_shortening("Beef Birria")
        assert not needs_shortening("x" * (short_title.SHORTEN_THRESHOLD - 1))
        assert needs_shortening("x" * short_title.SHORTEN_THRESHOLD)

    def test_the_threshold_and_the_limit_are_coherent(self):
        """Anything shortened must be able to land inside the limit."""
        assert short_title.MAX_SHORT_LEN < short_title.SHORTEN_THRESHOLD


class TestAcceptsRealShortenings:
    """All produced by the live models against this repo's recipes."""

    @pytest.mark.parametrize("original,candidate", [
        ("19 Calorie Fudgy Brownies (Crouton)", "Fudgy Brownies (Crouton)"),
        ("5-Ingredient Cottage Cheese Cookie Dough", "Cottage Cheese Cookie Dough"),
        ("Charred Corn Salad With White Beans", "Charred Corn Salad White Beans"),
        ("Cherry Vanilla Breakfast Smoothie", "Cherry Vanilla Smoothie"),
        ("Chick-Fil-A Style Chicken Nuggets", "Chick-Fil-A Chicken Nuggets"),
        ("Blueberry Donut Holes (Cottage Cheese Or Yogurt)", "Blueberry Donut Holes"),
        ("Maple Sweet Potato Salad - With Whipped Tahini And Crispy Chickpeas",
         "Maple Sweet Potato Salad"),
    ])
    def test_accepted(self, original, candidate):
        ok, reason = validate_short_title(original, candidate)
        assert ok, f"{candidate!r} rejected: {reason}"


class TestRejectsWhatTheModelActuallyDid:
    def test_invented_words(self):
        """Pressed by a retry, the model reaches into the ingredient list."""
        ok, reason = validate_short_title(
            "5 Min High-Fiber Shakshuka Breakfast", "High-Fiber Shakshuka Marinara")
        assert not ok and "never had" in reason and "marinara" in reason

    def test_a_renamed_dish(self):
        # Deliberately shorter than the original, so the length rule can't be what
        # rejects it — this has to fail on the invented word or it proves nothing.
        ok, reason = validate_short_title(
            "Slow Cooker Beef Birria Tacos With Consomme", "Chicken Tacos")
        assert not ok and "never had" in reason and "chicken" in reason

    def test_reordered_words(self):
        """Passes a set check, reads like a different (broken) dish."""
        ok, reason = validate_short_title(
            "19 Calorie Fudgy Brownies (Crouton)", "Fudgy (Crouton) Brownies")
        assert not ok and "reorders" in reason

    def test_an_abbreviation(self):
        """'w/' slipped through while single-character tokens were being dropped."""
        ok, reason = validate_short_title(
            "Chicken Fricassée (French Creamy Chicken Stew)",
            "Chicken Fricassee W/ Crouton")
        assert not ok, reason

    @pytest.mark.parametrize("original,candidate,compound", [
        ("Chocolate Peanut Butter Protein Pancake Bowl",
         "Chocolate Peanut Protein Pancake", "peanut butter"),
        ("5-Ingredient Cottage Cheese Cookie Dough",
         "Cottage Cookie Dough", "cottage cheese"),
        ("Boiled Egg With Soy Sauce Marinade And Kimchi",
         "Boiled Egg Soy Kimchi", "soy sauce"),
    ])
    def test_splitting_a_compound_food(self, original, candidate, compound):
        """'Cottage' and 'Peanut' are not foods. Both passed subset-and-order."""
        ok, reason = validate_short_title(original, candidate)
        assert not ok and compound in reason

    def test_too_long(self):
        ok, reason = validate_short_title(
            "Chamomile, Strawberry Jam & Triple-Berry Black Bean Brownies",
            "Chamomile Strawberry Black Bean Brownies")
        assert not ok and "over the" in reason

    def test_not_actually_shorter(self):
        ok, reason = validate_short_title("Beef Birria Tacos", "Beef Birria Tacos!!")
        assert not ok and "shorter" in reason

    @pytest.mark.parametrize("candidate", ["", "  ", "a", "the best"])
    def test_empty_or_contentless(self, candidate):
        ok, _ = validate_short_title("Some Long Recipe Name Here", candidate)
        assert not ok


class TestCollisions:
    """The corpus really contains these pairs; the distinguishing word is the point."""

    def test_dropping_the_variant_marker_collides(self):
        taken = {"High-Protein Bean Lentil Dip", "High-Protein Bean Lentil Dip (Crouton)"}
        ok, reason = validate_short_title(
            "High-Protein Bean Lentil Dip (Crouton)", "High-Protein Bean Lentil Dip", taken)
        assert not ok and "collides" in reason

    def test_dropping_a_trailing_letter_collides(self):
        taken = {"Chicken Caldo A", "Chicken Caldo B"}
        ok, reason = validate_short_title(
            "Chicken Caldo A Slow Simmered Broth", "Chicken Caldo B", taken)
        assert not ok

    def test_its_own_name_is_not_a_collision(self):
        """A recipe re-proposing over its own existing entry must not self-block."""
        ok, reason = validate_short_title(
            "Cherry Vanilla Breakfast Smoothie", "Cherry Vanilla Smoothie",
            {"Cherry Vanilla Breakfast Smoothie"})
        assert ok, reason


class TestNonLatinNamesMayBeTranslated:
    """The subset rule would reject exactly the names that need this most."""

    def test_a_korean_title_can_become_english(self):
        original = "[감자치즈빵] 화덕에 구운 것 같은 감자치즈빵! (후라이팬으로 맛있는 빵 만들기, Pot"
        ok, reason = validate_short_title(original, "Korean Potato Cheese Bread")
        assert ok, reason

    def test_but_it_still_has_to_fit(self):
        original = "[감자치즈빵] 화덕에 구운 것 같은 감자치즈빵! (후라이팬으로 맛있는 빵 만들기, Pot"
        ok, reason = validate_short_title(
            original, "Korean Potato Cheese Bread Made In A Frying Pan Like A Kiln")
        assert not ok and "over the" in reason

    def test_a_latin_name_with_an_accent_is_still_latin(self):
        """Fricassée must not be mistaken for a non-Latin script and freed up."""
        assert short_title.is_latin("Chicken Fricassée (French Creamy Chicken Stew)")
        ok, _ = validate_short_title(
            "Chicken Fricassée (French Creamy Chicken Stew)", "Beef Stew Surprise")
        assert not ok

    def test_accents_do_not_block_a_legitimate_shortening(self):
        ok, reason = validate_short_title(
            "Chicken Fricassée (French Creamy Chicken Stew)", "Creamy Chicken Stew")
        assert ok, reason


class TestIsLatin:
    @pytest.mark.parametrize("text,expected", [
        ("Beef Birria", True),
        ("Chicken Fricassée", True),
        ("Turkish Eggs (Çılbır)", True),
        ("감자치즈빵 화덕에 구운 것", False),
        ("", True),          # no letters at all — nothing to translate
        ("12345 !!!", True),
    ])
    def test_script_detection(self, text, expected):
        assert short_title.is_latin(text) is expected
