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
    expect(day.locator("button.meal")).to_contain_text(RECIPE)
    expect(page.locator("#meals-body button.open")).to_have_count(7)
    expect(page.locator("#meals-label")).not_to_contain_text("W")
    assert page_errors == []


def test_moving_a_meal_keeps_its_scale_and_never_uses_the_legacy_put(live_server, page, page_errors):
    week, wednesday = unique_week(21)
    cook = _cook(live_server, week, wednesday)
    friday = (date.fromisoformat(wednesday) + timedelta(days=2)).isoformat()
    puts = []
    page.on("request", lambda r: r.method == "PUT" and puts.append(r.url))
    _open(page, live_server, week)
    page.locator(f'.day[data-date="{wednesday}"] button.meal').click()
    expect(page.locator("#meal-body h2")).to_have_text(RECIPE)
    page.locator("#meal-body select").select_option(friday)
    expect(page.locator(f'.day[data-date="{friday}"] button.meal')).to_have_count(1)
    expect(page.locator(f'.day[data-date="{wednesday}"] button.meal')).to_have_count(0)
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
    page.locator("#buy-label").click()
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
    page.locator("#buy-label").click()
    first = page.locator("#buy-body .buy-row").first
    name = first.inner_text().strip()
    first.locator("input").check()
    expect(page.locator("#buy-body .buy-row.done")).to_have_count(1)
    page.reload(wait_until="networkidle")
    expect(page.locator("#buy-label")).to_contain_text("To buy · ")
    page.locator("#buy-label").click()
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
    page.route("**/api/use-it-up**", lambda route: route.fulfill(json={"at_risk": []}))
    _open(page, live_server, week)
    expect(page.locator("#hand-label")).to_have_text("On hand · 2 use soon")
    page.locator("#hand-label").click()
    groups = page.locator("#hand-body .grp").all_inner_texts()
    assert [g.lower() for g in groups] == ["use soon", "fridge", "freezer", "pantry"]
    soon = page.locator("#hand-body .soon-item > .item").all_inner_texts()
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
    expect(page.locator(f'.day[data-date="{wednesday}"] button.meal')).to_have_count(1)
    assert page.evaluate("window.__stayed") is True
    assert page_errors == []


def test_landscape_ipad_is_one_full_page_calendar(live_server, page):
    week, _ = unique_week(29)
    _open(page, live_server, week)
    boxes = page.evaluate(
        "() => [...document.querySelectorAll('.week .day')].map(d => d.getBoundingClientRect().toJSON())")
    assert len(boxes) == 7 and len({round(b["top"]) for b in boxes}) == 1, "days are not side by side"
    assert boxes[-1]["right"] - boxes[0]["left"] > IPAD["width"] * 0.9, "the calendar does not span the page"
    assert min(b["height"] for b in boxes) > IPAD["height"] * 0.5, "the calendar does not fill the page"
    assert page.evaluate("() => document.documentElement.scrollHeight <= window.innerHeight + 1")
    assert page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth + 1")


@pytest.mark.parametrize("viewport", [{"width": 820, "height": 1180}, {"width": 390, "height": 844}])
def test_narrow_screens_stack_the_days(live_server, page, viewport):
    page.set_viewport_size(viewport)
    page.goto(live_server.url("/"), wait_until="networkidle")
    tops = page.evaluate("() => [...document.querySelectorAll('.week .day')].map(d => d.getBoundingClientRect().top)")
    assert tops == sorted(tops) and len({round(t) for t in tops}) == 7
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
    page.locator('[popovertarget="all-pages"]').click()
    expect(page.locator("#all-pages")).to_be_visible()
    expect(page.locator('#all-pages a[href="/meal-planner"]')).to_be_visible()
    page.mouse.click(10, 400)
    expect(page.locator("#all-pages")).to_be_hidden()
    assert page_errors == []


