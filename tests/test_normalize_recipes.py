"""Repairs, exercised over temp files — never the real vault.

Fixtures carry the full required key set, because a real recipe does. Building
them from REQUIRED_KEYS rather than hand-listing 30 lines keeps them honest if
the schema gains a key.
"""
import sys

import pytest

import yaml

from lib.recipe_schema import REQUIRED_KEYS
from scripts.normalize_recipes import normalize_content, normalize_file

_BODY = "\n# Recipe\n\nBody stays untouched.\n"


def _doc(*, leading: str = "", trailing: str = "", **overrides) -> str:
    """A conforming recipe document, with `overrides` applied to frontmatter.

    ``leading`` is emitted before the generated keys and ``trailing`` after, so
    a test can control where drift sits relative to the canonical keys — the
    ordering that decides which duplicate YAML keeps.
    """
    values = {k: "x" for k in REQUIRED_KEYS}
    values["servings"] = 4
    values["nutrition_calories"] = 169
    values["nutrition_carbs"] = 12
    values["nutrition_fat"] = 9
    values.update(overrides)
    lines = [f"{k}: {values[k]}" for k in sorted(values)]
    fm = "\n".join(filter(None, [leading.strip("\n"), "\n".join(lines), trailing.strip("\n")]))
    return f"---\n{fm}\n---\n{_BODY}"


#: Watermelon Feta Salad's real shape: a servings range, plus legacy nutrition
#: keys sitting *above* the canonical ones (legacy-first, as all 13 corpus
#: files are).
RANGED = _doc(
    leading="calories: 3058\ncarbs: null\nfat: null",
    servings="6-8 as a side dish",
)

CLEAN = _doc()


def _fm(content: str) -> dict:
    return yaml.safe_load(content.split("---")[1])


def test_a_servings_range_becomes_its_low_end():
    out, _ = normalize_content("Watermelon Feta Salad", RANGED)
    assert _fm(out)["servings"] == 6


def test_a_repaired_servings_is_flagged_as_inferred():
    out, _ = normalize_content("Watermelon Feta Salad", RANGED)
    fm = _fm(out)
    assert fm["servings_inferred"] is True
    assert fm["servings_needs_review"] is True


def test_legacy_nutrition_keys_are_deleted():
    out, _ = normalize_content("Watermelon Feta Salad", RANGED)
    fm = _fm(out)
    assert "calories" not in fm
    assert "carbs" not in fm
    assert "fat" not in fm


def test_the_canonical_nutrition_values_are_untouched():
    out, _ = normalize_content("Watermelon Feta Salad", RANGED)
    fm = _fm(out)
    assert fm["nutrition_calories"] == 169
    assert fm["nutrition_carbs"] == 12
    assert fm["nutrition_fat"] == 9


def test_a_dropped_key_is_removed():
    content = _doc(trailing='recipe_url: "https://example.com"')
    out, changes = normalize_content("Chocolate Peanut Butter Bars", content)
    assert "recipe_url" not in _fm(out)
    assert any("recipe_url" in c for c in changes)


def test_the_body_is_never_touched():
    out, _ = normalize_content("Watermelon Feta Salad", RANGED)
    assert out.split("---", 2)[2] == RANGED.split("---", 2)[2]


def test_a_conforming_file_is_returned_byte_identical():
    out, changes = normalize_content("Fine Recipe", CLEAN)
    assert out == CLEAN
    assert changes == []


def test_normalization_is_idempotent():
    once, _ = normalize_content("Watermelon Feta Salad", RANGED)
    twice, changes = normalize_content("Watermelon Feta Salad", once)
    assert twice == once
    assert changes == []


def test_changes_name_every_repair():
    _, changes = normalize_content("Watermelon Feta Salad", RANGED)
    joined = " ".join(changes)
    assert "servings" in joined
    assert "calories" in joined


def test_a_file_with_no_frontmatter_is_left_alone():
    content = "# Just a body\n\nNo frontmatter here.\n"
    out, changes = normalize_content("Bare", content)
    assert out == content
    assert changes == []


def test_dry_run_does_not_write(tmp_path):
    p = tmp_path / "Watermelon Feta Salad.md"
    p.write_text(RANGED, encoding="utf-8")
    changes, written = normalize_file(p, apply=False)
    assert changes                       # it reports what it would do
    assert written is False
    assert p.read_text(encoding="utf-8") == RANGED   # but changes nothing


