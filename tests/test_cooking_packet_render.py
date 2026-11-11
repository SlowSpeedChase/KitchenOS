"""Rendering contracts, hostile text boundaries, and real browser editing flows."""
from copy import deepcopy
from pathlib import Path
import json

from bs4 import BeautifulSoup
import pytest
from flask import Flask, render_template

from lib.cooking_packet_render import render_print_packet

ROOT = Path(__file__).resolve().parents[1]
HOSTILE = '\"><script>alert(1)</script><img src=x onerror=alert(2)> & hostile'


def packet_fixture():
    return {
        "version": 1, "week": "2026-W40", "revision": 4, "status": "draft",
        "date_range": {"start": "2026-09-27", "end": "2026-10-04"},
        "generated_at": "2026-09-26T14:00:00Z", "store_refreshed_at": None,
        "cooks": [{"id": 58, "cook_id": 58, "recipe": "Bean soup", "meal": "dinner", "placements": [{"count": 1}]}],
        "production_schedule": [
            {"item_id": "schedule:cook:58", "cook_id": 58, "recipe": "Bean soup", "source": "cook_schedule",
             "date": "2026-09-29", "meal": "dinner", "start": "2026-09-29T18:00:00-05:00",
             "timezone": "America/Chicago", "duration_minutes": 60, "duration_source": "cook_schedule", "done": False},
            {"item_id": "schedule:prep", "text": "Soak beans", "source": "packet", "date": "2026-09-27", "duration_minutes": 15, "done": False}],
        "pull_list": [{"item_id": "pull:1", "item": "beans", "amount": 2, "unit": "cup", "location": "garage",
                       "location_uncertain": True, "inventory_amount": 2, "inventory_unit": "cup", "done": False,
                       "line_id": "requirement:beans", "credit_id": "credit:beans", "source_ingredient_ids": ["ingredient:1"]}],
        "shared_prep": [{"item_id": "shared:1", "text": "Drain cooked beans", "amount": 2, "unit": "cup", "recipes": ["Bean soup"], "done": False}],
        "recipe_cards": [{"item_id": "recipe:1", "recipe": "Bean soup", "display_name": "Bean soup", "scale": 1.5,
                          "source_url": "https://example.org/recipe?a=1&b=2", "ingredients": [{"item_id": "ingredient:1", "item": "beans", "amount": 2, "unit": "cup", "prep_stage": "prep_then_bag", "stage_source": "recipe", "stage_reason": "Drain before bagging.", "needs_review": False}],
                          "equipment": ["Pot"], "instruction_phases": {
                              "prep_or_flavor_base": [{"item_id": "step:1", "text": "Chop onion", "done": False}],
                              "cook": [{"item_id": "step:2", "text": "Simmer", "done": False}],
                              "finish_and_taste": [{"item_id": "step:3", "text": "Add lime", "done": False}]}}],
        "freeze_reheat": [{"item_id": "storage:1", "recipe": "Bean soup", "text": "Reheat gently", "phase": "reheat", "done": False}],
        "shopping_list": [{"item_id": "requirement:beans", "item": "beans", "needed": {"amount": 2, "unit": "cup"}, "source_ingredient_ids": ["ingredient:1"]}, {"item_id": "buy:1", "item": "lime", "needed": {"amount": 1, "unit": "whole"}, "to_buy": {"amount": 1, "unit": "whole"}, "done": False}],
        "cook_day_pull": [],
        "equipment": [{"item_id": "equipment:1", "text": "Pot"}],
        "warnings": [{"item_id": "warning:1", "text": "Verify bean timing"}],
        "needs_review": [{"item_id": "gone:1", "field": "notes", "value": "Keep my change", "reason": "Source item no longer exists"}],
        "store_snapshot": {"version": 1, "retailers": {"heb": {"display_name": "H-E-B Hancock", "address": "1000 E 41st", "checked_at": "2026-09-26", "stale": True}},
                           "recommendations": [{"item_id": "pick:1", "ingredient": "lime", "retailer": "heb", "product_name": "H-E-B limes", "brand": "H-E-B", "package": "1 whole", "display_price": "$0.50", "url": "https://example.org/product", "evidence": "Appropriate small package", "status": "found", "checked_at": "2026-09-26"}]},
    }


def soup(packet=None):
    return BeautifulSoup(render_print_packet(packet or packet_fixture()), "html.parser")


