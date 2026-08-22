"""Cook history: let real cooking backfill what the library doesn't know.

46% of recipes carry no `servings`, and nutrition for ~30% is stored per batch
rather than per serving — so the system cannot say whether a recipe is one
dinner or four frozen lunches. Asking the user to fill that in is a chore and
would not happen. Cooking it and recording the yield is not.

These aggregate the ledger onto the recipe note so the knowledge accumulates
as a side effect of use.
"""
import pytest

from lib import cook_history, serving_ledger as sl
from lib.recipe_parser import parse_recipe_file


@pytest.fixture
def recipes(tmp_vault):
    d = tmp_vault / "Recipes"
    d.mkdir(parents=True)
    return d


def _write_recipe(recipes, name, extra=""):
    (recipes / f"{name}.md").write_text(
        f"---\ntitle: {name}\ncuisine: American\n{extra}---\n\n# {name}\n\nBody.\n",
        encoding="utf-8",
    )


def _fm(recipes, name):
    return parse_recipe_file((recipes / f"{name}.md").read_text(encoding="utf-8"))["frontmatter"]


def _planned(recipe, produced, week="2026-W28", date="2026-07-07"):
    """A cook on the plan that has NOT happened yet — no `cooked_at`."""
    return sl.create_cook(recipe=recipe, week=week, servings_produced=produced,
                          date=date, meal="dinner")


def _cook(recipe, produced, week="2026-W28", date="2026-07-07"):
    """A cook that actually happened.

    A `cooks` row is created at *planning* time, so the ledger is mostly a
    record of intent; `cooked_at` is what makes one a cook. These helpers used
    to be the same function, which is how the module came to report
    `cook_count: 2` for a pair of recipes nobody had ever made.
    """
    row = _planned(recipe, produced, week=week, date=date)
    return sl.update_cook(row["id"], cooked_at=f"{date}T18:00:00Z")


# --------------------------------------------------------------------------
# Aggregation
# --------------------------------------------------------------------------

def test_no_cooks_yields_empty_stats(tmp_db):
    assert cook_history.recipe_stats("Never Made") == {}


def test_counts_cooks_and_records_observed_yield(tmp_db):
    _cook("Chili", 4)
    stats = cook_history.recipe_stats("Chili")
    assert stats["cook_count"] == 1
    assert stats["observed_servings"] == 4


def test_observed_yield_uses_the_median(tmp_db):
    """Median, not mean: one fat-fingered entry shouldn't move the estimate."""
    for produced in (4, 4, 40):
        _cook("Chili", produced)
    assert cook_history.recipe_stats("Chili")["observed_servings"] == 4


def test_counts_verdicts_separately_from_cooks(tmp_db):
    """Un-judged cooks must not count as negative reviews."""
    a, b, c = _cook("Chili", 4), _cook("Chili", 4), _cook("Chili", 4)
    sl.update_cook(a["id"], make_again=True)
    sl.update_cook(b["id"], make_again=False)
    # c deliberately left unjudged
    stats = cook_history.recipe_stats("Chili")
    assert stats["cook_count"] == 3
    assert stats["verdict_count"] == 2
    assert stats["make_again_count"] == 1


def test_tracks_the_most_recent_cook_date(tmp_db):
    _cook("Chili", 4, date="2026-07-07")
    _cook("Chili", 4, week="2026-W30", date="2026-07-21")
    assert cook_history.recipe_stats("Chili")["last_cooked"] == "2026-07-21"


def test_stats_are_scoped_to_one_recipe(tmp_db):
    _cook("Chili", 4)
    _cook("Tacos", 2)
    assert cook_history.recipe_stats("Chili")["cook_count"] == 1


# --------------------------------------------------------------------------
# Writing back to the note
# --------------------------------------------------------------------------

def test_sync_writes_stats_to_frontmatter(tmp_db, tmp_vault, recipes):
    _write_recipe(recipes, "Chili")
    _cook("Chili", 4)
    assert cook_history.sync_recipe("Chili") is True

    fm = _fm(recipes, "Chili")
    assert fm["cook_count"] == 1
    assert fm["observed_servings"] == 4
    assert fm["last_cooked"] == "2026-07-07"


