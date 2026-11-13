"""The tell-it bar, driven in a real browser against a throwaway server.

These cover what unit tests can't: the button is on the page, the sheet draws
each status, Undo really reverses, and the planner refreshes without a reload.
The server runs with KITCHENOS_NO_LLM=1 on copies of the vault and DB, so every
write here is throwaway — but tests still delete what they create, because the
server is shared by the whole e2e session.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from urllib.parse import quote

import pytest
import requests
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e


def _iso_week(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def _next(weekday: int) -> date:
    """Next occurrence of weekday (Mon=0) starting today — the engine's rule."""
    today = date.today()
    return today + timedelta(days=(weekday - today.weekday()) % 7)


def _board(live_server, week: str) -> list[dict]:
    return requests.get(live_server.url(f"/api/week-board/{week}"), timeout=30).json()["cooks"]


def _cooks(live_server, recipe, day):
    return [c for c in _board(live_server, _iso_week(day))
            if c["recipe"] == recipe and c.get("date") == day.isoformat()]


def _a_recipe(live_server) -> str:
    """A recipe the engine will resolve by name without asking anything.

    The copied DB is real data, so the first recipe may already be planned —
    and "put this on Wednesday" for a planned recipe is a plan-or-move ask,
    not a done. Pick one that isn't planned in the weeks the engine loads, and
    whose name is plain words no other recipe name contains.
    """
    resp = requests.get(live_server.url("/api/recipes"), timeout=60).json()
    names = [r["name"] for r in (resp if isinstance(resp, list) else resp["recipes"])]
    today = date.today()
    planned = {c["recipe"]
               for d in (today, today + timedelta(days=7))
               for c in _board(live_server, _iso_week(d))}
    lowered = [n.lower() for n in names]
    for name in names:
        low = name.lower()
        if name in planned or not re.fullmatch(r"[A-Za-z]+( [A-Za-z]+){1,3}", name):
            continue
        if sum(low in other for other in lowered) == 1:
            return name
    pytest.skip("no unplanned, unambiguous recipe in the corpus copy")


def _tell(page, text):
    page.click("#ko-tell-button")
    expect(page.locator("#ko-tell-sheet")).to_be_visible()
    page.fill("#ko-tell-input", text)
    page.click("#ko-tell-send")


def test_plan_from_recipe_page_then_undo(live_server, page, page_errors):
    name = _a_recipe(live_server)
    wednesday = _next(2)
    page.goto(live_server.url(f"/recipe/{quote(name)}"), wait_until="networkidle")
    _tell(page, "put this on wednesday")
    page.wait_for_selector("#ko-tell-undo")
    assert wednesday.strftime("%a") in page.inner_text("#ko-tell-result")
    assert _cooks(live_server, name, wednesday)

    # The recipe page has no in-place refresh, so the reload waits for close:
    # Undo must still be on screen and must still work.
    page.click("#ko-tell-undo")
    expect(page.locator("#ko-tell-result")).to_contain_text("Undone.")
    assert not _cooks(live_server, name, wednesday)
    with page.expect_navigation():
        page.click("#ko-tell-close")
    assert page_errors == []


def test_undo_on_the_planner_reverses_without_reload(live_server, page, page_errors):
    name = _a_recipe(live_server)
    friday = _next(4)
    page.goto(live_server.url(f"/meal-planner?week={_iso_week(friday)}"), wait_until="networkidle")
    page.evaluate("window.__noReload = true")
    _tell(page, f"put {name} on friday")
    page.wait_for_selector("#ko-tell-undo")
    assert page.evaluate("window.__noReload") is True, "planner reloaded instead of refetching"
    assert _cooks(live_server, name, friday)

    page.click("#ko-tell-undo")
    expect(page.locator("#ko-tell-result")).to_contain_text("Undone.")
    assert page.evaluate("window.__noReload") is True, "planner reloaded on undo"
    assert not _cooks(live_server, name, friday)
    assert page_errors == []


def test_ambiguous_recipe_asks_with_buttons(live_server, page, page_errors):
    saturday = _next(5)

    def caldos():
        return sorted(c["id"] for c in _board(live_server, _iso_week(saturday))
                      if c["recipe"].startswith("Chicken Caldo")
                      and c.get("date") == saturday.isoformat())

    before = caldos()
    page.goto(live_server.url("/"), wait_until="networkidle")
    _tell(page, "put chicken caldo on saturday")
    page.wait_for_selector(".ko-tell-option")
    labels = page.locator(".ko-tell-option").all_inner_texts()
    assert len(labels) >= 2
    page.locator(".ko-tell-option").first.click()
    page.wait_for_selector("#ko-tell-undo")
    assert len(caldos()) == len(before) + 1
    page.click("#ko-tell-undo")
    expect(page.locator("#ko-tell-result")).to_contain_text("Undone.")
    assert caldos() == before
    assert page_errors == []


def test_remove_asks_first_and_cancel_keeps_the_cook(live_server, page, page_errors):
    name = _a_recipe(live_server)
    sunday = _next(6)
    resp = requests.post(live_server.url("/api/cooks"), timeout=30, json={
        "recipe": name, "week": _iso_week(sunday), "date": sunday.isoformat(), "meal": "dinner",
        "servings_produced": 4})
    assert resp.status_code in (200, 201), resp.text
    cook_id = resp.json()["id"]
    try:
        page.goto(live_server.url(f"/recipe/{quote(name)}"), wait_until="networkidle")
        _tell(page, "take this off sunday")
        page.wait_for_selector("#ko-tell-confirm")
        page.click("#ko-tell-cancel")
        expect(page.locator("#ko-tell-sheet")).to_be_hidden()
        assert _cooks(live_server, name, sunday)
    finally:
        requests.delete(live_server.url(f"/api/cooks/{cook_id}"), timeout=30)
    assert page_errors == []


def test_escape_closes_the_sheet_and_returns_focus(live_server, page, page_errors):
    page.goto(live_server.url("/"), wait_until="networkidle")
    _tell(page, "zzzz qqqq")
    # A sentence it can't use draws a reason, keeps the sheet open, changes nothing.
    expect(page.locator("#ko-tell-result p")).not_to_be_empty()
    expect(page.locator("#ko-tell-undo")).to_have_count(0)
    expect(page.locator("#ko-tell-sheet")).to_be_visible()

    page.keyboard.press("Escape")
    expect(page.locator("#ko-tell-sheet")).to_be_hidden()
    expect(page.locator("#ko-tell-button")).to_be_focused()
    expect(page.locator("#ko-tell-button")).to_have_attribute("aria-expanded", "false")
    assert page_errors == []


def test_open_the_planner_navigates(live_server, page, page_errors):
    page.goto(live_server.url("/"), wait_until="networkidle")
    _tell(page, "open the planner")
    page.wait_for_url("**/meal-planner*")
    assert page_errors == []


def test_print_page_has_no_button(live_server, page):
    page.goto(live_server.url("/print/week"), wait_until="networkidle")
    assert page.locator("#ko-tell-button").count() == 0
