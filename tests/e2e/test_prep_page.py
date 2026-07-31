"""`/prep` — Today's Prep after it moved off the meal planner.

Prep is a *today* object; the planner is a *week* screen. It floated in the
planner's bottom-right dock, over the grid, reachable only by opening a week
planner and expanding a collapsed accordion — which is not where you are when
you'd act on it.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.e2e

PHONE = {"width": 430, "height": 932}


def _open(page, live_server, path="/prep"):
    page.set_viewport_size(PHONE)
    page.goto(live_server.url(path), wait_until="domcontentloaded")


class TestPage:
    def test_it_renders(self, live_server, page, page_errors):
        _open(page, live_server)
        assert page.locator("h1").inner_text().strip() == "Today's prep"
        assert page.locator(".sub").inner_text().strip(), "the subtitle states the state"
        assert page_errors == []

    def test_every_row_is_a_real_tap_target(self, live_server, page):
        """Prep gets ticked mid-cook, often one-handed."""
        _open(page, live_server)
        rows = page.locator(".task")
        if rows.count() == 0:
            pytest.skip("no tasks in the fixture week")
        for i in range(rows.count()):
            box = rows.nth(i).bounding_box()
            assert box["height"] >= 44, f"row {i} is {box['height']}px"

    def test_it_links_back_to_the_home_page(self, live_server, page):
        _open(page, live_server)
        assert page.locator('.kicker a[href="/"]').count() == 1


class TestTicking:
    def test_a_tick_persists_across_a_reload(self, live_server, page, page_errors):
        """`done` is written through /api/tasks/<week>/<id>/done, whose IDs are
        sha1(recipe|day|slot|step) — so it survives plan regeneration too."""
        _open(page, live_server)
        rows = page.locator(".task")
        if rows.count() == 0:
            pytest.skip("no tasks in the fixture week")

        first = rows.first
        task_id = first.get_attribute("data-task-id")
        was_done = "done" in (first.get_attribute("class") or "")

        first.click()
        page.wait_for_timeout(600)
        assert ("done" in (first.get_attribute("class") or "")) is not was_done

        page.reload(wait_until="domcontentloaded")
        after = page.locator(f'.task[data-task-id="{task_id}"]')
        assert after.count() == 1, "the step is still on the page"
        assert ("done" in (after.get_attribute("class") or "")) is not was_done, (
            "the tick did not survive a reload")

        # Leave the fixture as we found it.
        after.click()
        page.wait_for_timeout(400)
        assert page_errors == []


class TestHomePage:
    def test_the_home_page_carries_a_prep_card(self, live_server, page, page_errors):
        _open(page, live_server, "/")
        # Scoped to the live-state card: /prep is also in the collapsed
        # "All pages" registry below, so a bare href match finds two.
        card = page.locator('.today-card[href="/prep"]')
        assert card.count() == 1
        assert card.inner_text().strip(), "the card states a fact, not just a label"
        assert page_errors == []

    def test_the_home_page_stays_fast(self, live_server, page):
        """The card reads the task sidecar only when fresh. Calling
        `extract_tasks` here instead would regenerate it with an LLM pass —
        seconds — on every home-page load."""
        _open(page, live_server, "/")
        elapsed = page.evaluate(
            "() => performance.timing.responseEnd - performance.timing.requestStart")
        assert elapsed < 3000, f"/ took {elapsed}ms to respond"


class TestPlannerNoLongerCarriesIt:
    def test_the_prep_panel_is_gone_from_the_planner(self, live_server, page, page_errors):
        page.set_viewport_size({"width": 820, "height": 1180})
        page.goto(live_server.url("/meal-planner?touch=1"), wait_until="domcontentloaded")
        page.wait_for_selector(".grid-cell")
        assert page.locator("#prep-panel").count() == 0
        assert page.locator("#prep-body").count() == 0
        assert page_errors == [], "removing it must not leave a dangling reference"

    def test_use_it_up_still_works_on_the_planner(self, live_server, page):
        """The two panels shared their CSS classes — deleting one must not take
        the other's styling with it."""
        page.set_viewport_size({"width": 820, "height": 1180})
        page.goto(live_server.url("/meal-planner?touch=1"), wait_until="domcontentloaded")
        page.wait_for_selector("#useitup-panel")
        panel = page.locator("#useitup-panel")
        assert panel.count() == 1
        box = panel.bounding_box()
        assert box and box["height"] > 20, "still a styled panel, not an unstyled div"
