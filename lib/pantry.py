"""Pantry view of the unified inventory: 'what you have on hand'.

Storage is the DB-backed inventory table (`lib.inventory` /
`lib.inventory_db`) — the former `config/pantry.json` file is retired.
`load_pantry()` / `save_pantry()` adapt the inventory rows to the
`[{item, amount, unit}]` shape the shopping-list split logic expects.

This module remains the single source of truth for splitting recipe demand
against pantry stock and decrementing inventory after a shopping list is
confirmed.

It is intentionally separate from `config/pantry_staples.json` (used by
`lib.seasonality` for seasonal scoring) — the staples list is a flat,
opinionated set of "ingredients to ignore for seasonal matching", whereas
pantry inventory tracks actual quantities in the user's kitchen.
"""
from __future__ import annotations

import re
from typing import Optional

from lib.ingredient_aggregator import (
    GENERIC_COUNT,
    convert_from_base_unit,
    convert_to_base_unit,
    format_amount,
    get_unit_family,
    parse_amount_to_float,
    unit_compatibility,
)
from lib.use_it_up import _covers, _ingredient_phrase, _phrase


def _normalize(name: str) -> str:
    return (name or "").lower().strip()


_PARENTHETICAL_RE = re.compile(r"\([^)]*\)")
_ALTERNATIVE_RE = re.compile(r"\b(?:or|sub|subs|substitute|substitutes)\b", re.IGNORECASE)


def _match_text(item_name: str) -> str:
    """Ingredient text with prep-note parentheticals removed.

    A parenthetical is kept when it offers alternatives — "almond butter (or
    peanut, walnut, or cashew butter)" must still match a Peanut butter row,
    and so must "maple syrup (sub 2 tbsp honey)" — and dropped otherwise,
    because prep notes inject tokens that produce wrong matches: "cooking oil
    (for enchilada red sauce)" was matching an enchilada sauce row. The same
    recipe library writes substitutions both as "or" and as "sub", so both
    are recognized. This is why `ingredient_normalizer.normalize_name` is not
    used here: it strips every parenthetical, alternatives included.
    """
    def keep(m):
        return m.group(0) if _ALTERNATIVE_RE.search(m.group(0)) else " "
    return _PARENTHETICAL_RE.sub(keep, item_name or "").strip()


def load_pantry() -> list[dict]:
    """Pantry view of current stock: [{item, amount, unit}, ...].

    Sourced from the DB inventory table. Rows sharing (name, unit) across
    locations are summed — the shopping-list split doesn't care where an
    item lives.
    """
    from lib.inventory import read_inventory

    totals: dict[tuple[str, str], dict] = {}
    for it in read_inventory():
        key = (it.name.lower().strip(), it.unit.lower().strip())
        if key in totals:
            prev = parse_amount_to_float(totals[key]["amount"]) or 0.0
            totals[key]["amount"] = format_amount(prev + it.quantity)
        else:
            totals[key] = {
                "item": it.name,
                "amount": format_amount(it.quantity),
                "unit": it.unit,
            }
    return list(totals.values())


def save_pantry(items: list[dict]) -> None:
    """Reconcile a pantry list (post apply_decisions) into the inventory table.

    - (name, unit) present here and in DB → quantity updated. If the same
      (name, unit) exists in several locations, the first row absorbs the
      new total and the duplicates are dropped — acceptable loss of
      location detail for the rare duplicate case.
    - (name, unit) missing here but in DB → row deleted (used up).
    - new (name, unit) → inserted with defaults (pantry/manual).
    """
    from lib.inventory import InventoryItem, mutate_inventory

    new_by_key: dict[tuple[str, str], dict] = {}
    for entry in items:
        name = (entry.get("item") or "").strip()
        if not name:
            continue
        key = (name.lower(), (entry.get("unit") or "").lower().strip())
        new_by_key[key] = entry

    def reconcile(current: list[InventoryItem]) -> tuple[None, bool]:
        before = [item.to_dict() for item in current]
        kept: list[InventoryItem] = []
        seen: set[tuple[str, str]] = set()
        for item in current:
            key = (item.name.lower().strip(), item.unit.lower().strip())
            if key not in new_by_key:
                continue  # used up → drop row
            if key in seen:
                continue  # duplicate location row collapsed
            seen.add(key)
            amount = parse_amount_to_float(new_by_key[key].get("amount"))
            item.quantity = amount if amount is not None else item.quantity
            kept.append(item)

        for key, entry in new_by_key.items():
            if key not in seen:
                amount = parse_amount_to_float(entry.get("amount"))
                kept.append(InventoryItem(
                    name=entry["item"].strip(),
                    quantity=amount if amount is not None else 1.0,
                    unit=(entry.get("unit") or "ct").strip() or "ct",
                ))

        current[:] = kept
        changed = [item.to_dict() for item in current] != before
        return None, changed

    mutate_inventory(reconcile)


