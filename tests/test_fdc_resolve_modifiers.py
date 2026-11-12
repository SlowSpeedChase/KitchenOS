"""Resolver regressions found re-deriving a bean salad (2026-11-10).

Each case below was observed against the real local FDC store with
``use_cache=True, resolution_provider="none"``. The seeded rows are copied from
that store (description, dataset, kcal) so the ranking competition is the real
one, not an idealised one.
"""

import sqlite3
from datetime import datetime, timezone

import pytest

from lib import fdc_local, nutrition_engine, units


def _store(rows, portions=()):
    """rows: (fdc_id, data_type, description, kcal).
    portions: (fdc_id, label, unit_norm, gram_weight, amount)."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    fdc_local.ensure_schema(conn)
    now = datetime.now(timezone.utc).isoformat()
    for fid, dt, desc, kcal in rows:
        conn.execute(
            "INSERT INTO fdc_foods (fdc_id,data_type,description,name_norm,kcal_100g,"
            "kcal_source,protein_100g,carb_100g,fat_100g,brand_owner,dataset_rank,loaded_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (fid, dt, desc, fdc_local.normalize_food_name(desc), kcal, "1008",
             1, 1, 1, None, fdc_local.DATASET_RANK[dt], now))
    for p in portions:
        conn.execute("INSERT INTO fdc_portions (fdc_id,portion_label,unit_norm,"
                     "gram_weight,amount) VALUES (?,?,?,?,?)", p)
    conn.execute("INSERT INTO fdc_foods_fts(fdc_foods_fts) VALUES('rebuild')")
    conn.commit()
    return conn


SR, FND, SURVEY = "sr_legacy_food", "foundation_food", "survey_fndds_food"

TOMATO_ROWS = [
    (171719, SR, "Cherries, sweet, raw", 63.0),
    (2709231, SURVEY, "Cherries, raw", 71.0),
    (170457, SR, "Tomatoes, red, ripe, raw, year round average", 18.0),
    (2709719, SURVEY, "Tomatoes, raw", 20.0),
    (321360, FND, "Tomatoes, grape, raw", 27.0),
]


class TestModifierMustNotWin:
    """A word that qualifies the food must not let a different food win."""

    @pytest.mark.parametrize("item", [
        "cherry tomatoes", "cherry tomatoes, raw", "tomatoes, cherry",
    ])
    def test_cherry_tomatoes_resolve_to_a_tomato(self, item):
        r = fdc_local.resolve_local(_store(TOMATO_ROWS), item)
        assert r["description"].startswith("Tomatoes"), r["description"]

    def test_tomato_recalled_when_cherry_products_crowd_the_pool(self):
        # The real store has 40+ cherry pies/juices/candies and hundreds of
        # tomato products. bm25 favours the rarer token, so the OR query filled
        # every slot with cherries and no tomato was ever a candidate.
        noise = ([(900000 + i, SURVEY, f"Pie, cherry, style {i}", 260.0)
                  for i in range(45)]
                 + [(800000 + i, SURVEY, f"Tomato products, canned, sauce, variant {i}", 30.0)
                    for i in range(300)])
        r = fdc_local.resolve_local(_store(TOMATO_ROWS + noise), "cherry tomatoes")
        assert r["description"].startswith("Tomatoes"), r["description"]

    def test_grape_tomatoes_still_grape(self):
        r = fdc_local.resolve_local(_store(TOMATO_ROWS), "grape tomatoes")
        assert r["description"] == "Tomatoes, grape, raw"

    def test_plain_cherries_still_cherries(self):
        r = fdc_local.resolve_local(_store(TOMATO_ROWS), "cherries")
        assert r["description"].startswith("Cherries")

    def test_garbanzo_beans_are_chickpeas_not_pinto(self):
        conn = _store([
            (174286, SR, "Beans, pinto, canned, drained solids", 114.0),
            (2644288, FND, "Chickpeas (garbanzo beans, bengal gram), canned, "
                           "sodium added, drained and rinsed", 137.2),
            (173800, SR, "Chickpeas (garbanzo beans, bengal gram), mature seeds, "
                         "canned, drained solids", 139.0),
        ])
        r = fdc_local.resolve_local(conn, "garbanzo beans, canned, drained")
        assert r["description"].startswith("Chickpeas"), r["description"]


LEGUME_ROWS = [
    (2644281, FND, "Beans, cannellini, dry", 345.2),
    (2644287, FND, "Beans, cannellini, canned, sodium added, drained and rinsed", 115.4),
    (2707347, SURVEY, "Beans, NFS", 189.0),
]


class TestLegumeDefaultsToCanned:
    """Recipes that mean dry beans say so; the bare name means the can."""

    def test_bare_cannellini_is_canned(self):
        r = fdc_local.resolve_local(_store(LEGUME_ROWS), "cannellini beans")
        assert "canned" in r["description"], r["description"]

    @pytest.mark.parametrize("item", ["dried cannellini beans", "cannellini beans, dry"])
    def test_explicit_dry_still_dry(self, item):
        r = fdc_local.resolve_local(_store(LEGUME_ROWS), item)
        assert r["description"] == "Beans, cannellini, dry"


class TestCanSizeAside:
    """`1 can … (15-ounce)` states the can's weight; use it."""

    REC = {"source": "fdc", "source_id": "1", "description": "Chickpeas, canned",
           "per_100g": {"calories": 137}, "portions": [], "density_g_per_ml": None}

    def _grams(self, amount, unit, item):
        return nutrition_engine._resolve_grams(
            amount, unit, item, self.REC, use_cache=False, portion_provider="none")

    def test_can_with_ounce_aside_gets_weight(self):
        gr = self._grams("1", "can", "chickpeas (15-ounce)")
        assert gr.method == "can_size"
        assert gr.grams == pytest.approx(15 * 28.3495, rel=0.01)

    def test_multiple_cans_scale(self):
        gr = self._grams("2", "cans", "black beans (15 oz)")
        assert gr.grams == pytest.approx(2 * 15 * 28.3495, rel=0.01)

    def test_drained_can_counts_drained_solids_only(self):
        # The FDC record is per 100 g of *drained* beans; the 15 oz on the label
        # includes the liquid that was poured away.
        gr = self._grams("1", "can", "canned chickpeas, rinsed (15-ounce)")
        assert gr.method == "can_size"
        assert gr.grams == pytest.approx(15 * 28.3495 * nutrition_engine.DRAINED_FRACTION,
                                         rel=0.01)
        assert gr.needs_review

    def test_no_aside_still_unresolved(self):
        gr = self._grams("1", "can", "chickpeas")
        assert gr.method == "unresolved"

    def test_ounce_aside_on_non_container_unit_ignored(self):
        # "(15-ounce)" on a cup line is not a per-unit weight.
        gr = self._grams("1", "cup", "chickpeas (15-ounce)")
        assert gr.method != "can_size"


