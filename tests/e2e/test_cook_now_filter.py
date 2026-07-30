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


def test_every_row_links_to_its_recipe(live_server, page, page_errors):
    """A coverage percentage tells you nothing about whether you want to eat it.

    The whole row is the link, not just the name — on a phone a bare name is a
    small target. `data-group` has to survive the change to an <a>, since the
    filter tests above select on it.
    """
    page.goto(live_server.url("/cook-now"), wait_until="domcontentloaded")
    page.wait_for_selector(".recipe")

    rows = page.locator(".recipe")
    assert rows.count() > 0
    for i in range(rows.count()):
        row = rows.nth(i)
        assert row.evaluate("e => e.tagName") == "A", "row is not a link"
        assert row.get_attribute("href", ).startswith("/recipe/")
        assert row.get_attribute("data-group")
        assert row.bounding_box()["height"] >= 44, "tap target too small"
    assert page_errors == []


def test_recipe_link_survives_awkward_names(live_server, page, page_errors):
    """Real recipe names carry '+', '(', '!' — encodeURIComponent, not raw text.

    "Ham Cheddar + Chive Protein Biscuits" is the case that matters: an unencoded
    '+' is the classic way a name silently resolves to a different page.
    """
    page.goto(live_server.url("/cook-now"), wait_until="domcontentloaded")
    page.wait_for_selector(".recipe")

    hrefs = page.eval_on_selector_all(
        ".recipe", "els => els.map(e => [e.querySelector('.name').childNodes[0]"
                   ".textContent.trim(), e.getAttribute('href')])")

    # Guard the guard: which recipes reach the top 60 depends on current
    # inventory, so this assertion could quietly stop exercising anything. Skip
    # loudly rather than pass vacuously.
    awkward = [(n, h) for n, h in hrefs if any(c in n for c in "+()!&'")]
    if not awkward:
        pytest.skip("no awkward recipe names in the current Cook Now results")

    for name, href in awkward:
        if "+" in name:
            assert "%2B" in href, f"unencoded '+' in {href}"
        assert " " not in href, f"raw space in {href}"
    assert page_errors == []


def test_clicking_a_row_opens_that_recipe(live_server, page, page_errors):
    page.goto(live_server.url("/cook-now"), wait_until="domcontentloaded")
    page.wait_for_selector(".recipe")

    first = page.locator(".recipe").first
    name = first.locator(".name").evaluate("e => e.childNodes[0].textContent.trim()")
    first.click()
    page.wait_for_load_state("domcontentloaded")

    assert "/recipe/" in page.url
    assert name in page.locator("h1").first.inner_text()
    assert page_errors == []


def test_selection_survives_reload(live_server, page, page_errors):
    page.goto(live_server.url("/cook-now"), wait_until="domcontentloaded")
    page.wait_for_selector(".chip")
    page.locator(".chip", has_text="Desserts").click()

    page.reload()
    page.wait_for_selector(".chip")

    assert page.locator(".chip", has_text="Desserts").get_attribute("aria-pressed") == "true"
    assert page_errors == []
