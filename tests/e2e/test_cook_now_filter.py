"""The Cook Now meal-type chips, driven in a real browser.

The value of this test is the default: desserts must be hidden on first load
without the user doing anything. That is the entire reason the filter exists.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.e2e


def test_desserts_hidden_on_first_load(live_server, page, page_errors):
    page.goto(live_server.url("/cook-now"), wait_until="domcontentloaded")
    page.wait_for_selector(".chip")

    desserts = page.locator(".chip", has_text="Desserts")
    assert desserts.get_attribute("aria-pressed") == "false"
    assert page.locator('.recipe[data-group="Desserts"]').count() == 0
    assert page_errors == []


def test_toggling_desserts_reveals_them_without_refetching(live_server, page, page_errors):
    """Filtering is client-side: a chip toggle must not hit the API again."""
    calls = []

    def _count_call(route):
        calls.append(1)
        route.continue_()

    page.route("**/api/cook-now*", _count_call)

    page.goto(live_server.url("/cook-now"), wait_until="domcontentloaded")
    page.wait_for_selector(".chip")
    after_load = len(calls)

    page.locator(".chip", has_text="Desserts").click()

    assert page.locator(".chip", has_text="Desserts").get_attribute("aria-pressed") == "true"
    assert page.locator('.recipe[data-group="Desserts"]').count() > 0
    assert len(calls) == after_load, "chip toggle refetched the API"
    assert page_errors == []


def test_selection_survives_reload(live_server, page, page_errors):
    page.goto(live_server.url("/cook-now"), wait_until="domcontentloaded")
    page.wait_for_selector(".chip")
    page.locator(".chip", has_text="Desserts").click()

    page.reload()
    page.wait_for_selector(".chip")

    assert page.locator(".chip", has_text="Desserts").get_attribute("aria-pressed") == "true"
    assert page_errors == []
