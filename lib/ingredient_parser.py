"""Ingredient string parser - splits amount, unit, and item"""

# Unit normalization map
UNIT_ABBREVIATIONS = {
    "tablespoon": "tbsp", "tablespoons": "tbsp", "tbsp": "tbsp", "tbs": "tbsp",
    "teaspoon": "tsp", "teaspoons": "tsp", "tsp": "tsp",
    "cup": "cup", "cups": "cup",
    "ounce": "oz", "ounces": "oz", "oz": "oz",
    "pound": "lb", "pounds": "lb", "lb": "lb", "lbs": "lb",
    "gram": "g", "grams": "g", "g": "g",
    "kilogram": "kg", "kilograms": "kg", "kg": "kg",
    "milliliter": "ml", "milliliters": "ml", "ml": "ml",
    "liter": "l", "liters": "l", "l": "l",
    "clove": "clove", "cloves": "clove",
    "head": "head", "heads": "head",
    "knob": "knob",
    "bunch": "bunch", "bunches": "bunch",
    "sprig": "sprig", "sprigs": "sprig",
    "slice": "slice", "slices": "slice",
    "piece": "piece", "pieces": "piece",
    "can": "can", "cans": "can",
}


def normalize_unit(unit: str) -> str:
    """Normalize a unit string to its standard abbreviation.

    Args:
        unit: A unit string (e.g., "tablespoons", "Cup", "lbs")

    Returns:
        Normalized unit string (e.g., "tbsp", "cup", "lb")
        Unknown units pass through lowercased.
        Empty string returns empty string.
    """
    if not unit:
        return ""
    return UNIT_ABBREVIATIONS.get(unit.lower(), unit.lower())
