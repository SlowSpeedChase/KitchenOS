"""Every page styles through the design language, not through hex literals.

Ten templates each carried a private copy of one palette; they had already
drifted (review.html shipped an invalid five-digit `#d3355` that CSS silently
dropped). This test is what stops that recurring: a page either links
tokens.css and styles through the variables, or the suite says so.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.theme_allowlist import HEX, SYSTEM_COLOR, THEME_COLOR_LITERALS

REPO = Path(__file__).resolve().parents[1]
TEMPLATES = sorted(p for p in (REPO / "templates").glob("*.html"))
TOKENS_LINK = '<link rel="stylesheet" href="/static/tokens.css">'
KITCHENOS_LINK = '<link rel="stylesheet" href="/static/kitchenos.css">'

# The literal opening of a hand-rolled page — see _html_page() in
# api_server.py, which emits exactly this pair of lines. Matching the fuller
# literal (doctype *and* the <html> that immediately follows it) rather than
# a bare "<!DOCTYPE" substring is deliberate: a docstring once merely
# *mentioned* "<!DOCTYPE" while describing this guard and broke the build,
# forcing a reword. Prose describes a doctype; it does not reproduce the
# doctype line followed immediately by the html tag, so this pattern stays
# narrow to genuine page opens without needing to strip comments/docstrings
# via ast first.
DOCTYPE_PAGE = re.compile(r"<!DOCTYPE html>\s*<html\b")

assert TEMPLATES, "no templates found — check REPO resolution"


def _offending_hexes(text: str) -> list[str]:
    """Hex literals that are neither a theme-color meta value nor an rgba()."""
    bad = []
    for line in text.splitlines():
        if "theme-color" in line:
            # Only the two known Dawn/Ink ground values are legal here.
            for found in HEX.findall(line):
                if found not in THEME_COLOR_LITERALS:
                    bad.append(f"{found} (theme-color line)")
            continue
        bad.extend(HEX.findall(line))
    return bad


@pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: p.name)
def test_template_links_the_design_language(path: Path):
    text = path.read_text()
    assert TOKENS_LINK in text, f"{path.name} does not link tokens.css"
    assert KITCHENOS_LINK in text, f"{path.name} does not link kitchenos.css"


@pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: p.name)
def test_template_has_no_raw_hex(path: Path):
    offenders = _offending_hexes(path.read_text())
    assert not offenders, (
        f"{path.name} still hardcodes {len(offenders)} colour(s): "
        f"{sorted(set(offenders))}. Style through the tokens — see "
        f"docs/superpowers/specs/2026-07-30-light-and-dark-mode-design.md"
    )


@pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: p.name)
def test_template_has_no_system_colors(path: Path):
    """Canvas/CanvasText/GrayText pass the hex check clean but are still the
    OS palette, not ours — see the SYSTEM_COLOR docstring in theme_allowlist.
    """
    offenders = SYSTEM_COLOR.findall(path.read_text())
    assert not offenders, (
        f"{path.name} still uses {len(offenders)} CSS system colour(s): "
        f"{sorted(set(offenders))}. These track the OS palette, not the "
        f"design language — map Canvas/CanvasText/GrayText onto "
        f"--bg/--surface/--ink/--muted instead. See "
        f"docs/superpowers/specs/2026-07-30-light-and-dark-mode-design.md"
    )


def test_api_server_has_no_raw_hex():
    """api_server.py builds six pages plus the Claude bar as f-strings.

    Scanning the whole file is exact rather than approximate: a Flask server
    has no legitimate non-markup reason to name a colour.
    """
    offenders = _offending_hexes((REPO / "api_server.py").read_text())
    assert not offenders, (
        f"api_server.py still hardcodes {len(offenders)} colour(s): "
        f"{sorted(set(offenders))}"
    )


def test_api_server_has_no_system_colors():
    """Same blind spot as test_template_has_no_system_colors, for the six
    inline pages: Canvas/CanvasText/GrayText pass the hex check clean.
    """
    offenders = SYSTEM_COLOR.findall((REPO / "api_server.py").read_text())
    assert not offenders, (
        f"api_server.py still uses {len(offenders)} CSS system colour(s): "
        f"{sorted(set(offenders))}"
    )


def test_every_inline_page_goes_through_the_shared_head():
    """One hand-rolled page in api_server.py — the one inside _html_page().

    Six pages were hand-rolled with six different <head> blocks, which is how
    they ended up light-only while the templates moved on. See DOCTYPE_PAGE
    above for why this matches the fuller "<!DOCTYPE html><html>" pair
    instead of the bare substring.
    """
    text = (REPO / "api_server.py").read_text()
    found = DOCTYPE_PAGE.findall(text)
    assert len(found) == 1, (
        f"expected exactly 1 hand-rolled page (<!DOCTYPE html> followed by "
        f"<html>) in api_server.py, found {len(found)} — build the page "
        f"through _html_page()"
    )


HEX_SHOULD_NOT_MATCH = {
    # CSS id selectors — `-` is itself a word boundary, so a trailing \b
    # would not stop `#add` from matching inside these.
    "id selector": "#add-week-status { color: red; }",
    "id selector 2": "#add-sub-recipe { display: none; }",
    # HTML numeric character entities for emoji, not colours.
    "entity house": "&#127968;",
    "entity memo": "&#128221;",
    "entity robot": "&#129302;",
    # Invalid CSS hex lengths — 5 and 7 digits are not legal colours.
    "5-digit": "#d3355",
    "7-digit": "#1234567",
}

HEX_SHOULD_MATCH = {
    "3-digit": "#fff",
    "4-digit (with alpha)": "#8886",
    "6-digit": "#f4ede3",
    "8-digit (with alpha)": "#4a90d955",
    "in declaration": "color: #0071e3;",
}


@pytest.mark.parametrize("text", HEX_SHOULD_NOT_MATCH.values(), ids=HEX_SHOULD_NOT_MATCH.keys())
def test_hex_pattern_ignores_non_colours(text: str):
    """HEX has been wrong twice: id selectors, then HTML numeric entities.

    `#add-week-status` looks like a 3-digit hex colour `#add` followed by
    ordinary text unless the "no identifier character follows" lookahead is
    there, and `&#127968;` (an emoji entity) looks like a 6-digit hex colour
    unless the "not preceded by &" lookbehind is there. Both cases are
    plausible-looking # runs that are not colours, which is exactly the kind
    of thing a naive `#[0-9a-fA-F]{3,8}` regex gets wrong silently.
    """
    assert HEX.findall(text) == []


@pytest.mark.parametrize("text", HEX_SHOULD_MATCH.values(), ids=HEX_SHOULD_MATCH.keys())
def test_hex_pattern_finds_real_colours(text: str):
    """The lookbehind/lookahead guards must not swallow legitimate colours."""
    assert len(HEX.findall(text)) == 1


SYSTEM_COLOR_SHOULD_NOT_MATCH = {
    # Prose, not CSS — meal_planner.html:1369 says "off-canvas", lowercase,
    # inside a comment. SYSTEM_COLOR is case-sensitive on purpose: CSS system
    # colours are always spelled with this exact casing.
    "prose off-canvas": "the sidebar used to rip off-canvas behind a FAB",
    # A longer identifier that merely contains the keyword as a substring.
    # `-` breaks a word for HEX, but there is no such break inside
    # "CanvasKit" — \b must not fire between two word characters.
    "identifier substring": "CanvasKit.render(ctx);",
}

SYSTEM_COLOR_SHOULD_MATCH = {
    "Canvas": "background: Canvas;",
    "CanvasText": "color: CanvasText;",
    "GrayText": "color: GrayText;",
    "inside color-mix": "color-mix(in srgb, CanvasText 12%, Canvas)",
}


@pytest.mark.parametrize(
    "text", SYSTEM_COLOR_SHOULD_NOT_MATCH.values(), ids=SYSTEM_COLOR_SHOULD_NOT_MATCH.keys()
)
def test_system_color_pattern_ignores_non_colours(text: str):
    """Guards against the same two shapes of false positive as HEX: prose
    that happens to contain the word, and an identifier the keyword is only
    a substring of.
    """
    assert SYSTEM_COLOR.findall(text) == []


@pytest.mark.parametrize(
    "text", SYSTEM_COLOR_SHOULD_MATCH.values(), ids=SYSTEM_COLOR_SHOULD_MATCH.keys()
)
def test_system_color_pattern_finds_real_colours(text: str):
    assert len(SYSTEM_COLOR.findall(text)) >= 1
