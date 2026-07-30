#!/usr/bin/env python
"""Estimate a `servings` count for recipes that are missing one.

Why this matters: a recipe with no `servings` gets its per-serving macros
divided by 1 — i.e. the whole-batch numbers masquerade as one serving (a
5,000-kcal "serving"). Those recipes are untrustworthy, so the macro-aware
suggester and the print-week macros skip or flag them. Filling in a plausible
`servings` widens how much of the library the macro features can use.

**Mostly an estimate, not a measurement.** Automatic servings inference is
unreliable (the parked macro-planner work plateaued around 50% within ±1), so
this tool:
  - prefers a yield the recipe *states* ("Serves 4", "Makes 24 cookies") — that
    is a measurement, so it is written as plain fact with no review flag and is
    NOT clamped to `SERVINGS_MAX` (a 24-cookie batch is a real yield);
  - otherwise estimates from data already in the file — no vault DB, USDA, or LLM
    needed: a recipe missing `servings` currently stores WHOLE-BATCH
    `nutrition_calories` (the engine defaulted servings→1), so
    `servings ≈ batch_kcal / anchor(dish_type)`;
  - writes every *estimate* flagged `servings_inferred: true` +
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
import re
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

# A yield stated in the recipe text is a measurement, so it gets a far looser
# bound than the anchor estimate: clamping "Makes 24 cookies" to SERVINGS_MAX
# would corrupt a count the recipe told us outright.
STATED_MIN, STATED_MAX = 1, 200

# "Makes 2 cups" is a batch volume, not a yield. Since a stated count is written
# as fact with no review flag, a measure noun following the number has to
# disqualify the match — otherwise a 2-cup sauce silently becomes 2 servings.
_MEASURE_NOUN = (
    r"cups?|tbsp|tablespoons?|tsp|teaspoons?|ml|milliliters?|l|liters?|litres?|"
    r"oz|ounces?|g|grams?|kg|kilograms?|lbs?|pounds?|quarts?|qt|pints?|pt|"
    r"gallons?|gal|inch(?:es)?|cm"
)

# Yield patterns, tried in order; each captures the count in group 1.
_BODY_PATTERNS = [
    re.compile(r"(?:serves|feeds)\s+(?:about\s+)?(\d+)", re.IGNORECASE),
    # The \b after the digits is load-bearing: without it the group backtracks
    # to a shorter number to escape the exclusion, and "Makes 500 g" matches 50.
    re.compile(rf"(?:makes|yields?)\b[:\s]+(?:about\s+)?(\d+)\b"
               rf"(?!\s*(?:{_MEASURE_NOUN})\b)", re.IGNORECASE),
    re.compile(r"(\d+)\s+servings?\b", re.IGNORECASE),
]

_MANAGED = ("servings", "servings_inferred", "servings_needs_review")
# Cleared when a stated yield supersedes an earlier anchor estimate — `rewrite`
# only de-duplicates managed keys, so a stale flag has to be removed explicitly.
_INFERENCE_FLAGS = ("servings_inferred", "servings_needs_review")


def servings_from_body(body) -> int | None:
    """An explicit yield stated in the recipe text, or None if none is stated."""
    if not body:
        return None
    for pattern in _BODY_PATTERNS:
        m = pattern.search(body)
        if m:
            n = int(m.group(1))
            if STATED_MIN <= n <= STATED_MAX:
                return n
    return None


def _per_serving_kcal(batch, servings) -> int | None:
    """Per-serving kcal, or None when either figure is unusable."""
    if not servings:
        return None
    try:
        return round(int(batch) / servings)
    except (TypeError, ValueError):
        return None


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
            parsed = parse_recipe_file(filepath.read_text(encoding="utf-8"))
        except Exception:
            continue
        fm = parsed["frontmatter"]
        if _has_servings(fm):
            continue
        batch = fm.get("nutrition_calories")
        # A stated yield wins outright — it is what the recipe says it makes,
        # so it never goes through the kcal anchor.
        stated = servings_from_body(parsed.get("body"))
        if stated is not None:
            servings, anchor, status = stated, _anchor_for(fm), "stated"
        else:
            servings, anchor = estimate_servings(fm)
            status = "estimated" if servings else "needs-nutrition-first"
        rows.append({
            "file": filepath,
            "name": filepath.stem,
            "dish_type": str(fm.get("dish_type") or "—"),
            "batch_kcal": batch,
            "anchor": anchor,
            "servings": servings,
            "per_serving_kcal": _per_serving_kcal(batch, servings),
            "status": status,
        })
    return rows


def apply_row(row: dict) -> None:
    """Write the servings count, flagging it for review only if it was inferred."""
    filepath: Path = row["file"]
    backup.create_backup(filepath)
    content = filepath.read_text(encoding="utf-8")
    updates = {"servings": row["servings"]}
    remove: tuple = ()
    if row["status"] == "stated":
        # The recipe stated it, so drop any flag an earlier estimate left behind.
        remove = _INFERENCE_FLAGS
    else:
        updates["servings_inferred"] = "true"
        updates["servings_needs_review"] = "true"
    new = frontmatter.apply(content, updates, _MANAGED, remove)
    if new is not None:
        filepath.write_text(new, encoding="utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true",
                        help="Write the servings counts (default: preview only)")
    parser.add_argument("--limit", type=int, help="Process at most N recipes")
    parser.add_argument("--recipes-dir", type=Path, default=None,
                        help="Override the Recipes dir (default: vault Recipes)")
    args = parser.parse_args(argv)

    recipes_dir = args.recipes_dir or paths.recipes_dir()
    rows = plan_backfill(recipes_dir)
    stated = [r for r in rows if r["status"] == "stated"]
    estimated = [r for r in rows if r["status"] == "estimated"]
    unusable = [r for r in rows if r["status"] == "needs-nutrition-first"]
    writable = stated + estimated
    if args.limit is not None:
        writable = writable[:args.limit]

    if not rows:
        print("Every recipe already has a servings count. Nothing to do.")
        return 0

    print(f"{len(rows)} recipe(s) missing servings "
          f"({len(stated)} stated in the recipe, {len(estimated)} estimated, "
          f"{len(unusable)} need nutrition first):\n")
    print(f"{'recipe':<34} {'dish':<10} {'batch':>7} {'serv':>5} {'per':>6}  status")
    print("-" * 78)
    for r in rows:
        print(f"{r['name'][:33]:<34} {r['dish_type'][:9]:<10} "
              f"{str(r['batch_kcal'] or '—'):>7} {str(r['servings'] or '—'):>5} "
              f"{str(r['per_serving_kcal'] or '—'):>6}  {r['status']}")

    n_stated = len([r for r in writable if r["status"] == "stated"])
    n_estimated = len(writable) - n_stated

    if not args.apply:
        print(f"\nDRY RUN — nothing written. Re-run with --apply to write "
              f"{len(writable)} servings count(s): {n_stated} stated as fact, "
              f"{n_estimated} estimated and flagged servings_needs_review.")
        return 0

    for r in writable:
        apply_row(r)
    print(f"\nWrote servings to {len(writable)} recipe(s): {n_stated} stated by the "
          f"recipe itself, {n_estimated} flagged servings_inferred + "
          f"servings_needs_review (backups in .history/).")
    print("Next: .venv/bin/python backfill_nutrition.py --force   "
          "# recompute per-serving macros")
    print("Then review the recipes flagged servings_needs_review and fix any that look off.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