def test_print_contains_real_sections_phases_locations_and_saved_revision():
    html = soup()
    text = html.get_text(" ", strip=True)
    for label in ("Weekly schedule", "Pull for freezer prep", "Shared prep", "Finish and taste", "Freeze and reheat",
                  "Shopping for the complete meal", "Store picks", "Needs review", "Locations used", "Revision 4", "Generated", "Sep 27", "Oct 4"):
        assert label in text
    assert "Location unsure" in text and "garage" in text
    assert "Keep my change" in text and "Stale" in text
    assert "Scheduled" in text and "cook_schedule" not in text
    assert len(html.select("h1")) == 1
    assert html.select_one("table caption").get_text() == "Weekly schedule"
    assert html.select_one("thead th[scope=col]")


@pytest.mark.parametrize("area", ["header", "schedule", "pull", "prep", "recipe", "phase", "storage", "shopping", "retailer", "product", "review"])
def test_every_untrusted_section_is_text_not_markup(area):
    packet = packet_fixture()
    targets = {
        "header": packet, "schedule": packet["production_schedule"][1], "pull": packet["pull_list"][0],
        "prep": packet["shared_prep"][0], "recipe": packet["recipe_cards"][0],
        "phase": packet["recipe_cards"][0]["instruction_phases"]["cook"][0], "storage": packet["freeze_reheat"][0],
        "shopping": packet["shopping_list"][1], "retailer": packet["store_snapshot"]["retailers"]["heb"],
        "product": packet["store_snapshot"]["recommendations"][0], "review": packet["needs_review"][0],
    }
    target = targets[area]
    for key in list(target):
        if isinstance(target[key], str):
            target[key] = HOSTILE
    target["notes"] = HOSTILE
    target["text"] = HOSTILE
    if area == "header":
        target["title"] = HOSTILE
    html = soup(packet)
    assert not html.select("script, img, iframe, style")
    assert HOSTILE in html.get_text()
    for tag in html.find_all(True):
        assert not any(key.lower().startswith("on") for key in tag.attrs)


@pytest.mark.parametrize("url", ["javascript:alert(1)", "data:text/html,<script>x</script>", "//attacker.invalid", "https://example.org/\nattack"])
def test_unsafe_urls_are_never_clickable(url):
    packet = packet_fixture()
    packet["recipe_cards"][0]["source_url"] = url
    packet["store_snapshot"]["recommendations"][0]["url"] = url
    html = soup(packet)
    assert not any(a.get("href") == url for a in html.select("a"))


def test_safe_links_escape_attributes_and_print_the_source():
    packet = packet_fixture()
    packet["recipe_cards"][0]["source_url"] = 'https://example.org/?q=" onclick="bad&x=1'
    html = soup(packet)
    a = html.select_one(".recipe-sheet a.packet-source")
    assert a["href"] == 'https://example.org/?q=" onclick="bad&x=1'
    assert not a.has_attr("onclick")


def test_empty_optional_sections_are_omitted_and_empty_schedule_is_explained():
    html = soup({"version": 1, "week": "2026-W40", "revision": 1, "status": "draft"})
    text = html.get_text(" ", strip=True)
    assert "Weekly schedule" in text and "No scheduled tasks" in text
    for label in ("Shared prep", "Pull for freezer prep", "Freeze and reheat", "Store picks", "Locations used", "Needs review"):
        assert label not in text


def test_render_is_pure_and_does_not_mutate_the_packet(monkeypatch):
    import requests
    from lib import inventory_db
    packet = packet_fixture()
    before = deepcopy(packet)
    def forbidden(*args, **kwargs):
        raise AssertionError("renderer performed external work")
    monkeypatch.setattr(inventory_db, "connect", forbidden)
    monkeypatch.setattr(requests.sessions.Session, "request", forbidden)
    assert "Bean soup" in render_print_packet(packet)
    assert packet == before


def template(name, **kwargs):
    app = Flask(__name__, template_folder=str(ROOT / "templates"))
    with app.app_context():
        return render_template(name, **kwargs)


def test_template_autoescapes_week_and_only_accepts_renderer_fragment_as_safe():
    mobile = BeautifulSoup(template("cooking_packet.html", week=HOSTILE), "html.parser")
    assert mobile.select_one("main")["data-week"] == HOSTILE
    assert len(mobile.select("h1")) == len(mobile.select("main")) == 1
    assert not mobile.select("img")
    live = mobile.select_one('[aria-live="polite"]')
    assert live and not live.get_text(strip=True)
    assert mobile.select_one('a[href="#packet-main"]')
    printed = BeautifulSoup(template("print_cooking_packet.html", week="2026-W40", packet_html=render_print_packet(packet_fixture())), "html.parser")
    assert len(printed.select("h1")) == len(printed.select("main")) == 1
    assert printed.select_one("[data-print-action]")
    # Only renderer output is marked safe. Direct packet values are never template context.
    source = (ROOT / "templates/print_cooking_packet.html").read_text()
    assert source.count("|safe") == 1 and "packet_html|safe" in source


