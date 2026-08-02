"""Nutrition-quality gates for macro-aware planning.

Two predicates decide whether a recipe's stored per-serving macros may be
ranked against a macro target, and they answer different questions:

- ``implausible`` — could a *serving* of food look like this at all? Absolute
  bounds, no reference to how the number was derived.
- ``macro_eligible`` — is the number trustworthy enough to plan on? Wraps
  ``implausible`` and adds the provenance gates (coverage, servings).

Both read only the candidate dicts produced by
``lib.recipe_index.get_recipe_index`` (no file I/O) so the suggester can gate
cheaply while ranking.

**Why absolute bounds and not a consistency check.** The obvious test is the
Atwater identity — does ``4·protein + 4·carbs + 9·fat`` agree with the stated
calories? It is useless here, and measurably so: run across the 2026-08-02
corpus it flags **1** recipe out of 248. Calories and macros are derived from
the same per-100 g record and the same gram weights, so a wrong gram weight
makes them wrong *proportionally* — the 244 g-protein smoothie's stated 1440
kcal agrees with its own macros to within 1.4%. Atwater catches transcription
corruption; it cannot see resolution error. Only absolute bounds can.

**Why coverage was never enough.** ``nutrition_coverage`` asks "did every
countable ingredient line resolve to some food and some grams". Every
resolution *error* — a package-scale gram weight for "1 whole protein powder",
an FDC match of "eggs" onto dried egg white, an undivided batch — leaves
coverage at 1.0 or raises it. So the metric is orthogonal to correctness, and
the failure it does catch (unresolved lines) is the *undercount* direction
only. Measured on the same corpus: 45 recipes fail the bounds below, and 35 of
those 45 passed ``macro_eligible``. Those 35 included the top four results the
suggester returned for a real 190 g protein target.

Ineligible recipes are not discarded by callers; they score 0 on macro-fit and
fall back to the existing overlap/waste ranking, so a thin eligible pool
degrades gracefully rather than returning nothing.
"""

from __future__ import annotations

from lib.serving_ledger import COVERAGE_REVIEW_THRESHOLD

# Per-serving bounds. Calibrated against the corpus: the median recipe is 405
# kcal/serving and p90 is 1251, so the ceiling sits just under p90 and admits
# every ordinary large dinner while refusing whole-batch totals. The floor
# catches recipes whose caloric lines silently resolved to zero grams.
MIN_KCAL_PER_SERVING = 50
MAX_KCAL_PER_SERVING = 1200

# 70 g in one serving is already a very large portion of meat or a double
# scoop; past it the number is a resolution artifact, not a meal.
MAX_PROTEIN_G_PER_SERVING = 70

# Protein cannot supply most of a substantial meal's calories. Below the floor
# it easily can (jerky, egg whites, a broth), so the share test only applies to
# servings big enough for the claim to be impossible rather than merely lean.
MAX_PROTEIN_KCAL_SHARE = 0.65
PROTEIN_SHARE_MIN_KCAL = 200

KCAL_PER_G_PROTEIN = 4


def _number(value):
    """Coerce to float, or None if it isn't one.

    Frontmatter is LLM-authored: ``nutrition_calories: "lots"`` is a real shape
    this has to survive. A value we cannot read is not a value we can call
    implausible — that gap is ``macro_eligible``'s ``no_nutrition``.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def implausible(recipe: dict) -> tuple[bool, list[str]]:
    """Could one serving of food plausibly carry these macros?

    Args:
        recipe: a candidate dict — reads ``nutrition_calories`` and
            ``nutrition_protein``. Either may be absent or unparseable.

    Returns:
        ``(implausible, reasons)``. Reason codes: ``"kcal_too_low"``,
        ``"kcal_too_high"``, ``"protein_too_high"``,
        ``"protein_share_impossible"``.

    Missing or unreadable calories return ``(False, [])`` — absence of data is
    not evidence of a bad number, and reporting it here would double up on
    ``macro_eligible``'s ``no_nutrition``.
    """
    reasons: list[str] = []

    kcal = _number(recipe.get("nutrition_calories"))
    if kcal is None:
        return (False, reasons)

    if kcal < MIN_KCAL_PER_SERVING:
        reasons.append("kcal_too_low")
    elif kcal > MAX_KCAL_PER_SERVING:
        reasons.append("kcal_too_high")

    protein = _number(recipe.get("nutrition_protein"))
    if protein is not None:
        if protein > MAX_PROTEIN_G_PER_SERVING:
            reasons.append("protein_too_high")
        if kcal >= PROTEIN_SHARE_MIN_KCAL and \
                protein * KCAL_PER_G_PROTEIN > MAX_PROTEIN_KCAL_SHARE * kcal:
            reasons.append("protein_share_impossible")

    return (bool(reasons), reasons)


def implausibility_score(recipe: dict) -> float:
    """How badly the bounds are violated, for worst-first ranking. 0.0 = fine.

    Used to order the nutrition-review queue. Sorting that queue ascending by
    *coverage* — as it did — put the coverage-1.0 catastrophes at the bottom of
    the list built to find them.
    """
    bad, _ = implausible(recipe)
    if not bad:
        return 0.0

    kcal = _number(recipe.get("nutrition_calories"))
    protein = _number(recipe.get("nutrition_protein"))
    score = 0.0

    if kcal is not None:
        if kcal > MAX_KCAL_PER_SERVING:
            score = max(score, kcal / MAX_KCAL_PER_SERVING - 1.0)
        elif kcal < MIN_KCAL_PER_SERVING:
            # A 7-kcal serving is as wrong as a 4x overcount; express the
            # shortfall on the same scale rather than capping it at 1.0.
            score = max(score, MIN_KCAL_PER_SERVING / max(kcal, 1.0) - 1.0)

    if protein is not None and protein > MAX_PROTEIN_G_PER_SERVING:
        score = max(score, protein / MAX_PROTEIN_G_PER_SERVING - 1.0)

    return score


def macro_eligible(recipe: dict) -> tuple[bool, list[str]]:
    """Is this recipe's per-serving macro data trustworthy enough to rank on?

    Args:
        recipe: a candidate dict from ``get_recipe_index`` — expects the keys
            ``nutrition_calories``, ``nutrition_protein``,
            ``nutrition_coverage`` and ``servings`` (any may be ``None`` when
            absent from frontmatter).

    Returns:
        ``(eligible, reasons)`` — ``reasons`` lists why it is *not* eligible
        (empty when eligible). Reason codes: ``"no_nutrition"``,
        ``"low_coverage"``, ``"servings_unknown"``, plus any code from
        ``implausible``.
    """
    reasons: list[str] = []

    if recipe.get("nutrition_calories") is None:
        reasons.append("no_nutrition")

    coverage = recipe.get("nutrition_coverage")
    if coverage is None or float(coverage) < COVERAGE_REVIEW_THRESHOLD:
        reasons.append("low_coverage")

    if recipe.get("servings") is None:
        reasons.append("servings_unknown")

    _bad, bad_reasons = implausible(recipe)
    reasons.extend(bad_reasons)

    return (not reasons, reasons)
