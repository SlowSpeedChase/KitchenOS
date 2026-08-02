#!/usr/bin/env python3
"""Backfill nutrition data for existing recipes using the gram-based engine.

For each recipe with ``nutrition_calories: null`` (or all, with ``--force``):
  1. Parse the ingredient table from the recipe body.
  2. Compute per-serving macros with ``lib.nutrition_engine`` (USDA/OFF + grams,
     LLM only for unresolved portions).
  3. Write nutrition_* / nutrition_source / nutrition_confidence back to the
     frontmatter, de-duplicating any keys a prior run left behind. The
     nutrition verdict is recorded in its own ``nutrition_needs_review`` key;
     the shared ``needs_review`` flag (also set by extraction/normalizer/
     crouton_parser) is only ever escalated to "true" here, never cleared.

Usage:
    .venv/bin/python backfill_nutrition.py [--dry-run] [--limit N] [--force]
    .venv/bin/python backfill_nutrition.py --fix-duplicates [--dry-run]
"""

import argparse
import re
import sqlite3
import sys
import os
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from lib import frontmatter, paths
from lib.backup import create_backup
from lib.nutrition_engine import calculate_recipe_nutrition
from lib.recipe_parser import parse_recipe_file, parse_ingredient_table

# Scalar frontmatter keys this tool manages — de-duplicated and (re)written.
# Limiting to scalars keeps multi-line list keys (tags:, dietary:) untouched.
_MANAGED_KEYS = {
    "nutrition_calories", "nutrition_protein", "nutrition_carbs",
    "nutrition_fat", "nutrition_source", "nutrition_confidence",
    "serving_size", "needs_review", "nutrition_needs_review",
    "nutrition_coverage", "nutrition_unmatched",
}


def extract_ingredients(body: str) -> list[dict]:
    """Extract structured ingredients from recipe body markdown."""
    match = re.search(r"## Ingredients\n\n((?:\|[^\n]+\n)+)", body)
    if not match:
        return []
    return parse_ingredient_table(match.group(1))


def rewrite_frontmatter(fm: str, updates: dict) -> str:
    """Rewrite frontmatter: de-duplicate managed scalar keys and apply updates.

    Thin wrapper binding this script's ``_MANAGED_KEYS`` to the shared
    line-based editor in ``lib.frontmatter`` (which the cook-history sync also
    uses, so the two cannot drift apart).
    """
    return frontmatter.rewrite(fm, updates, _MANAGED_KEYS)


def _split_frontmatter(content: str):
    """Return (frontmatter_text, rest) or (None, None) if no frontmatter."""
    return frontmatter.split_frontmatter(content)


def write_nutrition_to_file(filepath: Path, result) -> None:
    """Write engine results into a recipe file's frontmatter (de-duplicated)."""
    content = filepath.read_text(encoding="utf-8")
    fm, rest = _split_frontmatter(content)
    if fm is None:
        return

    updates = {
        "nutrition_calories": result.nutrition.calories,
        "nutrition_protein": result.nutrition.protein,
        "nutrition_carbs": result.nutrition.carbs,
        "nutrition_fat": result.nutrition.fat,
        "nutrition_source": frontmatter.scalar(result.source),
        "nutrition_confidence": result.confidence,
        "serving_size": frontmatter.scalar("1 serving"),
    }
    updates["nutrition_needs_review"] = "true" if result.needs_review else "false"
    if result.needs_review:
        # Shared flag: escalate-only. It's also set by extraction inference,
        # lib/normalizer.py, and lib/crouton_parser.py — never clear a human
        # review flag those writers may have set for unrelated reasons.
        updates["needs_review"] = "true"

    updates["nutrition_coverage"] = result.coverage
    if result.unmatched:
        joined = "; ".join(result.unmatched)
        # Ingredient text is LLM-extracted from arbitrary recipe pages, so it can
        # contain a double quote (`2" piece ginger`) or a backslash. Building the
        # scalar with an f-string closed it early and broke the frontmatter of a
        # recipe that had just backfilled cleanly. frontmatter.scalar is the one
        # authority for this — same rule as lib/reminders.py: never interpolate
        # untrusted text into a quoted context by hand.
        updates["nutrition_unmatched"] = frontmatter.scalar(joined)

    new_fm = rewrite_frontmatter(fm, updates)
    if not result.unmatched:
        # No unmatched items this run — drop any stale nutrition_unmatched line
        # a previous (partial) backfill left behind.
        new_fm = "\n".join(
            l for l in new_fm.split("\n") if not l.startswith("nutrition_unmatched:")
        )
        if not new_fm.endswith("\n"):
            new_fm += "\n"
    filepath.write_text(f"---{new_fm}---{rest}", encoding="utf-8")


