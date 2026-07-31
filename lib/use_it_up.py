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

import re
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

# Recipes shown under each at-risk item. With the usual 1-3 items at risk this
# lands in the 5-15 range that's useful to scan, and — the actual point — no
# single item can flood the panel the way one lime once did with all ten slots.
RECIPES_PER_ITEM = 5

# Missing ingredients listed per recipe in the generated note.
_NOTE_MISSING_CAP = 4


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


_TRAILER_RE = re.compile(r"\([^)]*\)")
_OF_CHOICE_RE = re.compile(r"\bof choice\b", re.IGNORECASE)

# Qualifier clauses that hijack the last-word head heuristic on *inventory* names:
# "sliced ham off the bone" resolved to `bone`, so the ham could never match a
# recipe calling for ham — it was looking for a food called bone.
#
# `of` is deliberately absent. Stripping it would turn "Cream of tartar" into
# "cream" and "Canned cream of chicken soup" into "canned cream", both of which
# would then match every cream in the library. Those are the only three `of`
# names among the 215 live inventory rows and all three parse correctly today.
_QUALIFIER_TRAILER_RE = re.compile(r"\b(?:off|with|without)\b.*$", re.IGNORECASE)


def _core_head(text: str, strict: bool, fallback: Optional[str]) -> Optional[str]:
    """Head noun for the atomic-block test, ignoring trailing clauses.

    ``_head_token`` takes the last content word, so "almond milk (or milk of
    choice)" resolves to "choice" and the block that protects compound foods
    never fires.

    Only ingredient text needs stripping *here*, because a clean name has
    already been through ``_clean_name`` in ``_phrase`` — the fallback it gets
    passed is a head derived from the cleaned text, not the raw one.
    """
    if strict:
        return fallback
    cleaned = _OF_CHOICE_RE.sub(" ", _TRAILER_RE.sub(" ", text or ""))
    return _head_token(cleaned) or fallback


class Phrase(NamedTuple):
    """A food name reduced for matching: its content tokens plus its head noun.

    ``strict`` marks a *clean* name — an inventory row or a configured staple,
    written as just the food. Recipe ingredient text is not clean ("unsalted
    butter, softened", "flour spooned and leveled, see notes"), so its trailing
    word is unreliable as a head noun and it is parsed non-strict.

    "Clean" means the row names one food, not that it is free of qualifiers:
    real rows include "sliced ham off the bone" and "whey protein powder
    (chocolate fudge)". ``_phrase`` runs strict names through ``_clean_name``
    first so those clauses reach neither the tokens nor the head.

    ``core_head`` is the head noun used for the atomic-block test only: for
    noisy ingredient text it is resolved from a version of the text with
    trailing clauses (parentheticals, "of choice") stripped, since those can
    hijack ``_head_token``'s last-word heuristic away from the real food. The
    final strict-containment check in ``_covers`` keeps using ``head``, not
    this field — it means something different there (the phrase's own head,
    not a de-noised approximation).
    """
    tokens: frozenset
    head: Optional[str]
    strict: bool = True
    core_head: Optional[str] = None


def _clean_name(text: str) -> str:
    """Strip clauses that hijack the head-noun heuristic on a clean name.

    "Clean" names were assumed trustworthy enough to skip this. They are not:
    of the 215 live inventory rows, "sliced ham off the bone" resolved to `bone`
    and "whey protein powder (chocolate fudge)" to `fudge`. Both then matched
    nothing, silently — the ham showed no recipes for a month while the library
    held one whose ingredient is literally "ham".
    """
    return _QUALIFIER_TRAILER_RE.sub(" ", _TRAILER_RE.sub(" ", text or "")).strip()


def _phrase(text: str, strict: bool = True) -> Phrase:
    """Reduce a clean food name (inventory row, staple) to matchable form."""
    # The qualifier clause is stripped from the *tokens* as well as the head.
    # Fixing only the head is not enough: `_covers` requires token containment
    # in one direction, and {bone, ham, off} neither contains nor is contained
    # by {deli, ham} — so "sliced ham off the bone" still matched no ham recipe
    # even once its head read `ham`. Stripping gives {ham} ⊆ {deli, ham}.
    source = _clean_name(text) if strict else text
    return Phrase(_content_tokens(source), _head_token(source), strict,
                  _core_head(text, strict, _head_token(source)))


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
            # food: "vanilla" is not "vanilla almond milk". Use core_head, not
            # head: a trailing clause ("... or milk of choice") can hijack
            # head's last-word heuristic away from the real food noun.
            if longer.core_head is not None and longer.core_head in core:
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