@pytest.fixture
def browser_page():
    api = pytest.importorskip("playwright.sync_api")
    with api.sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 320, "height": 800}, reduced_motion="reduce")
        yield page
        browser.close()


def open_packet(page, packet=None, conflict=False, edit=True):
    saved = deepcopy(packet or packet_fixture())
    calls = []
    def serve(route):
        request = route.request
        path = request.url.split("kitchenos.test")[-1]
        if path.startswith("/static/"):
            name = path.split("?")[0].removeprefix("/static/")
            content_type = "text/javascript" if name.endswith(".js") else "text/css"
            route.fulfill(body=(ROOT / "static" / name).read_text(), content_type=content_type)
        elif request.method == "PATCH":
            body = request.post_data_json
            calls.append((path, body))
            if conflict:
                route.fulfill(status=409, json={"error": "Packet changed", "revision": 5})
            else:
                saved["revision"] += 1
                def apply(value):
                    if isinstance(value, dict):
                        for change in body["changes"]:
                            if value.get("item_id") == change["item_id"]:
                                value[change["field"]] = change["value"]
                                if change["field"] == "prep_stage":
                                    value.update(needs_review=False, stage_source="user", stage_reason="Ingredient destination reviewed by user.")
                        for child in value.values():
                            apply(child)
                    elif isinstance(value, list):
                        for child in value:
                            apply(child)
                apply(saved)
                if any(change["field"] == "prep_stage" for change in body["changes"]):
                    from lib.cooking_packet_builder import repartition_packet_pulls
                    repartition_packet_pulls(saved)
                route.fulfill(json=saved)
        elif request.method == "POST":
            calls.append((path, request.post_data_json))
            route.fulfill(json={"id": 58})
        elif path.startswith("/api/"):
            route.fulfill(json=saved)
        else:
            route.fulfill(body=template("cooking_packet.html", week="2026-W40"), content_type="text/html")
    page.route("**/*", serve)
    page.goto("http://kitchenos.test/cooking-packet?week=2026-W40")
    page.get_by_text("Edit schedule details", exact=True).wait_for()
    if edit:
        page.get_by_text("Edit schedule details", exact=True).click()
    return calls


def test_mobile_reflows_and_has_named_touch_controls(browser_page):
    page = browser_page
    open_packet(page)
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert page.locator("main").count() == page.locator("h1").count() == 1
    assert page.locator("[tabindex]").evaluate_all("nodes => nodes.every(n => Number(n.tabIndex) <= 0)")
    assert page.locator("button, input, select, textarea, summary").evaluate_all("nodes => nodes.filter(n => n.getClientRects().length).every(n => n.getBoundingClientRect().height >= 44)")
    assert page.locator("input, textarea, select").evaluate_all("nodes => nodes.every(n => n.labels.length > 0)")
    page.evaluate("document.documentElement.style.fontSize = '200%'")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


def test_checkbox_persists_with_exact_patch_shape(browser_page):
    page = browser_page
    calls = open_packet(page)
    page.get_by_label("Done: Soak beans", exact=True).check()
    page.get_by_role("status").filter(has_text="Saved").wait_for()
    assert calls[0] == ("/api/cooking-packets/2026-W40", {"expected_revision": 4, "changes": [{"item_id": "schedule:prep", "field": "done", "value": True}]})


def test_explicit_save_preserves_unsaved_text_on_conflict(browser_page):
    page = browser_page
    calls = open_packet(page, conflict=True)
    page.get_by_label("Task text: Soak beans", exact=True).fill("My revised soaking step")
    assert not calls
    page.get_by_role("button", name="Save Soak beans", exact=True).click()
    page.get_by_role("alert").filter(has_text="changed").wait_for()
    assert page.get_by_label("Task text: Soak beans", exact=True).input_value() == "My revised soaking step"
    assert "retry" in page.get_by_role("alert").filter(has_text="changed").inner_text().lower()
    assert calls[0][1]["changes"] == [{"item_id": "schedule:prep", "field": "text", "value": "My revised soaking step"}]


