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
    # import_epub.py — print page of the source cookbook
    "book_page",
    # scripts/enrich_recipes.py — sticky "this field has no value" record
    "enrich_none",
    # lib/cook_history.py sync
    "cook_count", "last_cooked", "make_again_count", "observed_servings",
    "verdict_count",
    # scripts/backfill_servings.py and scripts/normalize_recipes.py
    "servings_inferred", "servings_needs_review",
    # recipe extraction — tri-state: true / false / null. `null` is the honest
    # answer for most of the corpus and must stay distinct from `false`, since
    # "nobody has said" is not "it doesn't freeze".
    "freezes_well",
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


def duplicate_keys(fm_text: str) -> list[str]:
    """Top-level keys appearing more than once, in first-offence order.

    ``check_frontmatter`` takes an already-parsed dict, so it cannot see a
    duplicate — the mapping has already collapsed it, and PyYAML keeps only the
    last occurrence. That blind spot matters here specifically: the duplicate
    ``nutrition_calories:`` line ``migrate_recipes.rename_nutrition_keys`` used
    to emit is invisible to every dict-based check, so the corpus guard would
    have passed on exactly the artifact this branch exists to prevent.

    Operates on raw text, and only on top-level keys: an indented line is a list
    item or a continuation, never a key.
    """
    seen: set[str] = set()
    dupes: list[str] = []
    for line in fm_text.split("\n"):
        if not line or line[:1].isspace():
            continue
        m = _KEY_LINE_RE.match(line)
        if not m:
            continue
        key = m.group(1)
        if key in seen and key not in dupes:
            dupes.append(key)
        seen.add(key)
    return dupes


_KEY_LINE_RE = re.compile(r"^([A-Za-z_][\w]*):")

#: Words that mean "this number is a serving count". Deliberately excludes yield
#: verbs like "makes" — "Makes 24 cookies" is a yield, not 24 servings.
_SERVING_WORD = r"(?:serves|serving|servings|portions?|people|persons?)"


def servings_low_end(value) -> int | None:
    """Coerce a frontmatter ``servings`` value to its LOW end, or ``None``.

    User decision, 2026-07-31: a range collapses to its low end, because fewer
    servings means higher per-serving calories — the conservative direction for
    a macro target.

    **This is a *write*-time reader and is deliberately stricter than
    ``nutrition_engine._parse_servings``, in policy AND in parsing.** The engine
    reads a value someone else already stored and must return its best guess for
    a macro calculation, so it takes a range's midpoint and falls back to the
    first integer it can find anywhere in the string. This function decides what
    to *persist into the user's file*, where a wrong number is far worse than no
    number: `"makes 24 cookies, serves 6"` under a first-integer rule writes
    **24**, silently rescaling every per-serving macro by 4x. So it accepts only
    three unambiguous shapes and returns ``None`` for everything else, leaving
    the string in place for ``--check`` to keep reporting:

    1. a range — ``"4-6 servings (estimated)"`` → 4
    2. a number anchored to a serving word — ``"Serves 4"``, ``"about 2 servings"``
    3. a bare number — ``"8"``

    Both the policy and the parsing divergence are pinned by tests, so changing
    either side is a conscious act.
    """
    if isinstance(value, bool):  # bool is an int subclass — not a serving count
        return None
    if isinstance(value, (int, float)):
        return int(value) if value >= 1 else None
    if not isinstance(value, str):
        return None

    # 1. A range, first — "serves 4-6" must yield 4, not be caught by rule 2.
    #    Handles hyphen, en/em dash, and "to". A descending or zero pair is not
    #    a range (this is what keeps "2026-08-01" from reading as 2026).
    rng = re.search(r"(\d+)\s*(?:-|–|—|to)\s*(\d+)", value)
    if rng:
        lo, hi = int(rng.group(1)), int(rng.group(2))
        if lo >= 1 and hi >= lo:
            return lo

    # 2. A number anchored to a serving word, in either order. Anchoring rather
    #    than taking the first integer is what makes a yield ("24 cookies") lose
    #    to a serving count ("serves 6") in the same string.
    for pattern in (rf"{_SERVING_WORD}\s*:?\s*(\d+)", rf"(\d+)\s+{_SERVING_WORD}"):
        m = re.search(pattern, value, re.IGNORECASE)
        if m:
            n = int(m.group(1))
            if n >= 1:
                return n

    # 3. A bare number, and nothing else in the string.
    bare = re.fullmatch(r"\s*(\d+)\s*", value)
    if bare:
        n = int(bare.group(1))
        if n >= 1:
            return n

    return None
