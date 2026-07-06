"""Coverage/sanity semantics of calculate_recipe_nutrition.

Stub _resolve_food/_resolve_grams (monkeypatch) so no network is touched.
"""
import lib.nutrition_engine as ne
from lib import serving_ledger, units


def _stub_resolvers(monkeypatch, resolves: dict, confidences: dict = None):
    """resolves: item -> (per100g dict | None). None = unresolved.

    confidences: optional item -> food-resolution confidence override (default 0.8).
    """
    confidences = confidences or {}
    def fake_resolve_food(item, *, use_cache, resolution_provider):
        per = resolves.get(item)
        if per is None:
            return None, 0.0, "unresolved"
        rec = {"source": "usda", "source_id": "1", "description": item,
               "per_100g": per, "portions": [], "density_g_per_ml": None}
        return rec, confidences.get(item, 0.8), "match"
    def fake_resolve_grams(amount, unit, item, record, *, use_cache, portion_provider):
        return units.GramResult(100.0, "direct", 1.0, False, note="")
    monkeypatch.setattr(ne, "_resolve_food", fake_resolve_food)
    monkeypatch.setattr(ne, "_resolve_grams", fake_resolve_grams)


PER = {"calories": 200.0, "protein": 10.0, "carbs": 20.0, "fat": 5.0}


def test_full_coverage(monkeypatch, tmp_db):
    _stub_resolvers(monkeypatch, {"beans": PER, "beef": PER})
    r = ne.calculate_recipe_nutrition(
        [{"item": "beans", "amount": "1", "unit": "cup"},
         {"item": "beef", "amount": "1", "unit": "lb"}], 2)
    assert r.coverage == 1.0
    assert r.unmatched == []
    assert r.confidence == 0.8            # mean, not min
    assert r.needs_review is False


def test_one_unresolved_line_lowers_coverage_not_confidence(monkeypatch, tmp_db):
    _stub_resolvers(monkeypatch, {"beans": PER, "unicorn dust": None})
    r = ne.calculate_recipe_nutrition(
        [{"item": "beans", "amount": "1", "unit": "cup"},
         {"item": "unicorn dust", "amount": "1", "unit": "tsp"}], 2)
    assert r.coverage == 0.5
    assert r.unmatched == ["unicorn dust"]
    assert r.confidence == 0.8            # unresolved line excluded from mean
    assert r.needs_review is True         # coverage < 0.8


def test_to_taste_excluded_from_denominator(monkeypatch, tmp_db):
    _stub_resolvers(monkeypatch, {"beans": PER, "salt": None})
    r = ne.calculate_recipe_nutrition(
        [{"item": "beans", "amount": "1", "unit": "cup"},
         {"item": "salt", "amount": "1", "unit": "to taste"}], 2)
    assert r.coverage == 1.0


def test_kcal_sanity_flag(monkeypatch, tmp_db):
    huge = {"calories": 9000.0, "protein": 0.0, "carbs": 0.0, "fat": 0.0}
    _stub_resolvers(monkeypatch, {"lard": huge})
    r = ne.calculate_recipe_nutrition(
        [{"item": "lard", "amount": "1", "unit": "cup"}], 1)
    assert "kcal_out_of_range" in r.sanity_flags
    assert r.needs_review is True


def test_dominant_line_flag(monkeypatch, tmp_db):
    _stub_resolvers(monkeypatch, {"beans": PER, "beef": PER})
    def fake_grams(amount, unit, item, record, *, use_cache, portion_provider):
        g = 1000.0 if item == "beef" else 50.0
        return units.GramResult(g, "direct", 1.0, False, note="")
    monkeypatch.setattr(ne, "_resolve_grams", fake_grams)
    r = ne.calculate_recipe_nutrition(
        [{"item": "beans", "amount": "1", "unit": "cup"},
         {"item": "beef", "amount": "1", "unit": "lb"}], 4)
    assert "dominant_line" in r.sanity_flags


def test_confidence_is_mean_not_min(monkeypatch, tmp_db):
    # Two resolved, non-negligible lines at different confidences: 0.8 and 0.4.
    # mean([0.8, 0.4]) == 0.6, whereas the old min()-based rollup would give 0.4.
    _stub_resolvers(monkeypatch, {"beans": PER, "beef": PER},
                     confidences={"beans": 0.8, "beef": 0.4})
    r = ne.calculate_recipe_nutrition(
        [{"item": "beans", "amount": "1", "unit": "cup"},
         {"item": "beef", "amount": "1", "unit": "lb"}], 2)
    assert r.confidence == 0.6


def test_coverage_review_threshold_matches_serving_ledger():
    assert ne.COVERAGE_REVIEW_THRESHOLD == serving_ledger.COVERAGE_REVIEW_THRESHOLD
