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
    """Pins the deliberate POLICY divergence: low end here, midpoint there."""
    from lib.nutrition_engine import _parse_servings
    assert servings_low_end("6-8") == 6
    assert _parse_servings("6-8") == 7


@pytest.mark.parametrize("raw", [
    "makes 24 cookies, serves 6",
    "1 loaf (10 slices)",
    "9x13 pan",
    "350 degrees",
])
def test_the_write_time_reader_is_stricter_than_the_read_time_one(raw):
    """Pins the deliberate PARSING divergence, not just the policy.

    ``_parse_servings`` falls back to the first integer anywhere in the string
    because it must return something for a macro calculation it is already
    committed to. ``servings_low_end`` decides what to WRITE into the user's
    file, where a wrong number silently rescales every stored macro — so it
    refuses rather than guesses. If someone ever "fixes" one to match the other,
    this fails and makes them say why.
    """
    from lib.nutrition_engine import _parse_servings
    strict = servings_low_end(raw)
    loose = _parse_servings(raw)
    assert loose >= 1, "the engine still guesses, by design"
    assert strict is None or strict != loose, (
        f"{raw!r}: the write-time reader should refuse or disagree, got {strict}"
    )


class TestServingsLowEndDoesNotGuess:
    """A wrong servings value is worse than no value.

    The bare-integer fallback grabbed the FIRST number in arbitrary prose, so
    "makes 24 cookies, serves 6" returned 24 — a 4x error that silently
    rescales every per-serving macro. Returning None instead leaves the string
    in place, which --check keeps reporting until a human resolves it.

    The three values in the live corpus were all ranges and all resolved
    correctly; these are the ones the extractor could produce next.
    """

    @pytest.mark.parametrize("raw,expected", [
        # A range is unambiguous — take the low end.
        ("6-8", 6),
        ("4-6 servings (estimated)", 4),
        ("6-8 as a side dish", 6),
        ("6 to 8", 6),
        ("6–8", 6),
        # A number next to a serving word is unambiguous.
        ("Serves 4", 4),
        ("about 2 servings", 2),
        ("serves 6", 6),
        ("4 portions", 4),
        # A bare number is unambiguous.
        ("8", 8),
        (8, 8),
        (8.0, 8),
    ])
    def test_it_still_reads_what_is_unambiguous(self, raw, expected):
        assert servings_low_end(raw) == expected

    @pytest.mark.parametrize("raw,expected", [
        # A yield and a serving count in one string: anchor on the serving word,
        # never on position. The old first-integer rule returned the yield.
        ("makes 24 cookies, serves 6", 6),
        ("Makes about 20 meatballs, serves 5", 5),
        ("24 cookies (12 servings)", 12),
    ])
    def test_a_serving_word_beats_a_yield(self, raw, expected):
        assert servings_low_end(raw) == expected

    @pytest.mark.parametrize("raw", [
        "1 loaf (10 slices)",   # a yield with no serving count at all
        "Makes 24 cookies",     # ditto — "makes" is a yield word, not a serving one
        "9x13 pan",             # a pan size
        "350 degrees",          # an oven temperature
        "2026-08-01",           # a date
        "a few",
        "many servings",        # a serving word with no number
    ])
    def test_it_refuses_to_guess_from_prose(self, raw):
        assert servings_low_end(raw) is None, f"guessed a number from {raw!r}"


class TestDuplicateKeyDetection:
    """The branch's own central hazard, guarded at the artifact rather than the producer.

    check_frontmatter takes a dict, so by construction it cannot see two
    `nutrition_calories:` lines — the corpus guard would have passed cleanly on
    exactly the file migrate_recipes.rename_nutrition_keys used to emit. This
    checks the raw text instead, which is the only place the duplicate exists.
    """

    def test_a_duplicate_key_is_reported(self):
        from lib.recipe_schema import duplicate_keys
        fm = "title: X\nnutrition_calories: 3058\nnutrition_calories: 169\n"
        assert duplicate_keys(fm) == ["nutrition_calories"]

    def test_a_clean_frontmatter_reports_nothing(self):
        from lib.recipe_schema import duplicate_keys
        assert duplicate_keys("title: X\nservings: 4\n") == []

    def test_list_items_are_not_mistaken_for_keys(self):
        from lib.recipe_schema import duplicate_keys
        fm = "tags:\n  - a\n  - b\ndietary:\n  - a\n  - b\n"
        assert duplicate_keys(fm) == []

    def test_several_duplicates_are_all_reported_in_order(self):
        from lib.recipe_schema import duplicate_keys
        fm = "a: 1\nb: 1\na: 2\nb: 2\n"
        assert duplicate_keys(fm) == ["a", "b"]

    def test_a_key_repeated_three_times_is_reported_once(self):
        from lib.recipe_schema import duplicate_keys
        assert duplicate_keys("a: 1\na: 2\na: 3\n") == ["a"]
