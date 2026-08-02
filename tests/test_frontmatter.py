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


class TestSplitIsLineBased:
    """A '---' inside a *value* must not be mistaken for the closing delimiter.

    split_frontmatter used content.split('---', 2) — a substring split — while
    recipe_parser.parse_recipe_file uses a line-anchored regex. On a value like
    `video_title: "Noodles --- the viral one"` the two disagree: the checker
    sees the whole frontmatter, the editor is handed a block truncated mid-value,
    and new keys get inserted into the middle of that string. The result is
    unparseable YAML with a duplicated key.

    0 of 252 corpus files contain '---' in frontmatter today, but
    templates/recipe_template.py interpolates raw YouTube titles into
    video_title, so the corpus is one extraction away from it.
    """

    FM_WITH_DASHES = (
        '---\n'
        'title: "X"\n'
        'video_title: "Noodles --- the viral one"\n'
        'servings: 4\n'
        '---\n'
        '\n# X\n\nBody.\n'
    )

    def test_a_value_containing_dashes_does_not_truncate_the_frontmatter(self):
        from lib import frontmatter
        fm, rest = frontmatter.split_frontmatter(self.FM_WITH_DASHES)
        assert "servings: 4" in fm
        assert "the viral one" in fm

    def test_the_body_survives_a_value_containing_dashes(self):
        from lib import frontmatter
        fm, rest = frontmatter.split_frontmatter(self.FM_WITH_DASHES)
        assert "Body." in rest
        assert "video_title" not in rest

    def test_it_agrees_with_the_recipe_parser(self):
        from lib import frontmatter
        from lib.recipe_parser import parse_recipe_file
        fm, _ = frontmatter.split_frontmatter(self.FM_WITH_DASHES)
        parsed = parse_recipe_file(self.FM_WITH_DASHES)["frontmatter"]
        for key in parsed:
            assert f"{key}:" in fm, f"{key} visible to the parser but not the editor"

    def test_a_rewrite_keeps_the_document_parseable(self):
        import yaml
        from lib import frontmatter
        out = frontmatter.apply(self.FM_WITH_DASHES, {"servings": 6}, {"servings"})
        fm, rest = frontmatter.split_frontmatter(out)
        loaded = yaml.safe_load(fm)
        assert loaded["servings"] == 6
        assert loaded["video_title"] == "Noodles --- the viral one"
        assert "Body." in rest

    def test_a_rewrite_does_not_duplicate_the_edited_key(self):
        from lib import frontmatter
        out = frontmatter.apply(self.FM_WITH_DASHES, {"servings": 6}, {"servings"})
        fm, _ = frontmatter.split_frontmatter(out)
        assert [ln for ln in fm.splitlines() if ln.startswith("servings:")] == ["servings: 6"]

    def test_content_without_frontmatter_returns_none(self):
        from lib import frontmatter
        assert frontmatter.split_frontmatter("# Just a body\n") == (None, None)

    def test_a_body_horizontal_rule_is_not_a_frontmatter_delimiter(self):
        from lib import frontmatter
        content = "# Title\n\ntext\n\n---\n\nmore text\n"
        assert frontmatter.split_frontmatter(content) == (None, None)


class TestRemoveTakesContinuationLines:
    """Deleting a key must delete its value, including a multi-line one.

    remove dropped only the `key:` line, leaving indented continuation lines
    floating. PyYAML then either errors or folds them into the preceding key's
    value — silent corruption. The module docstring promises multi-line list
    values pass through untouched; remove quietly broke that promise.
    """

    def test_a_block_scalar_value_is_removed_with_its_key(self):
        import yaml
        from lib import frontmatter
        fm = 'title: "X"\ncalories: |\n  3058 total\n  whole recipe\nnutrition_calories: 152\n'
        out = frontmatter.rewrite(fm, {}, {"calories"}, remove={"calories"})
        loaded = yaml.safe_load(out)
        assert loaded == {"title": "X", "nutrition_calories": 152}

    def test_a_list_value_is_removed_with_its_key(self):
        import yaml
        from lib import frontmatter
        fm = 'title: "X"\nfat:\n  - 12\n  - 14\nnutrition_fat: 9\n'
        out = frontmatter.rewrite(fm, {}, {"fat"}, remove={"fat"})
        loaded = yaml.safe_load(out)
        assert loaded == {"title": "X", "nutrition_fat": 9}

    def test_an_unrelated_list_value_is_still_untouched(self):
        import yaml
        from lib import frontmatter
        fm = 'tags:\n  - a\n  - b\ncalories: 5\nnutrition_calories: 7\n'
        out = frontmatter.rewrite(fm, {}, {"calories"}, remove={"calories"})
        loaded = yaml.safe_load(out)
        assert loaded == {"tags": ["a", "b"], "nutrition_calories": 7}