def test_sync_preserves_existing_frontmatter(tmp_db, tmp_vault, recipes):
    """The note is hand-edited; only our keys may change."""
    _write_recipe(recipes, "Chili")
    _cook("Chili", 4)
    cook_history.sync_recipe("Chili")
    assert _fm(recipes, "Chili")["cuisine"] == "American"


def test_sync_is_idempotent(tmp_db, tmp_vault, recipes):
    """Re-running must not duplicate keys — the bug frontmatter.rewrite guards."""
    _write_recipe(recipes, "Chili")
    _cook("Chili", 4)
    cook_history.sync_recipe("Chili")
    cook_history.sync_recipe("Chili")
    body = (recipes / "Chili.md").read_text(encoding="utf-8")
    assert body.count("cook_count:") == 1


def test_sync_updates_stats_after_another_cook(tmp_db, tmp_vault, recipes):
    _write_recipe(recipes, "Chili")
    _cook("Chili", 4)
    cook_history.sync_recipe("Chili")
    _cook("Chili", 6, week="2026-W29", date="2026-07-14")
    cook_history.sync_recipe("Chili")
    assert _fm(recipes, "Chili")["cook_count"] == 2


def test_sync_does_not_overwrite_the_authored_servings(tmp_db, tmp_vault, recipes):
    """`servings` is the recipe's claim; `observed_servings` is what happened.

    Keeping both visible is the honest-about-inference rule — a disagreement is
    information, not an error to silently resolve.
    """
    _write_recipe(recipes, "Chili", extra="servings: 8\n")
    _cook("Chili", 4)
    cook_history.sync_recipe("Chili")
    fm = _fm(recipes, "Chili")
    assert fm["servings"] == 8
    assert fm["observed_servings"] == 4


def test_sync_is_a_noop_for_an_uncooked_recipe(tmp_db, tmp_vault, recipes):
    _write_recipe(recipes, "Chili")
    before = (recipes / "Chili.md").read_text(encoding="utf-8")
    assert cook_history.sync_recipe("Chili") is False
    assert (recipes / "Chili.md").read_text(encoding="utf-8") == before


def test_sync_tolerates_a_missing_recipe_file(tmp_db, tmp_vault, recipes):
    """Ledger rows can name recipes that were renamed or deleted."""
    _cook("Ghost Recipe", 4)
    assert cook_history.sync_recipe("Ghost Recipe") is False


def test_sync_clears_stats_when_the_last_cook_is_deleted(tmp_db, tmp_vault, recipes):
    """A stale "cooked 1 time" on a recipe with no cooks is worse than silence."""
    _write_recipe(recipes, "Chili")
    cook = _cook("Chili", 4)
    cook_history.sync_recipe("Chili")
    assert _fm(recipes, "Chili")["cook_count"] == 1

    sl.delete_cook(cook["id"])
    assert cook_history.sync_recipe("Chili") is True
    fm = _fm(recipes, "Chili")
    assert "cook_count" not in fm
    assert "observed_servings" not in fm
    assert fm["cuisine"] == "American", "unrelated keys must survive the cleanup"


def test_sync_all_covers_every_cooked_recipe(tmp_db, tmp_vault, recipes):
    _write_recipe(recipes, "Chili")
    _write_recipe(recipes, "Tacos")
    _cook("Chili", 4)
    _cook("Tacos", 2)
    result = cook_history.sync_all()
    assert result["updated"] == 2
    assert _fm(recipes, "Chili")["cook_count"] == 1
    assert _fm(recipes, "Tacos")["cook_count"] == 1


