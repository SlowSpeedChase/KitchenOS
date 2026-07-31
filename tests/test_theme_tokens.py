"""Every page styles through the design language, not through hex literals.

Ten templates each carried a private copy of one palette; they had already
drifted (review.html shipped an invalid five-digit `#d3355` that CSS silently
dropped). This test is what stops that recurring: a page either links
tokens.css and styles through the variables, or the suite says so.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.theme_allowlist import HEX, THEME_COLOR_LITERALS, UNCONVERTED

REPO = Path(__file__).resolve().parents[1]
TEMPLATES = sorted(p for p in (REPO / "templates").glob("*.html"))
TOKENS_LINK = '<link rel="stylesheet" href="/static/tokens.css">'
KITCHENOS_LINK = '<link rel="stylesheet" href="/static/kitchenos.css">'

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
    if path.name in UNCONVERTED:
        pytest.skip(f"{path.name} not yet converted")
    text = path.read_text()
    assert TOKENS_LINK in text, f"{path.name} does not link tokens.css"
    assert KITCHENOS_LINK in text, f"{path.name} does not link kitchenos.css"


@pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: p.name)
def test_template_has_no_raw_hex(path: Path):
    if path.name in UNCONVERTED:
        pytest.skip(f"{path.name} not yet converted")
    offenders = _offending_hexes(path.read_text())
    assert not offenders, (
        f"{path.name} still hardcodes {len(offenders)} colour(s): "
        f"{sorted(set(offenders))}. Style through the tokens — see "
        f"docs/superpowers/specs/2026-07-30-light-and-dark-mode-design.md"
    )


def test_api_server_has_no_raw_hex():
    """api_server.py builds six pages plus the Claude bar as f-strings.

    Scanning the whole file is exact rather than approximate: a Flask server
    has no legitimate non-markup reason to name a colour.
    """
    if "api_server.py" in UNCONVERTED:
        pytest.skip("api_server.py not yet converted")
    offenders = _offending_hexes((REPO / "api_server.py").read_text())
    assert not offenders, (
        f"api_server.py still hardcodes {len(offenders)} colour(s): "
        f"{sorted(set(offenders))}"
    )


def test_every_inline_page_goes_through_the_shared_head():
    """One <!DOCTYPE in api_server.py — the one inside _html_page().

    Six pages were hand-rolled with six different <head> blocks, which is how
    they ended up light-only while the templates moved on.
    """
    if "api_server.py" in UNCONVERTED:
        pytest.skip("api_server.py not yet converted")
    text = (REPO / "api_server.py").read_text()
    assert text.count("<!DOCTYPE") == 1, (
        f"expected exactly 1 <!DOCTYPE in api_server.py, found "
        f"{text.count('<!DOCTYPE')} — build the page through _html_page()"
    )


def test_allowlist_is_temporary():
    """Fails once UNCONVERTED empties, as a prompt to delete the machinery."""
    if UNCONVERTED:
        pytest.skip(f"{len(UNCONVERTED)} template(s) still to convert")
    pytest.fail(
        "UNCONVERTED is empty — the conversion is done. Delete the skip "
        "branches in this file and in tests/e2e/test_dark_mode.py, then "
        "delete UNCONVERTED from tests/theme_allowlist.py."
    )
