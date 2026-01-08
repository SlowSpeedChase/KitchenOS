"""Ingredient string parser - splits amount, unit, and item"""

from fractions import Fraction
import re
from typing import Dict

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

    amount_str = amount_str.strip()

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

    text = text.strip()

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