def test_invalid_duration_announces_error_and_focuses_control(browser_page):
    page = browser_page
    calls = open_packet(page)
    field = page.get_by_label("Duration in minutes: Soak beans", exact=True)
    field.fill("0")
    page.get_by_role("button", name="Save Soak beans", exact=True).click()
    assert not calls
    assert field.get_attribute("aria-invalid") == "true"
    assert field.get_attribute("aria-describedby")
    assert field.evaluate("node => node === document.activeElement")
    assert page.locator("#" + field.get_attribute("aria-describedby")).inner_text()


def test_cook_schedule_only_uses_ledger_and_exact_contract(browser_page):
    page = browser_page
    calls = open_packet(page)
    page.get_by_label("Date: Bean soup", exact=True).fill("2026-09-30")
    page.get_by_label("Start time: Bean soup", exact=True).fill("17:30")
    page.get_by_role("button", name="Save Bean soup", exact=True).click()
    page.get_by_role("status").filter(has_text="Saved").wait_for()
    assert calls[0] == ("/api/cooks/58/schedule", {"date": "2026-09-30", "meal": "dinner", "start": "2026-09-30T17:30:00-05:00", "timezone": "America/Chicago", "duration_minutes": 60, "servings_to_eat": 1})
    assert not any(path == "/api/cooking-packets/2026-W40" for path, _ in calls)


def test_mobile_hostile_text_and_urls_stay_inert(browser_page):
    page = browser_page
    packet = packet_fixture()
    packet["recipe_cards"][0].update(recipe=HOSTILE, display_name=HOSTILE, source_url="javascript:alert(1)")
    packet["store_snapshot"]["recommendations"][0].update(product_name=HOSTILE, url="javascript:alert(1)")
    open_packet(page, packet)
    page.get_by_text(HOSTILE, exact=True).first.wait_for(state="attached")
    assert page.locator("img, iframe, a[href^='javascript:']").count() == 0


def test_phase_override_moves_instruction_under_the_saved_phase():
    packet = packet_fixture()
    packet["recipe_cards"][0]["instruction_phases"]["cook"][0]["phase"] = "finish_and_taste"
    html = soup(packet)
    phase = next(block for block in html.select(".recipe-phase") if block.h4 and block.h4.get_text() == "Finish and taste")
    assert "Simmer" in phase.get_text()
    assert not any(block.h4 and block.h4.get_text() == "Cook" for block in html.select(".recipe-phase"))


def test_refresh_polls_saves_and_keeps_unsaved_text(browser_page):
    page = browser_page
    open_packet(page)
    page.get_by_label("Task text: Soak beans", exact=True).fill("Keep this draft")
    refreshes = []
    def refresh_api(route):
        if route.request.method == "POST":
            refreshes.append(route.request.post_data_json)
            route.fulfill(status=202, json={"operation_id": "job-1", "status": "pending"})
        else:
            route.fulfill(json={"status": "complete", "revision": 5})
    page.route("**/api/cooking-packets/2026-W40/refresh**", refresh_api)
    page.get_by_role("button", name="Refresh from week", exact=True).click()
    page.get_by_role("status").filter(has_text="Saved refreshed").wait_for(timeout=5000)
    assert page.get_by_label("Task text: Soak beans", exact=True).input_value() == "Keep this draft"
    assert len(refreshes) == 1 and refreshes[0]["request_id"]


def test_unassigned_cook_has_ledger_schedule_form(browser_page):
    page = browser_page
    packet = packet_fixture()
    packet["production_schedule"] = packet["production_schedule"][1:]
    packet["cooks"][0].update(source="cook", item_id="cook:58", date=None, meal=None, placements=[])
    calls = open_packet(page, packet)
    page.get_by_label("Date: Bean soup", exact=True).fill("2026-09-30")
    page.get_by_label("Start time: Bean soup", exact=True).fill("17:30")
    page.get_by_label("Timezone: Bean soup", exact=True).fill("America/Chicago")
    page.get_by_label("Duration in minutes: Bean soup", exact=True).fill("60")
    page.get_by_role("button", name="Save Bean soup", exact=True).click()
    page.get_by_role("status").filter(has_text="Saved cook schedule").wait_for(timeout=5000)
    assert calls[0][0] == "/api/cooks/58/schedule"


