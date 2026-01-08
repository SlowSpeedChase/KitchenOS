"""Ingredient string parser - splits amount, unit, and item"""

# Unit normalization map
UNIT_ABBREVIATIONS = {
    "tablespoon": "tbsp", "tablespoons": "tbsp", "tbsp": "tbsp", "tbs": "tbsp",
    "T": "tbsp",  # Capital T = tablespoon (common convention)
    "teaspoon": "tsp", "teaspoons": "tsp", "tsp": "tsp",
    "t": "tsp",   # Lowercase t = teaspoon
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

    Note: T/t are case-sensitive (T=tbsp, t=tsp), so we check
    the original case before falling back to lowercase lookup.
    """
    if not unit:
        return ""
    # Check case-sensitive abbreviations first (T/t)
    if unit in UNIT_ABBREVIATIONS:
        return UNIT_ABBREVIATIONS[unit]
    return UNIT_ABBREVIATIONS.get(unit.lower(), unit.lower())


# Informal measurements (amount defaults to 1)
INFORMAL_UNITS = [
    "a pinch", "a smidge", "a dash", "a sprinkle", "a handful", "a splash",
    "to taste", "as needed",
    "some", "a few", "a couple",
]


def is_informal_measurement(text: str) -> bool:
    """Check if text is an informal measurement phrase.

    Args:
        text: A measurement string to check

    Returns:
        True if the text matches an informal measurement phrase,
        False otherwise.
    """
    if not text:
        return False
    text_lower = text.lower().strip()
    return text_lower in INFORMAL_UNITS
