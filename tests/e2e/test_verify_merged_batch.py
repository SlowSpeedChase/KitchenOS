"""Verification of the 2026-07-31 merged batch (#60 meal macros, #64 week ranges).

Written to check the four things that had never been exercised outside a
container: a fractional sub-recipe surviving a save/reopen round trip, the live
macro readout and its per-slot target line, a meal on a legacy week counting
toward `macro_context.current`, and week-scoped surfaces reading as date ranges.
"""
from __future__ import annotations

import re

import pytest

pytestmark = pytest.mark.e2e

WEEK_ID_RE = re.compile(r"\b20\d\d-W\d\d\b")
WEEK_NUM_RE = re.compile(r"\bWeek\s+\d\d?\b")


def _open_planner(page, live_server):
    page.goto(live_server.url("/meal-planner"), wait_until="domcontentloaded")
    page.wait_for_selector(".recipe-card")


def _eligible_recipe(page):
    """Pick a macro-eligible recipe out of the page's own data."""
    return page.evaluate("""() => {
        const r = allRecipes.find(r => r.nutrition_calories != null
            && Number(r.nutrition_coverage) >= 0.8
            && r.servings != null && Number(r.servings) > 0);
        return r ? {name: r.name, cal: r.nutrition_calories,
                    protein: r.nutrition_protein} : null;
    }""")


class TestFractionalSubRecipe:
    def test_live_readout_scales_by_1_5_and_shows_a_slot_target(
            self, live_server, page, page_errors):
        _open_planner(page, live_server)
        recipe = _eligible_recipe(page)
        assert recipe, "no macro-eligible recipe in the corpus to test with"

        page.click("#tab-meals")
        page.click("#new-meal-btn")
        page.wait_for_selector("#meal-modal.visible")
        page.fill("#meal-name", "E2E Fractional Check")
        page.select_option("#meal-slot", "lunch")

        row = page.locator(".sub-recipe-row").first
        row.locator("select").select_option(recipe["name"])
        row.locator("input").fill("1.5")
        row.locator("input").dispatch_event("input")

        # The row states its own scaled contribution.
        contribution = row.locator(".sub-contribution").inner_text()
        assert f"{round(recipe['cal'] * 1.5)} kcal" in contribution, contribution

        # The totals line compares against a per-slot reference, not the day total.
        totals = page.locator("#meal-macro-readout .macro-totals").inner_text()
        assert "/" in totals, f"no target reference in readout: {totals!r}"
        shown = int(re.search(r"(\d+)\s*/", totals).group(1))
        assert shown == round(recipe["cal"] * 1.5), totals

        lunch_share = page.evaluate(
            "() => macroTargets.slot_shares.lunch * macroTargets.daily.calories")
        reference = int(re.search(r"/\s*(\d+)", totals).group(1))
        assert reference == round(lunch_share), (reference, lunch_share)
        assert page_errors == []

    def test_1_5_survives_save_and_reopen(self, live_server, page, page_errors):
        _open_planner(page, live_server)
        recipe = _eligible_recipe(page)
        page.click("#tab-meals")
        page.click("#new-meal-btn")
        page.wait_for_selector("#meal-modal.visible")
        page.fill("#meal-name", "E2E Roundtrip Meal")
        page.select_option("#meal-slot", "lunch")
        row = page.locator(".sub-recipe-row").first
        row.locator("select").select_option(recipe["name"])
        row.locator("input").fill("1.5")
        row.locator("input").dispatch_event("input")
        page.click("#meal-modal-save")
        page.wait_for_selector("#meal-modal.visible", state="hidden")

        # Reload from the server, not from in-memory state.
        _open_planner(page, live_server)
        page.click("#tab-meals")
        page.wait_for_selector(".meal-edit-btn")
        stored = page.evaluate(
            "() => mealsByName['E2E Roundtrip Meal'].sub_recipes[0].servings")
        assert stored == 1.5, f"servings came back as {stored!r}, not 1.5"

        page.locator(".meal-edit-btn").first.click()
        page.wait_for_selector("#meal-modal.visible")
        value = page.locator(".sub-recipe-row").first.locator("input").input_value()
        assert float(value) == 1.5, f"reopened editor shows {value!r}"
        assert page_errors == []


