#!/usr/bin/env python3
"""Tag recipes against the personal food profile in `My Meal System.md`.

Turns a pile of saved recipes into something retrievable: which craving each
one serves, whether it could work as a zero-prep buffer food, how hard it leans
on the dairy zone, and whether it plausibly supports the LDL / blood-sugar
goals. Without this the library can only be searched by ingredient, which is
not how a craving at 9pm actually presents.

Every value written is inference from an ingredient list, not a measurement —
each recipe gets `fit_source` and `fit_needs_review: true` accordingly.

Usage:
    .venv/bin/python backfill_fit.py [--dry-run] [--limit N] [--force]

Without --force, recipes that already carry `fit_craving_lane` are skipped, so
the script is cheap to re-run and safe to point at the whole library.
"""
import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from lib import frontmatter, paths, profile as profile_mod, recipe_fit
from lib.backup import create_backup
from lib.recipe_parser import parse_recipe_file, parse_ingredient_table


def extract_ingredients(body: str) -> list[str]:
    """Ingredient names from the recipe's markdown table."""
    match = re.search(r"## Ingredients\n\n((?:\|[^\n]+\n)+)", body)
    if not match:
        return []
    rows = parse_ingredient_table(match.group(1))
    return [r.get("item", "") for r in rows if r.get("item")]


def process(path: Path, profile, dry_run: bool) -> str:
    """Assess and tag one recipe. Returns an outcome for the run summary."""
    content = path.read_text(encoding="utf-8")
    parsed = parse_recipe_file(content)
    ingredients = extract_ingredients(parsed.get("body", ""))
    if not ingredients:
        return "no-ingredients"

    tags = recipe_fit.assess(path.stem, ingredients, profile)
    if tags is None:
        return "no-model"

    if dry_run:
        flags = "".join(t for t, on in
                        (("heart", tags["heart"]), ("steady", tags["steady"])) if on)
        print(f"  {path.stem[:44]:46} {tags['craving_lane']:6} "
              f"dairy={tags['dairy_load']:6} {tags['effort']:9} {flags}")
        return "assessed"

    updated = frontmatter.apply(content, recipe_fit.to_frontmatter(tags),
                                recipe_fit.MANAGED_KEYS)
    if updated is None:
        return "no-frontmatter"
    create_backup(path)  # timestamped copy in .history/, same as the nutrition backfill
    path.write_text(updated, encoding="utf-8")
    return "tagged"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="assess and print, write nothing")
    ap.add_argument("--limit", type=int, help="stop after N recipes")
    ap.add_argument("--force", action="store_true",
                    help="re-assess recipes that are already tagged")
    args = ap.parse_args()

    profile = profile_mod.load_profile()
    if profile is None:
        print(f"No {profile_mod.PROFILE_FILENAME} in the vault — nothing to tag against.",
              file=sys.stderr)
        return 1

    recipes = sorted(paths.recipes_dir().glob("*.md"))
    if not args.force:
        recipes = [p for p in recipes
                   if "fit_craving_lane:" not in p.read_text(encoding="utf-8")]
    if args.limit:
        recipes = recipes[:args.limit]

    if not recipes:
        print("Nothing to do — every recipe is already tagged (use --force to redo).")
        return 0

    print(f"Assessing {len(recipes)} recipes against {profile_mod.PROFILE_FILENAME}…")
    counts: dict[str, int] = {}
    for i, path in enumerate(recipes, 1):
        outcome = process(path, profile, args.dry_run)
        counts[outcome] = counts.get(outcome, 0) + 1
        if not args.dry_run and i % 10 == 0:
            print(f"  …{i}/{len(recipes)}")

    print("\nDone:")
    for outcome, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {n:4}  {outcome}")
    if counts.get("no-model"):
        print("\n  'no-model' means neither Claude nor Ollama answered — those "
              "recipes are untagged, not mistagged. Re-run to retry them.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
