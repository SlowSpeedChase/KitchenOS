"""Category + shoppable-quantity lookup for shopping lists.

Reads config/grocery_items.json (by_item overrides -> by_category defaults) to
answer two questions per ingredient:
  * what store category is it? (for grouping)
  * how do you buy it, and how many packages does the needed amount round up to?

Deterministic, hand-correctable. No LLM.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from functools import lru_cache
from typing import Optional

from lib.ingredient_aggregator import (
    parse_amount_to_float,
    get_unit_family,
    convert_to_base_unit,
    convert_from_base_unit,
)

_CONFIG = Path(__file__).resolve().parent.parent / "config" / "grocery_items.json"

_PLURAL = {"loaf": "loaves"}


@lru_cache(maxsize=1)
def _load() -> dict:
    if not _CONFIG.exists():
        return {"by_item": {}, "by_category": {}}
    try:
        data = json.loads(_CONFIG.read_text())
    except (json.JSONDecodeError, OSError):
        return {"by_item": {}, "by_category": {}}
    data.setdefault("by_item", {})
    data.setdefault("by_category", {})
    return data


def _norm(s: str) -> str:
    return (s or "").lower().strip()


def _match_by_item(item: str) -> Optional[dict]:
    """Exact match, then word-subset (like storage_locations)."""
    by_item = _load()["by_item"]
    key = _norm(item)
    if not key:
        return None
    if key in by_item:
        return by_item[key]
    tokens = set(key.split())
    for cand, entry in by_item.items():
        cand_tokens = set(cand.split())
        if cand_tokens and cand_tokens <= tokens:
            return entry
    return None


def assign_category(item: str) -> str:
    entry = _match_by_item(item)
    if entry and entry.get("category"):
        return entry["category"]
    return "other"


def _buy_unit(entry: Optional[dict], category: str) -> Optional[str]:
    if entry and entry.get("buy_unit"):
        return entry["buy_unit"]
    return _load()["by_category"].get(category, {}).get("buy_unit")


def _pluralize(unit: str, n: int) -> str:
    if n <= 1 or not unit:
        return unit
    if unit in _PLURAL:
        return _PLURAL[unit]
    # Don't pluralize weight/volume abbreviations (lb, oz, gal, tbsp, tsp, etc.)
    if unit.lower() in ("lb", "oz", "gal", "pt", "cup", "tbsp", "tsp", "ml", "l", "g", "kg"):
        return unit
    return unit if unit.endswith("s") else unit + "s"


def _labeled(buy_unit: str, label: Optional[str], n: int) -> str:
    u = _pluralize(buy_unit, n)
    return f"{u} ({label})" if label else u


def shoppable_quantity(item: str, amount, unit: str) -> dict:
    """Round a needed (amount, unit) up to how the item is purchased.

    Returns {"amount": str, "unit": str}. amount == "" means unmeasured
    (e.g. "to taste") — the line should show the item with no quantity.
    """
    amt = parse_amount_to_float(amount)
    if amt is None or amt <= 0:
        return {"amount": "", "unit": ""}

    entry = _match_by_item(item)
    category = entry["category"] if (entry and entry.get("category")) else "other"
    # Only use buy_unit from config if entry was found; unknown items use native unit
    buy_unit = _buy_unit(entry, category) if entry else None
    package = entry.get("package") if entry else None
    label = entry.get("label") if entry else None

    if package and buy_unit:
        pkg_qty = parse_amount_to_float(package.get("qty"))
        pkg_unit = package.get("unit", "")
        if pkg_qty and pkg_qty > 0:
            need_fam = get_unit_family(unit)
            pkg_fam = get_unit_family(pkg_unit)
            if need_fam == pkg_fam and need_fam in ("volume", "weight"):
                need_base = convert_to_base_unit(amt, unit, need_fam)
                pkg_base = convert_to_base_unit(pkg_qty, pkg_unit, pkg_fam)
                n = math.ceil(need_base / pkg_base) if pkg_base > 0 else 1
            elif need_fam == pkg_fam:  # count / other, same family
                n = math.ceil(amt / pkg_qty)
            else:
                n = 1  # can't convert across families -> assume one package covers
            return {"amount": str(n), "unit": _labeled(buy_unit, label, n)}

    if buy_unit:
        need_fam = get_unit_family(unit)
        bu_fam = get_unit_family(buy_unit)
        if need_fam == bu_fam and need_fam in ("volume", "weight"):
            base = convert_to_base_unit(amt, unit, need_fam)
            n_units = convert_from_base_unit(base, buy_unit, bu_fam)
            n = math.ceil(n_units)
        else:
            n = math.ceil(amt)
        return {"amount": str(n), "unit": _pluralize(buy_unit, n)}

    # No config entry at all: round up in the native unit.
    return {"amount": str(math.ceil(amt)), "unit": unit}