def test_checkbox_survives_reloading_saved_packet(browser_page):
    page = browser_page
    open_packet(page)
    page.get_by_label("Done: Soak beans", exact=True).check()
    page.get_by_role("status").filter(has_text="Saved checkbox").wait_for()
    page.reload()
    assert page.get_by_label("Done: Soak beans", exact=True).is_checked()


def test_print_repeats_footer_at_page_bottom_without_covering_recipe_text(browser_page, tmp_path):
    import shutil
    import subprocess
    executable = shutil.which("pdftotext")
    if not executable:
        pytest.skip("Poppler required for paged print position check")
    page = browser_page
    packet = packet_fixture()
    packet["recipe_cards"] = packet["recipe_cards"] * 4
    html = template("print_cooking_packet.html", week="2026-W40", packet_html=render_print_packet(packet))
    css = (ROOT / "static/cooking-packet.css").read_text()
    page.route("**/*", lambda route: route.fulfill(body=css, content_type="text/css") if "/static/" in route.request.url else route.fulfill(body=html, content_type="text/html"))
    page.goto("http://print.kitchenos.test/print/cooking-packet?week=2026-W40")
    page.emulate_media(media="print")
    pdf = tmp_path / "packet.pdf"
    page.pdf(path=str(pdf), print_background=True, prefer_css_page_size=True)
    bbox = subprocess.run([executable, "-bbox", str(pdf), "-"], check=True, capture_output=True, text=True).stdout
    document = BeautifulSoup(bbox, "xml")
    pages = document.find_all("page")
    assert len(pages) >= 2
    for printed_page in pages:
        assert float(printed_page["width"]) == 612
        assert float(printed_page["height"]) == 792
        words = printed_page.find_all("word")
        footers = [word for word in words if word.get_text() == "KitchenOS"]
        assert footers and all(float(word["yMin"]) > 720 for word in footers)
        assert any(word.get_text() == "Page" and float(word["yMin"]) > 720 for word in words)
        text = " ".join(word.get_text() for word in words)
        for number in range(1, 5):
            if f"{number} Bean soup" in text:
                assert "Freezer prep" in text, "A short recipe heading was stranded before its ingredients"


def test_invalid_timezone_announces_error_and_focuses_timezone(browser_page):
    page = browser_page
    calls = open_packet(page)
    timezone = page.get_by_label("Timezone: Bean soup", exact=True)
    timezone.fill("not/a-timezone")
    page.get_by_role("button", name="Save Bean soup", exact=True).click()
    assert not calls
    assert timezone.get_attribute("aria-invalid") == "true"
    assert timezone.evaluate("node => node === document.activeElement")
    assert page.locator("#" + timezone.get_attribute("aria-describedby")).inner_text()


def test_keyboard_starts_at_skip_link_and_has_visible_focus(browser_page):
    page = browser_page
    open_packet(page, edit=False)
    page.keyboard.press("Tab")
    focused = page.locator(":focus")
    assert focused.inner_text() == "Skip to cooking packet"
    assert focused.evaluate("n => getComputedStyle(n).outlineStyle") != "none"
    page.keyboard.press("Enter")
    assert page.url.endswith("#packet-main")


def test_mobile_opens_with_production_timeline_and_discloses_schedule_editor(browser_page):
    page = browser_page
    open_packet(page, edit=False)
    timeline = page.get_by_role("table", name="Weekly production timeline")
    assert timeline.is_visible()
    assert "Soak beans" in timeline.inner_text() and "60 min" in timeline.inner_text()
    assert not page.get_by_label("Date: Bean soup", exact=True).is_visible()
    page.get_by_text("Edit schedule details", exact=True).click()
    assert page.get_by_label("Date: Bean soup", exact=True).is_visible()


def test_saved_shopping_quantity_override_is_visible_in_print():
    packet = packet_fixture()
    packet["shopping_list"][1].update(amount="3", unit="whole", text="fresh limes")
    html = soup(packet)
    shopping = next(section for section in html.select("section") if section.h2 and section.h2.get_text() == "Shopping for the complete meal")
    assert "3 whole fresh limes" in shopping.get_text()


def test_shopping_quantity_save_uses_direct_packet_fields(browser_page):
    page = browser_page
    calls = open_packet(page)
    page.get_by_role("heading", name="Shopping for the complete meal", exact=True).click()
    amount = page.get_by_label("Quantity: lime", exact=True)
    assert amount.is_visible()
    amount.fill("3")
    page.get_by_role("button", name="Save lime", exact=True).click()
    page.get_by_role("status").filter(has_text="Saved packet").wait_for()
    assert calls[0][1]["changes"] == [{"item_id": "buy:1", "field": "amount", "value": "3"}]