class TestVolumePortions:
    """Volume lines on foods whose density is unknown but FDC ships a cup/tbsp."""

    def test_portion_amount_is_divided_out(self):
        # FDC rows record "0.5 cup = 129 g"; that is 258 g per cup, not 129.
        conn = _store([(323444, FND, "Cheese, ricotta, whole milk", 158.0)],
                      [(323444, "cup", "cup", 129.0, 0.5)])
        r = fdc_local.resolve_local(conn, "ricotta cheese")
        assert r["portions"][0]["gram_weight"] == pytest.approx(258.0)

    def test_portions_pooled_across_duplicate_descriptions(self):
        # Foundation's copy outranks SR's but ships no portions; SR's has the cup.
        conn = _store(
            [(2346406, FND, "Cucumber, with peel, raw", 15.9),
             (168409, SR, "Cucumber, with peel, raw", 15.0)],
            [(168409, "cup slices", "cup", 52.0, 0.5)])
        r = fdc_local.resolve_local(conn, "cucumber, chopped")
        gr = units.to_grams("1", "cup", "cucumber, chopped", usda_portions=r["portions"])
        assert gr.grams == pytest.approx(104.0)

    def test_dill_pickles_chopped_cup(self):
        conn = _store(
            [(324653, FND, "Pickles, cucumber, dill or kosher dill", 12.0),
             (168558, SR, "Pickles, cucumber, dill or kosher dill", 12.0)],
            [(324653, "spear", None, 40.4, 1.0),
             (168558, "cup (about 23 slices)", "cup", 155.0, 1.0),
             (168558, "cup, chopped or diced", "cup", 143.0, 1.0)])
        r = fdc_local.resolve_local(conn, "dill pickles, chopped")
        gr = units.to_grams("0.5", "cup", "dill pickles, chopped",
                            usda_portions=r["portions"])
        # prefers the portion whose prep word matches the line
        assert gr.grams == pytest.approx(71.5)

    def test_tbsp_derived_from_cup_portion(self):
        portions = [{"label": "cup sprigs", "gram_weight": 8.9, "unit": "cup"}]
        gr = units.to_grams("2", "tbsp", "dill, fresh", usda_portions=portions)
        assert gr.method == "usda_portion"
        assert gr.grams == pytest.approx(2 * 8.9 / 16, rel=0.01)


