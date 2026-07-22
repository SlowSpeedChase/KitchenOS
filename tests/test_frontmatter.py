"""Frontmatter editing must be surgical — it runs over hand-edited recipe notes.

These characterize behaviour that was previously untested inside
backfill_nutrition.py, including the two corruption bugs its comments record:
gluing the closing `---` onto a key, and duplicate managed keys accumulating
across runs.
"""
import pytest

from lib import frontmatter as fmod

MANAGED = {"nutrition_calories", "needs_review", "cook_count"}


def test_updates_an_existing_key_in_place():
    fm = "title: Chili\nnutrition_calories: 100\n"
    out = fmod.rewrite(fm, {"nutrition_calories": 250}, MANAGED)
    assert "nutrition_calories: 250" in out
    assert "nutrition_calories: 100" not in out
    assert "title: Chili" in out


def test_appends_a_missing_key():
    out = fmod.rewrite("title: Chili\n", {"cook_count": 3}, MANAGED)
    assert "cook_count: 3" in out
    assert "title: Chili" in out


def test_collapses_duplicate_managed_keys_keeping_the_last():
    """YAML is last-key-wins; a prior buggy run could leave several."""
    fm = "title: Chili\nneeds_review: true\nx: 1\nneeds_review: false\n"
    out = fmod.rewrite(fm, {}, MANAGED)
    assert out.count("needs_review:") == 1
    assert "needs_review: false" in out


def test_leaves_unmanaged_keys_completely_alone():
    """Including unmanaged duplicates — not ours to normalize."""
    fm = "title: Chili\ncuisine: Thai\ncuisine: Mexican\n"
    assert fmod.rewrite(fm, {}, MANAGED) == fm


def test_preserves_multiline_list_values():
    """Indented list items must not be mistaken for keys."""
    fm = "tags:\n  - korean\n  - bread\ndietary: []\n"
    out = fmod.rewrite(fm, {"cook_count": 1}, MANAGED)
    assert "  - korean" in out and "  - bread" in out
    assert "tags:" in out


def test_always_ends_with_a_newline():
    """Regression: a missing trailing newline glued the closing --- onto a key."""
    out = fmod.rewrite("title: Chili", {"cook_count": 2}, MANAGED)
    assert out.endswith("\n")


def test_new_key_lands_before_trailing_blank_lines():
    """Regression: appending at the very end corrupted the closing delimiter."""
    out = fmod.rewrite("title: Chili\n\n", {"cook_count": 2}, MANAGED)
    lines = [l for l in out.split("\n") if l]
    assert lines[-1] == "cook_count: 2"


def test_apply_round_trips_a_whole_note():
    note = "---\ntitle: Chili\n---\n\n# Chili\n\nBody text.\n"
    out = fmod.apply(note, {"cook_count": 4}, MANAGED)
    assert out.startswith("---\n")
    assert "cook_count: 4" in out
    assert out.endswith("# Chili\n\nBody text.\n")
    assert "---\n\n# Chili" in out, "closing delimiter must stay on its own line"


def test_apply_returns_none_without_frontmatter():
    assert fmod.apply("# Just a heading\n", {"cook_count": 1}, MANAGED) is None


def test_body_containing_a_triple_dash_is_not_truncated():
    """`split('---', 2)` must keep horizontal rules in the body intact."""
    note = "---\ntitle: Chili\n---\n\nIntro\n\n---\n\nOutro\n"
    out = fmod.apply(note, {"cook_count": 1}, MANAGED)
    assert "Intro" in out and "Outro" in out
