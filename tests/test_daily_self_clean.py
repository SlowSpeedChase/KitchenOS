"""The daily inventory self-clean actually runs daily, and /system-health
measures the threshold it promises.

`com.kitchenos.mealplan` runs generate_meal_plan.py every morning, but the
prune + view refresh sat after the "File already exists" early return — so it
ran once a week, and the health check (which counted *any* expired row, grace
window included) could not have passed even on the mornings it did run.
"""
from __future__ import annotations

import sys
from datetime import date, timedelta

from lib import health_assertions as ha
from lib.inventory import InventoryItem, add_items, read_inventory


def _expired(name, days_ago):
    return InventoryItem(name=name, quantity=1, unit="ct", category="dairy",
                         location="fridge",
                         expires=(date.today() - timedelta(days=days_ago)).isoformat())


class TestExpiryPruningCheck:
    def test_rows_inside_the_grace_window_are_ok(self, tmp_db, tmp_vault):
        add_items([_expired("Yogurt", 1), _expired("Milk", 3)])   # grace is 3 days
        assert ha.check_expiry_pruning()["status"] == ha.OK

    def test_a_row_past_the_grace_window_is_failing_and_names_the_count(
            self, tmp_db, tmp_vault):
        add_items([_expired("Yogurt", 1), _expired("Ricotta", 10)])
        c = ha.check_expiry_pruning()
        assert c["status"] == ha.FAILING
        assert c["detail"].startswith("1 row(s)"), c["detail"]
        assert "generate_meal_plan" in c["fix"] and "mealplan" in c["fix"]

    def test_empty_inventory_is_ok(self, tmp_db, tmp_vault):
        assert ha.check_expiry_pruning()["status"] == ha.OK


class TestRefreshInventoryViews:
    def test_prunes_overdue_rows_and_rewrites_both_views(self, tmp_db, tmp_vault):
        import generate_meal_plan as gmp
        (tmp_vault / "Recipes").mkdir()     # the views index the recipe library
        add_items([_expired("Yogurt", 1), _expired("Ricotta", 10)])
        out = gmp.refresh_inventory_views()
        assert out["pruned"] == 1
        assert {it.name for it in read_inventory()} == {"Yogurt"}
        assert out["views"] == ["Use It Up.md", "Cook Now.md"]
        assert (tmp_vault / "Use It Up.md").exists()
        assert (tmp_vault / "Cook Now.md").exists()
        # ...and the health check agrees the kitchen is clean afterwards.
        assert ha.check_expiry_pruning()["status"] == ha.OK

    def test_main_runs_the_self_clean_even_when_the_plan_file_exists(
            self, tmp_db, tmp_vault, tmp_path, monkeypatch):
        """The defect: six mornings a week the plan exists and main() returned
        before the self-clean. Now it runs first."""
        import generate_meal_plan as gmp
        plans = tmp_path / "Meal Plans"
        plans.mkdir()
        (plans / gmp.generate_filename(2030, 20)).write_text("# existing\n")
        monkeypatch.setattr(gmp, "MEAL_PLANS_PATH", plans)
        calls = []
        monkeypatch.setattr(gmp, "refresh_inventory_views", lambda: calls.append(1))
        monkeypatch.setattr(sys, "argv", ["generate_meal_plan.py", "--week", "2030-W20"])
        gmp.main()
        assert calls == [1], "self-clean skipped because the week file already existed"
        assert (plans / gmp.generate_filename(2030, 20)).read_text() == "# existing\n"

    def test_dry_run_does_not_self_clean(self, tmp_db, tmp_vault, tmp_path, monkeypatch):
        import generate_meal_plan as gmp
        monkeypatch.setattr(gmp, "MEAL_PLANS_PATH", tmp_path)
        calls = []
        monkeypatch.setattr(gmp, "refresh_inventory_views", lambda: calls.append(1))
        monkeypatch.setattr(sys, "argv", ["generate_meal_plan.py", "--week", "2030-W21", "--dry-run"])
        gmp.main()
        assert calls == [], "a dry run must not write to inventory"
