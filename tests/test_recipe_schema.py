"""The schema checker, exercised over synthetic frontmatter.

Hermetic by design: no vault, no DB. The corpus itself is audited by
tests/e2e/test_recipe_corpus_schema.py, which is a statement about the
user's data rather than about this code.
"""
import pytest

from lib.recipe_schema import (
    KNOWN_KEYS,
    LEGACY_NUTRITION_KEYS,
    REQUIRED_KEYS,
    check_frontmatter,
    servings_low_end,
)


def _valid_fm(**overrides):
    """A frontmatter dict that satisfies the schema, before overrides."""
    fm = {k: "x" for k in REQUIRED_KEYS}
    fm["servings"] = 4
    fm.update(overrides)
    return fm


def test_a_conforming_recipe_has_no_violations():
    assert check_frontmatter("Good Recipe", _valid_fm()) == []


def test_optional_keys_are_allowed():
    fm = _valid_fm(short_title="Short", enrich_none=["protein"], last_cooked="2026-07-01")
    assert check_frontmatter("Good Recipe", fm) == []


def test_string_servings_is_a_violation():
    v = check_frontmatter("Ranged", _valid_fm(servings="6-8"))
    assert [x.code for x in v] == ["servings_not_numeric"]
    assert v[0].recipe == "Ranged"
    assert v[0].key == "servings"
    assert "6-8" in v[0].detail


def test_numeric_servings_of_either_type_is_fine():
    assert check_frontmatter("Int", _valid_fm(servings=6)) == []
    assert check_frontmatter("Float", _valid_fm(servings=6.0)) == []


def test_null_servings_is_not_a_schema_violation():
    """A missing serving count is honest; macro_eligible already reports it."""
    assert check_frontmatter("Unknown", _valid_fm(servings=None)) == []


def test_legacy_nutrition_keys_are_violations():
    fm = _valid_fm(calories=3058, carbs=None, fat=None)
    codes = {(x.key, x.code) for x in check_frontmatter("Legacy", fm)}
    assert codes == {
        ("calories", "legacy_nutrition_key"),
        ("carbs", "legacy_nutrition_key"),
        ("fat", "legacy_nutrition_key"),
    }


def test_unknown_key_is_a_violation():
    v = check_frontmatter("Stray", _valid_fm(recipe_url="https://example.com"))
    assert [x.code for x in v] == ["unknown_key"]
    assert v[0].key == "recipe_url"


def test_missing_required_key_is_a_violation():
    fm = _valid_fm()
    del fm["dish_type"]
    v = check_frontmatter("Incomplete", fm)
    assert [(x.key, x.code) for x in v] == [("dish_type", "missing_required_key")]


def test_legacy_keys_are_not_also_reported_as_unknown():
    """One defect, one violation — a legacy key has its own actionable code."""
    v = check_frontmatter("Legacy", _valid_fm(calories=1))
    assert len(v) == 1


def test_violations_are_ordered_deterministically():
    fm = _valid_fm(calories=1, recipe_url="u", servings="6-8")
    first = [(x.key, x.code) for x in check_frontmatter("Multi", fm)]
    second = [(x.key, x.code) for x in check_frontmatter("Multi", dict(fm))]
    assert first == second


def test_legacy_keys_are_not_in_the_allowlist():
    assert not (LEGACY_NUTRITION_KEYS & KNOWN_KEYS)


@pytest.mark.parametrize("raw,expected", [
    ("6-8", 6),
    ("4-6 servings (estimated)", 4),
    ("6-8 as a side dish", 6),
    ("6 to 8", 6),
    ("6–8", 6),          # en dash
    ("Serves 4", 4),
    ("about 2 servings", 2),
    (8, 8),
    (8.0, 8),
    ("8", 8),
])
def test_servings_low_end_takes_the_low_end(raw, expected):
    assert servings_low_end(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "a few", "many servings", 0, -1, True, False])
def test_servings_low_end_returns_none_when_there_is_no_count(raw):
    assert servings_low_end(raw) is None


def test_servings_low_end_differs_from_the_nutrition_engine_midpoint():
    """Pins the deliberate divergence, so changing one side is a conscious act."""
    from lib.nutrition_engine import _parse_servings
    assert servings_low_end("6-8") == 6
    assert _parse_servings("6-8") == 7
