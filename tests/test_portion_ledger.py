"""Tests for the portion ledger — band validation + deterministic read/write."""

import sqlite3

import pytest

from lib import fdc_local


def _conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    fdc_local.ensure_schema(c)
    return c


class TestValidatePortionGrams:
    def test_reasonable_volume_passes(self):
        # 1 cup water ~= 240 g -> density ~1.0, in band.
        ok, _ = fdc_local.validate_portion_grams("milk", "cup", 244, {"calories": 60})
        assert ok

    def test_absurd_gram_weight_rejected(self):
        ok, reason = fdc_local.validate_portion_grams("flour", "cup", 5000, {"calories": 360})
        assert not ok and "gram" in reason.lower()

    def test_volume_density_out_of_band_rejected(self):
        # 1 tbsp (15 ml) claiming 200 g -> density ~13 g/ml, impossible.
        ok, reason = fdc_local.validate_portion_grams("spice", "tbsp", 200, {"calories": 300})
        assert not ok and "densit" in reason.lower()

    def test_implausible_calories_per_unit_rejected(self):
        # 1 cup at 236 g (density ~1.0, valid) but 700 kcal/100g -> 1652 kcal/cup,
        # over the ceiling. Isolates the kcal band from the density band.
        ok, reason = fdc_local.validate_portion_grams("dense", "cup", 236, {"calories": 700})
        assert not ok and ("kcal" in reason.lower() or "calor" in reason.lower())

    def test_count_unit_reasonable_passes(self):
        ok, _ = fdc_local.validate_portion_grams("medjool date", "whole", 24, {"calories": 277})
        assert ok

    def test_zero_or_negative_rejected(self):
        ok, _ = fdc_local.validate_portion_grams("x", "cup", 0, {"calories": 100})
        assert not ok


class TestWholeUnitPackageWeights:
    """`whole` is what the extractor emits when a recipe stated NO amount.

    Asking an LLM for "one whole olive oil" invites the answer "a bottle", and
    neither the density nor the kcal band applies to `whole` — so the ledger held
    olive oil at 965 g, all-purpose flour at 1000 g and honey at 800 g. One such
    line put 8,685 kcal into a single recipe, and 40 recipes stored a per-serving
    figure above the engine's sanity ceiling because of it.
    """

    @pytest.mark.parametrize("item,grams,kcal100", [
        ("olive oil", 965, 900),
        ("all-purpose flour", 1000, 366),
        ("honey", 800, 304),
        ("mayonnaise", 850, 680),
        ("water (extra if needed)", 1000, 0),
        ("butter", 454, 743),
        ("maple syrup", 828, 260),
        ("whole marinara sauce", 900, 80),
    ])
    def test_a_package_of_something_pourable_is_rejected(self, item, grams, kcal100):
        ok, reason = fdc_local.validate_portion_grams(
            item, "whole", grams, {"calories": kcal100})
        assert not ok
        assert "package" in reason

    @pytest.mark.parametrize("item,grams,kcal100", [
        ("whole rotisserie chicken", 1400, 257),   # genuinely one whole thing
        ("block extra firm tofu", 454, 144),
        ("large romaine lettuce heart", 340, 17),
        ("medium red grapefruit", 350, 42),
        ("pack of original hawaiian sweet rolls", 450, 320),
    ])
    def test_genuinely_countable_whole_foods_still_pass(self, item, grams, kcal100):
        """A whole chicken really is 1400 g — the guard must not eat these."""
        ok, reason = fdc_local.validate_portion_grams(
            item, "whole", grams, {"calories": kcal100})
        assert ok, reason

    def test_a_recipe_scale_amount_of_a_bulk_item_passes(self):
        # The guard is about package weights, not about the substance.
        ok, _ = fdc_local.validate_portion_grams("honey", "whole", 21, {"calories": 304})
        assert ok
        ok, _ = fdc_local.validate_portion_grams("olive oil", "tbsp", 14, {"calories": 900})
        assert ok

    def test_the_match_is_word_bounded(self):
        """'oil' must not fire on 'boiled', or the guard starts eating real food."""
        ok, _ = fdc_local.validate_portion_grams(
            "boiled whole potatoes", "whole", 400, {"calories": 87})
        assert ok


class TestLedgerReadWrite:
    def test_round_trip(self):
        c = _conn()
        fdc_local.ledger_put(c, "chia seed", "tbsp", 12.0, 0.9, "ollama", "1 tbsp chia ~12g")
        assert fdc_local.ledger_grams(c, "chia seed", "tbsp") == 12.0

    def test_miss_returns_none(self):
        c = _conn()
        assert fdc_local.ledger_grams(c, "unknown", "cup") is None

    def test_put_is_idempotent_upsert(self):
        c = _conn()
        fdc_local.ledger_put(c, "date", "whole", 20.0, 0.5, "ollama", "guess")
        fdc_local.ledger_put(c, "date", "whole", 24.0, 0.9, "human", "corrected")
        assert fdc_local.ledger_grams(c, "date", "whole") == 24.0
