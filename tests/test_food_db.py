"""Tests for lib/food_db.py — data-source clients (mocked HTTP)."""

from unittest.mock import patch, Mock

from lib.food_db import usda_search, usda_food_detail, off_search


class TestUsdaSearch:
    def test_returns_candidate_list_per_100g(self):
        mock = {
            "foods": [
                {"fdcId": 1, "description": "Flour, all-purpose",
                 "foodNutrients": [
                     {"nutrientId": 1008, "value": 364},
                     {"nutrientId": 1003, "value": 10.3},
                     {"nutrientId": 1005, "value": 76.3},
                     {"nutrientId": 1004, "value": 1.0},
                 ]},
                {"fdcId": 2, "description": "Flour, bread",
                 "foodNutrients": [{"nutrientId": 1008, "value": 361}]},
            ]
        }
        with patch("lib.food_db.requests.get") as g:
            g.return_value = Mock(status_code=200, json=lambda: mock)
            records = usda_search("flour")

        assert len(records) == 2                      # candidate LIST, not [0]
        assert records[0].source == "usda"
        assert records[0].source_id == "1"
        assert records[0].per_100g.calories == 364    # per-100g, not scaled
        assert records[0].per_100g.protein == 10.3

    def test_energy_from_atwater_when_1008_absent(self):
        # USDA Foundation Foods report energy under 2047 (Atwater General), not
        # 1008. Protein/fat/carb IDs are shared, so such a food otherwise looks
        # fully resolved but with 0 kcal -- the calorie leak. Read the fallback.
        mock = {"foods": [{"fdcId": 5, "description": "Cream, heavy",
                           "foodNutrients": [
                               {"nutrientId": 2047, "value": 340},   # energy, atwater
                               {"nutrientId": 1003, "value": 2.0},   # protein
                               {"nutrientId": 1004, "value": 36.0},  # fat
                               {"nutrientId": 1005, "value": 3.0},   # carbs
                           ]}]}
        with patch("lib.food_db.requests.get") as g:
            g.return_value = Mock(status_code=200, json=lambda: mock)
            records = usda_search("heavy cream")
        assert records[0].per_100g.calories == 340

    def test_energy_computed_via_atwater_when_no_energy_nutrient(self):
        # Some Foundation records carry macros but NO summary energy at all (oils,
        # butter) -- only fatty-acid rows. Derive kcal from macros: 4P + 4C + 9F.
        mock = {"foods": [{"fdcId": 7, "description": "Oil, olive, extra virgin",
                           "foodNutrients": [
                               {"nutrientId": 1003, "value": 0},     # protein
                               {"nutrientId": 1004, "value": 100.0}, # fat
                               {"nutrientId": 1005, "value": 0},     # carbs
                           ]}]}
        with patch("lib.food_db.requests.get") as g:
            g.return_value = Mock(status_code=200, json=lambda: mock)
            records = usda_search("olive oil")
        assert records[0].per_100g.calories == 900   # 9 * 100

    def test_reported_energy_preferred_over_atwater_estimate(self):
        # When a real energy value exists, use it -- don't override with the 4/4/9
        # estimate (which is an approximation).
        mock = {"foods": [{"fdcId": 8, "description": "Almonds",
                           "foodNutrients": [
                               {"nutrientId": 1008, "value": 579},
                               {"nutrientId": 1003, "value": 21.2},
                               {"nutrientId": 1004, "value": 49.9},
                               {"nutrientId": 1005, "value": 21.6},
                           ]}]}
        with patch("lib.food_db.requests.get") as g:
            g.return_value = Mock(status_code=200, json=lambda: mock)
            records = usda_search("almonds")
        assert records[0].per_100g.calories == 579   # reported, not 4*21.2+4*21.6+9*49.9

    def test_no_macros_no_energy_stays_zero(self):
        # Water/salt: no macros, no energy -> 0, not a bogus estimate.
        mock = {"foods": [{"fdcId": 9, "description": "Water, bottled",
                           "foodNutrients": []}]}
        with patch("lib.food_db.requests.get") as g:
            g.return_value = Mock(status_code=200, json=lambda: mock)
            records = usda_search("water")
        assert records[0].per_100g.calories == 0

    def test_energy_1008_preferred_over_atwater(self):
        mock = {"foods": [{"fdcId": 6, "description": "Sugar",
                           "foodNutrients": [
                               {"nutrientId": 1008, "value": 387},
                               {"nutrientId": 2047, "value": 999},
                           ]}]}
        with patch("lib.food_db.requests.get") as g:
            g.return_value = Mock(status_code=200, json=lambda: mock)
            records = usda_search("sugar")
        assert records[0].per_100g.calories == 387

    def test_retries_on_429_then_succeeds(self):
        # A transient rate-limit must not drop a resolvable food. Retry with
        # backoff, then return the successful result.
        ok = {"foods": [{"fdcId": 9, "description": "Honey",
                         "foodNutrients": [{"nutrientId": 1008, "value": 304}]}]}
        with patch("lib.food_db.time.sleep"), patch("lib.food_db.requests.get") as g:
            g.side_effect = [
                Mock(status_code=429),
                Mock(status_code=429),
                Mock(status_code=200, json=lambda: ok),
            ]
            records = usda_search("honey")
        assert g.call_count == 3
        assert len(records) == 1
        assert records[0].description == "Honey"

    def test_empty_on_persistent_429(self):
        # Exhausted retries on a persistent rate-limit still returns [].
        with patch("lib.food_db.time.sleep"), patch("lib.food_db.requests.get") as g:
            g.return_value = Mock(status_code=429)
            assert usda_search("flour") == []
        assert g.call_count > 1  # it retried, didn't give up on the first 429

    def test_empty_on_non_429_error(self):
        with patch("lib.food_db.requests.get") as g:
            g.return_value = Mock(status_code=500)
            assert usda_search("flour") == []
        assert g.call_count == 1  # non-429 errors are not retried


