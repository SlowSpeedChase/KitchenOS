"""Tests for the /refresh data-preservation helpers.

The bug being pinned: pressing "Refresh template" on a recipe re-rendered it
through a hand-built payload that had fallen behind the schema, so the file
came back with `banner: null`, `nutrition_calories: null` and no `short_title`
at all. It presents as harmless housekeeping.
"""

from lib import recipe_parser, recipe_schema
from lib.recipe_refresh import (
    banner_filename,
    preserve_unrendered,
    template_payload,
)
from templates.recipe_template import format_recipe_markdown

# A recipe carrying the full spread: required keys the template renders, plus
# optional keys written by other producers (enricher, backfill, cook_history).
FULL_MD = """---
title: "Chili"
banner: "[[Chili.jpg]]"
servings: 4
serving_size: "1 bowl"
difficulty: "easy"
cuisine: "American"
protein: "beef"
dish_type: "main"
prep_time: 10
cook_time: 30
total_time: 40
meal_occasion: ["dinner", "lunch"]
seasonal_ingredients: ["tomato"]
peak_months: [7, 8]
dietary: ["gluten-free"]
equipment: ["dutch oven"]
tags: ["recipe"]
cssclasses: ["recipe"]
nutrition_calories: 500
nutrition_protein: 30
nutrition_carbs: 40
nutrition_fat: 20
nutrition_source: "fdc"
nutrition_confidence: 0.8
nutrition_coverage: 0.95
nutrition_needs_review: false
needs_review: false
confidence_notes: ""
recipe_source: "ai_extraction"
source_url: "https://example.com/v"
source_channel: "Chef"
video_title: "Best Chili"
date_added: 2026-01-01
short_title: "Chili"
short_title_inferred: true
fit_effort: "low"
fit_needs_review: true
cook_count: 3
last_cooked: 2026-07-20
make_again_count: 2
---

## Ingredients

| Amount | Unit | Ingredient |
|--------|------|------------|
| 1 | lb | ground beef |

## Instructions

1. Brown the beef.
"""


def _render(md):
    """Re-render a note the way /refresh does, and return the new content."""
    parsed = recipe_parser.parse_recipe_file(md)
    fm, body = parsed["frontmatter"], parsed["body"]
    body_data = recipe_parser.parse_recipe_body(body)
    new = format_recipe_markdown(
        template_payload(fm, body_data),
        video_url=fm.get("source_url", ""),
        video_title=fm.get("video_title", ""),
        channel=fm.get("source_channel", ""),
        date_added=fm.get("date_added"),
    )
    return preserve_unrendered(new, fm), fm


class TestBannerFilename:
    def test_unwraps_an_obsidian_embed(self):
        assert banner_filename('"[[Chili.jpg]]"') == "Chili.jpg"

    def test_bare_filename_passes_through(self):
        assert banner_filename("Chili.jpg") == "Chili.jpg"

    def test_none_and_null_yield_none(self):
        assert banner_filename(None) is None
        assert banner_filename("") is None


class TestRefreshPreservesEverything:
    """A refresh must not cost the file anything it already knew."""

    def test_banner_survives(self):
        new, _ = _render(FULL_MD)
        assert recipe_parser.parse_recipe_file(new)["frontmatter"]["banner"] \
            == "[[Chili.jpg]]"

    def test_macros_survive(self):
        new, _ = _render(FULL_MD)
        fm = recipe_parser.parse_recipe_file(new)["frontmatter"]
        assert fm["nutrition_calories"] == 500
        assert fm["nutrition_protein"] == 30
        assert fm["nutrition_carbs"] == 40
        assert fm["nutrition_fat"] == 20

    def test_template_rendered_extras_survive(self):
        new, _ = _render(FULL_MD)
        fm = recipe_parser.parse_recipe_file(new)["frontmatter"]
        assert fm["serving_size"] == "1 bowl"
        assert fm["meal_occasion"] == ["dinner", "lunch"]
        assert fm["seasonal_ingredients"] == ["tomato"]
        assert fm["peak_months"] == [7, 8]

    def test_optional_keys_the_template_cannot_render_survive(self):
        """short_title, fit_*, coverage, cook history — written by other producers."""
        new, _ = _render(FULL_MD)
        fm = recipe_parser.parse_recipe_file(new)["frontmatter"]
        assert fm["short_title"] == "Chili"
        assert fm["nutrition_coverage"] == 0.95
        assert fm["fit_effort"] == "low"
        assert fm["cook_count"] == 3
        assert fm["last_cooked"] == "2026-07-20"
        assert fm["make_again_count"] == 2

    def test_no_declared_key_is_lost(self):
        """The general contract, not a spot-check of the keys we remembered."""
        new, original = _render(FULL_MD)
        fm = recipe_parser.parse_recipe_file(new)["frontmatter"]
        lost = [
            k for k, v in original.items()
            if k in recipe_schema.KNOWN_KEYS
            and v not in (None, "", [])
            and fm.get(k) in (None, "", [])
        ]
        assert lost == []

    def test_result_still_parses_and_declares_the_schema(self):
        new, _ = _render(FULL_MD)
        fm = recipe_parser.parse_recipe_file(new)["frontmatter"]
        assert set(recipe_schema.REQUIRED_KEYS) <= set(fm)


class TestPreserveUnrendered:
    def test_does_not_invent_keys_absent_from_the_original(self):
        new, _ = _render(FULL_MD)
        fm = recipe_parser.parse_recipe_file(new)["frontmatter"]
        assert "observed_servings" not in fm

    def test_ignores_keys_outside_the_schema(self):
        out = preserve_unrendered(FULL_MD, {"totally_made_up": "x"})
        assert "totally_made_up" not in out

    def test_no_loss_means_no_edit(self):
        assert preserve_unrendered(FULL_MD, {}) == FULL_MD

    def test_content_without_frontmatter_is_returned_unchanged(self):
        assert preserve_unrendered("# Plain\n", {"short_title": "x"}) == "# Plain\n"
