"""Use-It-Up suggester — recipes that consume at-risk food before it spoils.

Layer 1 of the food-waste features: scan inventory for items that are expired or
expiring soon (per ``lib/expiry``), then rank the recipe library by how much of
that at-risk stock each recipe would use. Answers "what should I cook so nothing
goes to waste?".

Matching reuses ``recipe_matcher``'s normalized/singularized token containment,
so "fresh strawberries" in inventory matches a "strawberries" recipe ingredient.
Expiry-only for now; once cooking decrements inventory (Layer 2) this can also
rank by leftover *quantity*, not just expiry.
"""
from __future__ import annotations

from datetime import date
from typing import NamedTuple, Optional

from lib.expiry import SOON_THRESHOLD_DAYS
from lib.inventory import _format_quantity
from lib.recipe_matcher import _content_tokens, _head_token

# Expired items are twice as urgent as expiring-soon ones when ranking recipes.
_STATUS_RANK = {"expired": 0, "soon": 1}
_STATUS_WEIGHT = {"expired": 2, "soon": 1}

# Only surface the actionable window: expiring within the next few days, or
# expired within this short grace period. Items expired longer ago are assumed
# already used/tossed (we don't decrement on cook yet) and dropped — the goal is
# a short, helpful nudge, not a guilt-inducing audit of everything you ever bought.
_EXPIRED_GRACE_DAYS = 2


# Compound foods whose head noun lies about what they are: peanut butter is not
# butter, coconut milk is not milk. Head-noun matching would happily equate them
# with the bare staple, so these only ever match themselves (exact token set).
_ATOMIC_FOODS: tuple[frozenset, ...] = tuple(
    _content_tokens(name) for name in (
        "peanut butter", "almond butter", "cashew butter", "apple butter",
        "cocoa butter", "coconut milk", "almond milk", "oat milk", "soy milk",
        "coconut cream", "butter beans", "cream of tartar",
        # A second class of compound: these do not lie about their head noun,
        # but the inventory rows they collide with reduce to a single generic
        # token ("shredded cheese" -> {cheese}, "Canned corn" -> {corn}), so
        # plain containment matched every cheese and every corn product.
        "cream cheese", "cottage cheese", "goat cheese", "feta cheese",
        "corn syrup", "corn tortilla", "corn meal", "cornmeal",
        "coconut yogurt", "cherry juice", "corn starch", "cornstarch",
    )
)


class Phrase(NamedTuple):
    """A food name reduced for matching: its content tokens plus its head noun.

    ``strict`` marks a *clean* name — an inventory row or a configured staple,
    written as just the food. Recipe ingredient text is not clean ("unsalted
    butter, softened", "flour spooned and leveled, see notes"), so its trailing
    word is unreliable as a head noun and it is parsed non-strict.
    """
    tokens: frozenset
    head: Optional[str]
    strict: bool = True


def _phrase(text: str, strict: bool = True) -> Phrase:
    """Reduce a clean food name (inventory row, staple) to matchable form."""
    return Phrase(_content_tokens(text), _head_token(text), strict)


def _ingredient_phrase(text: str) -> Phrase:
    """Reduce free-text recipe ingredient text to matchable form."""
    return _phrase(text, strict=False)


def _covers(a: Phrase, b: Phrase) -> bool:
    """True if ``a`` and ``b`` name the same food.

    Token containment in either direction is necessary. When the *containing*
    phrase is a clean name, containment must also reach its head noun, so a
    modifier-only overlap ("egg" inside "Lo mein egg noodles") is rejected.
    When the containing phrase is noisy ingredient text, plain containment
    stands — its extra words are preparation notes ("butter, softened"), not a
    different food. Compound foods in ``_ATOMIC_FOODS`` demand an exact match.
    """
    if not a.tokens or not b.tokens:
        return False
    if a.tokens == b.tokens:
        return True
    if a.tokens <= b.tokens:
        shorter, longer = a, b
    elif b.tokens <= a.tokens:
        shorter, longer = b, a
    else:
        return False
    # A compound food only matches something that names the whole compound:
    # "peanut butter" is not "butter", but it is still "creamy peanut butter,
    # softened". Blanket-rejecting anything atomic would break the latter.
    implicated = [c for c in _ATOMIC_FOODS if c <= longer.tokens]
    # If the shorter name is itself one of the compounds present, it names one
    # alternative in the line ("peanut butter" among a list of nut butters)
    # rather than being an incomplete version of another.
    if not any(c <= shorter.tokens for c in implicated):
        for core in implicated:
            # The compound IS this phrase's food (its head noun belongs to the
            # compound), so a name lacking the whole compound is a different
            # food: "vanilla" is not "vanilla almond milk".
            if longer.head is not None and longer.head in core:
                return False
            # The compound overlaps what the shorter name claims, so the shorter
            # name is an incomplete version of it: "butter" is not "peanut butter".
            if shorter.tokens & core:
                return False
    if not longer.strict:
        return True
    return longer.head is not None and longer.head in shorter.tokens


def _staple_phrases(staples: Optional[set] = None) -> list[Phrase]:
    """Phrases for the pantry staples the user 'always has' and self-manages."""
    if staples is None:
        from lib.meal_suggester import load_pantry_staples
        staples = load_pantry_staples()
    return [p for p in (_phrase(s) for s in staples) if p.tokens]


def _is_staple(item: Phrase, staple_phrases: list[Phrase]) -> bool:
    """True if the item is a known staple (e.g. 'salted butter' matches 'butter')."""
    return any(_covers(st, item) for st in staple_phrases)


def _days_to_expiry(expires: Optional[str], today: date) -> Optional[int]:
    if not expires:
        return None
    try:
        return (date.fromisoformat(expires) - today).days
    except ValueError:
        return None