class TestUsdaDetail:
    def test_parses_nutrients_and_portions(self):
        mock = {
            "fdcId": 123,
            "description": "Onions, raw",
            "foodNutrients": [
                {"nutrient": {"id": 1008}, "amount": 40},
                {"nutrient": {"id": 1003}, "amount": 1.1},
                {"nutrient": {"id": 1005}, "amount": 9.3},
                {"nutrient": {"id": 1004}, "amount": 0.1},
            ],
            "foodPortions": [
                {"gramWeight": 110, "portionDescription": "1 medium",
                 "measureUnit": {"name": "medium"}, "amount": 1},
                {"gramWeight": 0, "portionDescription": "bad"},
            ],
        }
        with patch("lib.food_db.requests.get") as g:
            g.return_value = Mock(status_code=200, json=lambda: mock)
            rec = usda_food_detail("123")

        assert rec is not None
        assert rec.per_100g.calories == 40
        assert rec.per_100g.carbs == 9.3
        assert len(rec.portions) == 1                 # zero-weight portion dropped
        assert rec.portions[0]["gram_weight"] == 110
        assert rec.portions[0]["label"] == "1 medium"

    def test_none_on_error(self):
        with patch("lib.food_db.requests.get") as g:
            g.return_value = Mock(status_code=404)
            assert usda_food_detail("123") is None


class TestOffSearch:
    def test_parses_per_100g(self):
        mock = {
            "products": [
                {"code": "abc", "product_name": "Protein Bar",
                 "nutriments": {
                     "energy-kcal_100g": 350, "proteins_100g": 30,
                     "carbohydrates_100g": 40, "fat_100g": 10,
                 }},
            ]
        }
        with patch("lib.food_db.requests.get") as g:
            g.return_value = Mock(status_code=200, json=lambda: mock)
            records = off_search("protein bar")

        assert len(records) == 1
        assert records[0].source == "off"
        assert records[0].per_100g.calories == 350
        assert records[0].per_100g.protein == 30

    def test_skips_products_without_data(self):
        mock = {"products": [{"code": "x", "product_name": "Mystery",
                              "nutriments": {}}]}
        with patch("lib.food_db.requests.get") as g:
            g.return_value = Mock(status_code=200, json=lambda: mock)
            assert off_search("mystery") == []