class TestHeadRulesDoNoHarm:
    """Cases the corpus diff caught while these rules were being tuned. Each
    was a regression from an earlier, broader version of the rule."""

    def test_garlic_cloves_are_garlic_not_the_spice(self):
        conn = _store([(1, SR, "Garlic, raw", 149.0),
                       (2, SR, "Spices, cloves, ground", 274.0)])
        r = fdc_local.resolve_local(conn, "large garlic cloves, smashed")
        assert r["description"] == "Garlic, raw"

    def test_kosher_salt_without_a_kosher_record_is_salt(self):
        # The variety rule must not fire when no record carries the variety.
        conn = _store([(1, SR, "Salt, table, iodized", 0.0),
                       (2, SR, "Pickles, cucumber, dill or kosher dill", 12.0)])
        r = fdc_local.resolve_local(conn, "kosher salt")
        assert r["description"].startswith("Salt")

    def test_class_record_head_is_its_second_field(self):
        # "Spices, onion powder" is headed by powder, so it wins "onion powder";
        # "Seeds, pumpkin seeds" is headed by seed, so it loses "pumpkin".
        conn = _store([(1, SR, "Onions, red, raw", 44.0),
                       (2, SR, "Spices, onion powder", 341.0),
                       (3, SR, "Baobab powder", 250.0),
                       (4, SR, "Pumpkin, raw", 26.0),
                       (5, FND, "Seeds, pumpkin seeds (pepitas), raw", 574.0)])
        assert fdc_local.resolve_local(conn, "onion powder")["description"] == \
            "Spices, onion powder"
        assert fdc_local.resolve_local(conn, "pumpkin")["description"] == "Pumpkin, raw"

    def test_fresh_rules_out_dried_and_grain(self):
        conn = _store([(1, SR, "Corn, dried (Navajo)", 386.0),
                       (2, SR, "Corn grain, white", 365.0),
                       (3, SR, "Corn, sweet, yellow, raw", 86.0)])
        r = fdc_local.resolve_local(conn, "ears fresh corn, husked")
        assert r["description"] == "Corn, sweet, yellow, raw"

    def test_filler_word_earns_no_head_bonus(self):
        conn = _store([(1, SR, "Salt, table, iodized", 0.0),
                       (2, SR, "Hearts of palm, raw", 28.0)])
        r = fdc_local.resolve_local(conn, "of fine sea salt")
        assert r["description"].startswith("Salt")

    def test_comma_list_has_no_head(self):
        assert fdc_local.query_head("green, brown, or french green lentils") == ("", "")
        assert fdc_local.query_head("cherry tomatoes, raw") == ("tomatoe", "cherry")
        assert fdc_local.query_head("fresh cilantro leaves and tender stems")[0] == "cilantro"


class TestGramGuards:
    def test_to_taste_amount_weighs_nothing(self, monkeypatch):
        # Parsed as amount "to taste", unit "whole": was weighed as one onion.
        rec = {"query_norm": "onion", "source": "fdc", "source_id": "1",
               "description": "Onions, raw", "per_100g": {"calories": 40},
               "portions": [], "density_g_per_ml": None}
        monkeypatch.setattr(nutrition_engine, "_resolve_food",
                            lambda *a, **k: (dict(rec), 0.85, "fdc-local"))
        res = nutrition_engine.calculate_recipe_nutrition(
            [{"amount": "to taste", "unit": "whole", "item": "onion"},
             {"amount": "100", "unit": "g", "item": "onion"}],
            1, use_cache=False, offline=True)
        assert res.line_items[0].grams == 0
        assert res.line_items[1].grams == 100

    def test_spice_never_borrows_a_vegetable_piece_weight(self):
        rec = {"source": "fdc", "source_id": "1", "description": "Spices, onion powder",
               "per_100g": {"calories": 341}, "portions": [], "density_g_per_ml": None}
        gr = nutrition_engine._resolve_grams("1", "whole", "onion powder", rec,
                                             use_cache=False, portion_provider="none")
        assert gr.grams == 0 and gr.method == "unresolved"

    def test_volume_portion_never_scales_up(self):
        portions = [{"label": "1 tablespoon", "gram_weight": 15.5, "unit": "tbsp"}]
        gr = units.to_grams("1", "cup", "protein powder", usda_portions=portions)
        assert gr.method == "unresolved"