def recipe_coverage(ingredients: list[str], inv_phrases: list[Phrase],
                    staple_sets: list[Phrase],
                    at_risk_sets: Optional[list[Phrase]] = None
                    ) -> tuple[int, int, list[str], bool]:
    """How much of a recipe you already have.

    Returns ``(have, total, missing, uses_at_risk)``. Staples count as
    always-on-hand: they raise coverage and never appear in ``missing``.
    Matching is presence-only, not quantity-aware. ``uses_at_risk`` is False
    whenever ``at_risk_sets`` is omitted.

    The single authority for this calculation. ``cook_now.generate`` ranks the
    whole library by it and ``suggest`` ranks each at-risk item's recipes by it —
    and this repo has already been bitten by two modules hand-writing the same
    rule (``unit_compatibility``, where the shopping list credited limes the cook
    then refused to spend). It lives here rather than in ``cook_now`` because
    ``cook_now`` already imports this module's matching machinery, so the
    dependency only points one way.

    One pass on purpose: it runs over the whole library (252 recipes x ~10
    ingredients) on a page with a 135 ms budget, and ``_ingredient_phrase`` is
    the expensive part — so at-risk is detected here rather than in a second
    loop that would parse every ingredient twice.
    """
    missing: list[str] = []
    uses_at_risk = False
    for ing in ingredients:
        phrase = _ingredient_phrase(ing)
        if not (_is_staple(phrase, staple_sets) or _matches(phrase, inv_phrases)):
            missing.append(ing)
        if at_risk_sets and not uses_at_risk and _matches(phrase, at_risk_sets):
            uses_at_risk = True
    total = len(ingredients)
    return total - len(missing), total, missing, uses_at_risk


def suggest(items: list, recipe_index: list[dict], today: Optional[date] = None,
            limit: int = 10, staples: Optional[set] = None,
            per_item: int = RECIPES_PER_ITEM) -> dict:
    """What to cook to use up what's about to go off, grouped by the item.

    Returns ``{"at_risk": [...], "suggestions": [...]}``.

    Each ``at_risk`` entry carries its **own** ranked ``recipes`` — the recipes
    that use *that* item, ordered by how much of each you already have
    (``recipe_coverage``), capped at ``per_item``. An item that matches nothing
    keeps an empty list rather than disappearing, because "there is nothing to
    cook with this ham" is the answer, and a flat list could only express it by
    omission.

    ``suggestions`` is a flat, deduplicated view of the same grouped data, kept
    so the generated note and ``kitchen_today`` keep working. It is derived, not
    ranked separately — there is one ranking in this module.

    Previously this returned a single flat list sorted by
    ``(uses_count, urgency, -len(recipe))``. With one matchable at-risk item
    every candidate ties on the first two, so the operative tiebreak was
    *shortest recipe name*: live, that rendered ten lime recipes and nothing at
    all for the ham expiring that day.
    """
    today = today or date.today()
    staple_sets = _staple_phrases(staples)
    flagged = at_risk_items(items, today, staple_sets)

    if not flagged:
        return {"at_risk": [], "suggestions": []}

    inv_phrases = [_phrase(it.name) for it in items]
    tokened = [(status, it, _phrase(it.name)) for status, it in flagged]

    # recipe name -> (coverage payload, [item names it uses])
    matched: dict[str, tuple[dict, list[dict]]] = {}
    for recipe in recipe_index:
        ingredients = recipe.get("ingredient_items", [])
        if not ingredients:
            continue
        ing_sets = [_ingredient_phrase(s) for s in ingredients]

        uses = [
            {"name": it.name, "status": status, "expires": it.expires}
            for status, it, item_phrase in tokened
            if _matches(item_phrase, ing_sets)
        ]
        if not uses:
            continue

        have, total, missing, _ = recipe_coverage(ingredients, inv_phrases, staple_sets)
        matched[recipe["name"]] = ({
            "recipe": recipe["name"],
            "display_name": recipe.get("display_name") or recipe["name"],
            "image": recipe.get("image"),
            "have": have,
            "total": total,
            "coverage": have / total if total else 0.0,
            "missing": missing,
            "uses": uses,
            "uses_count": len(uses),
            "urgency": sum(_STATUS_WEIGHT[u["status"]] for u in uses),
        }, [u["name"] for u in uses])

    at_risk = []
    for status, it in flagged:
        for_item = [payload for payload, used in matched.values() if it.name in used]
        # Most-covered first; then most at-risk items used, so a recipe clearing
        # two expiring things outranks an equally-covered one clearing one.
        for_item.sort(key=lambda r: (r["coverage"], r["uses_count"], -len(r["missing"])),
                      reverse=True)
        at_risk.append({
            "name": it.name,
            "status": status,
            "expires": it.expires,
            "quantity": it.quantity,
            "unit": it.unit,
            "location": it.location,
            "recipes": for_item[:per_item],
            "match_count": len(for_item),
        })

    # Flat view: item order (already urgency-sorted by at_risk_items), each item's
    # recipes in their ranked order, first occurrence wins.
    seen: set[str] = set()
    suggestions = []
    for entry in at_risk:
        for r in entry["recipes"]:
            if r["recipe"] in seen:
                continue
            seen.add(r["recipe"])
            suggestions.append(r)

    return {"at_risk": at_risk, "suggestions": suggestions[:limit]}