def test_recipe_source_link_has_touch_target(browser_page):
    page = browser_page
    open_packet(page)
    page.get_by_role("heading", name="Recipe cards", exact=True).click()
    link = page.get_by_role("link", name="View source", exact=True).filter(visible=True)
    assert link.bounding_box()["height"] >= 44


def test_shared_prep_prints_each_recipe_contribution_as_escaped_text():
    packet = packet_fixture()
    packet["shared_prep"][0]["contributions"] = [{"recipe": HOSTILE, "amount": "1.5", "unit": HOSTILE}]
    html = soup(packet)
    shared = next(section for section in html.select("section") if section.h2 and section.h2.get_text() == "Shared prep")
    assert HOSTILE in shared.get_text() and "1.5" in shared.get_text()
    assert not shared.select("script, img")


def test_mobile_pull_names_required_quantity_and_credited_source(browser_page):
    page = browser_page
    packet = packet_fixture()
    packet["pull_list"][0]["line_id"] = "buy:1"
    packet["shopping_list"][1]["needed"] = {"amount": 3, "unit": "cup"}
    open_packet(page, packet)
    page.get_by_role("heading", name="Pull for freezer prep", exact=True).click()
    assert page.get_by_text("Required: 3 cup", exact=True).is_visible()
    assert page.get_by_text("Credited from home: 2 cup · Location unsure", exact=True).is_visible()
    assert page.get_by_role("heading", name="garage", exact=True).is_visible()


STAGE_LABELS = {
    "bag_now": "Put in the freezer bag now", "prep_then_bag": "Prep first, then bag",
    "freeze_separately": "Freeze separately", "add_at_cook_time": "Add when starting the Instant Pot",
    "finish_after_cooking": "Stir in after pressure release", "serve_separately": "Serve separately",
    "needs_review": "Needs placement review — keep out of the bag",
}


def stage_packet():
    packet = packet_fixture()
    packet["recipe_cards"][0]["ingredients"] = [
        {"item_id": f"ingredient:{index}", "item": f"food-{stage}", "amount": index, "unit": "cup",
         "prep_stage": stage, "stage_source": "recipe", "stage_reason": HOSTILE, "needs_review": False}
        for index, stage in enumerate(STAGE_LABELS, 1)] + [
        {"item_id": "ingredient:suggested", "item": "model-suggested beans", "prep_stage": "bag_now", "needs_review": True, "stage_reason": HOSTILE},
        {"item_id": "ingredient:unknown", "item": HOSTILE, "prep_stage": HOSTILE, "stage_reason": HOSTILE, "needs_review": False},
        {"item_id": "ingredient:missing", "item": "missing stage"}]
    return packet


def test_print_places_each_ingredient_once_and_never_promotes_unconfirmed_suggestions():
    packet = stage_packet()
    html = soup(packet)
    card = html.select_one(".recipe-sheet")
    assert not any(heading.get_text(strip=True) == "Ingredients" for heading in html.select("h1,h2,h3,h4,h5"))
    assert "Freezer prep" in card.get_text() and "Cook-day directions" in card.get_text()
    assert "Only items listed under Put in the freezer bag now or Prep first, then bag belong in this bag." in card.get_text()
    for ingredient in packet["recipe_cards"][0]["ingredients"]:
        occurrences = card.select('[data-ingredient-id]')
        matches = [row for row in occurrences if row["data-ingredient-id"] == ingredient["item_id"]]
        assert len(matches) == 1
        actual_stage = ingredient.get("prep_stage")
        expected = actual_stage if actual_stage in STAGE_LABELS and ingredient.get("needs_review") is False else "needs_review"
        assert matches[0].find_parent(attrs={"data-prep-stage": expected})
        assert ingredient["item"] in matches[0].get_text()
    assert not html.select("script,img")
    assert HOSTILE in card.get_text()
    assert card.select_one(".keep-out")


@pytest.mark.parametrize("ingredients", [[], [{"item_id": "ingredient:1", "item": "beans", "prep_stage": "bag_now", "needs_review": True}]])
def test_empty_or_unconfirmed_freezer_bag_has_explicit_notice(ingredients):
    packet = packet_fixture()
    packet["recipe_cards"][0]["ingredients"] = ingredients
    card = soup(packet).select_one(".recipe-sheet")
    assert "Freezer prep" in card.get_text()
    assert "No ingredients are confirmed for this freezer bag yet." in card.get_text()


