"""The cook toast reports every outcome, not just decrements.

Drives renderCookToast directly rather than through a real cook: the point
under test is that a response with an empty `consumed` list still tells you
what happened, which is exactly the case the old duplicated code discarded.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.e2e


def test_toast_names_used_and_untracked_items(live_server, page, page_errors):
    page.goto(live_server.url("/meal-planner"), wait_until="domcontentloaded")
    page.evaluate("""renderCookToast({
        consumed: [],
        use_recorded: [{item: 'Mirin', unit: 'ct'}],
        not_tracked: ['dragon fruit'],
        skipped_staples: ['flour', 'salt']
    })""")

    text = page.locator("#toast").inner_text()
    assert "used: Mirin" in text
    assert "not tracked: dragon fruit" in text
    assert "2 staples assumed" in text
    assert "nothing tracked to decrement" not in text
    assert page_errors == []


def test_toast_marks_a_depleted_row_as_used_up(live_server, page, page_errors):
    page.goto(live_server.url("/meal-planner"), wait_until="domcontentloaded")
    page.evaluate("""renderCookToast({
        consumed: [{item: 'lime', unit: 'ct', before: 2, after: 0, depleted: true}],
        use_recorded: [], not_tracked: [], skipped_staples: []
    })""")

    assert "lime — used up" in page.locator("#toast").inner_text()
    assert page_errors == []


def test_toast_says_nothing_tracked_only_when_all_lists_are_empty(
        live_server, page, page_errors):
    page.goto(live_server.url("/meal-planner"), wait_until="domcontentloaded")
    page.evaluate("""renderCookToast({
        consumed: [], use_recorded: [], not_tracked: [], skipped_staples: []
    })""")

    assert "nothing tracked to decrement" in page.locator("#toast").inner_text()
    assert page_errors == []
