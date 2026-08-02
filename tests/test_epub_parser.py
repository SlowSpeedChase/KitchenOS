"""Tests for lib/epub_parser.py — structural extraction from cookbook EPUB XHTML.

Fixtures below are synthetic markup that mirrors the *class structure* of the source
EPUB (x11-Recipe-* / x11-Subrecipe-*). No book text is used.
"""

import pytest

from lib.epub_parser import (
    parse_recipe_xhtml,
    parse_yield,
    parse_dietary_tags,
    SUBHEAD_MARKER,
)


def _doc(body: str) -> str:
    """Wrap fixture markup in a minimal XHTML shell."""
    return f'<?xml version="1.0" encoding="utf-8"?><html><body>{body}</body></html>'


FULL_RECIPE = _doc("""
<h3 class="x11-Recipe-Title">Test Skillet Beans</h3>
<p class="x11-Recipe-Yield">Serves 4</p>
<p class="x11-Recipe-Head-Note-1P">Headnote prose that must not be imported.</p>
<p class="x11-Recipe-Tip-First">Tip prose that must not be imported.</p>
<p class="x11-Recipe-Ingredients-First">2 tablespoons olive oil</p>
<p class="x11-Recipe-Ingredients">1 yellow onion, diced</p>
<p class="x11-Recipe-Ingredients-Subhead">For the sauce</p>
<p class="x11-Recipe-Ingredients">3 cloves garlic</p>
<p class="x11-Recipe-Direction-First">Heat the oil in a skillet.</p>
<p class="x11-Recipe-Direction">Add the onion and cook until soft.</p>
""")


def test_parses_title():
    r = parse_recipe_xhtml(FULL_RECIPE)
    assert r["recipe_name"] == "Test Skillet Beans"


def test_parses_servings_from_yield():
    r = parse_recipe_xhtml(FULL_RECIPE)
    assert r["servings"] == 4


def test_ingredients_include_first_and_subsequent():
    r = parse_recipe_xhtml(FULL_RECIPE)
    items = [i["item"] for i in r["ingredients"]]
    assert "olive oil" in " ".join(items)
    assert any("onion" in i for i in items)


def test_ingredients_are_amount_unit_item_dicts():
    r = parse_recipe_xhtml(FULL_RECIPE)
    first = r["ingredients"][0]
    assert set(first) >= {"amount", "unit", "item", "inferred"}
    assert first["amount"] == "2"
    # parse_ingredient_best normalizes to KitchenOS's canonical unit vocabulary.
    assert first["unit"] == "tbsp"


def test_subhead_becomes_marker_row_not_an_ingredient():
    """The template renders a flat table, so a subhead is a bolded marker row
    with no amount/unit — never a parsed ingredient."""
    r = parse_recipe_xhtml(FULL_RECIPE)
    markers = [i for i in r["ingredients"] if i.get(SUBHEAD_MARKER)]
    assert len(markers) == 1
    assert markers[0]["amount"] == ""
    assert markers[0]["unit"] == ""
    assert "For the sauce" in markers[0]["item"]


def test_instructions_are_numbered_step_dicts():
    r = parse_recipe_xhtml(FULL_RECIPE)
    assert [i["step"] for i in r["instructions"]] == [1, 2]
    assert r["instructions"][0]["text"].startswith("Heat the oil")


def test_headnote_and_tip_prose_are_excluded():
    """Authored prose is deliberately not carried into the vault."""
    r = parse_recipe_xhtml(FULL_RECIPE)
    blob = repr(r)
    assert "Headnote prose" not in blob
    assert "Tip prose" not in blob


def test_document_without_recipe_title_returns_none():
    assert parse_recipe_xhtml(_doc('<p class="x04-Body-Text">Chapter intro.</p>')) is None


def test_subrecipe_ingredients_and_directions_are_captured():
    doc = _doc("""
    <h3 class="x11-Recipe-Title">With Component</h3>
    <p class="x11-Recipe-Yield">Serves 2</p>
    <p class="x11-Recipe-Ingredients-First">1 cup rice</p>
    <p class="x11-Subrecipe-Ingredients">2 tablespoons tahini</p>
    <p class="x11-Recipe-Direction-First">Cook the rice.</p>
    <p class="x11-Subrecipe-Direction">Whisk the tahini.</p>
    """)
    r = parse_recipe_xhtml(doc)
    items = " ".join(i["item"] for i in r["ingredients"])
    assert "tahini" in items
    assert any("tahini" in i["text"].lower() for i in r["instructions"])


def test_recipe_data_matches_pipeline_contract():
    """Keys the downstream chain (normalize -> enrich -> template) expects."""
    r = parse_recipe_xhtml(FULL_RECIPE)
    for key in ("recipe_name", "ingredients", "instructions", "servings",
                "description", "cuisine", "dish_type", "dietary", "equipment",
                "meal_occasion", "source"):
        assert key in r
    assert r["dietary"] == ["vegan"]


def test_dietary_badges_read_off_the_yield_line():
    doc = _doc("""
    <h3 class="x11-Recipe-Title">Badged</h3>
    <p class="x11-Recipe-Yield">Serves 4 | GF, NF</p>
    <p class="x11-Recipe-Ingredients-First">1 cup rice</p>
    <p class="x11-Recipe-Direction-First">Cook it.</p>
    """)
    r = parse_recipe_xhtml(doc)
    assert r["dietary"] == ["vegan", "gluten-free", "nut-free"]
    assert r["servings"] == 4


@pytest.mark.parametrize("text,expected", [
    ("Serves 4 | GF, SF, NF", ["gluten-free", "soy-free", "nut-free"]),
    ("Makes 1 cup (230 g) | GF", ["gluten-free"]),
    ("Serves 4", []),
    ("", []),
])
def test_parse_dietary_tags(text, expected):
    assert parse_dietary_tags(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("Serves 4", 4),
    ("Serves 4 to 6", 4),
    ("Makes 12 cookies", 12),
    ("Serves 6 as a side", 6),
    ("Makes about 2 cups", None),
    ("", None),
])
def test_parse_yield_variants(text, expected):
    assert parse_yield(text) == expected
