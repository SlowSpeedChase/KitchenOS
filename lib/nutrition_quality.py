"""Nutrition-quality gates for macro-aware planning.

A single predicate, ``macro_eligible``, decides whether a recipe's stored
per-serving macros are trustworthy enough to rank against a macro target.
It reads only the candidate dicts produced by ``lib.recipe_index.get_recipe_index``
(no file I/O) so the suggester can gate cheaply while ranking.

Eligibility is deliberately conservative — the same coverage threshold the
serving ledger uses to flag a day as low-confidence
(``serving_ledger.COVERAGE_REVIEW_THRESHOLD``). Ineligible recipes are not
discarded by callers; they simply score 0 on macro-fit and fall back to the
existing overlap/waste ranking, so a thin eligible pool degrades gracefully
rather than returning nothing.
"""

from __future__ import annotations

from lib.serving_ledger import COVERAGE_REVIEW_THRESHOLD


def macro_eligible(recipe: dict) -> tuple[bool, list[str]]:
    """Is this recipe's per-serving macro data trustworthy enough to rank on?

    Args:
        recipe: a candidate dict from ``get_recipe_index`` — expects the keys
            ``nutrition_calories``, ``nutrition_coverage`` and ``servings``
            (any may be ``None`` when absent from frontmatter).

    Returns:
        ``(eligible, reasons)`` — ``reasons`` lists why it is *not* eligible
        (empty when eligible). Reason codes: ``"no_nutrition"``,
        ``"low_coverage"``, ``"servings_unknown"``.
    """
    reasons: list[str] = []

    if recipe.get("nutrition_calories") is None:
        reasons.append("no_nutrition")

    coverage = recipe.get("nutrition_coverage")
    if coverage is None or float(coverage) < COVERAGE_REVIEW_THRESHOLD:
        reasons.append("low_coverage")

    if recipe.get("servings") is None:
        reasons.append("servings_unknown")

    return (not reasons, reasons)
