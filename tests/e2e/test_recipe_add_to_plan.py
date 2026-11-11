"""A recipe added from its own page must land somewhere a human can see it.

"Add to this week" on /recipe/<name> used to POST a cook with no date and no
meal. The planner's grids only render cooks that have both, and the one place
that did list them — the Unscheduled tray — lived inside the Freezer tab. So
the button said "Added", and the recipe was nowhere on the planner. Three
real cooks piled up that way before anyone noticed.

The fix has two halves, and each is tested here:
  * the recipe page asks for a day and a meal, so the cook is *placed*;
  * any cook that still has no slot shows on the planner's default tab.

Also covers /meal-calendar, the read-only agenda list of a week's plan.
"""
from __future__ import annotations

from datetime import date

import pytest
import requests

from tests.e2e._weeks import unique_week

pytestmark = pytest.mark.e2e


def _a_recipe(live_server) -> str:
    resp = requests.get(live_server.url("/api/recipes"), timeout=60).json()
    recipes = resp if isinstance(resp, list) else resp["recipes"]
    return recipes[0]["name"]


def _iso_week(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def test_add_from_recipe_page_places_the_cook(live_server, page, page_errors):
    name = _a_recipe(live_server)
    page.goto(live_server.url(f"/recipe/{name}"), wait_until="networkidle")
    page.wait_for_selector("#add-day option", state="attached")

    # Pick the second day offered (tomorrow) and lunch, so the test proves
    # the choice is honoured rather than a default that happens to match.
    day_value = page.locator("#add-day option").nth(1).get_attribute("value")
    page.select_option("#add-day", day_value)
    page.select_option("#add-meal", "lunch")
    page.click("#add-week-btn")
    page.wait_for_selector("#add-week-status a")

    week = _iso_week(date.fromisoformat(day_value))
    board = requests.get(live_server.url(f"/api/week-board/{week}"), timeout=30).json()
    placed = [c for c in board["cooks"]
              if c["recipe"] == name and c["date"] == day_value and c["meal"] == "lunch"]
    assert placed, f"no cook for {name} on {day_value} lunch in {week}: {board['cooks']}"
    assert any(p["destination"] == "slot" and p["date"] == day_value and p["meal"] == "lunch"
               for p in placed[0]["placements"]), placed[0]
    assert page_errors == []


def test_unscheduled_cook_is_visible_on_the_default_tab(live_server, page, page_errors):
    week, _wed = unique_week(17)
    name = _a_recipe(live_server)
    resp = requests.post(live_server.url("/api/cooks"), json={
        "recipe": name, "week": week, "scale": 1, "servings_produced": 4,
    }, timeout=30)
    assert resp.status_code in (200, 201), resp.text

    page.goto(live_server.url(f"/meal-planner?week={week}"), wait_until="networkidle")
    section = page.locator("#unscheduled-section")
    section.wait_for(state="visible", timeout=10_000)
    assert name in section.inner_text()
    assert page_errors == []


def test_meal_calendar_lists_the_week(live_server, page, page_errors):
    week, wed = unique_week(18)
    name = _a_recipe(live_server)
    resp = requests.post(live_server.url("/api/cooks"), json={
        "recipe": name, "week": week, "scale": 1, "servings_produced": 4,
        "date": wed, "meal": "dinner", "initial_placement_count": 1,
    }, timeout=30)
    assert resp.status_code in (200, 201), resp.text

    page.goto(live_server.url(f"/meal-calendar?week={week}"), wait_until="networkidle")
    day = page.locator(f'.day[data-date="{wed}"]')
    day.wait_for(timeout=10_000)
    text = day.inner_text()
    assert name in text and "dinner" in text.lower(), text
    # The recipe links to its page.
    assert day.locator("a.recipe").first.get_attribute("href").startswith("/recipe/")
    assert page_errors == []


def test_home_links_to_meal_calendar(live_server, page, page_errors):
    page.goto(live_server.url("/"), wait_until="networkidle")
    assert page.locator('a[href="/meal-calendar"]').count() >= 1
    assert page_errors == []
