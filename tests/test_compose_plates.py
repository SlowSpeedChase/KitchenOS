"""Tests for scripts/compose_plates.py — pairing mains with accompaniments that
reuse their ingredients."""

import pytest

from scripts.compose_plates import compose_plates, ACCOMPANIMENT_TYPES


def R(name, dish_type, items):
    return {"name": name, "dish_type": dish_type, "ingredient_items": items}


PANTRY = {"salt", "olive oil", "black pepper"}


def test_main_pairs_with_accompaniment_sharing_ingredients():
    recipes = [
        R("Chickpea Bowl", "main", ["chickpeas", "tahini", "lemon", "parsley"]),
        R("Tahini Sauce", "sauce", ["tahini", "lemon", "salt"]),
    ]
    plates = compose_plates(recipes, PANTRY, min_score=0.3)
    assert len(plates) == 1
    assert plates[0]["main"] == "Chickpea Bowl"
    assert [a["name"] for a in plates[0]["accompaniments"]] == ["Tahini Sauce"]


def test_shared_ingredients_are_reported():
    recipes = [
        R("Chickpea Bowl", "main", ["chickpeas", "tahini", "lemon"]),
        R("Tahini Sauce", "sauce", ["tahini", "lemon"]),
    ]
    plates = compose_plates(recipes, PANTRY, min_score=0.3)
    shared = plates[0]["accompaniments"][0]["shared_ingredients"]
    assert set(shared) == {"tahini", "lemon"}


def test_pantry_staples_do_not_create_overlap():
    """A side sharing only salt/oil with the main is not a real pairing."""
    recipes = [
        R("Chickpea Bowl", "main", ["chickpeas", "tahini", "salt", "olive oil"]),
        R("Plain Rice", "side", ["rice", "salt", "olive oil"]),
    ]
    plates = compose_plates(recipes, PANTRY, min_score=0.3)
    assert plates[0]["accompaniments"] == []


def test_main_never_pairs_with_itself():
    recipes = [R("Solo Main", "main", ["chickpeas", "tahini"])]
    plates = compose_plates(recipes, PANTRY, min_score=0.0)
    assert plates[0]["accompaniments"] == []


def test_source_suffixed_twin_is_not_paired_with_its_own_main():
    """Importers disambiguate collisions by appending the source; the two notes are
    the same dish, so one must not be served as a side for the other."""
    recipes = [
        R("Tofu Ricotta (Big Vegan Flavor)", "main", ["tofu", "miso", "lemon"]),
        R("Tofu Ricotta", "dip", ["tofu", "miso", "lemon"]),
        R("Herb Oil", "sauce", ["lemon", "miso"]),
    ]
    plates = compose_plates(recipes, PANTRY, min_score=0.3)
    paired = [a["name"] for a in plates[0]["accompaniments"]]
    assert "Tofu Ricotta" not in paired
    assert paired == ["Herb Oil"]


def test_min_score_suppresses_weak_pairings():
    recipes = [
        R("Chickpea Bowl", "main", ["chickpeas", "tahini"]),
        # Only 1 of 4 non-pantry items shared -> score 0.25
        R("Weak Side", "side", ["tahini", "rice", "peas", "corn"]),
    ]
    assert compose_plates(recipes, PANTRY, min_score=0.3)[0]["accompaniments"] == []
    assert compose_plates(recipes, PANTRY, min_score=0.2)[0]["accompaniments"]


def test_one_accompaniment_per_role():
    recipes = [
        R("Chickpea Bowl", "main", ["chickpeas", "tahini", "lemon"]),
        R("Tahini Sauce", "sauce", ["tahini", "lemon"]),
        R("Lemon Drizzle", "sauce", ["lemon", "tahini"]),
        R("Lemon Slaw", "salad", ["lemon", "tahini"]),
    ]
    plates = compose_plates(recipes, PANTRY, min_score=0.3)
    roles = [a["role"] for a in plates[0]["accompaniments"]]
    assert len(roles) == len(set(roles)), "a role must not repeat on one plate"
    assert set(roles) <= ACCOMPANIMENT_TYPES


def test_max_sides_caps_the_plate():
    recipes = [
        R("Bowl", "main", ["a", "b", "c"]),
        R("S1", "sauce", ["a", "b"]),
        R("S2", "salad", ["a", "c"]),
        R("S3", "bread", ["b", "c"]),
        R("S4", "dip", ["a", "b"]),
    ]
    plates = compose_plates(recipes, PANTRY, min_score=0.3, max_sides=2)
    assert len(plates[0]["accompaniments"]) == 2


def test_unrecognized_dish_types_are_ignored():
    """Desserts and drinks are neither anchors nor accompaniments."""
    recipes = [
        R("Chickpea Bowl", "main", ["chickpeas", "tahini"]),
        R("Tahini Cake", "dessert", ["tahini", "chickpeas"]),
        R("Mystery", None, ["tahini", "chickpeas"]),
    ]
    plates = compose_plates(recipes, PANTRY, min_score=0.3)
    assert len(plates) == 1
    assert plates[0]["accompaniments"] == []


def test_dish_type_variants_normalize():
    """'bowl' and 'entree' map to main; 'dressing' maps to sauce."""
    recipes = [
        R("Grain Bowl", "bowl", ["chickpeas", "tahini", "lemon"]),
        R("House Dressing", "dressing", ["tahini", "lemon"]),
    ]
    plates = compose_plates(recipes, PANTRY, min_score=0.3)
    assert len(plates) == 1
    assert plates[0]["accompaniments"][0]["role"] == "sauce"


def test_recipes_without_ingredients_are_skipped():
    recipes = [
        R("Empty Main", "main", []),
        R("Real Main", "main", ["chickpeas", "tahini"]),
        R("Tahini Sauce", "sauce", ["tahini", "chickpeas"]),
    ]
    plates = compose_plates(recipes, PANTRY, min_score=0.3)
    assert [p["main"] for p in plates] == ["Real Main"]


def test_plates_sorted_by_pairing_strength():
    recipes = [
        R("Strong", "main", ["a", "b"]),
        R("Weak", "main", ["c", "d"]),
        R("SauceA", "sauce", ["a", "b"]),
        R("SauceC", "sauce", ["c", "x", "y", "z"]),
    ]
    plates = compose_plates(recipes, PANTRY, min_score=0.2)
    assert plates[0]["main"] == "Strong"
