"""Cook-Now suggester — recipes ranked by how much of what they need is on hand.

Answers "what can I cook right now?" by scoring every recipe in the library by
the fraction of its ingredients currently in inventory. The best-covered recipes
surface first, with the still-missing ingredients listed so a near-miss ("you
have everything but buttermilk") is obvious at a glance.

This is the coverage-ranked complement to ``use_it_up`` (which ranks by *expiry
urgency*). The coverage calculation itself lives in ``use_it_up`` as
``recipe_coverage`` — both modules rank by it, this one across the whole library
and that one within each at-risk item, so it is written once rather than twice.

Staples are assumed always on hand: never "missing", never penalizing
coverage. A recipe made *entirely* of staples is demoted hard rather than
hidden — see ``_ALL_STAPLES_WEIGHT``. Matching is presence-only, not
quantity-aware.
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

# Protein per serving at which a dish counts as properly feeding you — read from
# the user's own target rather than guessed.
#
# This was hardcoded at 30 g, with a comment claiming it was "set against a
# 190 g/day target across roughly four eating occasions". Four times thirty is
# 120, not 190, so the factor saturated at two-thirds of a real eating occasion
# and a 30 g dish scored identically to a 68 g one. The ranking could not tell a
# light meal from a heavy one, which is most of what it exists to do.
EATING_OCCASIONS_PER_DAY = 4

#: Used when My Macros.md is absent or unreadable. Deliberately 120 g — the old
#: hardcoded 30 g x 4 — so a vault with no stated targets behaves exactly as it
#: did before, rather than silently acquiring someone else's numbers.
DEFAULT_DAILY_PROTEIN_G = 120.0


def meal_protein_target() -> float:
    """Protein per eating occasion, from My Macros.md.

    Falls back to ``DEFAULT_DAILY_PROTEIN_G`` when the vault states no target,
    and never returns zero — the value is a divisor on every render.
    """
    daily = None
    try:
        from lib import paths
        from lib.macro_targets import load_macro_targets
        targets = load_macro_targets(paths.vault_root())
        if targets is not None and targets.protein:
            daily = float(targets.protein)
    except Exception:
        daily = None
    if not daily or daily <= 0:
        daily = DEFAULT_DAILY_PROTEIN_G
    return daily / EATING_OCCASIONS_PER_DAY

# How far nutrition may move a ranking: a dish with no protein keeps 60% of its
# score, one at or above MEAL_PROTEIN_G keeps all of it. Dish type alone was not
# enough — muffins are `breakfast`, so they classify as a meal and came back at
# #2 on the real pantry. They are a meal the way a scone is a meal.
_NUTRITION_FLOOR = 0.6

# Unknown macros land mid-range rather than at the floor. Missing data is not
# evidence of poor nutrition, and burying every unmeasured recipe would quietly
# shrink the library the same way trusting bad macros quietly corrupted it.
_NUTRITION_UNKNOWN = 0.8


def _nutrition_factor(protein, target: float) -> float:
    """0.6–1.0 by how much protein a serving actually delivers."""
    if protein is None:
        return _NUTRITION_UNKNOWN
    share = min(max(protein, 0.0) / target, 1.0)
    return _NUTRITION_FLOOR + (1.0 - _NUTRITION_FLOOR) * share


# How many servings before a cooking session counts as batch cooking. Below this
# you are paying a whole session's setup and cleanup for a single meal; above it
# there is no further credit, because a 20-serving recipe is not five times
# better than a 4-serving one — it's the same trip to the stove.
BATCH_SERVINGS = 4.0
_YIELD_FLOOR = 0.85

#: Unknown yield sits at the midpoint, the same rule as unknown macros and
#: unknown cook time: missing data is not evidence of a bad recipe.
_YIELD_UNKNOWN = (_YIELD_FLOOR + 1.0) / 2


def _yield_factor(servings) -> float:
    """0.85–1.0 by how many meals one cooking session buys.

    The point of a batch on a week with no time is that it feeds you more than
    once — leftovers frozen and rotated are what make that variety rather than
    the same dinner three nights running.
    """
    try:
        count = float(servings)
    except (TypeError, ValueError):
        return _YIELD_UNKNOWN            # "6-8", "", None — all seen in this corpus
    if count <= 0:
        return _YIELD_UNKNOWN
    if count >= BATCH_SERVINGS:
        return 1.0
    span = (count - 1.0) / (BATCH_SERVINGS - 1.0)
    return _YIELD_FLOOR + (1.0 - _YIELD_FLOOR) * max(span, 0.0)


# What's already cooked doesn't need cooking. A banked recipe is demoted hard
# rather than hidden: it's still a true answer to "what could I eat", and the
# freezer tray above the list links to it — but it is the wrong answer to "what
# should I make", which is the question this page is asked.
_BANKED_WEIGHT = 0.5

# A recipe made entirely of staples — pasta dough, spice blends, plain
# pancakes — is perpetually "ready": staples never age out, so its coverage
# never moves and it squats at the top of a list being asked "what should I
# make". Demoted rather than hidden, same philosophy as _BANKED_WEIGHT
# (fresh-pasta night is real, so it stays findable by scrolling), but harder:
# a banked demotion expires when the freezer empties, an all-staples recipe
# never stops being all-staples. One real ingredient is enough to escape —
# then the recipe only ranks high when that ingredient is actually on hand,
# which is a legitimate claim on the top of the list. An unparseable
# ingredient counts as a non-staple, so a data gap escapes the demotion
# rather than triggering it.
_ALL_STAPLES_WEIGHT = 0.25


# Cook time, deliberately the weakest of the three factors: at most a 15% swing.
# Given two meals you can equally make and that will equally feed you, the faster
# one is the better answer — but speed must never promote a snack over dinner,
# which is the failure this whole ranking exists to fix.
FAST_MINUTES = 20.0
SLOW_MINUTES = 90.0
_SPEED_FLOOR = 0.85

#: 147 of 254 recipes carry no readable time, so unknown sits at the midpoint
#: rather than the floor — the same rule as unknown macros. Penalising missing
#: data would bury more than half the library for not having been measured.
_SPEED_UNKNOWN = (_SPEED_FLOOR + 1.0) / 2


def _speed_factor(minutes) -> float:
    """0.85–1.0 by how quickly it can be on the table."""
    if minutes is None:
        return _SPEED_UNKNOWN
    if minutes <= FAST_MINUTES:
        return 1.0
    if minutes >= SLOW_MINUTES:
        return _SPEED_FLOOR
    span = (minutes - FAST_MINUTES) / (SLOW_MINUTES - FAST_MINUTES)
    return 1.0 - (1.0 - _SPEED_FLOOR) * span


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
             today: Optional[date] = None, limit: int = 30,
             banked: Optional[set] = None,
             protein_target: Optional[float] = None,
             per_group: bool = False) -> dict:
    """Rank recipes by what you should actually make right now.

    Seven factors, multiplied: **coverage** (can you make it) × **meal tier**
    (is it a meal) × **nutrition** (will it feed you) × **speed** (how long
    until it's on the table) × **yield** (how many meals one session buys) ×
    **banked** (is it already cooked and in the freezer) × **all-staples**
    (is its readiness anything more than the staple assumption). Coverage
    alone answered a different question than the one the page is asked — on a
    pantry of dry goods it returned muffins, brownies, cookies and frosting,
    all correctly and none of them dinner.

    Returns ``{"recipes": [...]}``, each entry ``{recipe, image, dish_type,
    group, have, total, coverage, missing, at_risk, meal_tier, protein,
    minutes, servings, banked, freezes_well, all_staples, score}``, sorted by
    ``score`` descending and capped at ``limit``. Every non-coverage factor is
    reported alongside it so a surface can explain the order rather than
    presenting it as given.

    ``per_group=True`` applies ``limit`` *within each chip group* instead of to
    the whole list. This is what the ``/cook-now`` page needs: it filters
    client-side from one payload, and a single global cap taken *after* the
    meal-tier weighting silently emptied three of its six chips — on the real
    pantry the best dessert ranked 264th of 409 (0.35 tier weight), so a
    ``limit=60`` payload never carried one, and tapping Desserts revealed
    nothing. The chip is a *filter*; the tier weight is an *ordering*. A cap
    that lets the ordering act as a filter makes the chip a dead control. The
    flat ``Cook Now.md`` note keeps the global cap — it has no chips.

    Staples count as always-on-hand: they raise coverage but never
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
    if banked is None:
        # One query for the whole library, not one per recipe.
        from lib.serving_ledger import banked_recipes
        try:
            banked = banked_recipes()
        except Exception:
            banked = set()      # a ledger problem must not blank the suggestions
    if protein_target is None:
        protein_target = meal_protein_target()

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
        have, total, missing, at_risk, staple_count = recipe_coverage(
            ingredients, inv_phrases, staple_sets, at_risk_sets)

        coverage = have / total
        tier = meal_tier_for(recipe.get("dish_type"))
        minutes = recipe.get("total_time_minutes")
        protein = _trustworthy_protein(recipe)
        servings = recipe.get("servings")
        is_banked = recipe["name"] in banked
        # total >= 1 is guaranteed: empty ingredient lists are skipped above.
        all_staples = staple_count == total

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
            "minutes": minutes,
            "servings": servings,
            "banked": is_banked,
            "all_staples": all_staples,
            # Reported, never scored on: too sparse across the corpus to rank by.
            # A surface can label a batch "freezes well"; it must not reorder on
            # a field almost every recipe answers `null` to.
            "freezes_well": recipe.get("freezes_well"),
            "score": round(
                coverage
                * _TIER_WEIGHT[tier]
                * _nutrition_factor(protein, protein_target)
                * _speed_factor(minutes)
                * _yield_factor(servings)
                * (_BANKED_WEIGHT if is_banked else 1.0)
                * (_ALL_STAPLES_WEIGHT if all_staples else 1.0),
                4,
            ),
        })

    # Seven factors, multiplied — see the docstring. Protein and time sit inside the
    # score rather than acting as tiebreaks because coverage almost never ties,
    # so a tiebreak would never actually fire — which is how a 10 g muffin sat
    # second on a real pantry. `have` remains the final tiebreak so the order is
    # deterministic.
    recipes.sort(
        key=lambda r: (r["score"], r["protein"] or 0.0, r["have"]),
        reverse=True,
    )
    if not per_group:
        return {"recipes": recipes[:limit]}
    # Order is preserved — the list stays one score-sorted ranking — and each
    # group contributes at most `limit` entries, so every chip has depth even
    # when one group's scores all sit below another's.
    taken: dict[str, int] = {}
    kept = []
    for r in recipes:
        n = taken.get(r["group"], 0)
        if n < limit:
            taken[r["group"]] = n + 1
            kept.append(r)
    return {"recipes": kept}


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
