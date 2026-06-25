"""Consume-on-cook (Layer 2) — decrement inventory when you make a recipe.

Optional and additive: marking a recipe cooked subtracts its non-staple
ingredient amounts from tracked inventory, so true partial-package leftovers
become visible (e.g. 0.75 qt buttermilk left after a recipe that used ¼ cup).
Nothing requires this — inventory still self-cleans on expiry without it, and
staples are never decremented (KitchenOS assumes you always have them).

Reuses ``pantry.apply_decisions`` — the same unit-aware decrement the
shopping-list confirm uses — over the DB inventory table. Volume/weight amounts
convert within their family (cup → qt); cross-family pairs it can't convert
without density are left untouched and reported.
"""
from __future__ import annotations

from typing import Optional

from lib import paths
from lib.pantry import (
    apply_decisions,
    find_match,
    format_amount,
    load_pantry,
    parse_amount_to_float,
    save_pantry,
)
from lib.recipe_matcher import _content_tokens
from lib.recipe_parser import parse_recipe_body, parse_recipe_file
from lib.use_it_up import _is_staple, _staple_token_sets


def recipe_ingredients(recipe_name: str) -> Optional[list[dict]]:
    """Ingredient dicts ``[{amount, unit, item}]`` for a recipe, or None if missing."""
    path = paths.recipes_dir() / f"{recipe_name}.md"
    if not path.exists():
        return None
    parsed = parse_recipe_file(path.read_text(encoding="utf-8"))
    return parse_recipe_body(parsed.get("body", "")).get("ingredients", [])


def consume_recipe(recipe_name: str, servings: float = 1.0,
                   staples: Optional[set] = None) -> dict:
    """Decrement inventory by a cooked recipe's non-staple ingredients.

    ``servings`` multiplies the amounts (cook a double batch → 2.0). Returns:
        {recipe, consumed: [{item, unit, before, after, depleted}],
         skipped_staples: [...], not_tracked: [...], unconvertible: [...], error?}
    where ``not_tracked`` ingredients aren't in inventory (likely staples you
    don't track) and ``unconvertible`` matched an item but couldn't convert units.
    """
    ings = recipe_ingredients(recipe_name)
    if ings is None:
        return {"recipe": recipe_name, "error": "recipe not found",
                "consumed": [], "skipped_staples": [], "not_tracked": [],
                "unconvertible": []}

    staple_sets = _staple_token_sets(staples)
    pantry = load_pantry()
    before = {e["item"]: parse_amount_to_float(e["amount"]) or 0.0 for e in pantry}
    units = {e["item"]: e.get("unit") for e in pantry}

    decisions, skipped_staples, not_tracked, matched = [], [], [], set()
    for ing in ings:
        item = (ing.get("item") or "").strip()
        if not item:
            continue
        if _is_staple(_content_tokens(item), staple_sets):
            skipped_staples.append(item)
            continue
        match = find_match(item, pantry)
        if match is None:
            not_tracked.append(item)
            continue
        amt = parse_amount_to_float(ing.get("amount"))
        scaled = amt * servings if amt is not None else None
        decisions.append({
            "item": match["item"],  # exact pantry name so apply_decisions matches
            "amount": format_amount(scaled) if scaled is not None else ing.get("amount"),
            "unit": ing.get("unit") or "",
        })
        matched.add(match["item"])

    updated = apply_decisions(decisions, pantry)
    save_pantry(updated)
    after = {e["item"]: parse_amount_to_float(e["amount"]) or 0.0 for e in updated}

    consumed, unconvertible = [], []
    for name in matched:
        b = before.get(name, 0.0)
        if name not in after:
            consumed.append({"item": name, "unit": units.get(name),
                             "before": b, "after": 0.0, "depleted": True})
        elif after[name] < b - 1e-9:
            consumed.append({"item": name, "unit": units.get(name),
                             "before": b, "after": after[name], "depleted": False})
        else:
            unconvertible.append(name)  # matched but units didn't convert

    return {"recipe": recipe_name, "consumed": consumed,
            "skipped_staples": skipped_staples, "not_tracked": not_tracked,
            "unconvertible": unconvertible}
