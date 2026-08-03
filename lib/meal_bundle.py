"""One composite plate, expressed as the cook rows that represent it on a week.

A plate (`vault/Meals/<Name>.meal.md`) is not a ledger row of its own. Placing
one creates **one ordinary cook per sub-recipe**, all sharing a `bundle_id`, so
that every consumer downstream — `day_totals`, the shopping list, the freezer,
`cook_history`, `on_track`, `verdict_nudge`, `cook_sweep` — keeps seeing "one
recipe at one scale" and needs no bundle awareness whatsoever. The bundle is a
creation transaction and a display grouping, never a placement constraint.

This module owns the one rule that turns a `Meal` into those rows, and it is the
only place `sub_multiplier` and `recipe_base_servings` meet for that purpose.
It exists as a layer above `serving_ledger` because `meal_loader` imports
`MEALS` from `serving_ledger`, so the ledger can never import the meal side back.

**The identity this is built to preserve:**

    day_totals[date]  ==  meal_nutrition(meal) x outer

`meal_nutrition` sums `per_serving_macros x sub_multiplier(1.0, sub.servings)`;
`day_totals` sums `per_serving_macros x placement.count`. Setting each member's
initial placement count equal to its share makes the two expressions the same
arithmetic, and `nutrition_quality.eligible_macros` makes them apply the same
trust gate. Place 1.0 per member instead and the identity breaks for every
fractional sub-recipe — 13 of the 45 in the live corpus are 0.5, and one is 0.15.
`tests/test_meal_bundle.py::TestTheIdentity` is what pins it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from lib import meal_loader, serving_ledger
from lib.meal_plan_parser import sub_multiplier
from lib.week_view import recipe_base_servings

# What a recipe is assumed to yield when its file is missing or unreadable —
# mirroring recipe_base_servings' own fallback, applied here to a nonsense
# stated yield (a negative `servings`) that would otherwise produce a negative
# batch and get the whole plate refused.
_FALLBACK_SERVINGS = 4.0


def plan_bundle(meal, outer_scale: float = 1.0) -> list[dict]:
    """One Meal at ``outer_scale`` -> the member specs ``create_bundle`` wants.

    For each sub-recipe::

        share             = sub_multiplier(outer_scale, sub.servings)
        scale             = share
        servings_produced = recipe_base_servings(sub.recipe) * share
        initial_placement_count = share

    ``share`` is both the batch multiplier and the servings eaten at the slot.
    That is deliberate, not a coincidence — see the module docstring for why the
    two must be equal.

    Cooking a half batch of an 8-serving dip and eating half a serving leaves
    3.5 unassigned. That is correct rather than a bug: the freezer chip is where
    those go, and it is the same arithmetic the shopping list and `cook_sweep`
    already apply to ``scale``.
    """
    members = []
    for sub in meal.sub_recipes:
        share = sub_multiplier(outer_scale, sub.servings)
        base = recipe_base_servings(sub.recipe)
        # recipe_base_servings returns the file's stated yield, which can be
        # nonsense (`servings: -1` comes back as -1.0). A non-positive batch
        # would fail create_bundle's validation and refuse the whole plate, so
        # fall back the same way a missing file does.
        if base <= 0:
            base = _FALLBACK_SERVINGS
        members.append({
            "recipe": sub.recipe,
            "scale": share,
            "servings_produced": base * share,
            "initial_placement_count": share,
        })
    return members


def place_meal(meal_name: str, week: str, date: Optional[str] = None,
               meal_slot: Optional[str] = None, scale: float = 1.0,
               meals_dir: Optional[Path] = None) -> dict:
    """Put a plate on a week: load it, plan its members, write the bundle.

    Raises ``ValueError`` when the meal is unknown or carries no sub-recipes —
    the API turns those into a 404 and a 400 respectively. An empty plate would
    otherwise create a bundle with no rows, which is a bundle that does not exist.
    """
    meal = meal_loader.load_meal(meal_name, meals_dir=meals_dir)
    if meal is None:
        raise ValueError(f"meal '{meal_name}' not found")
    if not meal.sub_recipes:
        raise ValueError(f"meal '{meal_name}' has no sub-recipes to place")
    return serving_ledger.create_bundle(
        meal.name, plan_bundle(meal, scale), week,
        date=date, meal=meal_slot)


def group_bundles(cooks: list) -> list[dict]:
    """Partition a week's cooks into plates and standalone cooks, in order.

    Grouped by ``(bundle_id, date, meal)`` rather than ``bundle_id`` alone: a
    member dragged out of the plate keeps its bundle id but now lives in another
    cell, and drawing it as part of a card it is not in would be a lie. It
    becomes its own group, which is honest — you really did move the rice.

    Returns ``[{bundle_id, bundle_name, date, meal, cooks: [...]}, ...]`` with
    ``bundle_id`` None for a standalone cook. Lives here rather than only in the
    planner's JS so the grouping key has one definition.
    """
    groups: list[dict] = []
    index: dict = {}
    for cook in cooks:
        key = (cook.get("bundle_id"), cook.get("date"), cook.get("meal"))
        if cook.get("bundle_id") and key in index:
            index[key]["cooks"].append(cook)
            continue
        group = {
            "bundle_id": cook.get("bundle_id"),
            "bundle_name": cook.get("bundle_name"),
            "date": cook.get("date"),
            "meal": cook.get("meal"),
            "cooks": [cook],
        }
        groups.append(group)
        if cook.get("bundle_id"):
            index[key] = group
    return groups
