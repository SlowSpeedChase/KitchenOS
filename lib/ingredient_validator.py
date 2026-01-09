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


def is_malformed_ingredient(ing: dict) -> bool:
    """Detect common AI extraction errors in ingredient structure.

    Detects:
    - Unit field is "None", "null", or empty when amount contains unit words
    - Amount field contains unit words (e.g., "30 grams" instead of amount=30, unit=g)
    - Empty item field
    - Unit is "whole" but amount contains unit words

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

    # Check if amount contains unit words
    amount_has_unit = any(word in amount.split() for word in UNIT_WORDS)

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

    return False


def repair_ingredient(ing: dict) -> dict:
    """Re-parse a malformed ingredient using ingredient_parser.

    Combines all parts of the malformed ingredient into a single string
    and re-parses it to get correct amount/unit/item structure.

    Args:
        ing: Malformed ingredient dict

    Returns:
        Repaired ingredient dict with amount, unit, item, inferred keys
    """
    # Combine all parts into a single string
    parts = []

    amount = str(ing.get('amount', '')).strip()
    unit = str(ing.get('unit', '')).strip()
    item = str(ing.get('item', '')).strip()

    if amount:
        parts.append(amount)

    # Only include unit if it's meaningful (not none/null/whole when amount has units)
    if unit and unit.lower() not in ('none', 'null'):
        # Don't duplicate if amount already contains unit words
        amount_lower = amount.lower()
        if not any(word in amount_lower.split() for word in UNIT_WORDS):
            if unit.lower() != 'whole':
                parts.append(unit)

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
