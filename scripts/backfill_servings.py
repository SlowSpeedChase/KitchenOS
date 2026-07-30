#!/usr/bin/env python
"""Estimate a `servings` count for recipes that are missing one.

Why this matters: a recipe with no `servings` gets its per-serving macros
divided by 1 — i.e. the whole-batch numbers masquerade as one serving (a
5,000-kcal "serving"). Those recipes are untrustworthy, so the macro-aware
suggester and the print-week macros skip or flag them. Filling in a plausible
`servings` widens how much of the library the macro features can use.

**This is an estimate, not a measurement.** Automatic servings inference is
unreliable (the parked macro-planner work plateaued around 50% within ±1), so
this tool:
  - estimates from data already in the file — no vault DB, USDA, or LLM needed:
    a recipe missing `servings` currently stores WHOLE-BATCH `nutrition_calories`
    (the engine defaulted servings→1), so `servings ≈ batch_kcal / anchor(dish_type)`;
  - writes every estimate flagged `servings_inferred: true` +
    `servings_needs_review: true` (never presented as fact);
  - is **dry-run by default** — it prints a review table and writes nothing
    unless you pass `--apply`.

After `--apply`, re-run the nutrition engine so per-serving macros are recomputed
from the new counts:

    .venv/bin/python backfill_servings.py                 # preview (writes nothing)
    .venv/bin/python backfill_servings.py --apply          # write inferred servings
    .venv/bin/python backfill_nutrition.py --force         # recompute per-serving macros

Then eyeball the recipes flagged `servings_needs_review` and correct any that
look off — the anchor is a heuristic, not the truth.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import backup, frontmatter, paths  # noqa: E402
from lib.recipe_parser import parse_recipe_file  # noqa: E402

# Typical kcal per serving by dish type — the anchor the batch total is divided
# by. Deliberately coarse; every result is flagged for review.
DISH_ANCHOR_KCAL = {
    "main": 600, "entree": 600, "dinner": 600, "lunch": 550,
    "breakfast": 400, "side": 200, "salad": 300, "soup": 300,
    "snack": 200, "appetizer": 200, "dessert": 350, "baked": 300,
    "drink": 150, "beverage": 150, "sauce": 100, "condiment": 100,
}
DEFAULT_ANCHOR_KCAL = 500
SERVINGS_MIN, SERVINGS_MAX = 1, 12

_MANAGED = ("servings", "servings_inferred", "servings_needs_review")


def _has_servings(fm: dict) -> bool:
    """True when the recipe already carries a usable servings count."""
    v = fm.get("servings")
    if v is None:
        return False
    try:
        return float(v) >= 1
    except (TypeError, ValueError):
        return False


def _anchor_for(fm: dict) -> int:
    dish = str(fm.get("dish_type") or fm.get("meal_occasion") or "").strip().lower()
    return DISH_ANCHOR_KCAL.get(dish, DEFAULT_ANCHOR_KCAL)


def estimate_servings(fm: dict) -> tuple[int, int]:
    """(estimated_servings, anchor_kcal) from whole-batch calories, clamped.

    Assumes the stored ``nutrition_calories`` is the batch total (true for
    recipes with no ``servings``, which the engine divided by 1). Returns
    ``(0, anchor)`` when there is no calorie figure to anchor on.
    """
    anchor = _anchor_for(fm)
    batch = fm.get("nutrition_calories")
    try:
        batch = int(batch)
    except (TypeError, ValueError):
        return 0, anchor
    if batch <= 0:
        return 0, anchor
    est = round(batch / anchor)
    return max(SERVINGS_MIN, min(SERVINGS_MAX, est)), anchor


def plan_backfill(recipes_dir: Path) -> list[dict]:
    """Rows for every recipe missing servings: what we'd write and why."""
    rows = []
    for filepath in sorted(recipes_dir.glob("*.md")):
        try:
            fm = parse_recipe_file(filepath.read_text(encoding="utf-8"))["frontmatter"]
        except Exception:
            continue
        if _has_servings(fm):
            continue
        est, anchor = estimate_servings(fm)
        batch = fm.get("nutrition_calories")
        rows.append({
            "file": filepath,
            "name": filepath.stem,
            "dish_type": str(fm.get("dish_type") or "—"),
            "batch_kcal": batch,
            "anchor": anchor,
            "servings": est,
            "per_serving_kcal": round(int(batch) / est) if (est and batch) else None,
            "status": "estimated" if est else "needs-nutrition-first",
        })
    return rows


def apply_row(row: dict) -> None:
    """Write the inferred servings (+ review flags) into the recipe file."""
    filepath: Path = row["file"]
    backup.create_backup(filepath)
    content = filepath.read_text(encoding="utf-8")
    new = frontmatter.apply(content, {
        "servings": row["servings"],
        "servings_inferred": "true",
        "servings_needs_review": "true",
    }, _MANAGED)
    if new is not None:
        filepath.write_text(new, encoding="utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true",
                        help="Write inferred servings (default: preview only)")
    parser.add_argument("--limit", type=int, help="Process at most N recipes")
    parser.add_argument("--recipes-dir", type=Path, default=None,
                        help="Override the Recipes dir (default: vault Recipes)")
    args = parser.parse_args(argv)

    recipes_dir = args.recipes_dir or paths.recipes_dir()
    rows = plan_backfill(recipes_dir)
    estimatable = [r for r in rows if r["status"] == "estimated"]
    if args.limit is not None:
        estimatable = estimatable[:args.limit]

    if not rows:
        print("Every recipe already has a servings count. Nothing to do.")
        return 0

    print(f"{len(rows)} recipe(s) missing servings "
          f"({len(estimatable)} estimatable, "
          f"{len(rows) - len([r for r in rows if r['status'] == 'estimated'])} need nutrition first):\n")
    print(f"{'recipe':<34} {'dish':<10} {'batch':>7} {'serv':>5} {'per':>6}  status")
    print("-" * 78)
    for r in rows:
        print(f"{r['name'][:33]:<34} {r['dish_type'][:9]:<10} "
              f"{str(r['batch_kcal'] or '—'):>7} {str(r['servings'] or '—'):>5} "
              f"{str(r['per_serving_kcal'] or '—'):>6}  {r['status']}")

    if not args.apply:
        print(f"\nDRY RUN — nothing written. Re-run with --apply to write "
              f"{len(estimatable)} inferred servings (each flagged "
              f"servings_needs_review).")
        return 0

    for r in estimatable:
        apply_row(r)
    print(f"\nWrote inferred servings to {len(estimatable)} recipe(s) "
          f"(flagged servings_inferred + servings_needs_review; backups in .history/).")
    print("Next: .venv/bin/python backfill_nutrition.py --force   "
          "# recompute per-serving macros")
    print("Then review the recipes flagged servings_needs_review and fix any that look off.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
