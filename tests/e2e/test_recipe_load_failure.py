"""Recipe API failures must leave a usable Obsidian link and honest feedback."""
from urllib.parse import parse_qs, quote, urlsplit

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e


@pytest.fixture
def recipe_url(live_server):
    name = "Browser Access Test"
    note = live_server.vault / "Recipes" / f"{name}.md"
    note.write_text("""---
title: Browser Access Test
servings: 4
---

## Ingredients

| Amount | Unit | Ingredient |
|--------|------|------------|
| 2 | cup | beans |

## Instructions

1. Cook the beans.
""", encoding="utf-8")
    yield live_server.url("/recipe/" + quote(name))
    note.unlink(missing_ok=True)


@pytest.mark.parametrize("status,title", [
    (401, "Browser access required"),
    (403, "Browser access required"),
    (404, "Recipe not found"),
    (500, "Could not load recipe"),
])
def test_failed_load_keeps_obsidian_link(page, recipe_url, status, title):
    page.route("**/api/recipes/**", lambda route: route.fulfill(
        status=status, content_type="application/json", body='{"error":"Failed"}'))
    page.goto(recipe_url)
    expect(page.locator("#recipe-title")).to_have_text(title)
    uri = urlsplit(page.get_by_role("link", name="Open in Obsidian").get_attribute("href"))
    assert (uri.scheme, uri.netloc) == ("obsidian", "open")
    assert parse_qs(uri.query) == {"vault": ["KitchenOS"], "file": ["Recipes/Browser Access Test"]}
    expect(page.locator("#recipe-subtitle")).to_contain_text("Obsidian")
    expect(page.locator("#scale-select")).not_to_be_visible()
    expect(page.get_by_role("button", name="Add to meal plan")).to_be_disabled()


def test_network_failure_keeps_recovery_available(page, recipe_url):
    page.route("**/api/recipes/**", lambda route: route.abort())
    page.goto(recipe_url)
    expect(page.locator("#recipe-title")).to_have_text("Could not load recipe")
    expect(page.locator("#recipe-subtitle")).to_contain_text("reload")
    expect(page.locator("#obsidian-link")).to_have_attribute("href", "obsidian://open?vault=KitchenOS&file=Recipes%2FBrowser%20Access%20Test")
    expect(page.locator("#scale-select")).not_to_be_visible()


def test_successful_load_reveals_scaling_and_plan_action(page, recipe_url, page_errors):
    page.goto(recipe_url)
    expect(page.locator("#recipe-title")).to_have_text("Browser Access Test")
    expect(page.locator("#ingredients-body")).to_contain_text("beans")
    expect(page.locator("#instructions-list")).to_contain_text("Cook the beans")
    expect(page.get_by_role("button", name="Add to meal plan")).to_be_enabled()
    page.get_by_label("Scale", exact=True).select_option("2")
    expect(page.locator("#ingredients-body tr td").first).to_have_text("4")
    assert page_errors == []
