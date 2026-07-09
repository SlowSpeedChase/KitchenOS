"""Tests for lib/units.py — measurement → grams conversion."""

import pytest

from lib.units import (
    parse_amount_to_float,
    get_unit_family,
    to_grams,
    lookup_density,
    lookup_piece_weight,
)


class TestParseAmountToFloat:
    @pytest.mark.parametrize("raw,expected", [
        (2, 2.0),
        (1.5, 1.5),
        ("2", 2.0),
        ("1/2", 0.5),
        ("1 1/2", 1.5),
        ("two", 2.0),
        ("3-4", 3.5),
        ("1.5-2", 1.75),
        ("0.25", 0.25),
    ])
    def test_parses(self, raw, expected):
        assert parse_amount_to_float(raw) == pytest.approx(expected)

    @pytest.mark.parametrize("raw", [None, "", "  "])
    def test_none(self, raw):
        assert parse_amount_to_float(raw) is None


class TestUnitFamily:
    @pytest.mark.parametrize("unit,family", [
        ("g", "mass"), ("kg", "mass"), ("oz", "mass"), ("lb", "mass"),
        ("tsp", "volume"), ("tbsp", "volume"), ("cup", "volume"), ("ml", "volume"),
        ("clove", "count"), ("head", "count"), ("whole", "count"), ("slice", "count"),
        ("", "count"),
        ("to taste", "informal"), ("pinch", "informal"),
    ])
    def test_family(self, unit, family):
        assert get_unit_family(unit) == family


class TestToGramsMass:
    def test_oz(self):
        r = to_grams("2", "oz", "butter")
        assert r.grams == pytest.approx(56.699, abs=0.01)
        assert r.method == "mass"
        assert r.confidence == 1.0
        assert not r.needs_review

    def test_grams_passthrough(self):
        assert to_grams("100", "g", "sugar").grams == pytest.approx(100.0)


class TestToGramsVolume:
    def test_explicit_density(self):
        # 1 cup oil: 236.588 ml * 0.92 g/ml
        r = to_grams("1", "cup", "olive oil", density_g_per_ml=0.92)
        assert r.grams == pytest.approx(217.66, abs=0.1)
        assert r.method == "volume_density"

    def test_density_matters_flour_vs_oil(self):
        # Same volume, different ingredient → different grams (the whole point).
        flour = to_grams("1", "cup", "all-purpose flour")   # density from config
        oil = to_grams("1", "cup", "olive oil")
        assert flour.grams == pytest.approx(236.588 * 0.53, abs=0.1)
        assert oil.grams == pytest.approx(236.588 * 0.92, abs=0.1)
        assert flour.grams < oil.grams

    def test_volume_without_density_unresolved(self):
        r = to_grams("1", "cup", "mystery liquid xyz")
        assert r.method == "unresolved"
        assert r.needs_review

    def test_volume_uses_usda_portion_when_no_density(self):
        # FDC ships "1 cup = 226 g" household portions. The volume path must use
        # them when there is no density, instead of returning unresolved -- this is
        # the cottage-cheese-class miss (portion data present but ignored).
        r = to_grams(
            "1", "cup", "mystery food zzz",
            usda_portions=[{"label": "cup", "gram_weight": 226}],
        )
        assert r.grams == pytest.approx(226.0)
        assert r.method == "usda_portion"
        assert not r.needs_review

    def test_volume_portion_scales_with_quantity(self):
        r = to_grams(
            "2", "cup", "mystery food zzz",
            usda_portions=[{"label": "cup", "gram_weight": 226}],
        )
        assert r.grams == pytest.approx(452.0)

    def test_volume_density_preferred_over_portion(self):
        # When both exist, density is the more precise signal -- keep using it.
        r = to_grams(
            "1", "cup", "olive oil", density_g_per_ml=0.92,
            usda_portions=[{"label": "cup", "gram_weight": 999}],
        )
        assert r.method == "volume_density"

    def test_volume_portion_ignores_non_matching_label(self):
        # A RACC-only portion (FDA regulatory unit) must NOT match a cup request.
        r = to_grams(
            "1", "cup", "mystery food zzz",
            usda_portions=[{"label": "1.0 RACC", "gram_weight": 30}],
        )
        assert r.method == "unresolved"


class TestToGramsCount:
    def test_clove_from_config(self):
        r = to_grams("2", "clove", "garlic")
        assert r.grams == pytest.approx(10.0)   # 2 * 5g
        assert r.method == "piece_weight"

    def test_head_default(self):
        r = to_grams("0.5", "head", "cabbage")
        assert r.grams == pytest.approx(450.0)  # 0.5 * 900g

    def test_unknown_count_unresolved(self):
        r = to_grams("1", "whole", "imaginary widget")
        assert r.method == "unresolved"
        assert r.needs_review

    def test_usda_portion_fallback(self):
        r = to_grams(
            "1", "whole", "exotic fruit",
            usda_portions=[{"label": "1 whole fruit", "gram_weight": 120}],
        )
        assert r.grams == pytest.approx(120.0)
        assert r.method == "usda_portion"


class TestToGramsInformal:
    def test_to_taste_negligible(self):
        r = to_grams("1", "to taste", "salt")
        assert r.grams == 0.0
        assert r.method == "negligible"
        assert not r.needs_review


class TestConfigLookups:
    def test_density_substring(self):
        assert lookup_density("extra virgin olive oil") == pytest.approx(0.92)
        assert lookup_density("baby spinach") == pytest.approx(0.13)

    def test_piece_weight_size(self):
        assert lookup_piece_weight("egg", "large") == 50
        assert lookup_piece_weight("egg") == 50  # default
        assert lookup_piece_weight("garlic") == 5  # alias → garlic clove

    def test_unknown_returns_none(self):
        assert lookup_density("nonexistent ingredient zzz") is None
        assert lookup_piece_weight("nonexistent ingredient zzz") is None

    def test_beans_density_narrowed_to_dried_beans(self):
        # "beans" used to be the config key, so substring matching (either
        # direction) made it match ANY "*beans*" ingredient — including fresh
        # green beans and canned baked beans, which have wildly different
        # densities than dried beans. The key is now "dried beans" so only
        # that (and closer variants) match.
        assert lookup_density("dried beans") == pytest.approx(0.75)
        assert lookup_density("green beans") is None
        assert lookup_density("baked beans") is None


class TestAggregatorRegression:
    """The aggregator now derives its tables from lib.units — ensure parity."""

    def test_volume_combines(self):
        from lib.ingredient_aggregator import aggregate_ingredients
        out = aggregate_ingredients([
            {"amount": "2", "unit": "tsp", "item": "salt"},
            {"amount": "1", "unit": "tbsp", "item": "salt"},
        ])
        assert len(out) == 1
        # 2 tsp + 3 tsp = 5 tsp, most-common output unit is tsp
        assert out[0]["unit"] == "tsp"
        assert float(out[0]["amount"]) == pytest.approx(5.0)

    def test_weight_combines(self):
        from lib.ingredient_aggregator import aggregate_ingredients
        out = aggregate_ingredients([
            {"amount": "1", "unit": "lb", "item": "butter"},
            {"amount": "0.5", "unit": "lb", "item": "butter"},
        ])
        assert len(out) == 1
        assert out[0]["unit"] == "lb"
        assert float(out[0]["amount"]) == pytest.approx(1.5)
