"""The recipe page must not render Obsidian button source as recipe content.

Every recipe body opens with a `[!tools]` callout of ```button blocks, above the
`# Title`. The Full Recipe panel escaped what it didn't understand, so those
blocks arrived at the top of the page as literal "name Re-extract / type link /
action http://…".
"""
from __future__ import annotations

import pytest
import requests

pytestmark = pytest.mark.e2e

LEAKED = ["```", "type link", "action http", "name Re-extract",
          "name Refresh Template", "name Add to Meal Plan", "[!tools]"]


def _a_recipe_with_a_button_block(live_server):
    resp = requests.get(live_server.url("/api/recipes"), timeout=60).json()
    recipes = resp if isinstance(resp, list) else resp["recipes"]
    for r in recipes[:40]:
        detail = requests.get(live_server.url(f"/api/recipes/{r['name']}"), timeout=30)
        if detail.status_code != 200:
            continue
        if "```button" in (detail.json().get("body_markdown") or ""):
            return r["name"]
    return None


def test_button_block_is_not_rendered_as_content(live_server, page, page_errors):
    name = _a_recipe_with_a_button_block(live_server)
    assert name, "no recipe with a button block to test against"

    page.goto(live_server.url(f"/recipe/{name}"), wait_until="networkidle")
    page.wait_for_selector("#body-markdown")
    body = page.locator("#body-markdown").inner_text()

    for needle in LEAKED:
        assert needle not in body, (
            f"Obsidian chrome {needle!r} rendered as recipe content:\n"
            f"{body[:400]}")
    assert page_errors == []


def test_real_body_content_survives_the_strip(live_server, page, page_errors):
    """The strip must not eat the recipe: notes/equipment still render."""
    name = _a_recipe_with_a_button_block(live_server)
    detail = requests.get(live_server.url(f"/api/recipes/{name}"), timeout=30).json()
    md = detail.get("body_markdown") or ""

    page.goto(live_server.url(f"/recipe/{name}"), wait_until="networkidle")
    page.wait_for_selector("#body-markdown")
    body = page.locator("#body-markdown").inner_text()

    # Any h2 in the source that isn't the tools callout must still be shown.
    headings = [ln.strip("# ").strip() for ln in md.split("\n")
                if ln.startswith("## ")]
    assert headings, "fixture recipe has no sections to check"
    for h in headings:
        assert h in body, f"section {h!r} was stripped along with the chrome"
    assert page_errors == []


def test_blockquote_markers_are_not_shown_verbatim(live_server, page):
    name = _a_recipe_with_a_button_block(live_server)
    page.goto(live_server.url(f"/recipe/{name}"), wait_until="networkidle")
    page.wait_for_selector("#body-markdown")
    body = page.locator("#body-markdown").inner_text()
    assert not any(ln.strip().startswith(">") for ln in body.split("\n")), (
        f"raw blockquote markers in rendered body:\n{body[:400]}")


def test_template_html_comment_is_not_shown(live_server, page):
    """"My Notes" is seeded with an authoring prompt in an HTML comment."""
    name = _a_recipe_with_a_button_block(live_server)
    page.goto(live_server.url(f"/recipe/{name}"), wait_until="networkidle")
    page.wait_for_selector("#body-markdown")
    body = page.locator("#body-markdown").inner_text()
    assert "<!--" not in body and "-->" not in body, body[:300]
