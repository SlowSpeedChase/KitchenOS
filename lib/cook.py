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
from lib.ingredient_aggregator import (
    convert_to_base_unit,
    get_unit_family,
    unit_compatibility,
)
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


def _convert_base_amounts(p_qty: float, p_unit: str,
                          used_amt: float, used_unit: str) -> tuple[float, float]:
    """``(row, requested)`` expressed in the row's base unit.

    Mirrors ``apply_decisions``' base-unit math so the two cannot disagree about
    whether a decrement would empty a row. A cook may *reduce* a row but must
    never *remove* one: rows are packages, so a `5 oz` row matched by a `250 g`
    line is a unit-of-sale mismatch, not five ounces about to run out. The real
    library contains exactly that pair — a `5 oz` pumpkin row against `250 g
    pumpkin puree` — and deleting it is the un-healable direction (a missed
    depletion self-heals via the expiry prune).
    """
    p_unit_norm = (p_unit or "").lower().strip()
    used_unit_norm = (used_unit or "").lower().strip()
    family = get_unit_family(p_unit_norm)
    return (convert_to_base_unit(p_qty, p_unit_norm, family),
            convert_to_base_unit(used_amt, used_unit_norm, family))


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

    from lib.inventory import read_inventory

    staple_sets = _staple_phrases(staples)
    pantry = load_pantry()
    before = {e["item"]: parse_amount_to_float(e["amount"]) or 0.0 for e in pantry}
    units = {e["item"]: e.get("unit") for e in pantry}

    # Row-level facts the pantry view cannot express: load_pantry sums rows that
    # share (name, unit) across locations, so two 1-ct jars read as a single
    # 2.0 and the container gate fires on neither. Worse, save_pantry collapses
    # duplicate locations on write, so a decrement there deletes the second row
    # outright along with its stamps. Keep the row count and the smallest row so
    # the gate can see the parts rather than only the total.
    containers: dict[tuple[str, str], tuple[int, float]] = {}
    for it in read_inventory():
        key = (it.name.lower().strip(), it.unit.lower().strip())
        rows, smallest = containers.get(key, (0, it.quantity))
        containers[key] = (rows + 1, min(smallest, it.quantity))

    decisions: list[dict] = []
    skipped_staples: list[str] = []
    not_tracked: list[str] = []
    use_recorded: list[dict] = []
    matched: set[str] = set()
    # Base-unit total already committed against each row by earlier lines of this
    # same recipe. apply_decisions subtracts cumulatively, so the never-delete
    # guard has to see the running total: two 100 g lines against a 5 oz row
    # (≈141.7 g) each clear a check against the original quantity, then jointly
    # empty it.
    spent_base: dict[tuple[str, str], float] = {}

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
        r_unit = ing.get("unit") or ""
        mode = unit_compatibility(p_unit, r_unit)
        row_key = (match["item"].lower().strip(), p_unit.lower().strip())
        # Fall back to the summed view when the row isn't in the map, so an
        # unknown shape is treated as a single row of that size.
        rows, smallest = containers.get(row_key, (1, p_qty))

        # Weight/volume packages are containers too — 15 of 17 oz rows are a
        # 1.0 oz package — but their quantity isn't 1.0, so the count gate
        # misses them. Refuse any decrement that would empty the row, counting
        # what earlier lines of this recipe already spent against it.
        would_empty, u_base = False, 0.0
        if mode == "convert" and scaled is not None and p_qty is not None:
            row_base, u_base = _convert_base_amounts(p_qty, p_unit, scaled, r_unit)
            would_empty = (row_base - spent_base.get(row_key, 0.0) - u_base) <= 1e-9

        if (scaled is None
                or p_qty is None
                or mode is None
                # The container gate. `smallest` rather than the summed p_qty so
                # a 1-ct row hiding inside a multi-location total still counts,
                # and rows > 1 because spending from a sum picks a row for you.
                or p_qty == 1.0
                or smallest == 1.0
                or rows > 1
                or would_empty):
            _record_use(use_recorded, match["item"], p_unit)
            continue

        if mode == "convert":
            spent_base[row_key] = spent_base.get(row_key, 0.0) + u_base

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

    # One recipe can both decrement a row (a line whose units convert) and
    # merely use it (a line whose units don't). That is one cook touching one
    # row, so report the decrement — the stronger, more informative outcome —
    # and drop the redundant use record. This makes "exactly one bucket" true
    # per row as well as per line, and keeps the stamp below from counting the
    # same cook twice.
    consumed_keys = {((c["item"] or "").lower(), (c["unit"] or "").lower())
                     for c in consumed}
    use_recorded = [
        u for u in use_recorded
        if ((u["item"] or "").lower(), (u["unit"] or "").lower())
        not in consumed_keys
    ]

    # Stamp AFTER save_pantry. save_pantry re-reads inventory internally, so an
    # earlier stamp would survive — but a row this cook depleted is gone by now,
    # and stamping it would be a silent no-op UPDATE against a deleted row.
    # Doing it last means every ref names a row that still exists.
    stamp_at = now or datetime.now().isoformat(timespec="seconds")
    seen_refs: set[tuple[str, str]] = set()
    refs: list[tuple[str, str]] = []
    for entry in (*use_recorded, *consumed):
        ref = (entry["item"], entry["unit"] or "")
        key = (ref[0].lower(), ref[1].lower())
        if key not in seen_refs:
            seen_refs.add(key)
            refs.append(ref)
    if refs:
        stamp_inventory_use(refs, stamp_at)

    return {"recipe": recipe_name, "consumed": consumed,
            "skipped_staples": skipped_staples, "not_tracked": not_tracked,
            "use_recorded": use_recorded}
