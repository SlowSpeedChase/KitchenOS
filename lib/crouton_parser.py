"""Parser for Crouton .crumb recipe files.

Crouton is an iOS recipe manager that exports to .crumb JSON files.
See docs/plans/2026-02-17-crouton-import-design.md for full schema reference.
"""

import re

# Crouton quantityType enum → KitchenOS unit string
UNIT_MAP = {
    "CUP": "cup",
    "TABLESPOON": "tbsp",
    "TEASPOON": "tsp",
    "GRAMS": "g",
    "OUNCE": "oz",
    "POUND": "lb",
    "FLUID_OUNCE": "fl oz",
    "MILLS": "ml",
    "KGS": "kg",
    "CAN": "can",
    "BUNCH": "bunch",
    "PACKET": "packet",
    "PINCH": "pinch",
    "ITEM": "whole",
}


def map_quantity_type(quantity_type: str | None) -> str:
    """Map Crouton quantityType to KitchenOS unit string."""
    if not quantity_type:
        return "whole"
    return UNIT_MAP.get(quantity_type, "whole")


def map_ingredient(crouton_ing: dict) -> dict:
    """Convert a Crouton ingredient object to KitchenOS format."""
    name = crouton_ing.get("ingredient", {}).get("name", "")
    quantity = crouton_ing.get("quantity")

    if quantity:
        amount = quantity.get("amount", "")
        unit = map_quantity_type(quantity.get("quantityType"))
    else:
        amount = ""
        unit = ""

    return {"amount": amount, "unit": unit, "item": name, "inferred": False}


def map_steps(crouton_steps: list) -> list:
    """Convert Crouton steps to KitchenOS instruction format.

    Handles isSection=True steps as bold section headers prepended to the following step's text.
    """
    if not crouton_steps:
        return []

    sorted_steps = sorted(crouton_steps, key=lambda s: s.get("order", 0))
    instructions = []
    pending_section = None
    step_num = 1

    for s in sorted_steps:
        if s.get("isSection"):
            pending_section = s.get("step", "")
            continue

        text = s.get("step", "")
        if pending_section:
            text = f"**{pending_section}** \u2014 {text}"
            pending_section = None

        instructions.append({"step": step_num, "text": text, "time": None})
        step_num += 1

    return instructions


def extract_url_from_text(text: str) -> str:
    """Extract first URL from free text."""
    match = re.search(r'https?://\S+', text)
    return match.group(0) if match else ""


def format_duration(minutes: int | None) -> str | None:
    """Convert minutes integer to readable string."""
    if not minutes:
        return None
    if minutes == 60:
        return "1 hour"
    if minutes > 60:
        h = minutes // 60
        m = minutes % 60
        if m == 0:
            return f"{h} hours"
        return f"{h} hours {m} minutes"
    return f"{minutes} minutes"


def parse_crumb_file(crumb_data: dict) -> dict:
    """Parse a Crouton .crumb JSON dict into KitchenOS recipe_data format."""
    name = crumb_data.get("name", "Untitled Recipe")
    web_link = crumb_data.get("webLink", "")
    notes = crumb_data.get("notes", "")
    source_url = web_link or extract_url_from_text(notes)

    ingredients = [map_ingredient(ing) for ing in sorted(
        crumb_data.get("ingredients", []), key=lambda i: i.get("order", 0))]

    instructions = map_steps(crumb_data.get("steps", []))

    duration = crumb_data.get("duration", 0)
    cooking_duration = crumb_data.get("cookingDuration", 0)

    return {
        "recipe_name": name, "source_url": source_url,
        "source_channel": crumb_data.get("sourceName", ""),
        "source": "crouton_import",
        "servings": crumb_data.get("serves"),
        "prep_time": format_duration(duration),
        "cook_time": format_duration(cooking_duration),
        "ingredients": ingredients, "instructions": instructions,
        "notes": notes, "needs_review": True,
        "confidence_notes": "Imported from Crouton app. Metadata enriched by AI.",
        "description": "", "cuisine": None, "protein": None,
        "difficulty": None, "dish_type": None, "meal_occasion": [],
        "dietary": [], "equipment": [],
    }
