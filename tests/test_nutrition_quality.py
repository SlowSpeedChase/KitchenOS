"""Tests for the macro-eligibility predicate."""

from lib.nutrition_quality import macro_eligible
from lib.serving_ledger import COVERAGE_REVIEW_THRESHOLD


def _recipe(**overrides):
    """A fully-eligible candidate dict; override keys to make it fail a gate."""
    base = {
        "name": "Test",
        "nutrition_calories": 500,
        "nutrition_protein": 40,
        "nutrition_coverage": 0.95,
        "servings": 4,
    }
    base.update(overrides)
    return base


class TestMacroEligible:
    def test_fully_eligible(self):
        eligible, reasons = macro_eligible(_recipe())
        assert eligible is True
        assert reasons == []

    def test_no_nutrition(self):
        eligible, reasons = macro_eligible(_recipe(nutrition_calories=None))
        assert eligible is False
        assert "no_nutrition" in reasons

    def test_missing_coverage_is_low_coverage(self):
        eligible, reasons = macro_eligible(_recipe(nutrition_coverage=None))
        assert eligible is False
        assert "low_coverage" in reasons

    def test_coverage_below_threshold(self):
        eligible, reasons = macro_eligible(
            _recipe(nutrition_coverage=COVERAGE_REVIEW_THRESHOLD - 0.01)
        )
        assert eligible is False
        assert "low_coverage" in reasons

    def test_coverage_at_threshold_is_eligible(self):
        eligible, _ = macro_eligible(
            _recipe(nutrition_coverage=COVERAGE_REVIEW_THRESHOLD)
        )
        assert eligible is True

    def test_servings_unknown(self):
        eligible, reasons = macro_eligible(_recipe(servings=None))
        assert eligible is False
        assert "servings_unknown" in reasons

    def test_multiple_reasons_accumulate(self):
        eligible, reasons = macro_eligible(
            {"name": "Bare", "nutrition_calories": None,
             "nutrition_coverage": None, "servings": None}
        )
        assert eligible is False
        assert set(reasons) == {"no_nutrition", "low_coverage", "servings_unknown"}
