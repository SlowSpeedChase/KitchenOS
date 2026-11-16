"""The `/` dashboard, driven in a real browser against a throwaway vault and DB."""
from datetime import date, timedelta

import pytest
import requests
from playwright.sync_api import expect

from tests.e2e._weeks import unique_week

pytestmark = pytest.mark.e2e

IPAD = {"width": 1180, "height": 820}
RECIPE = "The Sexy Skillet Lasagna"


@pytest.fixture
def page_errors(page):
    """Console errors and uncaught exceptions, minus the one expected 404.

    A week with no saved shopping list answers 404, and the browser logs every
    failed fetch itself — the page cannot suppress that. It is matched by URL so
    a 404 for anything else (a missing script, a dead endpoint) still fails.
    """
    errors: list[str] = []

    def on_console(message):
        expected = "/api/shopping-list/saved/" in (message.location or {}).get("url", "")
        if message.type == "error" and not expected:
            errors.append(f"console: {message.text}")

    page.on("console", on_console)
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    return errors


def _cook(server, week, when, recipe=RECIPE):
    resp = requests.post(server.url("/api/cooks"), json={
        "recipe": recipe, "week": week, "scale": 1.0, "servings_produced": 8,
        "date": when, "meal": "dinner", "initial_placement_count": 1,
    }, timeout=30)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _open(page, server, week=None):
    """Open the dashboard on a week the test owns, or on the real current week."""
    page.set_viewport_size(IPAD)
    page.goto(server.url(f"/?week={week}" if week else "/"), wait_until="networkidle")


def test_week_lists_seven_days_with_the_planned_dinner(live_server, page, page_errors):
    week, wednesday = unique_week(20)
    _cook(live_server, week, wednesday)
    _open(page, live_server, week)
    expect(page.locator("#meals-body .day")).to_have_count(7)
    day = page.locator(f'#meals-body .day[data-date="{wednesday}"]')
    expect(day.locator("details.meal summary")).to_contain_text(RECIPE)
    expect(page.locator("#meals-body .open")).to_have_count(6)
    expect(page.locator("#meals-label")).not_to_contain_text("W")
    assert page_errors == []


def test_moving_a_meal_keeps_its_scale_and_never_uses_the_legacy_put(live_server, page, page_errors):
    week, wednesday = unique_week(21)
    cook = _cook(live_server, week, wednesday)
    friday = (date.fromisoformat(wednesday) + timedelta(days=2)).isoformat()
    puts = []
    page.on("request", lambda r: r.method == "PUT" and puts.append(r.url))
    _open(page, live_server, week)
    page.locator(f'.day[data-date="{wednesday}"] details.meal summary').click()
    page.locator(f'.day[data-date="{wednesday}"] select').select_option(friday)
    expect(page.locator(f'.day[data-date="{friday}"] details.meal')).to_have_count(1)
    expect(page.locator(f'.day[data-date="{wednesday}"] details.meal')).to_have_count(0)
    moved = requests.get(live_server.url(f"/api/cooks/{cook['id']}"), timeout=30).json()
    assert moved["date"] == friday
    assert moved["scale"] == cook["scale"]
    assert puts == []
    assert page_errors == []


def test_a_failed_meals_fetch_leaves_the_other_columns_alone(live_server, page):
    week, _ = unique_week(22)
    page.route("**/api/week-board/**", lambda route: route.fulfill(status=500, body="{}"))
    _open(page, live_server, week)
    expect(page.locator("#meals-body .note.bad")).to_be_visible()
    expect(page.locator("#meals-body button.act")).to_have_text("Try again")

def test_month_toggle_swaps_only_the_meals_column(live_server, page, page_errors):
    _open(page, live_server)
    page.locator("#view-month").click()
    expect(page.locator("#view-month")).to_have_attribute("aria-pressed", "true")
    expect(page.locator("#view-week")).to_have_attribute("aria-pressed", "false")
    cells = page.locator("#meals-body .month button.cell")
    expect(cells.first).to_be_visible()
    assert cells.count() in (28, 35, 42)
    expect(page.locator("#meals-body .month button.cell.today")).to_have_count(1)
    expect(page.locator("#buy-body")).to_be_visible()
    expect(page.locator("#hand-body")).to_be_visible()
    assert page_errors == []


def test_tapping_a_month_day_opens_that_week(live_server, page, page_errors):
    _open(page, live_server)
    page.locator("#view-month").click()
    page.locator("#meals-body .month button.cell.today").click()
    expect(page.locator("#view-week")).to_have_attribute("aria-pressed", "true")
    expect(page.locator("#meals-body .day.today")).to_have_count(1)
    expect(page.locator("#meals-label")).to_contain_text("This week")
    assert page_errors == []

def test_empty_week_offers_to_build_the_list(live_server, page, page_errors):
    week, wednesday = unique_week(25)
    _cook(live_server, week, wednesday)
    _open(page, live_server, week)
    build = page.locator("#buy-body button.act")
    expect(build).to_have_text("Build this week’s list")
    build.click()
    expect(page.locator("#buy-body .buy-row").first).to_be_visible()
    assert page_errors == []


