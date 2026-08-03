#!/usr/bin/env python3
"""
Compose plates: pair each main dish with the sides/sauces whose shopping lists its
own ingredients already cover.

Read-only — prints to the terminal and never writes to the vault.

The overlap scoring is not reimplemented here; it comes from lib.meal_suggester,
the same engine behind POST /api/recipes/by-ingredients. This module only adds the
composition layer (role filtering and per-role selection).

Usage:
    python scripts/compose_plates.py
    python scripts/compose_plates.py --limit 10 --min-score 0.35
    python scripts/compose_plates.py --json
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import paths
from lib.meal_suggester import (
    load_pantry_staples,
    normalize_ingredient,
    rank_candidates,
)
from lib.normalizer import normalize_field
from lib.recipe_index import get_recipe_index

MAIN_TYPES = {"main"}
ACCOMPANIMENT_TYPES = {"side", "salad", "sauce", "dip", "bread"}

# How deep to look before giving up on filling the remaining roles.
_RANK_DEPTH = 50


def _dish_type(recipe: dict):
    """Canonical dish_type for a recipe, or None if absent/unrecognized."""
    normalized = normalize_field("dish_type", recipe.get("dish_type"))
    return normalized if isinstance(normalized, str) else None


def _base_name(name: str) -> str:
    """Recipe name without its import-source suffix.

    Importers disambiguate a name collision by appending the source — "Whipped Tofu
    Ricotta (Big Vegan Flavor)". Those two notes are near-identical, so pairing one
    with the other is a plate of the same dish twice.
    """
    return re.sub(r"\s*\([^)]*\)\s*$", "", name).strip().lower()


def compose_plates(recipes, pantry, min_score=0.30, max_sides=3, limit=None):
    """Pair each main with accompaniments that reuse its ingredients.

    Args:
        recipes: Recipe index dicts (need 'name', 'dish_type', 'ingredient_items').
        pantry: Pantry staple names to exclude from overlap.
        min_score: Minimum overlap before an accompaniment is worth pairing.
        max_sides: Cap on accompaniments per plate.
        limit: Return at most this many plates.

    Returns:
        List of plate dicts: name, display_name, accompaniments
        (name/role/score/shared_ingredients), and strength.
    """
    anchors = []
    accompaniments = []

    for recipe in recipes:
        if not recipe.get("ingredient_items"):
            continue
        dish_type = _dish_type(recipe)
        if dish_type in MAIN_TYPES:
            anchors.append(recipe)
        elif dish_type in ACCOMPANIMENT_TYPES:
            accompaniments.append(dict(recipe, _role=dish_type))

    role_by_name = {a["name"]: a["_role"] for a in accompaniments}

    plates = []
    for main in anchors:
        main_items = {normalize_ingredient(i) for i in main["ingredient_items"]}

        # A same-name note from another source is the same dish, not a side for it.
        main_base = _base_name(main["name"])
        excluded = {a["name"] for a in accompaniments
                    if _base_name(a["name"]) == main_base} | {main["name"]}

        # at_risk=[] and macro_gap=None are load-bearing: left as None,
        # rank_candidates reads live inventory and ranks expiring items above
        # overlap, which would make this preview non-deterministic.
        ranked = rank_candidates(
            accompaniments,
            main_items,
            pantry,
            limit=_RANK_DEPTH,
            exclude_names=excluded,
            at_risk=[],
            macro_gap=None,
        )

        chosen = []
        used_roles = set()
        for candidate in ranked:
            if candidate["score"] < min_score:
                break  # ranked desc, so nothing below this qualifies either
            role = role_by_name.get(candidate["name"])
            if role is None or role in used_roles:
                continue
            used_roles.add(role)
            chosen.append({
                "name": candidate["name"],
                "role": role,
                "score": candidate["score"],
                "shared_ingredients": candidate["shared_ingredients"],
            })
            if len(chosen) >= max_sides:
                break

        plates.append({
            "main": main["name"],
            "display_name": main.get("display_name") or main["name"],
            "accompaniments": chosen,
            "strength": round(sum(a["score"] for a in chosen), 3),
        })

    plates.sort(key=lambda p: (len(p["accompaniments"]), p["strength"]), reverse=True)
    return plates[:limit] if limit else plates


def print_plates(plates, show_unpaired: bool):
    paired = [p for p in plates if p["accompaniments"]]
    unpaired = [p for p in plates if not p["accompaniments"]]

    for plate in paired:
        print(f"\n{plate['display_name']}")
        for acc in plate["accompaniments"]:
            shared = ", ".join(acc["shared_ingredients"][:6])
            more = "…" if len(acc["shared_ingredients"]) > 6 else ""
            print(f"   {acc['role']:<6} {acc['name']}")
            print(f"          {acc['score']:.0%} shared — {shared}{more}")

    if show_unpaired and unpaired:
        print(f"\n\nNo strong pairing ({len(unpaired)}):")
        for plate in unpaired:
            print(f"   {plate['display_name']}")

    print(f"\n{len(paired)} plates composed, {len(unpaired)} mains without a "
          f"strong pairing.")


def main():
    parser = argparse.ArgumentParser(
        description="Pair mains with sides/sauces that reuse their ingredients"
    )
    parser.add_argument("--limit", type=int, default=None,
                        help="Show at most N plates")
    parser.add_argument("--min-score", type=float, default=0.30,
                        help="Minimum ingredient overlap to pair (default: 0.30)")
    parser.add_argument("--max-sides", type=int, default=3,
                        help="Max accompaniments per plate (default: 3)")
    parser.add_argument("--show-unpaired", action="store_true",
                        help="Also list mains with no qualifying accompaniment")
    parser.add_argument("--json", action="store_true",
                        help="Emit JSON instead of formatted text")
    args = parser.parse_args()

    recipes = get_recipe_index(paths.recipes_dir(), include_ingredients=True)
    plates = compose_plates(
        recipes,
        load_pantry_staples(),
        min_score=args.min_score,
        max_sides=args.max_sides,
        limit=args.limit,
    )

    if args.json:
        print(json.dumps(plates, indent=2))
    else:
        print_plates(plates, args.show_unpaired)


if __name__ == "__main__":
    main()