class TestLegacyWeekCountsAPlannedMeal:
    """#60: a planned `[[Meal: X]]` used to contribute zero to the day's macros."""

    LEGACY_WEEK = "2026-W26"  # header still reads "Week 26 (Jun 22 - Jun 28, 2026)"

    def test_macro_context_current_counts_a_meal_on_a_legacy_week(
            self, live_server, page):
        import requests

        # A macro-eligible recipe, read from the server's own recipe index.
        recipes = requests.get(live_server.url("/api/recipes"), timeout=30).json()
        recipes = recipes if isinstance(recipes, list) else recipes["recipes"]
        pick = next(r for r in recipes
                    if r.get("nutrition_calories")
                    and (r.get("nutrition_coverage") or 0) >= 0.8
                    and r.get("servings"))

        created = requests.post(
            live_server.url("/api/meals"),
            json={"name": "E2E Legacy Week Meal", "description": "", "tags": [],
                  "slot": "lunch",
                  "sub_recipes": [{"recipe": pick["name"], "servings": 1.5}]},
            timeout=30)
        assert created.status_code in (200, 201), created.text

        # Put it on a legacy week, on a day whose other slots are empty so
        # `current` is attributable to this meal alone.
        plan = requests.get(
            live_server.url(f"/api/meal-plan/{self.LEGACY_WEEK}"), timeout=30).json()
        target_day = next(
            d for d in plan["days"]
            if not any(d.get(s) for s in ("breakfast", "lunch", "snack", "dinner")))
        for slot in ("breakfast", "lunch", "snack", "dinner"):
            target_day[slot] = None
        target_day["lunch"] = {"name": "E2E Legacy Week Meal",
                               "servings": 1, "kind": "meal"}
        put = requests.put(live_server.url(f"/api/meal-plan/{self.LEGACY_WEEK}"),
                           json=plan, timeout=30)
        assert put.status_code == 200, put.text

        got = requests.post(
            live_server.url("/api/suggest-meal"),
            json={"week": self.LEGACY_WEEK, "day": target_day["day"],
                  "meal": "dinner"},
            timeout=60).json()

        ctx = got.get("macro_context")
        assert ctx, f"no macro_context in response: {got}"
        expected = pick["nutrition_calories"] * 1.5
        assert ctx["current"]["calories"] > 0, (
            "a planned meal still counts as zero calories: "
            f"current={ctx['current']}")
        assert abs(ctx["current"]["calories"] - expected) < max(2.0, expected * 0.02), (
            f"current {ctx['current']['calories']} != expected {expected} "
            f"({pick['name']} @ 1.5)")


class TestShoppingListCreditsInventory:
    def test_already_have_section_names_what_it_credited(self, live_server):
        import requests

        weeks = ["2026-W26", "2026-W30", "2026-W31"]
        for week in weeks:
            resp = requests.post(live_server.url("/generate-shopping-list"),
                                 json={"week": week}, timeout=120)
            if resp.status_code != 200 or not resp.json().get("success"):
                continue
            note = requests.get(
                live_server.url(f"/current/shopping-list?week={week}"), timeout=30).text
            if "Already have" in note:
                # Credited notes must be plain bullets: a `- [ ]` here comes back
                # as a phantom manual item on the next regeneration.
                section = note.split("Already have", 1)[1].split("---")[0]
                print(f"\n[{week}] Already have:\n{section.strip()[:600]}")
                assert "[ ]" not in section, (
                    "checkbox inside the Already have section")
                assert re.search(r"\w", section), "Already have section is empty"
                return
        pytest.skip("no week credited anything from inventory to assert on")


class TestWeekSurfacesReadAsDateRanges:
    """#64: a week id is a key, never a label."""

    def test_planner_header_shows_a_range_not_an_id(
            self, live_server, page, page_errors):
        _open_planner(page, live_server)
        header = page.locator("#week-label, .week-label, header").first.inner_text()
        assert not WEEK_ID_RE.search(header), f"raw week id on planner header: {header!r}"
        assert not WEEK_NUM_RE.search(header), f"'Week N' on planner header: {header!r}"
        assert page_errors == []

    def test_plan_week_nav_shows_ranges(self, live_server, page, page_errors):
        page.goto(live_server.url("/plan-week"), wait_until="domcontentloaded")
        body = page.locator("body").inner_text()
        assert not WEEK_ID_RE.search(body), (
            "raw week id rendered at the user on /plan-week: "
            f"{WEEK_ID_RE.findall(body)[:5]}")
        assert not WEEK_NUM_RE.search(body), (
            f"'Week N' on /plan-week: {WEEK_NUM_RE.findall(body)[:5]}")
        assert page_errors == []
