"""Cook-Now suggester — recipes ranked by how much of what they need is on hand.

Answers "what can I cook right now?" by scoring every recipe in the library by
the fraction of its ingredients currently in inventory. The best-covered recipes
surface first, with the still-missing ingredients listed so a near-miss ("you
have everything but buttermilk") is obvious at a glance.

This is the coverage-ranked complement to ``use_it_up`` (which ranks by *expiry
urgency*). The coverage calculation itself lives in ``use_it_up`` as
``recipe_coverage`` — both modules rank by it, this one across the whole library
and that one within each at-risk item, so it is written once rather than twice.

Staples are assumed always on hand: never "missing", never penalizing coverage.
Matching is presence-only, not quantity-aware.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from lib.use_it_up import (
    _phrase,
    _staple_phrases,
    at_risk_items,
    recipe_coverage,
)

# The 13-value stored vocabulary collapsed into the 6 chips the page shows.
# Stored data stays precise; the interface stays usable. Adding a dish type to
# normalizer.VALID_DISH_TYPES without adding it here fails tests/test_cook_now.py.
DISH_TYPE_GROUPS = {
    "Mains": ("main", "sandwich", "soup"),
    "Breakfast": ("breakfast",),
    "Sides": ("side", "salad", "bread", "sauce"),
    "Snacks": ("snack", "appetizer", "dip"),
    "Desserts": ("dessert",),
    "Drinks": ("drink",),
}

# A recipe with a missing or unrecognized dish_type shows under Mains rather
# than vanishing: the filter must never make a cookable recipe unreachable
# because of a data gap.
DEFAULT_GROUP = "Mains"

# How much of an actual meal each dish type is.
#
# A pantry is mostly dry goods — flour, sugar, cocoa, baking powder, butter —
# so ranking on ingredient coverage alone systematically favours baking. On the
# real inventory the top five results were Blueberry Muffins, Gooey Chocolate
# Brownies, Chewy Peanut Butter Cookies, Strawberry Brownies and Strawberry
# Buttercream Frosting: all correct, none of them dinner. "What *can* I make"
# and "what *should* I make" are different questions on that inventory, and the
# page was answering the first while being asked the second.
MEAL_TIER = {
    "meal": ("main", "soup", "sandwich", "salad", "breakfast"),
    "component": ("side", "bread", "sauce", "dip", "appetizer"),
    "treat": ("snack", "drink"),
    "dessert": ("dessert",),
}

_TIER_FOR_DISH_TYPE = {
    dish_type: tier
    for tier, dish_types in MEAL_TIER.items()
    for dish_type in dish_types
}

# Coverage is multiplied by these. Weights rather than a hard sort so the
# ranking degrades honestly: a main you're one ingredient short of (0.8 × 1.0)
# still beats a fully-stocked dessert (1.0 × 0.35), because the card names what
# is missing and "closest real meal" is the useful answer — but a main you're
# missing most of (0.3) correctly sinks below it. The crossover lands near
# "missing more than half", which is where a suggestion stops being actionable.
_TIER_WEIGHT = {"meal": 1.0, "component": 0.7, "treat": 0.5, "dessert": 0.35}

#: Same reasoning as DEFAULT_GROUP — a data gap must not bury a real recipe.
DEFAULT_TIER = "meal"

# Protein per serving at which a dish counts as properly feeding you. Set
# against a 190 g/day target across roughly four eating occasions.
MEAL_PROTEIN_G = 30.0

# How far nutrition may move a ranking: a dish with no protein keeps 60% of its
# score, one at or above MEAL_PROTEIN_G keeps all of it. Dish type alone was not
# enough — muffins are `breakfast`, so they classify as a meal and came back at
# #2 on the real pantry. They are a meal the way a scone is a meal.
_NUTRITION_FLOOR = 0.6

# Unknown macros land mid-range rather than at the floor. Missing data is not
# evidence of poor nutrition, and burying every unmeasured recipe would quietly
# shrink the library the same way trusting bad macros quietly corrupted it.
_NUTRITION_UNKNOWN = 0.8


def _nutrition_factor(protein) -> float:
    """0.6–1.0 by how much protein a serving actually delivers."""
    if protein is None:
        return _NUTRITION_UNKNOWN
    share = min(max(protein, 0.0) / MEAL_PROTEIN_G, 1.0)
    return _NUTRITION_FLOOR + (1.0 - _NUTRITION_FLOOR) * share


def meal_tier_for(dish_type: Optional[str]) -> str:
    """How much of a meal this dish type is. Unknown values count as a meal."""
    if not isinstance(dish_type, str):
        return DEFAULT_TIER
    return _TIER_FOR_DISH_TYPE.get(dish_type.strip().lower(), DEFAULT_TIER)


def _trustworthy_protein(recipe: dict):
    """Per-serving protein, but only when the macros can be believed.

    Routed through the same gate the suggester uses. Without it this would
    reintroduce the failure Phase 1 fixed, in a new place: the recipe claiming
    244 g of protein per serving would top every list it appears in.
    """
    from lib.nutrition_quality import macro_eligible

    eligible, _ = macro_eligible(recipe)
    if not eligible:
        return None
    try:
        return float(recipe.get("nutrition_protein"))
    except (TypeError, ValueError):
        return None

_GROUP_FOR_DISH_TYPE = {
    dish_type: group
    for group, dish_types in DISH_TYPE_GROUPS.items()
    for dish_type in dish_types
}


def group_for(dish_type: Optional[str]) -> str:
    """The chip group a dish_type belongs to. Unknown values fall back to Mains."""
    # recipe_parser's hand-rolled YAML reader (lib/recipe_parser.py:49-55) can
    # hand back a list (`dish_type: [dessert]`) or an int (`dish_type: 2`) for
    # malformed frontmatter — normalizer.py:315 hits the same shape and guards
    # the same way. Without this, one bad line in any of 239 recipe files
    # raises AttributeError here and 500s the whole /api/cook-now page.
    if not isinstance(dish_type, str):
        return DEFAULT_GROUP
    return _GROUP_FOR_DISH_TYPE.get(dish_type.strip().lower(), DEFAULT_GROUP)


def generate(items: Optional[list] = None, recipe_index: Optional[list] = None,
             today: Optional[date] = None, limit: int = 30) -> dict:
    """Rank recipes by ingredient coverage against current inventory.

    Returns ``{"recipes": [...]}``, each entry
    ``{recipe, image, dish_type, group, have, total, coverage, missing, at_risk}``,
    sorted by coverage (then have count, then fewest missing) descending and capped at
    ``limit``. Staples count as always-on-hand: they raise coverage but never
    appear in ``missing``. ``at_risk`` is True when the recipe uses an item in
    the expiry window (per ``use_it_up.at_risk_items``).
    """
    if items is None:
        from lib.inventory import read_inventory
        items = read_inventory()
    if recipe_index is None:
        from lib import paths
        from lib.recipe_index import get_recipe_index
        recipe_index = get_recipe_index(paths.recipes_dir(), include_ingredients=True)

    staple_sets = _staple_phrases()
    inv_phrases = [_phrase(it.name) for it in items]
    at_risk_sets = [
        _phrase(it.name)
        for _, it in at_risk_items(items, today, staple_sets)
    ]

    recipes = []
    for recipe in recipe_index:
        ingredients = recipe.get("ingredient_items", [])
        if not ingredients:
            continue

        # Shared with use_it_up.suggest, which ranks each at-risk item's recipes
        # by the same coverage — one calculation, not two that can drift.
        have, total, missing, at_risk = recipe_coverage(
            ingredients, inv_phrases, staple_sets, at_risk_sets)

        coverage = have / total
        tier = meal_tier_for(recipe.get("dish_type"))
        protein = _trustworthy_protein(recipe)

        recipes.append({
            "recipe": recipe["name"],
            "image": recipe.get("image"),
            "dish_type": recipe.get("dish_type"),
            "group": group_for(recipe.get("dish_type")),
            "have": have,
            "total": total,
            "coverage": coverage,
            "missing": missing,
            "at_risk": at_risk,
            # Reported, not just used, so the page can say why something ranked
            # where it did rather than presenting an unexplained order.
            "meal_tier": tier,
            "protein": protein,
            "score": round(
                coverage * _TIER_WEIGHT[tier] * _nutrition_factor(protein), 4),
        })

    # Three factors, multiplied: can you make it, is it a meal, will it feed
    # you. Protein is inside the score rather than a tiebreak because coverage
    # almost never ties, so as a tiebreak it would never actually fire — which
    # is how a 10 g muffin sat second on a real pantry. `have` remains the final
    # tiebreak so the order is deterministic.
    recipes.sort(
        key=lambda r: (r["score"], r["protein"] or 0.0, r["have"]),
        reverse=True,
    )
    return {"recipes": recipes[:limit]}


def render_markdown(result: dict, today: Optional[date] = None) -> str:
    """Render the ranked coverage as the 'Cook Now.md' Obsidian note."""
    today = today or date.today()
    lines = [
        "---",
        "type: cook-now",
        f"last_updated: {today.isoformat()}",
        "---",
        "",
        "# 🍳 Cook Now",
        "",
        "> ⚠️ **Generated** from the KitchenOS database — recipes ranked by how "
        "much you already have on hand. Do not edit here; changes are overwritten.",
        "",
    ]

    recipes = result.get("recipes", [])
    if not recipes:
        lines.append("No recipes with ingredients in your library yet. 🤷\n")
        return "\n".join(lines) + "\n"

    lines += [
        "| Recipe | Have | Missing |",
        "|--------|------|---------|",
    ]
    any_at_risk = False
    for r in recipes:
        flag = " ⏳" if r["at_risk"] else ""
        any_at_risk = any_at_risk or r["at_risk"]
        pct = round(r["coverage"] * 100)
        have = f"{pct}% ({r['have']}/{r['total']})"
        missing = ", ".join(r["missing"]) if r["missing"] else "—"
        lines.append(f"| [[{r['recipe']}]]{flag} | {have} | {missing} |")

    if any_at_risk:
        lines += ["", "⏳ = uses an item expiring soon."]
    return "\n".join(lines) + "\n"


def write_note(today: Optional[date] = None) -> "object":
    """Regenerate the 'Cook Now.md' note at the vault root. Returns its path."""
    from lib import paths

    result = generate(today=today)
    path = paths.vault_root() / "Cook Now.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_markdown(result, today=today), encoding="utf-8")
    return path