def test_apply_writes_and_backs_up(tmp_path):
    p = tmp_path / "Watermelon Feta Salad.md"
    p.write_text(RANGED, encoding="utf-8")
    normalize_file(p, apply=True)
    assert _fm(p.read_text(encoding="utf-8"))["servings"] == 6
    backups = list((tmp_path / ".history").glob("*"))
    assert backups, "the vault is not in git — a backup is the only recovery path"


def test_apply_on_a_clean_file_writes_nothing(tmp_path):
    p = tmp_path / "Fine Recipe.md"
    p.write_text(CLEAN, encoding="utf-8")
    before = p.stat().st_mtime_ns
    assert normalize_file(p, apply=True) == ([], False)
    assert p.stat().st_mtime_ns == before
    assert not (tmp_path / ".history").exists()


def test_check_exits_nonzero_when_the_corpus_drifts(tmp_path, monkeypatch, capsys):
    from scripts import normalize_recipes

    (tmp_path / "Recipes").mkdir()
    (tmp_path / "Recipes" / "Ranged.md").write_text(RANGED, encoding="utf-8")
    monkeypatch.setenv("KITCHENOS_VAULT", str(tmp_path))
    monkeypatch.setattr(sys, "argv", ["normalize_recipes.py", "--check"])

    assert normalize_recipes.main() == 1
    assert "servings_not_numeric" in capsys.readouterr().out


def test_check_exits_zero_on_a_conforming_corpus(tmp_path, monkeypatch):
    from scripts import normalize_recipes

    (tmp_path / "Recipes").mkdir()
    (tmp_path / "Recipes" / "Fine Recipe.md").write_text(CLEAN, encoding="utf-8")
    monkeypatch.setenv("KITCHENOS_VAULT", str(tmp_path))
    monkeypatch.setattr(sys, "argv", ["normalize_recipes.py", "--check"])

    assert normalize_recipes.main() == 0


def test_a_missing_recipes_dir_is_an_error_not_a_clean_bill(tmp_path, monkeypatch):
    """An empty corpus must never report "0 violations".

    lib/paths.py resolves KITCHENOS_VAULT from the repo's own .env, which is
    git-ignored and therefore absent from every linked worktree — so running
    this from .worktrees/ silently found zero recipes and exited 0, which reads
    as "the corpus is clean" when it means "the corpus was never looked at".
    """
    from scripts import normalize_recipes

    monkeypatch.setenv("KITCHENOS_VAULT", str(tmp_path / "nowhere"))
    monkeypatch.setattr(sys, "argv", ["normalize_recipes.py", "--check"])

    with pytest.raises(SystemExit) as e:
        normalize_recipes.main()
    assert "no recipes" in str(e.value).lower()


def test_an_empty_recipes_dir_is_an_error(tmp_path, monkeypatch):
    from scripts import normalize_recipes

    (tmp_path / "Recipes").mkdir()
    monkeypatch.setenv("KITCHENOS_VAULT", str(tmp_path))
    monkeypatch.setattr(sys, "argv", ["normalize_recipes.py", "--check"])

    with pytest.raises(SystemExit) as e:
        normalize_recipes.main()
    assert "no recipes" in str(e.value).lower()


def test_the_error_names_the_directory_it_looked_in(tmp_path, monkeypatch):
    """So the fix (point KITCHENOS_VAULT at the main checkout) is obvious."""
    from scripts import normalize_recipes

    monkeypatch.setenv("KITCHENOS_VAULT", str(tmp_path / "nowhere"))
    monkeypatch.setattr(sys, "argv", ["normalize_recipes.py", "--apply"])

    with pytest.raises(SystemExit) as e:
        normalize_recipes.main()
    assert "nowhere" in str(e.value)


