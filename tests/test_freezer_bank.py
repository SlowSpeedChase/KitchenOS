"""The freezer as a bank of ready meals, not a write-only hole.

`placements.destination` has supported `freezer` since the ledger was written,
and `freezer_contents()` has been able to read it back the whole time — with
zero callers. No API route, no template, no script. So a serving could be banked
and then vanish: nothing displayed it, counted it, or reminded you it existed.

That is worse than not supporting freezing, because the write half works. These
tests cover the read half: what's banked, what it's worth, and what to eat first.
"""
import pytest

from lib import serving_ledger as sl


def _recipe(recipes_dir, name, *, calories=500, protein=40, servings=4,
            coverage=1.0):
    """Write a recipe file with the frontmatter the macro reader wants."""
    body = [
        "---",
        f"servings: {servings}",
        f"nutrition_calories: {calories}",
        f"nutrition_protein: {protein}",
        "nutrition_carbs: 30",
        "nutrition_fat: 15",
        f"nutrition_coverage: {coverage}",
        "---",
        f"# {name}",
    ]
    (recipes_dir / f"{name}.md").write_text("\n".join(body), encoding="utf-8")


@pytest.fixture
def recipes_dir(tmp_path):
    d = tmp_path / "Recipes"
    d.mkdir()
    return d


def _cook(recipe="Chili", servings=6.0, **over):
    kw = dict(recipe=recipe, week="2026-W28", scale=1.0,
              servings_produced=servings, date="2026-07-07", meal="dinner")
    kw.update(over)
    return sl.create_cook(**kw)


class TestGrouping:
    def test_an_empty_freezer_is_empty_not_an_error(self, tmp_db, recipes_dir):
        assert sl.freezer_summary(recipes_dir) == []

    def test_servings_of_one_recipe_group_into_a_single_row(self, tmp_db, recipes_dir):
        """Cooking Chili twice is one thing to eat, not two rows to reconcile."""
        _recipe(recipes_dir, "Chili")
        a = _cook("Chili", date="2026-07-07")
        b = _cook("Chili", date="2026-07-09")
        sl.add_placement(a["id"], "freezer", 3.0)
        sl.add_placement(b["id"], "freezer", 2.0)

        rows = sl.freezer_summary(recipes_dir)
        assert len(rows) == 1
        assert rows[0]["recipe"] == "Chili"
        assert rows[0]["servings"] == 5.0

    def test_slot_and_trash_placements_are_not_in_the_freezer(self, tmp_db, recipes_dir):
        _recipe(recipes_dir, "Chili")
        cook = _cook("Chili")
        sl.add_placement(cook["id"], "freezer", 2.0)
        sl.add_placement(cook["id"], "trash", 1.0)
        # the anchor serving is already a `slot` placement
        rows = sl.freezer_summary(recipes_dir)
        assert [r["servings"] for r in rows] == [2.0]

    def test_distinct_recipes_stay_distinct(self, tmp_db, recipes_dir):
        for n in ("Chili", "Curry"):
            _recipe(recipes_dir, n)
            sl.add_placement(_cook(n)["id"], "freezer", 2.0)
        assert {r["recipe"] for r in sl.freezer_summary(recipes_dir)} == {"Chili", "Curry"}


class TestEatTheOldestFirst:
    def test_rows_are_ordered_oldest_first(self, tmp_db, recipes_dir):
        """A freezer is FIFO or it's an archaeology site."""
        for name, day in (("New", "2026-07-20"), ("Old", "2026-07-01")):
            _recipe(recipes_dir, name)
            sl.add_placement(_cook(name, date=day)["id"], "freezer", 2.0)
        assert [r["recipe"] for r in sl.freezer_summary(recipes_dir)] == ["Old", "New"]

    def test_a_group_is_dated_by_its_oldest_serving(self, tmp_db, recipes_dir):
        _recipe(recipes_dir, "Chili")
        sl.add_placement(_cook("Chili", date="2026-07-09")["id"], "freezer", 1.0)
        sl.add_placement(_cook("Chili", date="2026-07-02")["id"], "freezer", 1.0)
        assert sl.freezer_summary(recipes_dir)[0]["banked_on"] == "2026-07-02"

    def test_when_it_was_actually_cooked_beats_when_it_was_planned(
            self, tmp_db, recipes_dir):
        """`date` is an intention; `cooked_at` is what happened."""
        _recipe(recipes_dir, "Chili")
        cook = _cook("Chili", date="2026-07-20")
        sl.update_cook(cook["id"], cooked_at="2026-07-03T18:00:00")
        sl.add_placement(cook["id"], "freezer", 2.0)
        assert sl.freezer_summary(recipes_dir)[0]["banked_on"] == "2026-07-03"


class TestWhatItIsWorth:
    def test_a_row_carries_per_serving_macros(self, tmp_db, recipes_dir):
        _recipe(recipes_dir, "Chili", protein=42, calories=600)
        sl.add_placement(_cook("Chili")["id"], "freezer", 3.0)
        row = sl.freezer_summary(recipes_dir)[0]
        assert (row["protein"], row["calories"]) == (42, 600)

    def test_totals_are_the_per_serving_value_times_the_bank(self, tmp_db, recipes_dir):
        """What the freezer is worth is the number that answers "do I need to cook"."""
        _recipe(recipes_dir, "Chili", protein=40, calories=500)
        sl.add_placement(_cook("Chili")["id"], "freezer", 3.0)
        row = sl.freezer_summary(recipes_dir)[0]
        assert (row["total_protein"], row["total_calories"]) == (120.0, 1500.0)

    def test_implausible_macros_are_withheld_rather_than_reported(
            self, tmp_db, recipes_dir):
        """Same gate as the suggester: a wrong number is worse than no number.

        Phase 1 established this — 244 g of protein per serving is not a
        datapoint, and a freezer tray totalling it would be a worse lie than a
        blank.
        """
        _recipe(recipes_dir, "Bogus", protein=244, calories=300)
        sl.add_placement(_cook("Bogus")["id"], "freezer", 2.0)
        row = sl.freezer_summary(recipes_dir)[0]
        assert row["protein"] is None
        assert row["total_protein"] is None
        assert row["servings"] == 2.0      # the servings are still real

    def test_a_missing_recipe_file_does_not_break_the_tray(self, tmp_db, recipes_dir):
        """The cook happened even if the recipe was since renamed or deleted."""
        sl.add_placement(_cook("Vanished")["id"], "freezer", 2.0)
        row = sl.freezer_summary(recipes_dir)[0]
        assert row["recipe"] == "Vanished"
        assert row["servings"] == 2.0
        assert row["protein"] is None


class TestBankedRecipeNames:
    """Cheap lookup for the suggester, which only needs "is this already banked"."""

    def test_it_names_what_is_in_the_freezer(self, tmp_db, recipes_dir):
        for n in ("Chili", "Curry"):
            sl.add_placement(_cook(n)["id"], "freezer", 1.0)
        assert sl.banked_recipes() == {"Chili", "Curry"}

    def test_it_is_empty_when_nothing_is_banked(self, tmp_db):
        _cook("Chili")          # slot placement only
        assert sl.banked_recipes() == set()
