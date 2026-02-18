"""Parser for Crouton .crumb recipe files.

Crouton is an iOS recipe manager that exports to .crumb JSON files.
See docs/plans/2026-02-17-crouton-import-design.md for full schema reference.
"""

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