def test_pull_groups_keep_legacy_and_unconfirmed_credits_for_cook_day_without_duplication():
    packet = packet_fixture()
    legacy = {"item_id": "pull:legacy", "item": HOSTILE, "amount": 9, "unit": "cup", "location": HOSTILE, "stage_reason": HOSTILE}
    packet["pull_list"].append(legacy)
    packet["cook_day_pull"] = [deepcopy(legacy)]
    html = soup(packet)
    prep = next(section for section in html.select("section") if section.h2 and section.h2.get_text() == "Pull for freezer prep")
    later = next(section for section in html.select("section") if section.h2 and section.h2.get_text() == "Keep for cook day")
    assert "2 cup beans" in prep.get_text()
    assert HOSTILE not in prep.get_text()
    assert len(later.select("li")) == 1
    assert "Needs placement review" in later.get_text() and HOSTILE in later.get_text()
    assert not html.select("script,img")


def test_browser_confirms_unchanged_stage_then_reloads_in_confirmed_bag_group(browser_page):
    page = browser_page
    packet = packet_fixture()
    packet["recipe_cards"][0]["ingredients"][0].update(prep_stage="bag_now", needs_review=True, stage_source="model", stage_reason=HOSTILE)
    packet["cook_day_pull"] = packet.pop("pull_list")
    calls = open_packet(page, packet)
    page.get_by_role("heading", name="Recipe cards", exact=True).click()
    control = page.get_by_label("Prep stage: beans", exact=True)
    assert control.input_value() == "bag_now"
    assert len(control.locator("option").all()) == 7
    assert control.locator("xpath=ancestor::*[@data-prep-stage][1]").get_attribute("data-prep-stage") == "needs_review"
    assert page.get_by_text("Saving confirms your chosen placement. Suggested placement is not confirmed yet.", exact=True).is_visible()
    page.get_by_role("button", name="Save placement", exact=True).click()
    page.get_by_role("status").filter(has_text="Saved placement").wait_for()
    assert calls[0][1] == {"expected_revision": 4, "changes": [{"item_id": "ingredient:1", "field": "prep_stage", "value": "bag_now"}]}
    page.reload()
    page.get_by_role("heading", name="Recipe cards", exact=True).click()
    control = page.get_by_label("Prep stage: beans", exact=True)
    assert control.locator("xpath=ancestor::*[@data-prep-stage][1]").get_attribute("data-prep-stage") == "bag_now"
    assert page.get_by_role("heading", name="Pull for freezer prep", exact=True).count() == 1
    assert page.get_by_role("heading", name="Keep for cook day", exact=True).count() == 0


def test_browser_stage_conflict_preserves_unsaved_selection(browser_page):
    page = browser_page
    calls = open_packet(page, conflict=True)
    page.get_by_role("heading", name="Recipe cards", exact=True).click()
    control = page.get_by_label("Prep stage: beans", exact=True)
    control.select_option("finish_after_cooking")
    assert not calls
    page.get_by_role("button", name="Save placement", exact=True).click()
    page.get_by_role("alert").filter(has_text="changed").wait_for()
    assert control.input_value() == "finish_after_cooking"
    assert calls[0][1]["changes"] == [{"item_id": "ingredient:1", "field": "prep_stage", "value": "finish_after_cooking"}]


def test_browser_all_ingredient_paths_are_inert_and_touch_sized(browser_page):
    page = browser_page
    open_packet(page, stage_packet())
    page.get_by_role("heading", name="Recipe cards", exact=True).click()
    assert page.locator('[data-ingredient-id]').count() == 10
    assert page.locator('select[name="prep_stage"]').count() == 10
    assert not page.locator("img,iframe,[onclick],[onerror]").count()
    assert page.locator('select[name="prep_stage"], .placement-form button').evaluate_all("nodes => nodes.every(n => n.getBoundingClientRect().height >= 44)")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.evaluate("document.documentElement.style.fontSize = '200%'")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


@pytest.mark.parametrize("stage", list(STAGE_LABELS))
def test_hostile_ingredient_identity_and_reason_are_escaped_in_each_placement_group(stage):
    packet = packet_fixture()
    ingredient = packet["recipe_cards"][0]["ingredients"][0]
    ingredient.update(item_id=HOSTILE, item=HOSTILE, prep_stage=stage, stage_reason=HOSTILE, needs_review=False)
    html = soup(packet)
    row = html.select_one('[data-ingredient-id]')
    assert row["data-ingredient-id"] == HOSTILE and HOSTILE in row.get_text()
    assert row.find_parent(attrs={"data-prep-stage": stage})
    assert not html.select("script,img,[onerror],[onclick]")


