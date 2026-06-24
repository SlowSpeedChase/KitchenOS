"""Tests for the validation harness pure logic + golden-set integrity."""
import importlib.util
import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SPEC = importlib.util.spec_from_file_location(
    "validate_nutrition", _ROOT / "scripts" / "validate_nutrition.py"
)
validate_nutrition = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(validate_nutrition)


class TestPctErr:
    def test_exact(self):
        assert validate_nutrition._pct_err(10, 10) == 0.0

    def test_off_by_20pct(self):
        assert validate_nutrition._pct_err(8, 10) == 0.2

    def test_both_zero(self):
        assert validate_nutrition._pct_err(0, 0) == 0.0

    def test_expected_zero_actual_nonzero(self):
        assert validate_nutrition._pct_err(5, 0) == 1.0


class TestGoldenSetIntegrity:
    def test_nutrition_golden_schema(self):
        data = json.loads(
            (_ROOT / "tests" / "golden" / "nutrition_golden.json").read_text()
        )
        assert data["recipes"]
        for entry in data["recipes"]:
            assert entry["file"].endswith(".md")
            assert isinstance(entry["servings"], int)
            for m in ("calories", "protein", "carbs", "fat"):
                assert m in entry["published"]

    def test_resolution_golden_schema(self):
        data = json.loads(
            (_ROOT / "tests" / "golden" / "resolution_golden.json").read_text()
        )
        assert data["food_resolution"] and data["portions"]
        for c in data["food_resolution"]:
            assert c["ingredient"] and c["expect_keywords"]
        for c in data["portions"]:
            assert c["expected_grams"] > 0
