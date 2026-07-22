"""The "Extracted from" attribution must survive a bracketed video title.

Found in the wild on a Korean recipe: the title begins "[감자치즈빵] …", so the
rendered line became

    *Extracted from [[감자치즈빵] …](https://youtube.com/…) on 2026-01-08*

which Obsidian reads as a wikilink to "감자치즈빵" rather than an external link
to the video. Bracketed titles are common on Korean and Japanese cooking
channels, so this recurs rather than being a one-off.
"""
from templates.recipe_template import format_recipe_markdown

RECIPE = {"title": "Potato Cheese Bread", "ingredients": [], "instructions": []}
URL = "https://www.youtube.com/watch?v=d3sdpcaMbPk"


def _attribution(markdown: str) -> str:
    return next(l for l in markdown.splitlines() if l.startswith("*Extracted from"))


def test_bracketed_title_does_not_become_a_wikilink():
    md = format_recipe_markdown(
        RECIPE, URL, "[감자치즈빵] Potato Cheese Bread", "table diary")
    line = _attribution(md)
    assert "[[" not in line, f"title's brackets opened a wikilink: {line}"
    assert URL in line


def test_bracketed_title_text_is_preserved():
    """Escaped, not stripped — the bracket is part of the channel's title."""
    md = format_recipe_markdown(
        RECIPE, URL, "[감자치즈빵] Potato Cheese Bread", "table diary")
    assert "감자치즈빵" in _attribution(md)


def test_trailing_bracket_is_also_escaped():
    line = _attribution(format_recipe_markdown(
        RECIPE, URL, "Kimchi [spicy] fried rice", "chan"))
    assert "[[" not in line and "spicy" in line


def test_ordinary_title_is_left_alone():
    line = _attribution(format_recipe_markdown(
        RECIPE, URL, "Butter Biscuits", "chan"))
    assert "[Butter Biscuits](" in line


def test_missing_title_still_renders():
    assert "Unknown Video" in _attribution(
        format_recipe_markdown(RECIPE, URL, None, "chan"))
