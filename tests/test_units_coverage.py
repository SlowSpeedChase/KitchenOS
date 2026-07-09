"""Grams-coverage fixes for lib/units.py + lib/ingredient_parser.py (bucket #1).

Informal measures that were slipping to 'unresolved' should read as negligible;
approximate spoon measures that carry real macros should map to real units.
"""
import pytest

from lib.ingredient_parser import normalize_unit
from lib.ingredient_text import clean_for_matching
from lib.units import get_unit_family, to_grams


# --- informal units → negligible (not unresolved) ----------------------------

def test_a_sprinkle_is_informal():
    # regression: units.py INFORMAL_UNITS diverged from the parser's and dropped
    # "a sprinkle", so it fell through to family 'other' → unresolved.
    assert get_unit_family("a sprinkle") == "informal"


def test_a_smidge_is_informal():
    assert get_unit_family("a smidge") == "informal"


def test_a_sprinkle_resolves_negligible():
    r = to_grams(1, "a sprinkle", "garam masala")
    assert r.method == "negligible"
    assert r.needs_review is False


# --- spoonful/dollop/drizzle → real units (carry real macros) ---------------

def test_spoonful_maps_to_tablespoon():
    assert normalize_unit("spoonful") == "tbsp"


def test_dollop_maps_to_tablespoon():
    assert normalize_unit("dollop") == "tbsp"


def test_drizzle_maps_to_teaspoon():
    assert normalize_unit("drizzle") == "tsp"


def test_spoonful_of_peanut_butter_resolves_to_grams():
    # spoonful → tbsp → volume; with a density it yields real grams, not zero
    r = to_grams(1, "spoonful", "peanut butter", density_g_per_ml=0.95)
    assert r.grams > 0
    assert r.method == "volume_density"


def test_spoonful_family_is_volume():
    assert get_unit_family("spoonful") == "volume"


# --- bucket #2: unit-aware piece weights -------------------------------------

def test_cloves_garlic_reversed_wording_resolves():
    # "cloves garlic" (word order) didn't substring-match "garlic clove"
    r = to_grams(2, "clove", "cloves garlic")
    assert r.method == "piece_weight"
    assert r.grams == pytest.approx(10, abs=1)   # 2 × 5 g


def test_head_garlic_disambiguated_by_unit():
    # piece type lives in the UNIT (head), not the item text
    r = to_grams(0.5, "head", "garlic, separated and peeled")
    assert r.method == "piece_weight"
    assert r.grams == pytest.approx(25, abs=2)    # 0.5 × 50 g


def test_cilantro_whole_resolves():
    r = to_grams(1, "whole", "cilantro")
    assert r.method == "piece_weight"
    assert r.grams > 0


def test_existing_garlic_cloves_still_resolves():
    # regression: the working case must keep working
    r = to_grams(2, "whole", "garlic cloves")
    assert r.method == "piece_weight"
    assert r.grams == pytest.approx(10, abs=1)


def test_unit_combine_does_not_invent_matches():
    # a count unit + an unknown food must stay unresolved, not match by accident
    r = to_grams(1, "clove", "dragonfruit zest")
    assert r.method == "unresolved"


# --- bucket #3: densities ----------------------------------------------------

@pytest.mark.parametrize("item", [
    "heavy whipping cream",     # alias → heavy cream (had no substring match)
    "red pepper flakes",
    "baking powder",
    "baking soda",
    "vanilla extract",
    "coconut milk",
    "almond milk",
    "cream cheese",
    "ricotta",
    "salsa",
])
def test_common_volume_items_resolve_to_grams(item):
    r = to_grams(1, "cup", item)
    assert r.method == "volume_density"
    assert r.grams > 0


def test_red_pepper_flakes_teaspoon_is_small_but_nonzero():
    r = to_grams(1, "tsp", "red pepper flakes")
    assert r.method == "volume_density"
    assert 1 < r.grams < 6          # a tsp of flakes ~2-3 g


# --- bucket #4: accent stripping for food matching ---------------------------

@pytest.mark.parametrize("raw,expected", [
    ("jalapeños", "jalapenos"),      # ñ broke the USDA match; jalapenos resolves
    ("crème fraîche", "creme fraiche"),
    ("café", "cafe"),
    ("jalapeño", "jalapeno"),
])
def test_clean_for_matching_strips_accents(raw, expected):
    assert clean_for_matching(raw) == expected


def test_clean_for_matching_leaves_plain_ascii_untouched():
    assert clean_for_matching("chicken breast") == "chicken breast"


def test_piece_weight_matches_accented_item():
    # accent-stripping must also apply on the units-table path, not just food match
    r = to_grams(1, "whole", "jalapeños")
    assert r.method == "piece_weight"
    assert r.grams == pytest.approx(14, abs=1)
