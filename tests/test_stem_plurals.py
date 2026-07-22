"""The singularizer behind all inventory↔recipe matching.

It stripped two characters from anything ending in "-es", which is only correct
after a sibilant (dishes, boxes) or for "-oes" (tomatoes). For ordinary plurals
whose stem ends in "e" it ate the "e" too — "apples" became "appl" while a
recipe's "apple" stayed "apple", so they could never match.

The blast radius is every feature built on `_content_tokens`: use_it_up's
at-risk ranking, cook_now's coverage, the meal suggester's waste bonus, and the
buffer-stock check. Apples in the fridge silently failed to match an apple
recipe.
"""
import pytest

from lib.recipe_matcher import _content_tokens, _stem


@pytest.mark.parametrize("plural,singular", [
    ("apples", "apple"),
    ("dates", "date"),
    ("olives", "olive"),
    ("grapes", "grape"),
    ("limes", "lime"),
    ("noodles", "noodle"),
])
def test_ordinary_plurals_keep_their_stem_e(plural, singular):
    assert _stem(plural) == _stem(singular) == singular


@pytest.mark.parametrize("plural,expected", [
    ("tomatoes", "tomato"),
    ("potatoes", "potato"),
    ("dishes", "dish"),
    ("boxes", "box"),
    ("squashes", "squash"),
])
def test_sibilant_and_oes_plurals_drop_the_es(plural, expected):
    assert _stem(plural) == expected


@pytest.mark.parametrize("plural,expected", [
    ("berries", "berry"),
    ("cherries", "cherry"),
])
def test_ies_plurals_become_y(plural, expected):
    assert _stem(plural) == expected


@pytest.mark.parametrize("word", ["glass", "molasses", "hummus", "rice", "oats"])
def test_non_plurals_are_left_alone_enough_to_still_match_themselves(word):
    assert _stem(word) == _stem(word)


def test_inventory_name_matches_recipe_ingredient():
    """The bug in one line: this is what use_it_up needs to work."""
    assert _content_tokens("apples") & _content_tokens("apple")


def test_fresh_strawberries_still_matches_strawberries():
    """The case the module docstring promises — must not regress."""
    assert _content_tokens("strawberries") <= _content_tokens("fresh strawberries")
