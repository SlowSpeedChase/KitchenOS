"""Grams-coverage fixes for lib/units.py + lib/ingredient_parser.py (bucket #1).

Informal measures that were slipping to 'unresolved' should read as negligible;
approximate spoon measures that carry real macros should map to real units.
"""
from lib.ingredient_parser import normalize_unit
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
