"""Tests for the macro-eligibility predicate."""

from lib.nutrition_quality import (
    MAX_KCAL_PER_SERVING,
    MAX_PROTEIN_G_PER_SERVING,
    MIN_KCAL_PER_SERVING,
    implausibility_score,
    implausible,
    macro_eligible,
)
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


class TestImplausible:
    """Absolute per-serving bounds.

    These exist because coverage is orthogonal to correctness: it asks "did
    every ingredient line resolve to some food and some grams", and every
    resolution *error* (a package-scale gram weight, a wrong FDC match, an
    undivided batch) leaves coverage at 1.0. Measured on the 2026-08-02 corpus,
    35 of the 45 recipes failing these bounds passed ``macro_eligible``.
    """

    def test_ordinary_recipe_is_plausible(self):
        bad, reasons = implausible(_recipe())
        assert bad is False
        assert reasons == []

    def test_kcal_above_ceiling(self):
        # Chipotle Adobo Chicken Burrito: 3009 kcal/serving, coverage 1.0.
        bad, reasons = implausible(_recipe(nutrition_calories=3009, nutrition_protein=178))
        assert bad is True
        assert "kcal_too_high" in reasons

    def test_kcal_below_floor(self):
        # Mac And Greens: two unresolved caloric lines silently became 0 g.
        bad, reasons = implausible(_recipe(nutrition_calories=7, nutrition_protein=1))
        assert bad is True
        assert "kcal_too_low" in reasons

    def test_protein_above_ceiling(self):
        # Peanut Butter Chocolate Coffee Smoothie: "1 whole protein powder"
        # resolved to a 300 g package.
        bad, reasons = implausible(_recipe(nutrition_calories=1150, nutrition_protein=244))
        assert bad is True
        assert "protein_too_high" in reasons

    def test_protein_share_impossible(self):
        # 100 g protein in 500 kcal = 80% of calories from protein.
        bad, reasons = implausible(_recipe(nutrition_calories=500, nutrition_protein=100))
        assert bad is True
        assert "protein_share_impossible" in reasons

    def test_low_calorie_items_exempt_from_protein_share(self):
        # A 150 kcal serving that is mostly protein is ordinary (jerky, egg
        # whites, a protein shot) — the share test only bites above a floor.
        bad, reasons = implausible(_recipe(nutrition_calories=150, nutrition_protein=30))
        assert bad is False
        assert reasons == []

    def test_missing_protein_skips_protein_checks(self):
        bad, reasons = implausible(_recipe(nutrition_calories=500, nutrition_protein=None))
        assert bad is False

    def test_missing_calories_is_not_implausible(self):
        # "No data" is macro_eligible's no_nutrition reason, not an
        # implausibility claim — don't report the same gap twice.
        bad, reasons = implausible(_recipe(nutrition_calories=None))
        assert bad is False
        assert reasons == []

    def test_garbage_values_do_not_raise(self):
        bad, reasons = implausible(_recipe(nutrition_calories="lots", nutrition_protein="some"))
        assert bad is False

    # Boundaries are pinned deliberately: the portion-ledger band check shipped
    # as `g > 300.0` and the single worst row in the corpus was exactly 300.0.
    def test_ceiling_is_inclusive(self):
        assert implausible(_recipe(nutrition_calories=MAX_KCAL_PER_SERVING))[0] is False
        assert implausible(_recipe(nutrition_calories=MAX_KCAL_PER_SERVING + 1))[0] is True

    def test_floor_is_inclusive(self):
        assert implausible(_recipe(nutrition_calories=MIN_KCAL_PER_SERVING))[0] is False
        assert implausible(_recipe(nutrition_calories=MIN_KCAL_PER_SERVING - 1))[0] is True

    def test_protein_ceiling_is_inclusive(self):
        at = _recipe(nutrition_calories=1200, nutrition_protein=MAX_PROTEIN_G_PER_SERVING)
        assert implausible(at)[0] is False
        over = _recipe(nutrition_calories=1200,
                       nutrition_protein=MAX_PROTEIN_G_PER_SERVING + 1)
        assert implausible(over)[0] is True


class TestMacroEligibleGatesOnPlausibility:
    """The gate must refuse what the bounds refuse.

    This is the whole point: before this, a 244 g-protein smoothie with
    coverage 1.0 was the suggester's top pick for closing a protein gap.
    """

    def test_implausible_recipe_is_ineligible(self):
        eligible, reasons = macro_eligible(
            _recipe(nutrition_calories=3009, nutrition_protein=178)
        )
        assert eligible is False
        assert "kcal_too_high" in reasons

    def test_plausible_recipe_still_eligible(self):
        eligible, reasons = macro_eligible(_recipe())
        assert eligible is True
        assert reasons == []

    def test_reasons_merge_with_existing_gates(self):
        eligible, reasons = macro_eligible(
            _recipe(nutrition_calories=5460, nutrition_protein=15, servings=None)
        )
        assert eligible is False
        assert "kcal_too_high" in reasons
        assert "servings_unknown" in reasons


class TestImplausibilityScore:
    """Magnitude, for ranking the review queue worst-first."""

    def test_plausible_scores_zero(self):
        assert implausibility_score(_recipe()) == 0.0

    def test_worse_violations_score_higher(self):
        mild = implausibility_score(_recipe(nutrition_calories=1400, nutrition_protein=20))
        severe = implausibility_score(_recipe(nutrition_calories=5460, nutrition_protein=15))
        assert severe > mild > 0.0

    def test_floor_violation_scores(self):
        assert implausibility_score(_recipe(nutrition_calories=7, nutrition_protein=1)) > 0.0