def test_dragging_a_meal_to_another_day_moves_the_cook(live_server, page, page_errors):
    week, wednesday = unique_week(32)
    cook = _cook(live_server, week, wednesday)
    friday = (date.fromisoformat(wednesday) + timedelta(days=2)).isoformat()
    puts = []
    page.on("request", lambda r: r.method == "PUT" and puts.append(r.url))
    _open(page, live_server, week)
    source = page.locator(f'.day[data-date="{wednesday}"] button.meal').bounding_box()
    target = page.locator(f'.day[data-date="{friday}"] .slots').bounding_box()
    # Sortable listens for pointer events; Playwright's drag_to() does not produce them.
    page.mouse.move(source["x"] + source["width"] / 2, source["y"] + 12)
    page.mouse.down()
    page.mouse.move(target["x"] + target["width"] / 2, target["y"] + 20, steps=12)
    page.mouse.move(target["x"] + target["width"] / 2, target["y"] + 24, steps=4)
    page.mouse.up()
    expect(page.locator(f'.day[data-date="{friday}"] button.meal')).to_have_count(1)
    moved = requests.get(live_server.url(f"/api/cooks/{cook['id']}"), timeout=30).json()
    assert moved["date"] == friday and moved["scale"] == cook["scale"]
    assert puts == []
    assert page_errors == []


def test_add_meal_on_an_empty_day_plans_from_could_make(live_server, page, page_errors):
    week, wednesday = unique_week(33)
    page.route("**/api/cook-now**", lambda route: route.fulfill(json={"recipes": [
        {"recipe": RECIPE, "meal_tier": "meal", "score": 0.9, "have": 9, "total": 10,
         "minutes": 45, "at_risk": True, "servings": 8, "group": "Mains"},
        {"recipe": "Some Dessert", "meal_tier": "dessert", "score": 0.99, "have": 3, "total": 3,
         "minutes": 10, "at_risk": False, "servings": 4, "group": "Desserts"},
        {"recipe": "Some Porridge", "meal_tier": "meal", "score": 0.5, "have": 2, "total": 3,
         "minutes": 5, "at_risk": False, "servings": 2, "group": "Breakfast"},
    ]}))
    _open(page, live_server, week)
    page.locator(f'.day[data-date="{wednesday}"] button.open').click()
    expect(page.locator("#cook-pop")).to_be_visible()
    expect(page.locator("#cook-day")).to_have_value(wednesday)
    expect(page.locator("#cook-body .make")).to_have_count(3)
    assert page.locator("#cook-body .grp").all_inner_texts() == ["MAINS", "BREAKFAST", "DESSERTS"]
    rows = page.locator("#cook-body .make").first
    expect(rows).to_contain_text("Have 9 of 10")
    expect(rows).to_contain_text("uses what expires")
    rows.get_by_role("button", name=f"Add {RECIPE}").click()
    expect(page.locator("#cook-pop")).to_be_hidden()
    expect(page.locator(f'.day[data-date="{wednesday}"] button.meal')).to_contain_text(RECIPE)
    assert page_errors == []


def _use_soon_routes(page, state):
    """Inventory with one expiring item, backed by a tiny in-test store so the
    page's own action buttons can be watched changing it."""
    soon = (date.today() + timedelta(days=1)).isoformat()

    def inventory(route):
        items = [] if state.get("gone") else [{
            "name": "spinach", "quantity": 1.0, "unit": "ct", "category": "produce",
            "location": "freezer" if state.get("frozen") else "fridge", "source": "manual",
            "expires": None if state.get("frozen") else soon,
            "expiry_status": None if state.get("frozen") else "soon"}]
        route.fulfill(json=items)

    def action(route):
        verb = route.request.url.rsplit("/", 1)[-1]
        state.setdefault("calls", []).append((verb, route.request.post_data_json))
        state["gone" if verb == "remove" else "frozen"] = True
        route.fulfill(json={"status": "ok"})

    page.route("**/api/inventory", inventory)
    page.route("**/api/inventory/remove", action)
    page.route("**/api/inventory/freeze", action)
    page.route("**/api/use-it-up**", lambda route: route.fulfill(json={"at_risk": [{
        "name": "spinach", "recipes": [{"recipe": RECIPE, "display_name": "Skillet Lasagna",
                                        "have": 9, "total": 10, "missing": ["ricotta"]}]}]}))


