"""The nightly sweep: a planned cook whose day has passed counts as cooked."""

import pytest

from lib import cook_sweep, serving_ledger as sl


@pytest.fixture(autouse=True)
def _no_real_consumption(monkeypatch):
    """Record what would be spent instead of touching inventory."""
    spent = []
    monkeypatch.setattr(cook_sweep.cook_module, "consume_recipe",
                        lambda name, servings=1.0, **kw: spent.append((name, servings)))
    return spent


@pytest.fixture
def spent(_no_real_consumption):
    return _no_real_consumption


def _cook(recipe="Chili", week="2026-W28", date="2026-07-07", **kw):
    return sl.create_cook(recipe=recipe, week=week, servings_produced=4.0,
                          date=date, meal="dinner", **kw)


TODAY = "2026-07-10"


class TestDueCooks:
    def test_a_past_cook_is_due(self, tmp_db):
        _cook(date="2026-07-07")
        assert [c["recipe"] for c in cook_sweep.due_cooks(TODAY)] == ["Chili"]

    def test_todays_cook_is_not_due_yet(self, tmp_db):
        """Tonight's dinner has not happened when the nightly job runs."""
        _cook(date=TODAY, week="2026-W28")
        assert cook_sweep.due_cooks(TODAY) == []

    def test_a_future_cook_is_not_due(self, tmp_db):
        _cook(date="2026-07-09", week="2026-W28")
        assert cook_sweep.due_cooks("2026-07-08") == []

    def test_an_undated_cook_is_never_due(self, tmp_db):
        """The unscheduled tray is a parking space, not a claim about the past."""
        sl.create_cook(recipe="Chili", week="2026-W28", servings_produced=4.0)
        assert cook_sweep.due_cooks(TODAY) == []

    def test_an_already_cooked_row_is_not_due(self, tmp_db):
        row = _cook()
        sl.update_cook(row["id"], cooked_at="2026-07-07T18:00:00Z")
        assert cook_sweep.due_cooks(TODAY) == []


class TestSweep:
    def test_it_marks_the_cook(self, tmp_db):
        row = _cook()
        result = cook_sweep.sweep(TODAY)
        assert result["marked"] == ["Chili"]
        assert sl.get_cook(row["id"])["cooked_at"] is not None

    def test_it_stamps_the_planned_day_not_today(self, tmp_db):
        """`last_cooked` should say when it was eaten, not when we noticed."""
        row = _cook(date="2026-07-07")
        cook_sweep.sweep(TODAY)
        assert sl.get_cook(row["id"])["cooked_at"].startswith("2026-07-07")

    def test_it_spends_the_pantry(self, tmp_db, spent):
        _cook()
        cook_sweep.sweep(TODAY)
        assert spent == [("Chili", 1.0)]

    def test_scale_multiplies_what_is_spent(self, tmp_db, spent):
        _cook(scale=2.0)
        cook_sweep.sweep(TODAY)
        assert spent == [("Chili", 2.0)]

    def test_running_twice_spends_once(self, tmp_db, spent):
        """Idempotent: a swept cook carries cooked_at and is no longer due."""
        _cook()
        cook_sweep.sweep(TODAY)
        cook_sweep.sweep(TODAY)
        assert len(spent) == 1

    def test_a_failing_consume_still_records_the_cook(self, tmp_db, monkeypatch):
        """The cook record is the memory; inventory is derived from it."""
        def boom(*a, **kw):
            raise RuntimeError("pantry exploded")
        monkeypatch.setattr(cook_sweep.cook_module, "consume_recipe", boom)
        row = _cook()
        result = cook_sweep.sweep(TODAY)
        assert result["failed"] == 1
        assert sl.get_cook(row["id"])["cooked_at"] is not None

    def test_several_due_cooks_are_all_swept(self, tmp_db, spent):
        _cook(recipe="Chili", date="2026-07-06")
        _cook(recipe="Tacos", date="2026-07-07")
        result = cook_sweep.sweep(TODAY)
        assert sorted(result["marked"]) == ["Chili", "Tacos"]
        assert result["consumed"] == 2

    def test_nothing_due_is_a_clean_no_op(self, tmp_db, spent):
        assert cook_sweep.sweep(TODAY) == {"marked": [], "consumed": 0, "failed": 0}
        assert spent == []
