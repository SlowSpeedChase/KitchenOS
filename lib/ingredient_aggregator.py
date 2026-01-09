"""Ingredient aggregation logic for shopping list generation.

Combines like ingredients across recipes, handling unit conversion
within unit families (volume, weight, count).
"""

from typing import Dict, List, Optional
import re

# Unit conversion factors (to base unit within family)
VOLUME_UNITS = {
    'tsp': 1,
    'tbsp': 3,       # 3 tsp
    'cup': 48,       # 48 tsp
    'ml': 0.2029,    # tsp
    'l': 202.9,      # tsp
}

WEIGHT_UNITS = {
    'oz': 1,
    'lb': 16,        # 16 oz
    'g': 0.035274,   # oz
    'kg': 35.274,    # oz
}

COUNT_UNITS = {
    'clove', 'cloves',
    'slice', 'slices',
    'piece', 'pieces',
    'bunch', 'bunches',
    'head', 'heads',
    'can', 'cans',
    'package', 'packages',
    'sprig', 'sprigs',
    'whole',
}


def normalize_item_name(item: str) -> str:
    """Normalize item name for grouping."""
    if not item:
        return ""
    return item.lower().strip()


def get_unit_family(unit: str) -> str:
    """Determine which unit family a unit belongs to."""
    if not unit:
        return 'other'

    unit_lower = unit.lower()

    if unit_lower in VOLUME_UNITS:
        return 'volume'
    if unit_lower in WEIGHT_UNITS:
        return 'weight'
    if unit_lower in COUNT_UNITS:
        return 'count'

    return 'other'


def parse_amount_to_float(amount) -> Optional[float]:
    """Convert amount string/number to float."""
    if amount is None or amount == '':
        return None

    if isinstance(amount, (int, float)):
        return float(amount)

    if isinstance(amount, str):
        amount = amount.strip()
        if not amount:
            return None

        # Handle ranges: "3-4" -> 3.5
        range_match = re.match(r'^(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)$', amount)
        if range_match:
            low, high = float(range_match.group(1)), float(range_match.group(2))
            return (low + high) / 2

        try:
            return float(amount)
        except ValueError:
            return None

    return None


def convert_to_base_unit(amount: float, unit: str, family: str) -> float:
    """Convert amount to base unit within its family."""
    unit_lower = unit.lower()

    if family == 'volume' and unit_lower in VOLUME_UNITS:
        return amount * VOLUME_UNITS[unit_lower]
    elif family == 'weight' and unit_lower in WEIGHT_UNITS:
        return amount * WEIGHT_UNITS[unit_lower]

    return amount


def convert_from_base_unit(amount: float, target_unit: str, family: str) -> float:
    """Convert amount from base unit to target unit."""
    target_lower = target_unit.lower()

    if family == 'volume' and target_lower in VOLUME_UNITS:
        return amount / VOLUME_UNITS[target_lower]
    elif family == 'weight' and target_lower in WEIGHT_UNITS:
        return amount / WEIGHT_UNITS[target_lower]

    return amount


def choose_best_output_unit(total_base: float, family: str, original_units: List[str]) -> str:
    """Choose the best output unit for a given total."""
    if not original_units:
        if family == 'volume':
            return 'tsp'
        elif family == 'weight':
            return 'oz'
        return 'whole'

    unit_counts = {}
    for u in original_units:
        u_lower = u.lower()
        unit_counts[u_lower] = unit_counts.get(u_lower, 0) + 1

    most_common = max(unit_counts, key=unit_counts.get)
    return most_common


def format_amount(amount: float) -> str:
    """Format a float amount for display."""
    if amount == int(amount):
        return str(int(amount))

    rounded = round(amount, 2)
    if rounded == int(rounded):
        return str(int(rounded))

    return f"{rounded:.2f}".rstrip('0').rstrip('.')


def sum_unit_family(items: List[dict], family: str) -> dict:
    """Sum ingredients within a unit family."""
    if not items:
        return {}

    if len(items) == 1:
        return items[0].copy()

    total_base = 0.0
    original_units = []

    for item in items:
        amount = parse_amount_to_float(item.get('amount'))
        unit = item.get('unit', '')

        if amount is not None:
            base_amount = convert_to_base_unit(amount, unit, family)
            total_base += base_amount
            if unit:
                original_units.append(unit)

    output_unit = choose_best_output_unit(total_base, family, original_units)
    final_amount = convert_from_base_unit(total_base, output_unit, family)

    return {
        'amount': format_amount(final_amount),
        'unit': output_unit,
        'item': items[0].get('item', ''),
    }


def combine_ingredient_group(items: List[dict]) -> List[dict]:
    """Combine ingredients with the same item name."""
    if not items:
        return []

    by_family = {
        'volume': [],
        'weight': [],
        'count': [],
        'other': [],
        'no_amount': [],
    }

    for item in items:
        unit = item.get('unit', '')
        amount = item.get('amount')

        amount_float = parse_amount_to_float(amount)
        if amount_float is None:
            by_family['no_amount'].append(item)
        else:
            family = get_unit_family(unit)
            by_family[family].append(item)

    results = []

    for family, group in by_family.items():
        if not group:
            continue

        if family == 'no_amount':
            results.append(group[0])
        elif family == 'other':
            by_unit = {}
            for item in group:
                u = item.get('unit', '').lower()
                if u not in by_unit:
                    by_unit[u] = []
                by_unit[u].append(item)

            for unit_group in by_unit.values():
                if len(unit_group) == 1:
                    results.append(unit_group[0])
                else:
                    total = 0.0
                    for item in unit_group:
                        amt = parse_amount_to_float(item.get('amount'))
                        if amt is not None:
                            total += amt
                    results.append({
                        'amount': format_amount(total),
                        'unit': unit_group[0].get('unit', ''),
                        'item': unit_group[0].get('item', ''),
                    })
        else:
            summed = sum_unit_family(group, family)
            if summed:
                results.append(summed)

    return results


def aggregate_ingredients(all_ingredients: List[dict]) -> List[dict]:
    """Combine like ingredients across recipes."""
    if not all_ingredients:
        return []

    groups = {}

    for ing in all_ingredients:
        item = ing.get('item', '')
        key = normalize_item_name(item)

        if not key:
            continue

        if key not in groups:
            groups[key] = []
        groups[key].append(ing)

    results = []
    for key, items in groups.items():
        combined = combine_ingredient_group(items)
        results.extend(combined)

    results.sort(key=lambda x: normalize_item_name(x.get('item', '')))

    return results


def format_ingredient(ing: dict) -> str:
    """Format an ingredient dict as a display string."""
    amount = ing.get('amount', '')
    unit = ing.get('unit', '')
    item = ing.get('item', '')

    if not amount:
        if unit and unit not in ('whole', ''):
            return f"{unit} {item}".strip()
        return item.strip()

    parts = []

    if amount:
        parts.append(str(amount))

    if unit and unit not in ('whole', ''):
        try:
            amt_float = float(amount)
            if amt_float > 1 and not unit.endswith('s') and unit not in ('tsp', 'tbsp', 'oz', 'lb', 'g', 'kg', 'ml', 'l'):
                unit = unit + 's'
        except (ValueError, TypeError):
            pass
        parts.append(unit)

    if item:
        parts.append(item)

    return ' '.join(parts)
