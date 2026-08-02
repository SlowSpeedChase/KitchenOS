"""Keep everything a recipe file already knows when re-rendering it.

``/refresh`` ("Refresh template") re-renders a recipe from its own frontmatter
through ``templates.recipe_template.format_recipe_markdown``. It rebuilt the
template's input dict by hand, and that dict had fallen a long way behind the
schema — it passed 18 keys where the template renders 30. Everything it omitted
came back as ``null``: the hero image, all four macros, ``serving_size``,
``meal_occasion``, ``seasonal_ingredients``, ``peak_months``. Worse, the keys
the template has no slot for at all — ``short_title``, the ``fit_*`` family,
``nutrition_coverage``, ``cook_count``, ``last_cooked`` — were dropped outright,
because a re-render writes the template's keys and nothing else.

The button presents as harmless housekeeping. It cost the file its macros.

Two functions, because there are two different losses:

- ``template_payload`` — keys the template *can* render but wasn't being given.
- ``preserve_unrendered`` — keys the render has no slot for, merged back after.

``preserve_unrendered`` is deliberately **not** driven by a list of key names.
It restores any schema-known key that the original file had and the re-render
lost, whatever that key is. A hand-maintained list falling behind the schema is
the bug being fixed here; writing a second hand-maintained list would rebuild
it. This is safe precisely because ``/refresh`` re-renders existing data and
never intends to clear anything — so "the original had it and the new render
doesn't" always means loss, never intent.
"""

from __future__ import annotations

import re

from lib import frontmatter, recipe_parser, recipe_schema

# banner is stored as an Obsidian embed — `banner: "[[Chili.jpg]]"` — while the
# template takes the bare filename and builds the wikilink itself.
_BANNER_RE = re.compile(r"\[\[(.+?)\]\]")


def banner_filename(banner) -> str | None:
    """The bare image filename inside a ``"[[Name.jpg]]"`` banner value."""
    if not banner or not isinstance(banner, str):
        return None
    m = _BANNER_RE.search(banner)
    return m.group(1) if m else (banner or None)


def _is_empty(value) -> bool:
    """Did this key effectively survive the re-render?

    ``recipe_parser`` yields ``''`` for a bare key and ``[]`` for an empty list,
    and the template writes the literal ``null`` for an absent scalar, which
    parses back as ``None``. All three mean "gone".
    """
    return value is None or value == "" or value == [] or value == "null"


def template_payload(fm: dict, body_data: dict) -> dict:
    """Build ``format_recipe_markdown``'s input from an existing recipe's data.

    Args:
        fm: the recipe's current frontmatter dict.
        body_data: ``recipe_parser.parse_recipe_body`` output for its body.

    Returns:
        A ``recipe_data`` dict carrying every key the template can render.
    """
    return {
        "recipe_name": fm.get("title", "Untitled"),
        "description": body_data.get("description", ""),
        "prep_time": fm.get("prep_time"),
        "cook_time": fm.get("cook_time"),
        "total_time": fm.get("total_time"),
        "servings": fm.get("servings"),
        "serving_size": fm.get("serving_size"),
        "difficulty": fm.get("difficulty"),
        "cuisine": fm.get("cuisine"),
        "protein": fm.get("protein"),
        "dish_type": fm.get("dish_type"),
        "dietary": fm.get("dietary", []),
        "equipment": fm.get("equipment", []),
        "meal_occasion": fm.get("meal_occasion", []),
        "seasonal_ingredients": fm.get("seasonal_ingredients", []),
        "peak_months": fm.get("peak_months", []),
        "image_filename": banner_filename(fm.get("banner")),
        "nutrition_calories": fm.get("nutrition_calories"),
        "nutrition_protein": fm.get("nutrition_protein"),
        "nutrition_carbs": fm.get("nutrition_carbs"),
        "nutrition_fat": fm.get("nutrition_fat"),
        "nutrition_source": fm.get("nutrition_source"),
        "nutrition_confidence": fm.get("nutrition_confidence"),
        "ingredients": body_data.get("ingredients", []),
        "instructions": body_data.get("instructions", []),
        "video_tips": body_data.get("video_tips", []),
        "needs_review": fm.get("needs_review", False),
        "confidence_notes": fm.get("confidence_notes", ""),
        "source": fm.get("recipe_source", "unknown"),
    }


def preserve_unrendered(new_content: str, original_fm: dict) -> str:
    """Restore schema-known keys the re-render lost.

    Args:
        new_content: the freshly rendered note.
        original_fm: the frontmatter dict read *before* re-rendering.

    Returns:
        ``new_content`` with the lost keys merged back, or unchanged if nothing
        was lost (or if it somehow has no frontmatter to edit).
    """
    new_fm = recipe_parser.parse_recipe_file(new_content)["frontmatter"]

    restore = {
        key: value
        for key, value in original_fm.items()
        if key in recipe_schema.KNOWN_KEYS
        and not _is_empty(value)
        and _is_empty(new_fm.get(key))
    }
    if not restore:
        return new_content

    merged = frontmatter.apply(new_content, restore, managed_keys=restore.keys())
    return merged if merged is not None else new_content