def find_match(item_name: str, pantry: list[dict]) -> Optional[dict]:
    """The pantry entry naming the same food as `item_name`, or None.

    Exact name first, then the head-noun matcher shared with Cook Now and Use
    It Up. The old character-substring fallback is gone: it matched "lemon" to
    "Lemon pepper seasoning" and every peanut-butter line to the "butter"
    staple row, and 436597d already replaced it everywhere else. The
    head-noun matcher runs on `_match_text(item_name)` rather than the fully
    raw string: prep-note parentheticals inject noise tokens that produce
    wrong matches ("cooking oil (for enchilada red sauce)" was matching an
    enchilada sauce row), but a parenthetical carrying alternatives
    ("almond butter (or peanut ...)") is kept, since dropping it loses a real
    match. The exact-name check above still runs on the untouched
    `item_name` — only the fuzzy match is affected.
    """
    target = _normalize(item_name)
    if not target:
        return None
    for entry in pantry:
        if _normalize(entry.get("item")) == target:
            return entry

    phrase = _ingredient_phrase(_match_text(item_name))
    if not phrase.tokens:
        return None
    for entry in pantry:
        name = entry.get("item") or ""
        if name and _covers(_phrase(name), phrase):
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
    # get_unit_family/convert_to_base_unit only lowercase, they don't strip —
    # unit_compatibility does both. Normalize once here so family lookups and
    # base-unit math agree with what unit_compatibility already decided.
    p_unit_norm = p_unit.lower().strip()
    unit_norm = (unit or "").lower().strip()
    p_family = get_unit_family(p_unit_norm)
    n_family = get_unit_family(unit_norm)

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
        n_base = convert_to_base_unit(n_amt, unit_norm, n_family)
        p_base = convert_to_base_unit(p_amt, p_unit_norm, p_family)
        if p_base >= n_base:
            return {"from_pantry": needed, "to_buy": None, "warning": None}
        # partial cover: pantry has p_base, need n_base; buy the rest in recipe's unit
        remaining_base = n_base - p_base
        remaining_in_recipe_unit = convert_from_base_unit(remaining_base, unit_norm, n_family)
        pantry_in_recipe_unit = convert_from_base_unit(p_base, unit_norm, n_family)
        return {
            "from_pantry": {"amount": format_amount(pantry_in_recipe_unit), "unit": unit},
            "to_buy": {"amount": format_amount(remaining_in_recipe_unit), "unit": unit},
            "warning": None,
        }

    # count / other: 1:1 when the units are the same or either side is generic.
    # This treats "6 cloves garlic" as covering "10 whole garlic" 1:1, which is
    # correct for almost every count ingredient (cloves, lemons, eggs, onions).
    # The rule lives in unit_compatibility so apply_decisions applies the same
    # one — they used to disagree.
    # Stripped as well as lowered: a padded " whole " would otherwise fall out
    # of GENERIC_COUNT and pick the pantry's unit for display instead of the
    # recipe's. Same normalization unit_compatibility applies.
    n_unit_lower = (unit or "").lower().strip()
    if unit_compatibility(p_unit, unit) == "one_to_one":
        # Display in the recipe's unit if specified, else the pantry's.
        out_unit = unit if n_unit_lower not in GENERIC_COUNT else (p_unit or unit)
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

            mode = unit_compatibility(p_unit, used_unit)
            if mode == "convert":
                # Same normalization as unit_compatibility (lower + strip) —
                # get_unit_family/convert_to_base_unit only lowercase, so a
                # padded unit ("10 lb " decremented by "1 g") would otherwise
                # resolve to family "other" here and silently skip the base-
                # unit conversion, subtracting raw amounts across mismatched
                # units instead.
                p_unit_norm = p_unit.lower().strip()
                used_unit_norm = used_unit.lower().strip()
                p_family = get_unit_family(p_unit_norm)
                p_base = convert_to_base_unit(p_amt, p_unit_norm, p_family)
                u_base = convert_to_base_unit(used_amt, used_unit_norm, p_family)
                remaining_base = max(0.0, p_base - u_base)
                if remaining_base <= 1e-9:
                    updated.pop(idx)
                else:
                    remaining_native = convert_from_base_unit(remaining_base, p_unit_norm, p_family)
                    entry["amount"] = format_amount(remaining_native)
            elif mode == "one_to_one":
                remaining = max(0.0, p_amt - used_amt)
                if remaining <= 1e-9:
                    updated.pop(idx)
                else:
                    entry["amount"] = format_amount(remaining)
            # If units don't match family, do nothing — caller should have warned.
            break
    return updated


def stock_for_ingredients(
    items: list[str],
    pantry: Optional[list[dict]] = None,
) -> list[Optional[dict]]:
    """For each ingredient name, the pantry row covering it — or None.

    Answers **presence, not sufficiency**: "is this food in the kitchen at all",
    not "is there enough". Sufficiency depends on the recipe's scale, which the
    reader changes on the fly (`/recipe/<name>` has a 1x-4x selector), so a
    server-side "enough" would be a lie the moment they scale it up — and
    deciding it client-side would mean a second copy of the unit-conversion
    rules that `unit_compatibility` is meant to own. Presence is the honest
    answer to "what would I have to go buy".

    Matching is delegated to :func:`find_match`, so this and the shopping list
    can never disagree about whether you own something.

    Returns a list positionally aligned with ``items`` — an entry is the matched
    ``{item, amount, unit}`` pantry row, or None. ``pantry=None`` loads the
    current inventory.
    """
    if pantry is None:
        pantry = load_pantry()
    return [find_match(name or "", pantry) for name in items]