def generate(items: Optional[list] = None, recipe_index: Optional[list] = None,
             today: Optional[date] = None, limit: int = 10,
             per_item: int = RECIPES_PER_ITEM) -> dict:
    """Compute suggestions from live inventory + the recipe library."""
    if items is None:
        from lib.inventory import read_inventory
        items = read_inventory()
    if recipe_index is None:
        from lib import paths
        from lib.recipe_index import get_recipe_index
        recipe_index = get_recipe_index(paths.recipes_dir(), include_ingredients=True)
    return suggest(items, recipe_index, today=today, limit=limit, per_item=per_item)


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

    # One section per item, each with its own recipes. A single "Cook these"
    # list could not say which item a recipe was for, and could only report an
    # item with no options by leaving it out.
    for r in at_risk:
        marker = "🔴 expired" if r["status"] == "expired" else "🟡 soon"
        qty = _format_quantity(r["quantity"])
        lines += [
            f"## {r['name']}",
            "",
            f"{marker} — {qty} {r['unit']}, {r['location']} — expires {r['expires']}",
            "",
        ]

        recipes = r.get("recipes", [])
        if not recipes:
            lines += ["_Nothing in your library uses this — time to improvise._", ""]
            continue

        lines += ["| Recipe | Have | Missing |", "|--------|------|---------|"]
        for s in recipes:
            pct = round(s["coverage"] * 100)
            have = f"{pct}% ({s['have']}/{s['total']})"
            # Capped: raw ingredient text carries its whole parenthetical
            # ("of cannellini beans or navy beans, or chickpeas, drained and
            # rinsed (15-ounce/440g)"), so an uncapped list makes the table
            # unreadable in exactly the rows you were least likely to cook.
            shown = [m.split(",")[0].strip() for m in s["missing"][:_NOTE_MISSING_CAP]]
            extra = len(s["missing"]) - len(shown)
            missing = ", ".join(shown) + (f", +{extra} more" if extra > 0 else "")
            missing = missing or "—"
            also = [u["name"] for u in s["uses"] if u["name"] != r["name"]]
            flag = f" ♻️ also uses {', '.join(also)}" if also else ""
            lines.append(f"| [[{s['recipe']}]]{flag} | {have} | {missing} |")

        hidden = r.get("match_count", len(recipes)) - len(recipes)
        if hidden > 0:
            lines.append("")
            lines.append(f"_{hidden} more recipe{'s' if hidden != 1 else ''} "
                         f"use{'' if hidden != 1 else 's'} this, with less on hand._")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def write_note(today: Optional[date] = None) -> "object":
    """Regenerate the 'Use It Up.md' note at the vault root. Returns its path."""
    from lib import paths

    result = generate(today=today)
    path = paths.vault_root() / "Use It Up.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_markdown(result, today=today), encoding="utf-8")
    return path
