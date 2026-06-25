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
from typing import Optional

from lib.expiry import SOON_THRESHOLD_DAYS
from lib.inventory import _format_quantity
from lib.recipe_matcher import _content_tokens

# Expired items are twice as urgent as expiring-soon ones when ranking recipes.
_STATUS_RANK = {"expired": 0, "soon": 1}
_STATUS_WEIGHT = {"expired": 2, "soon": 1}

# Only surface the actionable window: expiring within the next few days, or
# expired within this short grace period. Items expired longer ago are assumed
# already used/tossed (we don't decrement on cook yet) and dropped — the goal is
# a short, helpful nudge, not a guilt-inducing audit of everything you ever bought.
_EXPIRED_GRACE_DAYS = 2


def _staple_token_sets(staples: Optional[set] = None) -> list[frozenset]:
    """Token sets for the pantry staples the user 'always has' and self-manages."""
    if staples is None:
        from lib.meal_suggester import load_pantry_staples
        staples = load_pantry_staples()
    return [t for t in (_content_tokens(s) for s in staples) if t]


def _is_staple(item_tokens: frozenset, staple_sets: list[frozenset]) -> bool:
    """True if the item is a known staple (e.g. 'salted butter' matches 'butter')."""
    return any(st <= item_tokens for st in staple_sets)


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
        staple_sets = _staple_token_sets()

    flagged = []
    for it in items:
        delta = _days_to_expiry(getattr(it, "expires", None), today)
        if delta is None or delta > soon_days or delta < -expired_grace_days:
            continue
        if _is_staple(_content_tokens(it.name), staple_sets):
            continue
        status = "expired" if delta < 0 else "soon"
        flagged.append((status, it))
    flagged.sort(key=lambda f: (_STATUS_RANK[f[0]], f[1].expires or ""))
    return flagged


def _matches(item_tokens: frozenset, ingredient_token_sets: list[frozenset]) -> bool:
    """True if the item shares a token-subset with any recipe ingredient."""
    if not item_tokens:
        return False
    for ing in ingredient_token_sets:
        if ing and (item_tokens <= ing or ing <= item_tokens):
            return True
    return False


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
    flagged = at_risk_items(items, today, _staple_token_sets(staples))

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

    tokened = [(status, it, _content_tokens(it.name)) for status, it in flagged]

    suggestions = []
    for recipe in recipe_index:
        ing_sets = [_content_tokens(s) for s in recipe.get("ingredient_items", [])]
        if not ing_sets:
            continue
        uses, urgency = [], 0
        for status, it, item_tokens in tokened:
            if _matches(item_tokens, ing_sets):
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