def test_browser_stage_validation_announces_and_focuses_invalid_select(browser_page):
    page = browser_page
    calls = open_packet(page)
    page.get_by_role("heading", name="Recipe cards", exact=True).click()
    control = page.get_by_label("Prep stage: beans", exact=True)
    control.evaluate("node => { node.value = ''; }")
    page.get_by_role("button", name="Save placement", exact=True).click()
    assert not calls
    assert control.get_attribute("aria-invalid") == "true"
    assert control.get_attribute("aria-describedby")
    assert control.evaluate("node => node === document.activeElement")
    assert page.locator("#" + control.get_attribute("aria-describedby")).inner_text()


def test_browser_bag_to_finish_edit_moves_credit_to_cook_day_and_keeps_other_drafts(browser_page):
    page = browser_page
    calls = open_packet(page)
    page.get_by_label("Task text: Soak beans", exact=True).fill("Keep my unsaved task")
    page.get_by_role("heading", name="Recipe cards", exact=True).click()
    control = page.get_by_label("Prep stage: beans", exact=True)
    control.select_option("finish_after_cooking")
    page.get_by_role("button", name="Save placement", exact=True).click()
    page.get_by_role("status").filter(has_text="Saved placement").wait_for()
    assert page.get_by_label("Task text: Soak beans", exact=True).input_value() == "Keep my unsaved task"
    control = page.get_by_label("Prep stage: beans", exact=True)
    assert control.evaluate("node => node === document.activeElement")
    assert page.get_by_role("heading", name="Keep for cook day", exact=True).count() == 1
    assert page.get_by_role("heading", name="Pull for freezer prep", exact=True).count() == 0
    page.get_by_role("heading", name="Keep for cook day", exact=True).click()
    later = page.locator('details[data-section="Keep for cook day"]')
    assert "Stir in after pressure release" in later.inner_text()
    assert later.locator('select[name="prep_stage"]').count() == 0
    assert calls[0][1] == {"expected_revision": 4, "changes": [{"item_id": "ingredient:1", "field": "prep_stage", "value": "finish_after_cooking"}]}
    page.reload()
    page.get_by_role("heading", name="Recipe cards", exact=True).click()
    assert page.get_by_label("Prep stage: beans", exact=True).input_value() == "finish_after_cooking"


def test_letter_print_long_placement_card_flows_without_a_mostly_blank_page(browser_page, tmp_path):
    import subprocess
    import shutil
    executable = shutil.which("pdfinfo")
    if not executable:
        pytest.skip("Poppler required for print page count check")
    packet = stage_packet()
    packet["recipe_cards"][0]["ingredients"] = packet["recipe_cards"][0]["ingredients"][:7]
    for ingredient in packet["recipe_cards"][0]["ingredients"]:
        ingredient["stage_reason"] = "Keep this ingredient separate until its confirmed preparation stage."
    packet["recipe_cards"][0]["ingredients"][-1].update(prep_stage="bag_now", needs_review=True)
    packet["cook_day_pull"] = [{"item_id": "pull:later", "item": "Lime juice", "amount": 1, "unit": "portion", "location": "Refrigerator", "source_ingredient_ids": ["ingredient:5"], "stage_reason": "Keep chilled until cooking day."}]
    html = template("print_cooking_packet.html", week="2026-W40", packet_html=render_print_packet(packet))
    page = browser_page
    def serve(route):
        if "/static/" in route.request.url:
            filename = route.request.url.split("/static/")[-1].split("?")[0]
            route.fulfill(body=(ROOT / "static" / filename).read_text(), content_type="text/javascript" if filename.endswith(".js") else "text/css")
        else:
            route.fulfill(body=html, content_type="text/html")
    page.route("**/*", serve)
    page.goto("http://print.kitchenos.test/print/cooking-packet?week=2026-W40")
    page.emulate_media(media="print")
    pdf = tmp_path / "long-placement-card.pdf"
    page.pdf(path=str(pdf), print_background=True, prefer_css_page_size=True)
    info = subprocess.run([executable, str(pdf)], check=True, capture_output=True, text=True).stdout
    count = int(next(line.split(":")[1].strip() for line in info.splitlines() if line.startswith("Pages:")))
    assert count <= 3, "A long placement card must flow instead of reserving a mostly blank page"
