"""Ingredient validation and repair for AI extraction errors."""

from lib.ingredient_parser import parse_ingredient


# Unit words that should NOT appear in the amount field
UNIT_WORDS = [
    'cup', 'cups', 'tbsp', 'tablespoon', 'tablespoons',
    'tsp', 'teaspoon', 'teaspoons', 'gram', 'grams', 'g',
    'oz', 'ounce', 'ounces', 'lb', 'pound', 'pounds',
    'ml', 'milliliter', 'milliliters', 'liter', 'liters', 'l',
    'kg', 'kilogram', 'kilograms',
]

# Non-standard unit names that indicate AI formatting errors
MALFORMED_UNITS = [
    'half_cup', 'quarter_cup', 'third_cup', 'three_quarters_cup',
    'half_teaspoon', 'quarter_teaspoon',
    'half_tablespoon', 'quarter_tablespoon',
    'two_tablespoons', 'three_tablespoons',
]

# Regex to detect units concatenated with numbers (e.g., "20g", "100ml")
import re
AMOUNT_WITH_UNIT_PATTERN = re.compile(r'^\d+(?:\.\d+)?\s*(g|kg|ml|l|oz|lb)$', re.IGNORECASE)


def is_malformed_ingredient(ing: dict) -> bool:
    """Detect common AI extraction errors in ingredient structure.

    Detects:
    - Unit field is "None", "null", or empty when amount contains unit words
    - Amount field contains unit words (e.g., "30 grams" instead of amount=30, unit=g)
    - Amount field has unit concatenated (e.g., "20g" instead of amount=20, unit=g)
    - Empty item field
    - Unit is "whole" but amount contains unit words
    - Unit is non-standard name (e.g., "half_cup" instead of "cup")
    - Amount is "None" or "null"

    Args:
        ing: Ingredient dict with amount, unit, item keys

    Returns:
        True if ingredient appears malformed and needs repair
    """
    amount = str(ing.get('amount', '')).lower().strip()
    unit = str(ing.get('unit', '')).lower().strip()
    item = str(ing.get('item', '')).strip()

    # Empty item is malformed
    if not item:
        return True

    # Amount is "none" or "null"
    if amount in ('none', 'null', ''):
        return True

    # Check if amount contains unit words (space-separated)
    amount_has_unit = any(word in amount.split() for word in UNIT_WORDS)

    # Check if amount has unit concatenated (e.g., "20g", "100ml")
    if AMOUNT_WITH_UNIT_PATTERN.match(amount):
        return True

    # Unit is "none"/"null"/empty but amount has unit words
    if unit in ('none', 'null', '') and amount_has_unit:
        return True

    # Amount contains unit words (regardless of unit field)
    # e.g., amount="1/4 cup", unit="oz" - the "cup" in amount indicates parsing failed
    if amount_has_unit:
        return True

    # Unit is nonsensical "none" or "null" string
    if unit in ('none', 'null'):
        return True

    # Unit is non-standard AI-generated name
    if unit in MALFORMED_UNITS:
        return True

    return False


def repair_ingredient(ing: dict) -> dict:
    """Re-parse a malformed ingredient using ingredient_parser.

    Intelligently combines parts of the malformed ingredient, excluding
    bad unit values, then re-parses to get correct structure.

    Args:
        ing: Malformed ingredient dict

    Returns:
        Repaired ingredient dict with amount, unit, item, inferred keys
    """
    amount = str(ing.get('amount', '')).strip()
    unit = str(ing.get('unit', '')).strip()
    item = str(ing.get('item', '')).strip()

    parts = []

    # Handle amount
    amount_lower = amount.lower()
    if amount_lower not in ('none', 'null', ''):
        parts.append(amount)
        amount_has_embedded_unit = (
            AMOUNT_WITH_UNIT_PATTERN.match(amount_lower) or
            any(word in amount_lower.split() for word in UNIT_WORDS)
        )
    else:
        amount_has_embedded_unit = False

    # Handle unit - only include if valid and not redundant
    unit_lower = unit.lower()
    unit_is_bad = (
        unit_lower in ('none', 'null', '') or
        unit_lower in MALFORMED_UNITS or
        amount_has_embedded_unit  # Don't add unit if amount already has one
    )

    if not unit_is_bad:
        # Unit looks valid, include it
        parts.append(unit)
    elif amount_lower in ('none', 'null', '') and unit_lower not in ('none', 'null', ''):
        # Amount is empty but we have a unit - might be informal like "pinch"
        # Include it so parser can handle "pinch salt"
        if unit_lower not in MALFORMED_UNITS:
            parts.append(unit)

    # Always include item
    if item:
        parts.append(item)

    combined = ' '.join(parts).strip()

    if not combined:
        # Can't repair empty ingredient, return as-is
        return ing

    # Re-parse with ingredient_parser
    parsed = parse_ingredient(combined)

    # Preserve inferred flag if it existed
    parsed['inferred'] = ing.get('inferred', False)

    return parsed


def validate_ingredients(ingredients: list, verbose: bool = False) -> list:
    """Validate and repair a list of ingredients.

    Args:
        ingredients: List of ingredient dicts from AI extraction
        verbose: If True, print repair messages

    Returns:
        List of validated/repaired ingredient dicts
    """
    if not ingredients:
        return []

    cleaned = []
    repairs_made = 0

    for ing in ingredients:
        if not isinstance(ing, dict):
            # Skip non-dict entries
            continue

        if is_malformed_ingredient(ing):
            repaired = repair_ingredient(ing)
            cleaned.append(repaired)
            repairs_made += 1

            if verbose:
                original = f"{ing.get('amount')} {ing.get('unit')} {ing.get('item')}"
                fixed = f"{repaired.get('amount')} {repaired.get('unit')} {repaired.get('item')}"
                print(f"  Repaired: '{original.strip()}' -> '{fixed.strip()}'")
        else:
            cleaned.append(ing)

    if verbose and repairs_made > 0:
        print(f"  Fixed {repairs_made} malformed ingredient(s)")

    return cleaned
