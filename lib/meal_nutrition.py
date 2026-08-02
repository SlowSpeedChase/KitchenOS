"""Calories and macros for a meal bundle, rolled up from its sub-recipes.

A meal (`vault/Meals/<Name>.meal.md`) stores no nutrition of its own — it is
derived here, at read time, every time. That is deliberate and load-bearing:
`backfill_nutrition.py --force` re-derives per-recipe macros whenever the USDA
resolver improves, so a rollup stamped into `.meal.md` frontmatter would go
stale silently and nothing would ever notice. Nothing in this module writes.

The trust rules are not new. This is a composition of three existing pieces:

- ``meal_plan_parser.sub_multiplier`` — the shared rule for how a sub-recipe's
  own ``servings`` scales (the sibling ``flatten_to_recipes`` isn't used here: it
  loads the meal by name off disk, and this has to work for a Meal a caller is
  still holding in memory)
- ``serving_ledger.recipe_macros`` — the safe frontmatter read that degrades to
  ``None`` on any per-recipe failure
- ``nutrition_quality.macro_eligible`` — the same gate the suggester ranks on

An untrusted sub-recipe is **excluded from the totals and named**, never counted
as zero and never counted at face value. The distinction matters most for
``servings_unknown``: a recipe with no serving count had its batch divided by 1,
so its "per-serving" macros are whole-recipe totals. Multiplying one of those by
1.5 would add thousands of phantom kcal to the meal — worse than admitting the
number is unknown.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from lib.meal_plan_parser import sub_multiplier
from lib.nutrition_quality import macro_eligible
from lib.serving_ledger import recipe_macros

MACRO_KEYS = ("calories", "protein", "carbs", "fat")


def _eligibility(macros: Optional[dict]) -> tuple[bool, list[str]]:
    """Is this sub-recipe's macro data trustworthy? Reuses the suggester's gate.

    ``recipe_macros`` returns a macro-shaped dict while ``macro_eligible`` reads
    an index-shaped one, so translate rather than re-reading the file. A missing
    recipe (``None``) can't be judged by the gate at all — it's simply absent.
    """
    if macros is None:
        return False, ["missing"]
    return macro_eligible({
        "nutrition_calories": macros.get("calories"),
        # Protein is load-bearing for the plausibility bounds, not decoration:
        # without it a sub-recipe claiming 244 g/serving passes on calories
        # alone and its garbage lands in the bundle's rollup.
        "nutrition_protein": macros.get("protein"),
        "nutrition_coverage": macros.get("coverage"),
        "servings": macros.get("servings"),
    })


def meal_nutrition(
    meal,
    recipes_dir: Path,
    macro_cache: Optional[dict] = None,
) -> dict:
    """Roll a meal's sub-recipes up into one set of macros.

    Args:
        meal: a ``meal_loader.Meal``.
        recipes_dir: the Recipes folder, for per-recipe frontmatter lookups.
        macro_cache: optional ``{recipe_name: macros | None}`` memo, so a caller
            rolling up many meals (``/api/meals``) reads each recipe file once
            rather than once per meal that references it. Mutated in place.

    Returns:
        ``{calories, protein, carbs, fat, sub: [...], incomplete: bool,
        excluded: [name, ...]}``. Totals cover only the eligible sub-recipes;
        ``incomplete`` is True when any were left out, and ``excluded`` names
        them in the order they appear in the meal.
    """
    cache = macro_cache if macro_cache is not None else {}
    totals = {k: 0.0 for k in MACRO_KEYS}
    subs: list[dict] = []
    excluded: list[str] = []

    for sub in meal.sub_recipes:
        name = sub.recipe
        if name not in cache:
            cache[name] = recipe_macros(name, recipes_dir)
        macros = cache[name]
        eligible, reasons = _eligibility(macros)

        # The rollup is per *one* serving of the bundle (a caller placing it on a
        # board at x2 scales the result), so the outer factor is 1.0 — but route
        # it through the shared rule anyway, since a Meal built in memory by an
        # API caller hasn't been through meal_loader's coercion.
        servings = sub_multiplier(1.0, sub.servings)
        row = {
            "recipe": name,
            "servings": servings,
            "eligible": eligible,
            "reasons": reasons,
        }
        if eligible:
            for k in MACRO_KEYS:
                contribution = float(macros[k]) * servings
                row[k] = contribution
                totals[k] += contribution
        else:
            for k in MACRO_KEYS:
                row[k] = None
            excluded.append(name)
        subs.append(row)

    return {
        **totals,
        "sub": subs,
        "incomplete": bool(excluded),
        "excluded": excluded,
    }