def test_ticking_an_item_persists_across_reload(live_server, page, page_errors):
    week, wednesday = unique_week(26)
    _cook(live_server, week, wednesday)
    made = requests.post(live_server.url("/generate-shopping-list"), json={"week": week}, timeout=60)
    assert made.status_code == 200, made.text
    _open(page, live_server, week)
    first = page.locator("#buy-body .buy-row").first
    name = first.inner_text().strip()
    first.locator("input").check()
    expect(page.locator("#buy-body .buy-row.done")).to_have_count(1)
    page.reload(wait_until="networkidle")
    done = page.locator("#buy-body .buy-row.done")
    expect(done).to_have_count(1)
    expect(done).to_contain_text(name)
    expect(page.locator("#buy-body .buy-row").last).to_have_class("buy-row done")
    assert page_errors == []

def _inventory_fixture():
    soon = (date.today() + timedelta(days=2)).isoformat()
    gone = (date.today() - timedelta(days=1)).isoformat()

    def item(name, location, **extra):
        return {"name": name, "quantity": 1.0, "unit": "ct", "category": "other",
                "location": location, "source": "manual", "expires": None,
                "expiry_status": None, **extra}

    return [
        item("spinach", "fridge", expires=soon, expiry_status="soon"),
        item("yogurt", "fridge", expires=gone, expiry_status="expired"),
        item("eggs", "fridge", quantity=12.0),
        item("adobo", "freezer", quantity=2.0, unit="servings"),
        item("rice", "pantry"),
        item("kosher salt", "pantry", source="staple"),
    ]


def test_on_hand_leads_with_what_expires_and_folds_staples(live_server, page, page_errors):
    week, _ = unique_week(27)
    page.route("**/api/inventory", lambda route: route.fulfill(json=_inventory_fixture()))
    _open(page, live_server, week)
    groups = page.locator("#hand-body .grp").all_inner_texts()
    assert [g.lower() for g in groups] == ["use soon", "fridge", "freezer", "pantry"]
    soon = page.locator("#hand-body .grp.soon ~ .item").all_inner_texts()
    assert soon[0].lower().startswith("yogurt") and "expired" in soon[0].lower()
    assert soon[1].lower().startswith("spinach") and "2 days" in soon[1].lower()
    assert page.locator("#hand-body .item", has_text="spinach").count() == 1
    staples = page.locator("#hand-body details.staples")
    expect(staples.locator("summary")).to_have_text("Staples · 1")
    expect(staples.locator(".item")).to_be_hidden()
    expect(page.locator("#hand-body .item", has_text="eggs")).to_contain_text("12")
    assert page_errors == []

def test_a_command_refreshes_in_place_without_a_reload(live_server, page, page_errors):
    week, wednesday = unique_week(28)
    _open(page, live_server, week)
    page.evaluate("window.__stayed = true")
    _cook(live_server, week, wednesday)
    cancelled = page.evaluate(
        "() => !document.dispatchEvent(new CustomEvent('kitchenos:changed', {cancelable: true}))")
    assert cancelled, "the dashboard must preventDefault so the command bar does not reload the page"
    expect(page.locator(f'.day[data-date="{wednesday}"] details.meal')).to_have_count(1)
    assert page.evaluate("window.__stayed") is True
    assert page_errors == []


def test_landscape_ipad_shows_three_columns_without_page_scroll(live_server, page):
    week, _ = unique_week(29)
    _open(page, live_server, week)
    tops = page.evaluate("() => [...document.querySelectorAll('.col')].map(c => c.getBoundingClientRect().top)")
    assert len(set(round(t) for t in tops)) == 1, "columns are not side by side"
    assert page.evaluate("() => document.documentElement.scrollHeight <= window.innerHeight + 1")
    assert page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth + 1")


@pytest.mark.parametrize("viewport", [{"width": 820, "height": 1180}, {"width": 390, "height": 844}])
def test_narrow_screens_stack_in_reading_order(live_server, page, viewport):
    page.set_viewport_size(viewport)
    page.goto(live_server.url("/"), wait_until="networkidle")
    tops = page.evaluate("() => [...document.querySelectorAll('.col')].map(c => c.getBoundingClientRect().top)")
    assert tops == sorted(tops) and len(set(round(t) for t in tops)) == 3
    assert page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth + 1")


def test_controls_are_thumb_sized(live_server, page):
    week, _ = unique_week(30)
    _open(page, live_server, week)
    heights = page.evaluate(
        "() => [...document.querySelectorAll('.seg button, .menu-btn, .nav-btn')]"
        ".map(b => b.getBoundingClientRect().height)")
    assert heights and min(heights) >= 44


def test_all_pages_popover_opens_and_light_dismisses(live_server, page, page_errors):
    week, _ = unique_week(31)
    _open(page, live_server, week)
    page.locator(".menu-btn").click()
    expect(page.locator("#all-pages")).to_be_visible()
    expect(page.locator('#all-pages a[href="/meal-planner"]')).to_be_visible()
    page.mouse.click(10, 400)
    expect(page.locator("#all-pages")).to_be_hidden()
    assert page_errors == []
