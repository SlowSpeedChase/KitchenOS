"""Every page actually renders Ink in dark mode and Dawn in light.

The static guard proves a template links tokens.css and names no hex. It
cannot prove the page obeys them — a body that never sets `background` at
all passes the lint and still renders browser-white. This does the looking.
"""
from __future__ import annotations

import pytest

from tests.theme_allowlist import TEMPLATE_ROUTES, UNCONVERTED

pytestmark = pytest.mark.e2e

# The Dawn and Ink grounds, as the browser reports them.
DAWN = "rgb(244, 237, 227)"
INK = "rgb(15, 17, 22)"

ROUTABLE = [(name, route) for name, route in TEMPLATE_ROUTES.items() if route]


def _a_recipe_name(live_server) -> str:
    """First recipe in the fixture vault — deterministic, no API dependency."""
    names = sorted(p.stem for p in (live_server.vault / "Recipes").glob("*.md"))
    assert names, "fixture vault has no recipes"
    return names[0]


def _resolve(route: str, live_server) -> str:
    return route.replace("{recipe}", _a_recipe_name(live_server))


def _body_background(page) -> str:
    return page.evaluate(
        "getComputedStyle(document.body).backgroundColor"
    )


@pytest.mark.parametrize("name,route", ROUTABLE, ids=[n for n, _ in ROUTABLE])
def test_page_follows_the_os_theme(name, route, live_server, page, page_errors):
    if name in UNCONVERTED:
        pytest.skip(f"{name} not yet converted")
    url = live_server.url(_resolve(route, live_server))

    page.emulate_media(color_scheme="dark")
    page.goto(url, wait_until="networkidle")
    assert _body_background(page) == INK, f"{name} is not Ink in dark mode"

    page.emulate_media(color_scheme="light")
    page.goto(url, wait_until="networkidle")
    assert _body_background(page) == DAWN, f"{name} is not Dawn in light mode"

    assert page_errors == [], f"{name} raised: {page_errors}"


@pytest.mark.parametrize(
    "name,route",
    [("print_week.html", "/print/week"),
     ("recipe_card.html", "/recipe-card/{recipe}")],
)
def test_paper_is_always_dawn(name, route, live_server, page):
    """A dark-mode Mac must still print ink on white.

    print_week.html sets `print-color-adjust: exact`, so an Ink ground here
    does not degrade politely — it prints a black page.
    """
    if name in UNCONVERTED:
        pytest.skip(f"{name} not yet converted")
    page.emulate_media(media="print", color_scheme="dark")
    page.goto(live_server.url(_resolve(route, live_server)),
              wait_until="networkidle")
    assert _body_background(page) == DAWN, (
        f"{name} would print an Ink ground from a dark-mode machine"
    )
