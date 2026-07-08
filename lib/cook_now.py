"""Cook-Now suggester — recipes ranked by how much of what they need is on hand.

Answers "what can I cook right now?" by scoring every recipe in the library by
the fraction of its ingredients currently in inventory. The best-covered recipes
surface first, with the still-missing ingredients listed so a near-miss ("you
have everything but buttermilk") is obvious at a glance.

This is the coverage-ranked complement to ``use_it_up`` (which ranks by *expiry
urgency*). It reuses that module's matching machinery wholesale: normalized
token-containment (``recipe_matcher._content_tokens`` + ``use_it_up._matches``),
staple detection (staples are assumed always on hand — never "missing", never
penalize coverage), and the at-risk expiry window (to flag recipes that would
also use up something expiring soon). Matching is presence-only, not
quantity-aware, consistent with ``use_it_up``.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from lib.recipe_matcher import _content_tokens
from lib.use_it_up import (
    _is_staple,
    _matches,
    _staple_token_sets,
    at_risk_items,
)


def generate(items: Optional[list] = None, recipe_index: Optional[list] = None,
             today: Optional[date] = None, limit: int = 30) -> dict:
    """Rank recipes by ingredient coverage against current inventory.

    Returns ``{"recipes": [...]}``, each entry
    ``{recipe, image, have, total, coverage, missing, at_risk}``, sorted by
    coverage (then have count, then fewest missing) descending and capped at
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

    staple_sets = _staple_token_sets()
    inv_token_sets = [_content_tokens(it.name) for it in items]
    at_risk_sets = [
        _content_tokens(it.name)
        for _, it in at_risk_items(items, today, staple_sets)
    ]

    recipes = []
    for recipe in recipe_index:
        ingredients = recipe.get("ingredient_items", [])
        if not ingredients:
            continue

        missing = []
        at_risk = False
        for ing in ingredients:
            ing_tokens = _content_tokens(ing)
            on_hand = _is_staple(ing_tokens, staple_sets) or _matches(ing_tokens, inv_token_sets)
            if not on_hand:
                missing.append(ing)
            if _matches(ing_tokens, at_risk_sets):
                at_risk = True

        total = len(ingredients)
        have = total - len(missing)
        recipes.append({
            "recipe": recipe["name"],
            "image": recipe.get("image"),
            "have": have,
            "total": total,
            "coverage": have / total,
            "missing": missing,
            "at_risk": at_risk,
        })

    recipes.sort(key=lambda r: (r["coverage"], r["have"], -len(r["missing"])),
                 reverse=True)
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