def fix_duplicates_in_file(filepath: Path) -> bool:
    """De-duplicate managed frontmatter keys in place. Returns True if changed."""
    content = filepath.read_text(encoding="utf-8")
    fm, rest = _split_frontmatter(content)
    if fm is None:
        return False
    new_fm = rewrite_frontmatter(fm, {})
    if new_fm == fm:
        return False
    filepath.write_text(f"---{new_fm}---{rest}", encoding="utf-8")
    return True


def _print_audit(result) -> None:
    """Print the per-ingredient audit trail (grams, source, contribution)."""
    for li in result.line_items:
        cal = li.contribution.get("calories", 0)
        print(
            f"      {li.item[:28]:28} {li.grams:8.1f} g  {li.grams_method:14}"
            f" {li.food_source or '-':5} {cal:6.0f} kcal"
        )
    flag = " [needs review]" if result.needs_review else ""
    sanity = f" [{', '.join(result.sanity_flags)}]" if result.sanity_flags else ""
    print(
        f"      → per serving: {result.nutrition.calories} kcal /"
        f" {result.nutrition.protein}p / {result.nutrition.carbs}c /"
        f" {result.nutrition.fat}f  (servings={result.servings_used},"
        f" coverage={result.coverage}, conf={result.confidence}){flag}{sanity}"
    )


def backfill_recipe(filepath: Path, dry_run: bool = False) -> bool:
    """Backfill nutrition for a single recipe file.

    Returns True if nutrition was calculated (or would be in dry_run).
    """
    content = filepath.read_text(encoding="utf-8")
    parsed = parse_recipe_file(content)
    body = parsed["body"]

    ingredients = extract_ingredients(body)
    if not ingredients:
        return False

    # Pass servings raw (may be None) so the engine flags servings_inferred
    # instead of silently treating the whole recipe as one serving.
    result = calculate_recipe_nutrition(ingredients, parsed["frontmatter"].get("servings"))
    if result is None:
        return False

    if dry_run:
        _print_audit(result)
    else:
        create_backup(filepath)
        write_nutrition_to_file(filepath, result)

    return True


def collect_recipes_needing_backfill(recipes_dir: Path, force: bool = False) -> list[Path]:
    """Return recipe files with null nutrition_calories (or all, with force)."""
    files = []
    for md_file in sorted(recipes_dir.glob("*.md")):
        if md_file.name.startswith("."):
            continue
        try:
            content = md_file.read_text(encoding="utf-8")
            parsed = parse_recipe_file(content)
            fm = parsed["frontmatter"]
            if "source_url" not in fm:
                continue
            if force or fm.get("nutrition_calories") is None:
                files.append(md_file)
        except Exception:
            continue
    return files


def collect_all_recipes(recipes_dir: Path) -> list[Path]:
    return [
        f for f in sorted(recipes_dir.glob("*.md")) if not f.name.startswith(".")
    ]


def run_fix_duplicates(recipes_dir: Path, dry_run: bool) -> None:
    print(f"Scanning for duplicate nutrition keys: {recipes_dir}\n")
    changed = 0
    for filepath in collect_all_recipes(recipes_dir):
        content = filepath.read_text(encoding="utf-8")
        fm, _ = _split_frontmatter(content)
        if fm is None:
            continue
        if rewrite_frontmatter(fm, {}) != fm:
            print(f"  {filepath.name}: duplicate keys"
                  f"{' (would fix)' if dry_run else ' — fixed'}")
            if not dry_run:
                create_backup(filepath)
                fix_duplicates_in_file(filepath)
            changed += 1
    print(f"\n{'[DRY RUN] ' if dry_run else ''}Files with duplicates: {changed}")


