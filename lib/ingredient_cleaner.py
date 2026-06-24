"""Make recipe ingredient rows clean enough for macro math.

Phase A (mathematical accuracy) of the ingredient-cleaning feature. Given a raw
ingredient dict ``{amount, unit, item, inferred}`` from any source, produce a
:class:`CleanIngredient` whose amount is a **decimal**, whose unit has a known
family, and whose item is a food name — or which is flagged ``needs_review`` /
``dropped`` so a bad row can't silently corrupt a recipe's macros.

What it fixes (the math-critical failure modes found in the vault audit):

- **A1** decimal amounts incl. Unicode fractions — handled in
  ``ingredient_parser`` so every path benefits; here we enforce decimal output
  (ranges → midpoint).
- **A2** amount/unit embedded in the item (``"¾ cup greek yogurt"``,
  ``"(estimated) 1/2 cup parmesan"``, ``"(14-ounce) can coconut milk"``) →
  recovered into the amount/unit fields.
- **A3** unit-family validation: an unrecognized unit, or a liquid/powder given a
  count unit (``maple syrup`` × ``whole``), is flagged rather than miscounted.
- **A4** non-ingredient rows (leaked oven temps/instructions like ``"°f oil"``,
  empty or unit-only items) are dropped.

Item-text *presentation* cleanup (stripping ``*(inferred)*`` markers, duplicate
words, prep parentheticals) is deliberately deferred to Phase B.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from lib.ingredient_parser import (
    WORD_NUMBERS,
    normalize_unit,
    parse_ingredient,
    replace_unicode_fractions,
)
from lib.ingredient_validator import is_malformed_ingredient, repair_ingredient
from lib.units import (
    COUNT_UNITS,
    MASS_G,
    VOLUME_ML,
    get_unit_family,
    lookup_density,
    parse_amount_to_float,
)

# Strong signals that a "row" is actually a leaked instruction, not an ingredient.
_INSTRUCTION_MARKERS = ("°", "preheat", "degrees", "fahrenheit", "celsius",
                        "oven to", "°f", "°c")

# Leading meta words to drop before checking for an embedded quantity.
_META_PREFIX = re.compile(
    r"^\s*(estimated|optional|about|approx\.?|approximately|roughly|~)\s+",
    re.IGNORECASE,
)

# A split range whose tail leaked into the item: amount="1", item="to 1 1/4 cup
# water" really means "1 to 1 1/4 cup water". Recover it to the midpoint.
_TO_RANGE = re.compile(r"^to\s+([\d/.\s]+?)\s+([a-zA-Z]+)\s+(.+)$", re.IGNORECASE)

# Markers for ingredients with no real quantity in the source — garnishes,
# seasonings, frying oil. Treated as negligible (informal, 0 g) rather than
# flagged, since there is no amount to recover.
_GARNISH = re.compile(
    r"\b(to taste|as needed|for (garnish|serving|topping|frying|brushing|"
    r"drizzling|dusting|greasing|the pan|the grill)|pinch of|a pinch|"
    r"handful of|a handful|dollop|to serve|to garnish)\b",
    re.IGNORECASE,
)


@dataclass
class CleanIngredient:
    amount: str        # decimal string ("0.5", "2", "1.33")
    unit: str
    item: str
    inferred: bool
    dropped: bool      # True → not a real ingredient; caller should exclude it
    needs_review: bool
    note: str = ""

    def to_ingredient(self) -> dict:
        """Back to the {amount, unit, item, inferred} dict used everywhere."""
        return {"amount": self.amount, "unit": self.unit,
                "item": self.item, "inferred": self.inferred}


def _format_decimal(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _is_instruction_leak(*fields: str) -> bool:
    blob = " ".join(f or "" for f in fields).lower()
    return any(m in blob for m in _INSTRUCTION_MARKERS)


def _normalize_item_for_qty(item: str) -> str:
    """Prepare an item string for embedded-quantity parsing.

    Turns ``"(14-ounce) can coconut milk"`` into ``"14 ounce can coconut milk"``
    and strips leading meta words like ``"(estimated)"``.
    """
    s = item.replace("(", " ").replace(")", " ")
    s = re.sub(r"(\d)-(?=[a-zA-Z])", r"\1 ", s)   # "14-ounce" -> "14 ounce"
    s = _META_PREFIX.sub("", s)
    return re.sub(r"\s+", " ", s).strip()


def _starts_with_quantity(text: str) -> bool:
    return bool(re.match(r"^\d", text))


def clean_ingredient(ing: dict) -> CleanIngredient:
    """Clean one ingredient dict into a macro-ready CleanIngredient."""
    amount = replace_unicode_fractions(str(ing.get("amount", "")).strip())
    unit = str(ing.get("unit", "")).strip()
    item = replace_unicode_fractions(str(ing.get("item", "")).strip())
    inferred = bool(ing.get("inferred", False))
    notes: list[str] = []

    # --- A4: drop non-ingredient rows -----------------------------------------
    low_item = item.lower()
    if (_is_instruction_leak(amount, item)
            or not item
            or low_item in COUNT_UNITS
            or low_item in VOLUME_ML
            or low_item in MASS_G):
        return CleanIngredient(amount or "1", unit or "whole", item, inferred,
                               dropped=True, needs_review=True,
                               note="not an ingredient (instruction/empty/unit-only)")

    # --- A2: recover amount/unit embedded in the item -------------------------
    # Split-range tail: amount="1", item="to 1 1/4 cup water" → 1.125 cup water.
    range_match = _TO_RANGE.match(item)
    if range_match:
        low = parse_amount_to_float(amount)
        high = parse_amount_to_float(range_match.group(1))
        if low is not None and high is not None and high >= low:
            amount = str((low + high) / 2)
            unit = range_match.group(2)
            item = range_match.group(3).strip()
            notes.append("recovered split range from item")

    qty_item = _normalize_item_for_qty(item)
    if range_match:
        pass  # already handled above
    elif _starts_with_quantity(qty_item):
        parsed = parse_ingredient(qty_item)
        if parsed["item"] and parse_amount_to_float(parsed["amount"]) is not None:
            amount, unit, item = parsed["amount"], parsed["unit"], parsed["item"]
            notes.append("amount recovered from item")
    elif is_malformed_ingredient({"amount": amount, "unit": unit, "item": item}):
        rep = repair_ingredient({"amount": amount, "unit": unit,
                                 "item": item, "inferred": inferred})
        amount, unit, item = rep["amount"], rep["unit"], rep["item"]
        notes.append("repaired malformed fields")

    needs_review = False

    # --- Unquantified garnish/seasoning → negligible (no amount in source) -----
    # Only when there's no real measure already present (a measured
    # "2 tbsp olive oil for drizzling" keeps its 2 tbsp).
    if _GARNISH.search(item):
        current_family = get_unit_family(normalize_unit(unit) if unit else "whole")
        if current_family in ("count", "other", "informal"):
            unit = "to taste"   # informal → engine treats as 0 g, not an error
            notes.append("unquantified garnish/seasoning → negligible")

    # --- A1/decimal: enforce a decimal amount (ranges → midpoint) -------------
    # parse_amount silently falls back to 1 for junk, so detect non-numeric
    # amounts ("Tomato Sauce", "Large bunch") explicitly and flag them.
    amount_is_junk = (bool(re.search(r"[a-zA-Z]", amount))
                      and amount.lower() not in WORD_NUMBERS)
    amt_f = parse_amount_to_float(amount)
    if amount_is_junk or amt_f is None or amt_f <= 0:
        amount_str = "1"
        needs_review = True
        notes.append(f"amount '{amount}' not numeric — defaulted to 1")
    else:
        amount_str = _format_decimal(amt_f)

    # --- A3: unit normalization + family validation ---------------------------
    unit = normalize_unit(unit) if unit else "whole"
    family = get_unit_family(unit)
    if family == "other":
        needs_review = True
        notes.append(f"unrecognized unit '{unit}'")
    elif family == "count" and lookup_density(item) is not None:
        # A liquid/powder measured by count (e.g. "maple syrup" × "whole") can't
        # be converted to grams reliably — flag rather than miscount.
        needs_review = True
        notes.append("liquid/powder with a count unit")

    if not item:
        return CleanIngredient(amount_str, unit, item, inferred,
                               dropped=True, needs_review=True, note="empty item")

    return CleanIngredient(amount_str, unit, item, inferred,
                           dropped=False, needs_review=needs_review,
                           note="; ".join(notes))


def clean_ingredients(ingredients: list[dict]) -> list[CleanIngredient]:
    """Clean a list of ingredient dicts (non-dict entries skipped)."""
    return [clean_ingredient(ing) for ing in ingredients if isinstance(ing, dict)]


def clean_ingredient_list(ingredients: list[dict]) -> list[dict]:
    """Clean a list and return ingredient dicts, excluding dropped non-food rows.

    The extraction-pipeline entry point: feed the output of
    ``validate_ingredients`` through this so saved recipes carry decimal amounts
    and recovered units. (Imported here rather than into ``ingredient_validator``
    to avoid a circular import.)
    """
    return [c.to_ingredient() for c in clean_ingredients(ingredients) if not c.dropped]
