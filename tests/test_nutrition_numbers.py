"""E2 — fix the nutrition numbers (docs/superpowers/plans/2026-11-15-nutrition-numbers.md).

Every seeded row is copied from the real local FDC store (fdc_id, dataset,
description, kcal) so the ranking competition is the real one.
"""

import pytest

from lib import fdc_local, nutrition_engine

from tests.test_fdc_resolve_modifiers import FND, SR, SURVEY, _store

EGG_ROWS = [
    (323604, FND, "Egg, whole, raw, frozen, pasteurized", 150.0),
    (323697, FND, "Egg, white, raw, frozen, pasteurized", 48.0),
    (323793, FND, "Egg, white, dried", 376.0),
    (329490, FND, "Egg, whole, dried", 575.0),
    (329716, FND, "Egg, yolk, dried", 654.0),
    (171287, SR, "Egg, whole, raw, fresh", 143.0),
    (172183, SR, "Egg, white, raw, fresh", 52.0),
    (172184, SR, "Egg, yolk, raw, fresh", 322.0),
    (173424, SR, "Egg, whole, cooked, hard-boiled", 155.0),
    (172204, SR, "Egg, white, dried", 382.0),
]


class TestEggIsAWholeRawEgg:
    @pytest.mark.parametrize("item", ["eggs", "large eggs", "egg", "eggs (beaten)",
                                      "large egg (whisked)"])
    def test_bare_egg_is_whole_raw(self, item):
        r = fdc_local.resolve_local(_store(EGG_ROWS), item)
        assert r["description"] == "Egg, whole, raw, fresh", r["description"]

    @pytest.mark.parametrize("item,want", [
        ("egg whites", "Egg, white, raw, fresh"),
        ("egg yolks", "Egg, yolk, raw, fresh"),
        ("hard-boiled eggs", "Egg, whole, cooked, hard-boiled"),
        ("dried egg white powder", "Egg, white, dried"),
    ])
    def test_a_line_that_names_the_form_keeps_it(self, item, want):
        r = fdc_local.resolve_local(_store(EGG_ROWS), item)
        assert r["description"] == want, r["description"]

    def test_a_spice_record_is_never_penalised_for_being_dried(self):
        # A spice is dried by default: "1 tsp oregano" means the jar.
        cand = {"description": "Spices, oregano, dried", "name_norm": "dried oregano spice",
                "dataset_rank": 1, "kcal_source": "1008", "bm": -5}
        gate = frozenset({"dried"})
        assert fdc_local.score_candidate("oregano", cand, ("oregano", ""), False, gate) == \
            fdc_local.score_candidate("oregano", cand, ("oregano", ""), False)

    def test_only_a_dried_record_still_resolves(self):
        # The state penalty fires only when some candidate lacks the word.
        rows = [(323793, FND, "Egg, white, dried", 376.0)]
        r = fdc_local.resolve_local(_store(rows), "egg")
        assert r["description"] == "Egg, white, dried"


class TestPeppercornsArePepper:
    ROWS = [(170931, SR, "Spices, pepper, black", 251.0),
            (170932, SR, "Spices, pepper, red or cayenne", 318.0),
            (2710672, SURVEY, "Black Russian", 279.0)]

    @pytest.mark.parametrize("item", ["black peppercorns, approximately",
                                      "whole black peppercorns", "peppercorns"])
    def test_peppercorns_resolve_to_black_pepper(self, item):
        r = fdc_local.resolve_local(_store(self.ROWS), item)
        assert r["description"] == "Spices, pepper, black", r["description"]


class TestLedgerBand:
    def test_round_package_guess_at_the_ceiling_is_rejected(self):
        ok, _ = fdc_local.validate_portion_grams("protein powder", "whole", 300.0,
                                                 {"calories": 352})
        assert not ok

    @pytest.mark.parametrize("item,g", [("mozzarella cheese", 340),
                                        ("unsweetened cocoa powder", 250),
                                        ("oil spray", 280),
                                        ("pie dough rounds", 500)])
    def test_package_of_a_bulk_substance_is_rejected(self, item, g):
        ok, _ = fdc_local.validate_portion_grams(item, "whole", g, {"calories": 300})
        assert not ok

    def test_can_ceiling(self):
        assert fdc_local.validate_portion_grams("crushed tomatoes", "can", 794,
                                                {"calories": 30})[0]
        assert not fdc_local.validate_portion_grams("refried beans", "can", 800,
                                                    {"calories": 90})[0]

    def test_a_real_whole_food_still_passes(self):
        assert fdc_local.validate_portion_grams("whole chicken", "whole", 1400,
                                                {"calories": 215})[0]

    def test_stale_ledger_row_is_not_used(self, monkeypatch):
        # A row written before the band tightened must stop counting on read.
        monkeypatch.setattr(fdc_local, "ledger_grams", lambda conn, item, unit: 300.0)
        record = {"description": "Nutritional powder mix, protein, NFS",
                  "per_100g": {"calories": 352}, "portions": [],
                  "density_g_per_ml": None}
        gr = nutrition_engine._resolve_grams("1", "whole", "protein powder", record,
                                             use_cache=True, portion_provider="none")
        assert gr.method != "ledger"


def _oil(item, amount, unit):
    return {"item": item, "amount": amount, "unit": unit}


class TestFryingMedium:
    @pytest.fixture(autouse=True)
    def _oil_store(self, monkeypatch):
        record = {"query_norm": "oil", "source": "fdc", "source_id": "1",
                  "description": "Oil, peanut, salad or cooking",
                  "per_100g": {"calories": 884, "protein": 0, "carbs": 0, "fat": 100},
                  "portions": [], "density_g_per_ml": 0.92}
        monkeypatch.setattr(nutrition_engine, "_resolve_food",
                            lambda item, **kw: (dict(record), 0.9, "fdc-local"))

    def _kcal(self, ing):
        r = nutrition_engine.calculate_recipe_nutrition([ing], 1, use_llm=False)
        return r.total.calories, r.line_items[0]

    def test_oil_said_to_be_for_frying_counts_only_what_is_absorbed(self):
        full, _ = self._kcal(_oil("peanut oil", "1", "cup"))
        fried, line = self._kcal(_oil("peanut oil, for frying", "1", "cup"))
        assert fried == pytest.approx(full * nutrition_engine.FRYING_ABSORBED_FRACTION, rel=0.01)
        assert line.needs_review and "frying" in line.note

    def test_a_vat_of_oil_is_a_frying_medium(self):
        kcal, line = self._kcal(_oil("peanut oil", "8", "cup"))
        assert kcal < 2000
        assert "frying" in line.note

    def test_a_cup_of_dressing_oil_is_eaten(self):
        kcal, line = self._kcal(_oil("olive oil", "1", "cup"))
        assert kcal > 1500
        assert "frying" not in (line.note or "")
