"""Consume-on-cook (Layer 2) — decrement inventory when you make a recipe.

Optional and additive: marking a recipe cooked subtracts its non-staple
ingredient amounts from tracked inventory, so true partial-package leftovers
become visible (e.g. 0.75 qt buttermilk left after a recipe that used ¼ cup).
Nothing requires this — inventory still self-cleans on expiry without it, and
staples are never decremented (KitchenOS assumes you always have them).

Reuses ``pantry.apply_decisions`` — the same unit-aware decrement the
shopping-list confirm uses — over the DB inventory table. Volume/weight amounts
convert within their family (cup → qt).

Inventory holds *containers*, not measured quantities: 188 of 198 count rows
sit at quantity exactly 1.0, meaning one package. Such a row is never
decremented — it is use-stamped instead (``last_used``/``use_count``), so a
recipe calling for three bay leaves cannot delete the jar.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from lib import paths
from lib.ingredient_aggregator import unit_compatibility
from lib.inventory_db import stamp_inventory_use
from lib.pantry import (
    apply_decisions,
    find_match,
    format_amount,
    load_pantry,
    parse_amount_to_float,
    save_pantry,
)
from lib.recipe_parser import parse_recipe_body, parse_recipe_file
from lib.use_it_up import _ingredient_phrase, _is_staple, _staple_phrases


def recipe_ingredients(recipe_name: str) -> Optional[list[dict]]:
    """Ingredient dicts ``[{amount, unit, item}]`` for a recipe, or None if missing."""
    path = paths.recipes_dir() / f"{recipe_name}.md"
    if not path.exists():
        return None
    parsed = parse_recipe_file(path.read_text(encoding="utf-8"))
    return parse_recipe_body(parsed.get("body", "")).get("ingredients", [])


def _record_use(bucket: list[dict], item: str, unit: Optional[str]) -> None:
    """Append a row to the use-recorded list, deduped by (item, unit).

    A recipe can name the same inventory row twice ("1 tsp cinnamon" in the
    rub and "1/2 tsp" in the glaze); that is one container, used once.
    """
    key = ((item or "").lower(), (unit or "").lower())
    for existing in bucket:
        if ((existing["item"] or "").lower(),
                (existing["unit"] or "").lower()) == key:
            return
    bucket.append({"item": item, "unit": unit})


def consume_recipe(recipe_name: str, servings: float = 1.0,
                   staples: Optional[set] = None,
                   now: Optional[str] = None) -> dict:
    """Apply a cooked recipe to inventory. Returns a four-outcome summary.

    ``servings`` multiplies the amounts (a double batch → 2.0). ``now`` is the
    use-stamp timestamp; defaults to the current time and is injectable for
    tests. Returns::

        {recipe, consumed: [{item, unit, before, after, depleted}],
         skipped_staples: [...], not_tracked: [...],
         use_recorded: [{item, unit}], error?}

    Every ingredient lands in exactly one bucket:

    - ``skipped_staples`` — an assumed-on-hand staple; never tracked.
    - ``not_tracked``     — no inventory row names this food.
    - ``consumed``        — quantity actually decremented.
    - ``use_recorded``    — the row was used but must not be decremented,
      because its units don't convert, its amount is unparseable, or it is a
      container (quantity exactly 1.0).

    The container gate is the load-bearing safety rule: 188 of 198 count rows
    in the real inventory sit at exactly 1.0, meaning "one package". Subtracting
    from those would delete a whole jar of bay leaves for a recipe using three.
    A missed depletion self-heals through the expiry prune; a deleted jar does
    not, and pollutes the shopping list.
    """
    ings = recipe_ingredients(recipe_name)
    if ings is None:
        return {"recipe": recipe_name, "error": "recipe not found",
                "consumed": [], "skipped_staples": [], "not_tracked": [],
                "use_recorded": []}

    staple_sets = _staple_phrases(staples)
    pantry = load_pantry()
    before = {e["item"]: parse_amount_to_float(e["amount"]) or 0.0 for e in pantry}
    units = {e["item"]: e.get("unit") for e in pantry}

    decisions: list[dict] = []
    skipped_staples: list[str] = []
    not_tracked: list[str] = []
    use_recorded: list[dict] = []
    matched: set[str] = set()

    for ing in ings:
        item = (ing.get("item") or "").strip()
        if not item:
            continue
        if _is_staple(_ingredient_phrase(item), staple_sets):
            skipped_staples.append(item)
            continue
        match = find_match(item, pantry)
        if match is None:
            not_tracked.append(item)
            continue

        p_unit = match.get("unit") or ""
        p_qty = parse_amount_to_float(match.get("amount"))
        amt = parse_amount_to_float(ing.get("amount"))
        scaled = amt * servings if amt is not None else None

        if (scaled is None
                or p_qty is None
                or p_qty == 1.0
                or unit_compatibility(p_unit, ing.get("unit") or "") is None):
            _record_use(use_recorded, match["item"], p_unit)
            continue

        decisions.append({
            "item": match["item"],  # exact pantry name so apply_decisions matches
            "amount": format_amount(scaled),
            "unit": ing.get("unit") or "",
        })
        matched.add(match["item"])

    if decisions:
        updated = apply_decisions(decisions, pantry)
        save_pantry(updated)
        after = {e["item"]: parse_amount_to_float(e["amount"]) or 0.0
                 for e in updated}
    else:
        after = before

    consumed = []
    for name in sorted(matched):
        b = before.get(name, 0.0)
        if name not in after:
            consumed.append({"item": name, "unit": units.get(name),
                             "before": b, "after": 0.0, "depleted": True})
        elif after[name] < b - 1e-9:
            consumed.append({"item": name, "unit": units.get(name),
                             "before": b, "after": after[name],
                             "depleted": False})
        else:
            # Defensive: the gate should have caught this. Report it as use
            # rather than silently claiming a decrement that didn't happen.
            _record_use(use_recorded, name, units.get(name))

    # Stamp AFTER save_pantry — save_pantry is DELETE-all + re-INSERT, so a
    # stamp written before it would be replaced by the pre-cook row values.
    stamp_at = now or datetime.now().isoformat(timespec="seconds")
    refs = [(u["item"], u["unit"] or "") for u in use_recorded]
    refs += [(c["item"], c["unit"] or "") for c in consumed]
    if refs:
        stamp_inventory_use(refs, stamp_at)

    return {"recipe": recipe_name, "consumed": consumed,
            "skipped_staples": skipped_staples, "not_tracked": not_tracked,
            "use_recorded": use_recorded}
