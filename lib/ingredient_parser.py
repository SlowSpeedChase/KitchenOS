"""Ingredient string parser - splits amount, unit, and item"""

import os
from fractions import Fraction
import re
from typing import Dict

_ML_FLAGS = {"1", "true", "yes", "on"}

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


def _clean_item(item: str) -> str:
    """Clean an ingredient item string - lowercase, strip whitespace and trailing punctuation."""
    return item.lower().strip().rstrip(',.;:')


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


# Word to number mapping
WORD_NUMBERS = {
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
    "eleven": "11", "twelve": "12",
}

# Unicode vulgar fractions → ASCII fraction strings. Recipe sources frequently
# use these (½ ⅓ ¼ …) and the old parser silently fell back to "1", corrupting
# the amount. We expand them to ASCII so the fraction logic converts to decimals.
UNICODE_FRACTIONS = {
    "¼": "1/4", "½": "1/2", "¾": "3/4",
    "⅓": "1/3", "⅔": "2/3",
    "⅕": "1/5", "⅖": "2/5", "⅗": "3/5", "⅘": "4/5",
    "⅙": "1/6", "⅚": "5/6",
    "⅛": "1/8", "⅜": "3/8", "⅝": "5/8", "⅞": "7/8",
    "⅐": "1/7", "⅑": "1/9", "⅒": "1/10",
}


def replace_unicode_fractions(text: str) -> str:
    """Expand Unicode vulgar fractions to ASCII, inserting a space after a
    leading digit so mixed numbers parse correctly ("1½" -> "1 1/2")."""
    if not text:
        return text
    out = []
    for ch in text:
        if ch in UNICODE_FRACTIONS:
            if out and out[-1].isdigit():
                out.append(" ")
            out.append(UNICODE_FRACTIONS[ch])
        else:
            out.append(ch)
    return "".join(out)


def parse_amount(amount_str: str) -> str:
    """
    Parse amount string to normalized form.

    - Fractions -> decimals (1/2 -> 0.5)
    - Mixed fractions -> decimals (1 1/2 -> 1.5)
    - Ranges preserved (3-4 -> 3-4)
    - Word numbers -> digits (one -> 1)
    - Empty -> "1"

    Args:
        amount_str: Amount string to parse (e.g., "1/2", "1 1/2", "one")

    Returns:
        Normalized amount string
    """
    if not amount_str:
        return "1"

    amount_str = replace_unicode_fractions(amount_str.strip()).strip()

    # Check for word numbers
    if amount_str.lower() in WORD_NUMBERS:
        return WORD_NUMBERS[amount_str.lower()]

    # Check for ranges (preserve as-is)
    if re.match(r'^\d+-\d+$', amount_str):
        return amount_str

    # Check for decimals (preserve as-is)
    if re.match(r'^\d+\.\d+$', amount_str):
        return amount_str

    # Normalize spaces around slashes
    normalized = re.sub(r'(\d)\s*/\s*(\d)', r'\1/\2', amount_str)

    # Try mixed fraction: "1 1/2"
    mixed_match = re.match(r'^(\d+)\s+(\d+/\d+)$', normalized)
    if mixed_match:
        whole, frac = mixed_match.groups()
        total = float(whole) + float(Fraction(frac))
        return _format_decimal(total)

    # Try simple fraction: "1/2"
    frac_match = re.match(r'^(\d+/\d+)$', normalized)
    if frac_match:
        total = float(Fraction(frac_match.group(1)))
        return _format_decimal(total)

    # Try whole number
    whole_match = re.match(r'^(\d+)$', normalized)
    if whole_match:
        return whole_match.group(1)

    # Fallback: return "1"
    return "1"


def _format_decimal(value: float) -> str:
    """Format float to clean decimal string."""
    if value == int(value):
        return str(int(value))
    return f"{value:.2f}".rstrip('0').rstrip('.')


# Units that are definitely units (not item descriptors)
KNOWN_UNITS = set(UNIT_ABBREVIATIONS.keys()) | {
    "knob", "pinch", "dash", "splash",
}


