"""Pantry inventory: structured 'what you have on hand'.

Storage: `config/pantry.json`, a list of `{item, amount, unit}` entries.

This module is the single source of truth for reading, writing, splitting
recipe demand against pantry, and decrementing inventory after a shopping
list is confirmed.

It is intentionally separate from `config/pantry_staples.json` (used by
`lib.seasonality` for seasonal scoring) — the staples list is a flat,
opinionated set of "ingredients to ignore for seasonal matching", whereas
pantry inventory tracks actual quantities in the user's kitchen.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from lib.ingredient_aggregator import (
    convert_from_base_unit,
    convert_to_base_unit,
    format_amount,
    get_unit_family,
    parse_amount_to_float,
)


PANTRY_PATH = Path(__file__).resolve().parent.parent / "config" / "pantry.json"


def _normalize(name: str) -> str:
    return (name or "").lower().strip()


def load_pantry(path: Optional[Path] = None) -> list[dict]:
    """Load pantry inventory; return [] if the file is missing."""
    p = path or PANTRY_PATH
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [dict(entry) for entry in data if isinstance(entry, dict)]
    except (OSError, json.JSONDecodeError):
        return []
    return []


def save_pantry(items: list[dict], path: Optional[Path] = None) -> None:
    """Write pantry inventory atomically (via tmp + rename)."""
    p = path or PANTRY_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    cleaned = []
    for entry in items:
        item = (entry.get("item") or "").strip()
        if not item:
            continue
        cleaned.append({
            "item": item,
            "amount": entry.get("amount", ""),
            "unit": entry.get("unit", ""),
        })
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(cleaned, indent=2) + "\n", encoding="utf-8")
    tmp.replace(p)


def find_match(item_name: str, pantry: list[dict]) -> Optional[dict]:
    """Return the first pantry entry whose normalized item matches `item_name`."""
    target = _normalize(item_name)
    if not target:
        return None
    for entry in pantry:
        if _normalize(entry.get("item")) == target:
            return entry
    # fallback: substring match (handles "all-purpose flour" vs "flour")
    for entry in pantry:
        pname = _normalize(entry.get("item"))
        if pname and (pname in target or target in pname):
            return entry
    return None


def split_against_pantry(item: str, amount, unit: str, pantry: list[dict]) -> dict:
    """Split a recipe-demand line against the pantry.

    Returns a dict with keys:
        from_pantry: {"amount": str, "unit": str} | None
        to_buy:     {"amount": str, "unit": str} | None
        warning:    str | None — set when units are in different families

    The pantry inventory is NOT mutated. Use `apply_decisions()` for that.
    """
    needed = {"amount": amount, "unit": unit}
    pantry_entry = find_match(item, pantry)
    if pantry_entry is None:
        return {"from_pantry": None, "to_buy": needed, "warning": None}

    p_amt = parse_amount_to_float(pantry_entry.get("amount"))
    n_amt = parse_amount_to_float(amount)
    p_unit = pantry_entry.get("unit") or ""
    p_family = get_unit_family(p_unit)
    n_family = get_unit_family(unit)

    # Pantry has the item but no parseable quantity → assume fully stocked.
    if p_amt is None:
        return {"from_pantry": needed, "to_buy": None, "warning": None}

    # Recipe has no parseable amount → treat pantry as covering the line.
    if n_amt is None:
        return {"from_pantry": needed, "to_buy": None, "warning": None}

    # Cross-family mismatch → flag and don't subtract automatically.
    if p_family != n_family and p_family != "other" and n_family != "other":
        return {
            "from_pantry": None,
            "to_buy": needed,
            "warning": f"pantry has {format_amount(p_amt)} {p_unit}, recipe asks {amount} {unit} (different units)",
        }

    if p_family in ("volume", "weight"):
        n_base = convert_to_base_unit(n_amt, unit, n_family)
        p_base = convert_to_base_unit(p_amt, p_unit, p_family)
        if p_base >= n_base:
            return {"from_pantry": needed, "to_buy": None, "warning": None}
        # partial cover: pantry has p_base, need n_base; buy the rest in recipe's unit
        remaining_base = n_base - p_base
        remaining_in_recipe_unit = convert_from_base_unit(remaining_base, unit, n_family)
        pantry_in_recipe_unit = convert_from_base_unit(p_base, unit, n_family)
        return {
            "from_pantry": {"amount": format_amount(pantry_in_recipe_unit), "unit": unit},
            "to_buy": {"amount": format_amount(remaining_in_recipe_unit), "unit": unit},
            "warning": None,
        }

    # count / other: combine if same unit, or if either side is the generic
    # "whole" / empty (the auto-fallback when no unit is parsed). This treats
    # "6 cloves garlic" as covering "10 whole garlic" 1:1, which is correct
    # for almost every count ingredient (cloves, lemons, eggs, onions, ...).
    p_unit_lower = (p_unit or "").lower()
    n_unit_lower = (unit or "").lower()
    generic = {"", "whole"}
    units_compatible = (
        p_unit_lower == n_unit_lower
        or p_unit_lower in generic
        or n_unit_lower in generic
    )
    if units_compatible:
        # Display in the recipe's unit if specified, else the pantry's.
        out_unit = unit if n_unit_lower not in generic else (p_unit or unit)
        if p_amt >= n_amt:
            return {"from_pantry": needed, "to_buy": None, "warning": None}
        return {
            "from_pantry": {"amount": format_amount(p_amt), "unit": out_unit},
            "to_buy": {"amount": format_amount(n_amt - p_amt), "unit": out_unit},
            "warning": None,
        }

    # Different "count" units (e.g. recipe wants "slices", pantry has "loaves") → warn.
    return {
        "from_pantry": None,
        "to_buy": needed,
        "warning": f"pantry has {format_amount(p_amt)} {p_unit}, recipe asks {amount} {unit}",
    }


def apply_decisions(decisions: list[dict], pantry: list[dict]) -> list[dict]:
    """Subtract user-confirmed pantry usage from the inventory.

    Each decision is `{item, amount, unit}` describing how much of the
    pantry's stock the user actually used. Items whose remaining amount
    drops to zero (or below) are removed from the inventory.

    Returns a new list; the input is not mutated.
    """
    updated: list[dict] = [dict(entry) for entry in pantry]
    for decision in decisions:
        used_item = _normalize(decision.get("item"))
        used_amt = parse_amount_to_float(decision.get("amount"))
        used_unit = decision.get("unit") or ""
        if not used_item or used_amt is None or used_amt <= 0:
            continue

        for idx, entry in enumerate(updated):
            if _normalize(entry.get("item")) != used_item:
                continue
            p_amt = parse_amount_to_float(entry.get("amount"))
            p_unit = entry.get("unit") or ""
            if p_amt is None:
                # Pantry had no amount; assume the decision empties it.
                updated.pop(idx)
                break

            p_family = get_unit_family(p_unit)
            u_family = get_unit_family(used_unit)
            if p_family in ("volume", "weight") and p_family == u_family:
                p_base = convert_to_base_unit(p_amt, p_unit, p_family)
                u_base = convert_to_base_unit(used_amt, used_unit, u_family)
                remaining_base = max(0.0, p_base - u_base)
                if remaining_base <= 1e-9:
                    updated.pop(idx)
                else:
                    remaining_native = convert_from_base_unit(remaining_base, p_unit, p_family)
                    entry["amount"] = format_amount(remaining_native)
            elif (p_unit or "").lower() == (used_unit or "").lower():
                remaining = max(0.0, p_amt - used_amt)
                if remaining <= 1e-9:
                    updated.pop(idx)
                else:
                    entry["amount"] = format_amount(remaining)
            # If units don't match family, do nothing — caller should have warned.
            break
    return updated