def require_food_store():
    """Refuse to run when the local FDC store is empty.

    `data/` is git-ignored, so `data/kitchenos.db` exists only in the main
    checkout — but `inventory_db.connect()` creates the file and schema on
    demand, so running this from a linked worktree silently opens a *new, empty*
    database. Every ingredient then fails to resolve and the whole corpus is
    rewritten at ~0.3 coverage, overwriting good data with garbage that still
    looks like a successful run.

    Observed live on 2026-08-01: three recipes went from coverage 1.0 to
    0.33/0.55/0.70, one from 357 kcal to 7, because the backfill ran from
    .worktrees/ and built its own empty DB.
    """
    from lib import inventory_db

    path = inventory_db.db_path()

    # Open read-only, never through inventory_db.connect() — that creates the
    # file and schema on demand, so the guard used to reject the empty database
    # *it had just created*, leaving a fully-schema'd decoy behind. data/ is
    # git-ignored, so that decoy persists invisibly and every other tool run
    # from the same directory (api_server, mcp_server, receipt ingest) then
    # reads and writes it instead of the real database.
    # The engine needs more than a food list: fdc_portions supplies grams per
    # unit, without which nothing resolves even though every food is present.
    # Flooring only fdc_foods left a partially-loaded store passing the guard and
    # producing the same silent garbage, one table over.
    required = ("fdc_foods", "fdc_portions")
    counts = {name: 0 for name in required}
    if path.exists():
        try:
            conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            try:
                for name in required:
                    try:
                        counts[name] = conn.execute(
                            f"SELECT COUNT(*) FROM {name}"
                        ).fetchone()[0]
                    except sqlite3.Error:
                        counts[name] = 0
            finally:
                conn.close()
        except sqlite3.Error:
            pass

    empty = [name for name, n in counts.items() if n == 0]
    if empty:
        raise SystemExit(
            f"{', '.join(empty)} empty in {path}\n"
            "Refusing to run: every ingredient would fail to resolve and the\n"
            "recipes would be rewritten at ~0.3 coverage, destroying good data.\n"
            "If you are in a linked worktree, data/ lives only in the main\n"
            "checkout — point KITCHENOS_DB at it, e.g.\n"
            "  KITCHENOS_DB=/Users/<you>/Dev/KitchenOS/data/kitchenos.db \\\n"
            "    ../../.venv/bin/python backfill_nutrition.py --force --only \"<name>\"\n"
            "(A genuinely fresh environment needs scripts/load_fdc_bulk.py first.)"
        )


def apply_limit(candidates, limit, only):
    """Apply --limit, refusing to silently truncate an explicit --only list.

    --limit slices after --only, so `--only A --only B --only C --limit 1`
    processed A and dropped B and C with no message — the exact silence
    select_only exists to prevent.
    """
    if not limit:
        return candidates
    if only and limit < len(candidates):
        raise SystemExit(
            f"--limit {limit} would drop {len(candidates) - limit} of the "
            f"{len(candidates)} recipes named by --only. Drop --limit, or name fewer."
        )
    return candidates[:limit]


def select_only(candidates, names):
    """Narrow ``candidates`` to the recipes named in ``names``.

    A name that matches nothing is an error, not a silent no-op: the caller
    asked for a specific recipe to be re-derived, and quietly doing zero work
    would look identical to success.
    """
    if not names:
        return candidates
    by_stem = {p.stem: p for p in candidates}
    missing = [n for n in names if n not in by_stem]
    if missing:
        raise SystemExit(
            f"--only: no such recipe(s) in the candidate set: {', '.join(missing)}"
        )
    # dict.fromkeys dedupes while keeping the caller's order — a repeated
    # --only used to process the file twice, which also risked two backups
    # landing in the same second.
    return [by_stem[n] for n in dict.fromkeys(names)]


def main():
    parser = argparse.ArgumentParser(
        description="Backfill nutrition data for recipes (gram-based engine)"
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing files")
    parser.add_argument("--limit", type=int, help="Process at most N recipes")
    parser.add_argument(
        "--only", action="append", default=[], metavar="NAME",
        help="only this recipe (by filename stem); repeatable",
    )
    parser.add_argument(
        "--force", action="store_true", help="Re-process even recipes with existing data"
    )
    parser.add_argument(
        "--fix-duplicates", action="store_true",
        help="Only de-duplicate managed frontmatter keys; don't recalculate",
    )
    args = parser.parse_args()

    recipes_dir = paths.recipes_dir()

    if args.fix_duplicates:
        run_fix_duplicates(recipes_dir, args.dry_run)
        return

    if args.dry_run:
        print("DRY RUN — no files will be modified\n")

    print(f"Scanning: {recipes_dir}")
    require_food_store()

    candidates = collect_recipes_needing_backfill(recipes_dir, force=args.force)
    candidates = select_only(candidates, args.only)

    candidates = apply_limit(candidates, args.limit, args.only)

    print(f"Recipes to process: {len(candidates)}\n")

    updated = skipped = failed = 0

    for filepath in candidates:
        print(f"  {filepath.name}...")
        try:
            if backfill_recipe(filepath, dry_run=args.dry_run):
                updated += 1
            else:
                print("    skipped (no ingredients / unresolved)")
                skipped += 1
        except Exception as e:
            print(f"    ERROR: {e}")
            failed += 1

    print(f"\n{'[DRY RUN] ' if args.dry_run else ''}Done:")
    print(f"  Updated: {updated}")
    print(f"  Skipped: {skipped}")
    print(f"  Failed:  {failed}")


if __name__ == "__main__":
    main()
