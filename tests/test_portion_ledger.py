"""Tests for the portion ledger — band validation + deterministic read/write."""

import sqlite3

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
