"""Aggregate the serving ledger back onto recipe notes.

The recipe library does not know what it yields: 46% of notes carry no
``servings``, and stored nutrition is often per batch rather than per serving.
That gap is why the system cannot say whether a recipe is tonight's dinner or
four frozen lunches — and it is why automated planning on top of it would be
guesswork.

Asking someone to fill that in is a chore, and chores do not survive contact
with a tired Tuesday. Cooking the thing and recording the yield is not a chore,
it is the act itself. This module turns those ledger rows into frontmatter so
the knowledge accrues as a side effect of use.

The authored ``servings`` is never overwritten. It is the recipe's claim;
``observed_servings`` is what actually happened. A disagreement between them is
information (the recipe over-promises, or the cook scaled it), so both stay
visible rather than one silently winning — the same honest-about-inference rule
the nutrition fields follow.
"""
from __future__ import annotations

import statistics
from typing import Optional

from lib import backup, frontmatter, inventory_db, paths

# Keys this module owns. Anything else in the note is left byte-identical.
MANAGED_KEYS = frozenset({
    "cook_count", "observed_servings", "make_again_count",
    "verdict_count", "last_cooked",
})


def recipe_stats(recipe: str) -> dict:
    """Ledger aggregates for one recipe, or ``{}`` if it has never been cooked."""
    conn = inventory_db.connect()
    try:
        rows = conn.execute(
            "SELECT servings_produced, make_again, date, cooked_at"
            " FROM cooks WHERE recipe = ?", (recipe,)
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        return {}

    # A `cooks` row is created when a recipe is dropped onto the board, so the
    # table is mostly a record of *intent*. Counting rows therefore measured
    # planning, not cooking: the live ledger held 16 rows against 2 real cooks,
    # yet 10 recipes carried `last_cooked` and 13 carried `cook_count`. Worse
    # for this module's actual purpose — learning a recipe's true yield from
    # what came out of the pan — a batch that was never made has no yield to
    # observe, and a plan for next month is not the last time you made it.
    #
    # `cooked_at` is the signal. A verdict counts too: judging a dish asserts
    # you made it, and the verdict nudge asks about dishes whose date has passed,
    # so a verdict on a row nobody tapped 🍳 for is a real path.
    cooked = [r for r in rows
              if r["cooked_at"] is not None or r["make_again"] is not None]
    if not cooked:
        return {}

    yields = [float(r["servings_produced"]) for r in cooked
              if r["servings_produced"] is not None]
    # A verdict of NULL means "not judged", which must not read as a bad review,
    # so verdicts are counted separately from cooks rather than defaulting to 0.
    verdicts = [r["make_again"] for r in cooked if r["make_again"] is not None]
    # Prefer when it was cooked; fall back to the planned date only for a row
    # that *is* cooked (a verdict without a timestamp).
    dates = [r["cooked_at"] or r["date"] for r in cooked
             if (r["cooked_at"] or r["date"])]

    stats = {
        "cook_count": len(cooked),
        "verdict_count": len(verdicts),
        "make_again_count": sum(1 for v in verdicts if v),
    }
    if yields:
        # Median, not mean: with a handful of data points one mistyped yield
        # would drag the estimate somewhere the recipe has never been.
        median = statistics.median(yields)
        stats["observed_servings"] = int(median) if median == int(median) else round(median, 1)
    if dates:
        stats["last_cooked"] = max(dates)[:10]
    return stats


def _recipe_path(recipe: str, recipes_dir=None):
    """Locate a recipe note, tolerating case drift between ledger and filename."""
    d = recipes_dir or paths.recipes_dir()
    exact = d / f"{recipe}.md"
    if exact.exists():
        return exact
    target = recipe.strip().lower()
    for candidate in d.glob("*.md"):
        if candidate.stem.lower() == target:
            return candidate
    return None


def sync_recipe(recipe: str, recipes_dir=None) -> bool:
    """Write this recipe's cook stats onto its note. True if the file changed.

    Degrades quietly when the note is missing or has no frontmatter: ledger rows
    outlive renames and deletions, and a stale row must never break a cook write.
    """
    path = _recipe_path(recipe, recipes_dir)
    if path is None:
        return False

    stats = recipe_stats(recipe)
    original = path.read_text(encoding="utf-8")
    if not stats:
        # Every cook was deleted. Strip the keys rather than leaving a stale
        # "cooked 3 times" on a recipe with no cooks — a wrong number is worse
        # than no number, and Phase-4 trend views read these directly.
        if not any(f"\n{k}:" in f"\n{original}" for k in MANAGED_KEYS):
            return False
        updated = frontmatter.apply(original, {}, MANAGED_KEYS, remove=MANAGED_KEYS)
    else:
        updated = frontmatter.apply(original, stats, MANAGED_KEYS)
    if updated is None or updated == original:
        return False
    # write_note snapshots first: this runs automatically from a cook write, so
    # nobody is watching, and the vault is not in git.
    return backup.write_note(path, updated)


def sync_all(recipes_dir=None) -> dict:
    """Refresh every recipe that has ever been cooked."""
    conn = inventory_db.connect()
    try:
        names = [r["recipe"] for r in
                 conn.execute("SELECT DISTINCT recipe FROM cooks").fetchall()]
    finally:
        conn.close()

    updated = sum(1 for name in names if sync_recipe(name, recipes_dir))
    return {"recipes": len(names), "updated": updated}
