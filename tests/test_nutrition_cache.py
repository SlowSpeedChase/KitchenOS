"""Tests for the nutrition food-data cache in lib/inventory_db.py."""

from lib import inventory_db


def test_food_cache_roundtrip(tmp_db):
    inventory_db.put_food_cache({
        "query_norm": "flour",
        "source": "usda",
        "source_id": "123",
        "description": "Flour, all-purpose",
        "per_100g": {"calories": 364, "protein": 10, "carbs": 76, "fat": 1},
        "portions": [{"label": "1 cup", "gram_weight": 125}],
        "density_g_per_ml": 0.53,
    })

    got = inventory_db.get_food_cache("flour", "usda")
    assert got is not None
    assert got["source_id"] == "123"
    assert got["per_100g"]["calories"] == 364
    assert got["portions"][0]["gram_weight"] == 125
    assert got["density_g_per_ml"] == 0.53


def test_food_cache_upsert(tmp_db):
    base = {"query_norm": "egg", "source": "usda", "source_id": "1",
            "per_100g": {"calories": 100}, "portions": []}
    inventory_db.put_food_cache(base)
    inventory_db.put_food_cache({**base, "source_id": "2",
                                 "per_100g": {"calories": 143}})
    got = inventory_db.get_food_cache("egg", "usda")
    assert got["source_id"] == "2"
    assert got["per_100g"]["calories"] == 143


def test_food_cache_miss(tmp_db):
    assert inventory_db.get_food_cache("nope", "usda") is None


def test_food_resolution_roundtrip_and_upsert(tmp_db):
    inventory_db.put_food_resolution("onion", "usda", "999", 0.9, "exact")
    got = inventory_db.get_food_resolution("onion")
    assert got["source_id"] == "999"
    assert got["resolver"] == "exact"

    inventory_db.put_food_resolution("onion", "off", "888", 0.7, "llm-ollama")
    got = inventory_db.get_food_resolution("onion")
    assert got["source"] == "off"
    assert got["source_id"] == "888"
    assert got["resolver"] == "llm-ollama"


def test_food_resolution_miss(tmp_db):
    assert inventory_db.get_food_resolution("nope") is None