class TestCookHistoryBacksUp:
    """Syncing cook stats edits a real recipe, automatically, with no prompt.

    It wrote straight over the file. The vault is not in git, so a bad sync had
    no recovery path at all.
    """

    def _recipe(self, tmp_path, name="Chili"):
        p = tmp_path / f"{name}.md"
        p.write_text(
            f'---\ntitle: "{name}"\nservings: 4\n---\n\n# {name}\n\nMy hand-written notes.\n',
            encoding="utf-8",
        )
        return p

    def test_a_stats_write_snapshots_the_previous_file(self, tmp_path, monkeypatch):
        from lib import cook_history
        p = self._recipe(tmp_path)
        monkeypatch.setattr(cook_history, "recipe_stats", lambda r: {"cook_count": 3})

        assert cook_history.sync_recipe("Chili", recipes_dir=tmp_path) is True
        snaps = list((tmp_path / ".history").glob("Chili_*.md"))
        assert len(snaps) == 1
        assert "My hand-written notes." in snaps[0].read_text(encoding="utf-8")
        assert "cook_count: 3" in p.read_text(encoding="utf-8")

    def test_an_unchanged_sync_writes_nothing(self, tmp_path, monkeypatch):
        """sync_all runs over the whole corpus; it must not spam .history."""
        from lib import cook_history
        p = self._recipe(tmp_path)
        monkeypatch.setattr(cook_history, "recipe_stats", lambda r: {"cook_count": 3})

        cook_history.sync_recipe("Chili", recipes_dir=tmp_path)
        before = p.stat().st_mtime_ns
        assert cook_history.sync_recipe("Chili", recipes_dir=tmp_path) is False
        assert p.stat().st_mtime_ns == before
        assert len(list((tmp_path / ".history").glob("Chili_*.md"))) == 1


# --------------------------------------------------------------------------
# Planned is not cooked
# --------------------------------------------------------------------------
#
# A `cooks` row is created when you drop a recipe onto the board, so the table
# is mostly a record of *intent*. Counting rows therefore measured planning:
# the live ledger had 16 rows and 2 real cooks, yet 10 recipes carried
# `last_cooked` and 13 carried `cook_count`. The module's own purpose — learning
# a recipe's real yield from what actually came out of the pan — cannot work on
# batches that were never made. Nothing consumes these fields yet, which is why
# this is worth fixing now rather than after something starts trusting them.

def test_a_planned_cook_is_not_a_cook(tmp_db):
    _planned("Chili", 4)
    assert cook_history.recipe_stats("Chili") == {}


def test_planned_cooks_do_not_inflate_the_count(tmp_db):
    _cook("Chili", 4)
    _planned("Chili", 4)
    _planned("Chili", 4)
    assert cook_history.recipe_stats("Chili")["cook_count"] == 1


def test_observed_yield_ignores_batches_never_made(tmp_db):
    _cook("Chili", 4)
    _planned("Chili", 40)          # a scaled-up plan for next week
    assert cook_history.recipe_stats("Chili")["observed_servings"] == 4


def test_last_cooked_comes_from_cooked_at_not_the_planned_date(tmp_db):
    """A cook planned for next month must not read as the last time you made it."""
    _cook("Chili", 4, date="2026-07-07")
    _planned("Chili", 4, week="2026-W35", date="2026-08-26")
    assert cook_history.recipe_stats("Chili")["last_cooked"] == "2026-07-07"


def test_a_verdict_counts_as_having_cooked_it(tmp_db):
    """Judging a dish asserts you made it, even if 🍳 was never tapped.

    The verdict nudge asks about dishes whose date has passed, so this is a
    real path to a verdict on a row that carries no `cooked_at`.
    """
    row = _planned("Chili", 4)
    sl.update_cook(row["id"], make_again=True)
    stats = cook_history.recipe_stats("Chili")
    assert stats["cook_count"] == 1
    assert stats["verdict_count"] == 1
    assert stats["make_again_count"] == 1


class TestCookedRecipeNames:
    def test_planned_but_never_cooked_is_absent(self, recipes):
        """A cooks row is created at PLANNING time. Counting rows measured
        planning, not cooking: the live ledger held 16 rows against 2 real
        cooks. This is the regression that guards never_cooked."""
        _write_recipe(recipes, "Lamb Ragu")
        _planned("Lamb Ragu", 4)
        assert cook_history.cooked_recipe_names() == set()

    def test_cooked_at_makes_it_cooked(self, recipes):
        _write_recipe(recipes, "Lamb Ragu")
        _cook("Lamb Ragu", 4)
        assert cook_history.cooked_recipe_names() == {"Lamb Ragu"}

    def test_a_verdict_alone_makes_it_cooked(self, recipes):
        """Judging a dish asserts you made it, even with no cooked_at stamp."""
        _write_recipe(recipes, "Shakshuka")
        row = _planned("Shakshuka", 2)
        sl.update_cook(row["id"], make_again=True)
        assert cook_history.cooked_recipe_names() == {"Shakshuka"}