def parse_ingredient(text: str) -> Dict[str, str]:
    """
    Parse an ingredient string into amount, unit, and item.

    Returns:
        {"amount": str, "unit": str, "item": str}
    """
    if not text:
        return {"amount": "1", "unit": "whole", "item": ""}

    # Expand Unicode fractions up front so the numeric regexes below (which only
    # match ASCII) catch a leading "½".
    text = replace_unicode_fractions(text.strip()).strip()

    # Handle comma format: "Chicken Breasts, 500 g"
    if ", " in text:
        parts = text.rsplit(", ", 1)
        if len(parts) == 2:
            potential_item, potential_qty = parts
            # Check if second part looks like quantity
            if re.match(r'^[\d/\s]+\s*\w*$', potential_qty) or _starts_with_informal(potential_qty):
                qty_parsed = _parse_quantity_unit(potential_qty)
                return {
                    "amount": qty_parsed["amount"],
                    "unit": qty_parsed["unit"],
                    "item": _clean_item(potential_item),
                }

    # Check for informal measurement at start
    text_lower = text.lower()
    for informal in INFORMAL_UNITS:
        if text_lower.startswith(informal):
            remainder = text[len(informal):].strip()
            return {
                "amount": "1",
                "unit": informal,
                "item": _clean_item(remainder) if remainder else "",
            }

    # Check for "X to taste" at end
    if text_lower.endswith(" to taste"):
        item = text[:-9].strip()
        return {"amount": "1", "unit": "to taste", "item": _clean_item(item)}

    # Parse standard format: "amount unit item" or "amount item"
    return _parse_standard_format(text)


def _starts_with_informal(text: str) -> bool:
    """Check if text starts with an informal measurement."""
    text_lower = text.lower().strip()
    return any(text_lower.startswith(inf) for inf in INFORMAL_UNITS)


def _parse_quantity_unit(text: str) -> Dict[str, str]:
    """Parse just the quantity/unit part (no item)."""
    text = text.strip()

    # Handle informal
    for informal in INFORMAL_UNITS:
        if text.lower() == informal:
            return {"amount": "1", "unit": informal}

    # Try to extract number and unit
    match = re.match(r'^([\d/.\s-]+)\s*(.*)$', text)
    if match:
        amount_part, unit_part = match.groups()
        amount = parse_amount(amount_part.strip())
        unit = normalize_unit(unit_part.strip()) if unit_part.strip() else "whole"
        return {"amount": amount, "unit": unit}

    return {"amount": "1", "unit": "whole"}


def _parse_standard_format(text: str) -> Dict[str, str]:
    """Parse 'amount unit item' or 'amount item' format."""
    # Handle inch notation: 1" knob -> 1 knob
    text = re.sub(r'(\d+)\s*["\'\u201c\u201d]', r'\1 ', text)

    # Try to match: number + optional unit + item
    pattern = r'^([\d/.\s-]+)?\s*(.*)$'
    match = re.match(pattern, text.strip())

    if not match:
        return {"amount": "1", "unit": "whole", "item": _clean_item(text)}

    amount_part, remainder = match.groups()
    amount_part = (amount_part or "").strip()
    remainder = (remainder or "").strip()

    # Parse the amount
    if amount_part:
        amount = parse_amount(amount_part)
    else:
        amount = "1"

    # Now try to extract unit from remainder
    if not remainder:
        return {"amount": amount, "unit": "whole", "item": ""}

    # Check if first word is a known unit
    words = remainder.split(None, 1)
    first_word = words[0].lower() if words else ""

    # Check against known units
    if first_word in KNOWN_UNITS or first_word in UNIT_ABBREVIATIONS:
        unit = normalize_unit(first_word)
        item = words[1] if len(words) > 1 else ""
        return {"amount": amount, "unit": unit, "item": _clean_item(item)}

    # No unit found - use "whole"
    return {"amount": amount, "unit": "whole", "item": _clean_item(remainder)}


def ml_enabled() -> bool:
    """Whether the opt-in ML ingredient fast-path is turned on."""
    return os.environ.get("KITCHENOS_ML_INGREDIENTS", "").strip().lower() in _ML_FLAGS


def parse_ingredient_best(text: str) -> Dict[str, str]:
    """Parse an ingredient, using the ML fast-path when opted in.

    When ``KITCHENOS_ML_INGREDIENTS`` is enabled and the ML parser returns a
    high-confidence result (>= CONFIDENCE_THRESHOLD), use it; otherwise fall
    back to the rule-based ``parse_ingredient`` (also for low-confidence/edge
    lines). Off by default → identical to ``parse_ingredient``. The returned
    dict is the same ``{amount, unit, item}`` shape either way (a drop-in).
    """
    if ml_enabled():
        from lib.ingredient_ml import parse_ingredient_ml, CONFIDENCE_THRESHOLD
        ml = parse_ingredient_ml(text)
        if ml and ml.get("confidence", 0) >= CONFIDENCE_THRESHOLD and ml.get("item"):
            return {"amount": ml["amount"], "unit": ml["unit"], "item": ml["item"]}
    return parse_ingredient(text)
