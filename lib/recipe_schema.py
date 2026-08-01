"""The one declaration of what a recipe's frontmatter may contain.

Recipe files are written by six different producers — the extractor, the
nutrition backfill, the fit backfill, the enricher, the short-title backfill and
the cook-history sync — and nothing ever stated what the union of their output
was allowed to look like. Drift accumulated silently: 13 files carried a legacy
nutrition key beside the canonical one, 3 carried a servings *range* that three
subsystems each read differently, and 1 carried a one-off key.

This module is pure: it takes an already-parsed frontmatter dict and reports
what is wrong with it. It performs no I/O, so it is equally usable from a
hermetic unit test, from an audit of the real vault, and from the normalizer
that repairs what it reports.

The allowlists below are *measured* against the 252-file corpus, not designed.
Adding a key to a recipe template means adding it here in the same commit —
that is the point of the guard, not an inconvenience it imposes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

#: Present on every one of the 252 files. A recipe missing one is malformed.
REQUIRED_KEYS = frozenset({
    "banner", "confidence_notes", "cook_time", "cssclasses", "cuisine",
    "date_added", "dietary", "difficulty", "dish_type", "equipment",
    "meal_occasion", "needs_review", "nutrition_calories", "nutrition_carbs",
    "nutrition_fat", "nutrition_protein", "nutrition_source", "peak_months",
    "prep_time", "protein", "recipe_source", "seasonal_ingredients",
    "serving_size", "servings", "source_channel", "source_url", "tags",
    "title", "total_time", "video_title",
})

#: Written by a specific producer for a subset of recipes. All optional by
#: design — see docs/OPERATIONS.md and CLAUDE.md for who writes each.
OPTIONAL_KEYS = frozenset({
    # backfill_fit.py — inference, always flagged
    "fit_buffer_candidate", "fit_craving_lane", "fit_dairy_load", "fit_effort",
    "fit_heart", "fit_needs_review", "fit_note", "fit_source", "fit_steady",
    # backfill_nutrition.py
    "nutrition_confidence", "nutrition_coverage", "nutrition_needs_review",
    "nutrition_unmatched",
    # scripts/backfill_short_titles.py
    "short_title", "short_title_inferred",
    # scripts/enrich_recipes.py — sticky "this field has no value" record
    "enrich_none",
    # lib/cook_history.py sync
    "cook_count", "last_cooked", "make_again_count", "observed_servings",
    "verdict_count",
    # scripts/backfill_servings.py and scripts/normalize_recipes.py
    "servings_inferred", "servings_needs_review",
})

KNOWN_KEYS = REQUIRED_KEYS | OPTIONAL_KEYS

#: Pre-``nutrition_*`` names. The canonical keys are FDC-sourced and per-serving;
#: these survivors are whole-recipe totals from an earlier era and disagree by up
#: to 18x. They are deleted, never migrated — every file carrying one already has
#: a non-null canonical value (verified across the corpus, 2026-08-01).
LEGACY_NUTRITION_KEYS = frozenset({"calories", "carbs", "fat"})

#: Keys removed outright by user decision (2026-07-31). ``recipe_url`` held the
#: creator's own recipe page on exactly one file; it is *not* a duplicate of
#: ``source_url``, which holds that file's YouTube short.
DROPPED_KEYS = frozenset({"recipe_url"})


@dataclass(frozen=True)
class Violation:
    """One thing wrong with one recipe's frontmatter."""

    recipe: str
    key: str
    code: str
    detail: str


def check_frontmatter(recipe: str, fm: dict) -> list[Violation]:
    """Report every way ``fm`` departs from the schema, in a stable order.

    Order is (missing required, then by key name) so two runs over the same
    input produce identical output — the audit diffs its own results.
    """
    out: list[Violation] = []

    for key in sorted(REQUIRED_KEYS - set(fm)):
        out.append(Violation(
            recipe, key, "missing_required_key",
            f"every recipe carries {key!r}; this one does not",
        ))

    for key in sorted(fm):
        if key in LEGACY_NUTRITION_KEYS:
            out.append(Violation(
                recipe, key, "legacy_nutrition_key",
                f"{key!r} is superseded by 'nutrition_{key}' and disagrees with it",
            ))
        elif key not in KNOWN_KEYS:
            out.append(Violation(
                recipe, key, "unknown_key",
                f"{key!r} is not in the declared schema",
            ))

    servings = fm.get("servings")
    if servings is not None and not isinstance(servings, (int, float)):
        out.append(Violation(
            recipe, "servings", "servings_not_numeric",
            f"servings={servings!r} is read as 4.0 by week_view and as a "
            f"different number by nutrition_engine",
        ))

    return out


def servings_low_end(value) -> int | None:
    """Coerce a frontmatter ``servings`` value to its LOW end, or ``None``.

    User decision, 2026-07-31: a range collapses to its low end, because fewer
    servings means higher per-serving calories — the conservative direction for
    a macro target. This deliberately differs from
    ``nutrition_engine._parse_servings``, which takes the midpoint; the
    divergence is pinned by a test so changing either side is a conscious act.

    Returns ``None`` when nothing numeric is present, so the caller can leave
    the value alone rather than invent one.
    """
    if isinstance(value, bool):  # bool is an int subclass — not a serving count
        return None
    if isinstance(value, (int, float)):
        return int(value) if value >= 1 else None
    if not isinstance(value, str):
        return None

    # A range first, so "4-6" yields 4 rather than the bare first integer rule
    # below happening to agree. Handles hyphen, en/em dash, and "to".
    rng = re.search(r"(\d+)\s*(?:-|–|—|to)\s*(\d+)", value)
    if rng:
        lo, hi = int(rng.group(1)), int(rng.group(2))
        if lo >= 1 and hi >= lo:
            return lo

    single = re.search(r"\d+", value)
    if single:
        n = int(single.group())
        if n >= 1:
            return n
    return None