def at_risk_items(items: list, today: Optional[date] = None,
                  staple_sets: Optional[list[frozenset]] = None,
                  soon_days: int = SOON_THRESHOLD_DAYS,
                  expired_grace_days: int = _EXPIRED_GRACE_DAYS) -> list[tuple[str, object]]:
    """Items in the actionable expiry window, most urgent first.

    Included when expiring within ``soon_days`` or expired no more than
    ``expired_grace_days`` ago. Long-expired items are dropped (assumed already
    used). Staples (butter, flour, milk, …) are excluded entirely — the user
    keeps those stocked and manages their freshness, so KitchenOS never nags.
    """
    today = today or date.today()
    if staple_sets is None:
        staple_sets = _staple_phrases()

    flagged = []
    for it in items:
        delta = _days_to_expiry(getattr(it, "expires", None), today)
        if delta is None or delta > soon_days or delta < -expired_grace_days:
            continue
        if _is_staple(_phrase(it.name), staple_sets):
            continue
        status = "expired" if delta < 0 else "soon"
        flagged.append((status, it))
    flagged.sort(key=lambda f: (_STATUS_RANK[f[0]], f[1].expires or ""))
    return flagged


def _matches(item: Phrase, ingredient_phrases: list[Phrase]) -> bool:
    """True if the item names the same food as any recipe ingredient."""
    return any(_covers(item, ing) for ing in ingredient_phrases)


def suggest(items: list, recipe_index: list[dict], today: Optional[date] = None,
            limit: int = 10, staples: Optional[set] = None) -> dict:
    """Rank recipes by how much at-risk inventory they use.

    Returns ``{"at_risk": [...], "suggestions": [...]}``. Each suggestion is
    ``{recipe, image, uses: [{name, status, expires}], uses_count, urgency}``,
    sorted by number of at-risk items used (then urgency). Staples are excluded
    from the at-risk list but assumed available, so a recipe needing flour +
    butter + the expiring item still surfaces.
    """
    today = today or date.today()
    flagged = at_risk_items(items, today, _staple_phrases(staples))

    at_risk = [
        {
            "name": it.name,
            "status": status,
            "expires": it.expires,
            "quantity": it.quantity,
            "unit": it.unit,
            "location": it.location,
        }
        for status, it in flagged
    ]
    if not flagged:
        return {"at_risk": [], "suggestions": []}

    tokened = [(status, it, _phrase(it.name)) for status, it in flagged]

    suggestions = []
    for recipe in recipe_index:
        ing_sets = [_ingredient_phrase(s) for s in recipe.get("ingredient_items", [])]
        if not ing_sets:
            continue
        uses, urgency = [], 0
        for status, it, item_phrase in tokened:
            if _matches(item_phrase, ing_sets):
                uses.append({"name": it.name, "status": status, "expires": it.expires})
                urgency += _STATUS_WEIGHT[status]
        if uses:
            suggestions.append({
                "recipe": recipe["name"],
                "image": recipe.get("image"),
                "uses": uses,
                "uses_count": len(uses),
                "urgency": urgency,
            })

    suggestions.sort(key=lambda s: (s["uses_count"], s["urgency"], -len(s["recipe"])),
                     reverse=True)
    return {"at_risk": at_risk, "suggestions": suggestions[:limit]}


def generate(items: Optional[list] = None, recipe_index: Optional[list] = None,
             today: Optional[date] = None, limit: int = 10) -> dict:
    """Compute suggestions from live inventory + the recipe library."""
    if items is None:
        from lib.inventory import read_inventory
        items = read_inventory()
    if recipe_index is None:
        from lib import paths
        from lib.recipe_index import get_recipe_index
        recipe_index = get_recipe_index(paths.recipes_dir(), include_ingredients=True)
    return suggest(items, recipe_index, today=today, limit=limit)


def render_markdown(result: dict, today: Optional[date] = None) -> str:
    """Render the generated suggestions as the 'Use It Up.md' Obsidian note."""
    today = today or date.today()
    lines = [
        "---",
        "type: use-it-up",
        f"last_updated: {today.isoformat()}",
        "---",
        "",
        "# 🥗 Use It Up",
        "",
        "> ⚠️ **Generated** from the KitchenOS database — cook these to use food "
        "before it spoils. Do not edit here; changes are overwritten.",
        "",
    ]

    at_risk = result.get("at_risk", [])
    if not at_risk:
        lines.append("Nothing expiring soon — your fridge is in good shape. ✅\n")
        return "\n".join(lines) + "\n"

    lines += ["## At risk", ""]
    for r in at_risk:
        marker = "🔴 expired" if r["status"] == "expired" else "🟡 soon"
        qty = _format_quantity(r["quantity"])
        lines.append(
            f"- {marker} — **{r['name']}** ({qty} {r['unit']}, {r['location']}) "
            f"— expires {r['expires']}"
        )

    lines += ["", "## Cook these", ""]
    suggestions = result.get("suggestions", [])
    if not suggestions:
        lines.append("_No recipes in your library use these items — time to improvise._")
    else:
        for s in suggestions:
            used = ", ".join(u["name"] for u in s["uses"])
            count = s["uses_count"]
            plural = "item" if count == 1 else "items"
            lines.append(f"- [[{s['recipe']}]] — uses {count} at-risk {plural}: {used}")
    return "\n".join(lines) + "\n"


def write_note(today: Optional[date] = None) -> "object":
    """Regenerate the 'Use It Up.md' note at the vault root. Returns its path."""
    from lib import paths

    result = generate(today=today)
    path = paths.vault_root() / "Use It Up.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_markdown(result, today=today), encoding="utf-8")
    return path
