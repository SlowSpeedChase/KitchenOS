"""Tests for the /plan-week command center."""

from datetime import date

from lib import plan_week

T = {"calories": 2300, "protein": 190, "carbs": 228, "fat": 70}


def _slots(**kw):
    return {m: kw.get(m, []) for m in ("breakfast", "lunch", "snack", "dinner")}


def _r(name):
    return {"name": name, "kind": "recipe", "servings": 1}


class TestWeekMath:
    def test_shift_week_roundtrips(self):
        assert plan_week.shift_week(plan_week.shift_week("2026-W31", 1), -1) == "2026-W31"

    def test_shift_week_crosses_year(self):
        # W01 minus one lands in the prior year's last week.
        prev = plan_week.shift_week("2026-W01", -1)
        assert prev.startswith("2025-W5")  # W52 or W53

    def test_default_week_is_next_week(self):
        # 2026-07-30 is a Thursday in W31; +7 days → W32.
        assert plan_week.default_week(date(2026, 7, 30)) == "2026-W32"


class TestRenderPlanCenter:
    def _packet(self):
        return {
            "week": "2026-W32", "targets": T,
            "days": [
                {"day": "Monday", "date": "2026-08-03",
                 "slots": _slots(breakfast=[_r("Oats")], dinner=[_r("Beef Bowl")]),
                 "macros": {"calories": 2180, "protein": 184, "carbs": 210, "fat": 66},
                 "incomplete": False},
                {"day": "Tuesday", "date": "2026-08-04",
                 "slots": _slots(), "macros": None, "incomplete": False},
            ],
        }

    def test_planned_week_shows_status_and_actions(self):
        html = plan_week.render_plan_center_html(
            "2026-W32", self._packet(), T, "https://ko.example", "2026-W31", "2026-W33")
        assert "Plan your week" in html
        # three actions, each linking to the right surface for the week
        assert "https://ko.example/meal-planner?week=2026-W32" in html
        assert "https://ko.example/nutrition-review" in html
        assert "https://ko.example/print/week?week=2026-W32" in html
        # per-day status: protein vs target + prev/next nav
        assert "184/190g protein" in html
        assert "plan-week?week=2026-W31" in html and "plan-week?week=2026-W33" in html

    def test_empty_week_shows_start_hint(self):
        html = plan_week.render_plan_center_html(
            "2026-W40", None, T, "", "2026-W39", "2026-W41")
        assert "empty" in html.lower()
        assert "meal-planner?week=2026-W40" in html  # still offers the fill action