class TestLegacyKeyNeedsItsCanonicalTwin:
    """Deleting a legacy nutrition key is only safe if the canonical one exists.

    lib/recipe_schema documents "every file carrying one already has a non-null
    canonical value (verified 2026-08-01)" — but that was a property of the data,
    not a check. Removing on sight destroys the file's only calorie value, and it
    is the exact mirror of the migrate_recipes bug this branch fixed: that one
    refuses to rename ONTO an existing key, this one must refuse to delete
    WITHOUT one.
    """

    def test_a_legacy_key_is_kept_when_the_canonical_one_is_missing(self):
        content = _doc(leading="calories: 357", nutrition_calories=None)
        # strip the canonical line entirely
        content = "\n".join(
            ln for ln in content.splitlines() if not ln.startswith("nutrition_calories:")
        ) + "\n"
        out, changes = normalize_content("Orphan", content)
        assert "calories: 357" in out
        assert any("UNREPAIRED" in c or "kept" in c.lower() for c in changes), changes

    def test_a_legacy_key_is_kept_when_the_canonical_one_is_null(self):
        content = _doc(leading="calories: 357", nutrition_calories="null")
        out, changes = normalize_content("NullCanonical", content)
        assert "calories: 357" in out

    def test_a_legacy_key_is_still_dropped_when_the_canonical_one_has_a_value(self):
        content = _doc(leading="calories: 3058")
        out, changes = normalize_content("Normal", content)
        assert "\ncalories:" not in out
        assert _fm(out)["nutrition_calories"] == 169

    def test_the_kept_key_keeps_check_failing_rather_than_silently_passing(self):
        """An unrepairable file must stay visible, not be quietly accepted."""
        from lib.recipe_schema import check_frontmatter
        content = _doc(leading="calories: 357", nutrition_calories="null")
        out, _ = normalize_content("NullCanonical", content)
        import yaml
        still = check_frontmatter("NullCanonical", yaml.safe_load(out.split("---")[1]))
        assert any(v.code == "legacy_nutrition_key" for v in still)


class TestUnrepairableWorkIsNotReportedAsSuccess:
    """The one place the branch didn't apply its own rule to itself.

    --apply returned 0 unconditionally, so a violation the tool structurally
    cannot fix scrolled past inside up to 252 files of output while the run
    reported success — and --check then failed forever on it. `Modified: N`
    also counted files where nothing was written.
    """

    def _corpus(self, tmp_path, monkeypatch, **files):
        (tmp_path / "Recipes").mkdir()
        for name, content in files.items():
            (tmp_path / "Recipes" / f"{name}.md").write_text(content, encoding="utf-8")
        monkeypatch.setenv("KITCHENOS_VAULT", str(tmp_path))

    def test_apply_exits_nonzero_when_something_could_not_be_repaired(
        self, tmp_path, monkeypatch, capsys
    ):
        from scripts import normalize_recipes
        # a servings string with no recoverable number
        self._corpus(tmp_path, monkeypatch, Vague=_doc(servings="a few"))
        monkeypatch.setattr(sys, "argv", ["normalize_recipes.py", "--apply"])

        assert normalize_recipes.main() == 1
        out = capsys.readouterr().out
        assert "Vague" in out
        assert "could not" in out.lower() or "unrepaired" in out.lower()

    def test_apply_exits_zero_when_everything_was_repaired(self, tmp_path, monkeypatch):
        from scripts import normalize_recipes
        self._corpus(tmp_path, monkeypatch, Ranged=RANGED)
        monkeypatch.setattr(sys, "argv", ["normalize_recipes.py", "--apply"])
        assert normalize_recipes.main() == 0

    def test_modified_count_excludes_files_nothing_was_written_to(
        self, tmp_path, monkeypatch, capsys
    ):
        from scripts import normalize_recipes
        self._corpus(tmp_path, monkeypatch, Vague=_doc(servings="a few"))
        monkeypatch.setattr(sys, "argv", ["normalize_recipes.py", "--apply"])
        normalize_recipes.main()
        assert "Modified: 0 file(s)" in capsys.readouterr().out

    def test_the_unrepaired_recipes_are_named_in_a_trailing_summary(
        self, tmp_path, monkeypatch, capsys
    ):
        """A line scrolled past 252 files ago is not a report."""
        from scripts import normalize_recipes
        self._corpus(tmp_path, monkeypatch, Vague=_doc(servings="a few"))
        monkeypatch.setattr(sys, "argv", ["normalize_recipes.py", "--apply"])
        normalize_recipes.main()
        tail = capsys.readouterr().out.rsplit("Modified:", 1)[-1]
        assert "Vague" in tail


class TestServingsChangeMarksMacrosStale:
    """A stdout line is not a persistent record.

    Changing servings invalidates the stored per-serving macros, but the only
    signal was a console message — and on any re-run the file is conforming, so
    the list of files needing a re-derive is never printed again.
    """

    def test_a_servings_change_flags_nutrition_for_review(self):
        out, _ = normalize_content("Watermelon Feta Salad", RANGED)
        assert _fm(out)["nutrition_needs_review"] is True

    def test_a_file_with_no_servings_change_is_not_flagged(self):
        content = _doc(leading="calories: 3058")
        out, _ = normalize_content("LegacyOnly", content)
        assert _fm(out).get("nutrition_needs_review") is not True