def test_use_soon_strip_opens_the_panel_on_that_item(live_server, page, page_errors):
    week, _ = unique_week(34)
    _use_soon_routes(page, {})
    _open(page, live_server, week)
    chip = page.locator("#soon-strip .chip")
    expect(chip).to_have_count(1)
    expect(chip).to_contain_text("spinach")
    expect(chip).to_contain_text("1 day")
    chip.click()
    row = page.locator("#hand-body .soon-item")
    expect(row).to_be_visible()
    expect(row.locator(".make")).to_contain_text("Skillet Lasagna")
    expect(row.locator(".make")).to_contain_text("Need 1 more: ricotta")
    expect(page.locator('#hand-body a[href="/review"]').first).to_be_visible()
    assert page_errors == []


def test_used_it_up_removes_the_item_and_clears_the_strip(live_server, page, page_errors):
    week, _ = unique_week(35)
    state = {}
    _use_soon_routes(page, state)
    _open(page, live_server, week)
    page.locator("#soon-strip .chip").click()
    page.get_by_role("button", name="Used it up").click()
    expect(page.locator("#hand-body .soon-item")).to_have_count(0)
    expect(page.locator("#soon-strip")).to_be_hidden()
    assert state["calls"] == [("remove", {"name": "spinach", "location": "fridge"})]
    assert page_errors == []


def test_freeze_it_moves_the_item_out_of_use_soon(live_server, page, page_errors):
    week, _ = unique_week(36)
    state = {}
    _use_soon_routes(page, state)
    _open(page, live_server, week)
    page.locator("#soon-strip .chip").click()
    page.get_by_role("button", name="Freeze it").click()
    expect(page.locator("#hand-body .soon-item")).to_have_count(0)
    expect(page.locator("#hand-body .grp", has_text="freezer")).to_be_visible()
    assert state["calls"][0][0] == "freeze"
    assert page_errors == []


def test_cook_today_plans_the_recipe_for_tonight(live_server, page, page_errors):
    _use_soon_routes(page, {})
    _open(page, live_server)
    before = page.locator(".day.today button.meal").count()
    page.locator("#soon-strip .chip").click()
    page.get_by_role("button", name=f"Cook {RECIPE} today").click()
    expect(page.locator(".day.today button.meal")).to_have_count(before + 1)
    assert page_errors == []


def test_meal_panel_removes_a_meal_from_the_plan(live_server, page, page_errors):
    week, wednesday = unique_week(37)
    cook = _cook(live_server, week, wednesday)
    _open(page, live_server, week)
    page.locator(f'.day[data-date="{wednesday}"] button.meal').click()
    panel = page.locator("#meal-pop")
    expect(panel).to_be_visible()
    expect(panel.get_by_role("link", name="Open recipe")).to_be_visible()
    panel.get_by_role("button", name="Remove from plan").click()
    expect(panel).to_be_hidden()
    expect(page.locator(f'.day[data-date="{wednesday}"] button.meal')).to_have_count(0)
    assert requests.get(live_server.url(f"/api/cooks/{cook['id']}"), timeout=30).status_code == 404
    assert page_errors == []


def test_meal_panel_marks_a_meal_cooked(live_server, page, page_errors):
    week, wednesday = unique_week(38)
    cook = _cook(live_server, week, wednesday)
    _open(page, live_server, week)
    page.locator(f'.day[data-date="{wednesday}"] button.meal').click()
    page.locator("#meal-pop").get_by_role("button", name="Cooked it").click()
    expect(page.locator(f'.day[data-date="{wednesday}"] button.meal.cooked')).to_have_count(1)
    assert requests.get(live_server.url(f"/api/cooks/{cook['id']}"), timeout=30).json()["cooked_at"]
    assert page_errors == []
