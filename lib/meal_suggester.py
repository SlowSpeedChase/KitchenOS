"""Meal suggestion engine — ingredient overlap scoring with AI reasoning."""

import json
import os
import re
from pathlib import Path
from typing import Optional

import requests

try:
    import anthropic
    _api_key = os.getenv("ANTHROPIC_API_KEY")
    anthropic_client = anthropic.Anthropic(api_key=_api_key) if _api_key else None
except ImportError:
    anthropic_client = None

PANTRY_CONFIG_PATH = Path(__file__).parent.parent / "config" / "pantry_staples.json"

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "mistral:7b"

CLAUDE_MODEL = "claude-haiku-4-5-20251001"
CLAUDE_MAX_TOKENS = 200

OVERLAP_THRESHOLD = 0.5

# Macro-aware ranking. When a day's remaining macro gap is passed to the ranker,
# recipes are scored on how much of that gap one serving closes — protein is
# weighted over calories because it's the user's priority and the hardest macro
# to hit. macro_fit is a secondary sort axis *below* waste (never waste food) and
# *above* ingredient overlap. With no gap passed, macro_fit is 0 for every recipe
# and the sort collapses to the original (waste, overlap) order.
MACRO_PROTEIN_WEIGHT = 0.7
MACRO_CALORIE_WEIGHT = 0.3
MACRO_FIT_THRESHOLD = 0.5

# Layer 3 (waste-aware planning): using up food you already have that's about to
# spoil is the primary ranking axis — recipes are sorted by how many at-risk
# items they use first, then by planned-meal overlap as the tiebreak. This bonus
# is the per-item weight in the informational ``rank_score`` (count + overlap);
# at 1.0 that number stays monotonic with the (waste_count, overlap) sort key.
WASTE_BONUS = 1.0

# Words to strip from ingredient names for normalization
PREP_WORDS = {
    "diced", "minced", "chopped", "sliced", "grated", "shredded",
    "crushed", "ground", "dried", "fresh", "frozen", "canned",
    "finely", "roughly", "thinly", "coarsely",
    "large", "medium", "small", "extra", "boneless", "skinless",
    "low-fat", "nonfat", "whole", "raw",
}


def _profile_block() -> str:
    """The user's food system as a prompt section, or '' if they have none.

    Always safe to interpolate: an absent profile yields an empty string, so
    suggestions degrade to the previous behaviour rather than failing. Any
    section the user adds to the note reaches the model here without a code
    change — that is the point of passing prose rather than parsed fields.
    """
    try:
        from lib import profile as profile_mod
        p = profile_mod.load_profile()
    except Exception:
        return ""
    if p is None:
        return ""
    return f"## Their food system (personal profile)\n{p.prompt_context()}\n"


def load_pantry_staples() -> set[str]:
    """Load pantry staples from config file."""
    try:
        with open(PANTRY_CONFIG_PATH) as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def _waste_uses(recipe_items: list[str],
                at_risk: list[tuple[str, frozenset]]) -> list[str]:
    """At-risk inventory names this recipe would use up.

    Matches each at-risk item against the recipe's ingredients via the same
    singularized token-containment as ``use_it_up`` ("fresh strawberries" in the
    fridge matches a "strawberries" ingredient). Returns the at-risk item names,
    de-duplicated, preserving the (urgency-sorted) order they were passed in.
    """
    if not at_risk:
        return []
    from lib.recipe_matcher import _content_tokens

    ing_sets = [t for t in (_content_tokens(i) for i in recipe_items) if t]
    if not ing_sets:
        return []
    used = []
    for name, item_tokens in at_risk:
        if not item_tokens:
            continue
        if any(item_tokens <= ing or ing <= item_tokens for ing in ing_sets):
            if name not in used:
                used.append(name)
    return used


def load_at_risk_index(today=None) -> list[tuple[str, frozenset]]:
    """Live at-risk inventory as ``(name, token_set)`` pairs, most urgent first.

    Reuses ``use_it_up.at_risk_items`` (expiry window + staple exclusion) so the
    suggester and the Use-It-Up note agree on what counts as at risk. Returns an
    empty list (degrading to plain overlap ranking) if inventory can't be read.
    """
    try:
        from lib.inventory import read_inventory
        from lib.recipe_matcher import _content_tokens
        from lib.use_it_up import at_risk_items

        flagged = at_risk_items(read_inventory(), today)
        return [(it.name, _content_tokens(it.name)) for _status, it in flagged]
    except Exception:
        return []


# The recipe template annotates rendered ingredient rows ("water *(inferred)*"),
# and get_recipe_index reads those cells straight back as ingredient_items. Left in
# place the annotation is treated as part of the name, so "water *(inferred)*" never
# matches the pantry staple "water" and manufactures false overlap between any two
# recipes that happen to share an inferred item.
_DISPLAY_ANNOTATION = re.compile(r"\*\([^)]*\)\*")

# Cookbook ingredient lines carry metric conversions and cross-references in
# parentheses ("1 pound (455 g) white beans", "cashew cheese (this page)"), and a
# prep or variety clause after a comma ("1 large yellow onion, diced"; "white beans,
# such as great northern"). Both are noise for matching: they made "garlic cloves ,
# peeled" and "garlic cloves" two different ingredients, and left names like
# "yellow onion ," that match nothing at all.
_PARENTHETICAL = re.compile(r"\([^)]*\)")


def normalize_ingredient(item: str) -> str:
    """Normalize an ingredient name for matching.

    Lowercases, strips display annotations, parenthetical asides, any clause after
    the first comma, preparation methods and adjectives.
    """
    item = _DISPLAY_ANNOTATION.sub(" ", item)
    item = _PARENTHETICAL.sub(" ", item)
    item = item.split(",")[0]
    item = item.lower().strip()
    words = item.split()
    filtered = [w for w in words if w not in PREP_WORDS]
    return " ".join(filtered) if filtered else item


def _candidate_macros(recipe: dict) -> Optional[dict]:
    """Per-serving macros off a recipe-index candidate dict, or None.

    Reads the ``nutrition_*`` keys already surfaced by ``get_recipe_index`` — no
    file I/O. Returns None when the recipe has no calorie figure (the same
    presence gate ``serving_ledger.recipe_macros`` uses).
    """
    if recipe.get("nutrition_calories") is None:
        return None
    return {
        "calories": int(recipe.get("nutrition_calories") or 0),
        "protein": int(recipe.get("nutrition_protein") or 0),
        "carbs": int(recipe.get("nutrition_carbs") or 0),
        "fat": int(recipe.get("nutrition_fat") or 0),
    }


def _gap_fit(macros: dict, gap: dict) -> float:
    """How much of the day's remaining protein+calorie gap one serving closes.

    Each term is capped at 1.0 (``min``) so an oversized recipe cannot outscore a
    right-sized one, and a macro whose gap is already met (``<= 0``) contributes
    nothing. Protein is weighted over calories per the user's priority.
    """
    gap_p = gap.get("protein") or 0
    gap_c = gap.get("calories") or 0
    fill_p = min(macros["protein"], gap_p) / gap_p if gap_p > 0 else 0.0
    fill_c = min(macros["calories"], gap_c) / gap_c if gap_c > 0 else 0.0
    return round(MACRO_PROTEIN_WEIGHT * fill_p + MACRO_CALORIE_WEIGHT * fill_c, 3)


#: Nouns naming the *form* a staple is sold or measured in. "garlic cloves" is
#: garlic; "garlic powder" is not, and neither is "garlic bread" — a
#: transformation or a different dish is a different food, which is the
#: compound-food trap the audit files under Phase 4. Keep this list to words that
#: describe shape or packaging only.
_STAPLE_FORM_NOUNS = {
    "clove", "cloves", "head", "heads", "bulb", "bulbs",
    "leaf", "leaves", "sprig", "sprigs", "stalk", "stalks",
}


def _is_pantry(name: str, pantry: set) -> bool:
    """Whether a normalized ingredient is a pantry staple.

    Exact match, or a qualified form of one. The qualifier can sit on either
    side, and both directions had to be fixed separately:

    - **Before** the staple — "kosher salt", "extra-virgin olive oil", "freshly
      ground black pepper". Handled by the suffix test.
    - **After** it — "garlic cloves", "onion bulb". This one was open until
      2026-08-02 and mattered more than it looks: with `garlic` slipping the
      filter, it counted as genuine shared shopping in **77 of 144** composed
      plate pairings, and inflated every overlap score in `use_it_up`, `cook_now`
      and POST /api/recipes/by-ingredients, which share this scorer.

    The trailing form is deliberately restricted to `_STAPLE_FORM_NOUNS` rather
    than "any single extra word", because "garlic powder" and "garlic bread" are
    different foods and must keep scoring as real ingredients.
    """
    if name in pantry:
        return True
    if any(name.endswith(" " + staple) for staple in pantry):
        return True
    words = name.split()
    return (
        len(words) > 1
        and words[-1] in _STAPLE_FORM_NOUNS
        and " ".join(words[:-1]) in pantry
    )


def score_overlap(
    recipe_items: list[str],
    planned_items: set[str],
    pantry: set[str],
) -> tuple[float, set[str]]:
    """Score a recipe's ingredient overlap with planned meals.

    Args:
        recipe_items: Ingredient item strings from the recipe
        planned_items: Set of normalized ingredient names already planned
        pantry: Set of pantry staple names to exclude

    Returns:
        (score 0.0-1.0, set of shared ingredient names)
    """
    normalized = [normalize_ingredient(item) for item in recipe_items]
    non_pantry = [n for n in normalized if not _is_pantry(n, pantry)]

    if not non_pantry:
        return 0.0, set()

    shared = {n for n in non_pantry if n in planned_items}
    score = len(shared) / len(non_pantry)
    return score, shared


def rank_candidates(
    candidates: list[dict],
    planned_items: set[str],
    pantry: set[str],
    limit: int = 10,
    exclude_names: set[str] | None = None,
    at_risk: list[tuple[str, frozenset]] | None = None,
    macro_gap: dict | None = None,
) -> list[dict]:
    """Rank recipe candidates by ingredient overlap, biased toward using waste.

    Args:
        candidates: List of recipe dicts with 'name' and 'ingredient_items'
        planned_items: Set of normalized ingredient names from planned meals
        pantry: Pantry staples to exclude
        limit: Max candidates to return
        exclude_names: Recipe names to skip (already planned)
        at_risk: Optional ``(name, token_set)`` pairs for inventory that's
            expiring soon (from :func:`load_at_risk_index`). Recipes that use
            these get a ``WASTE_BONUS`` per item, so the plan fights food waste.
        macro_gap: Optional ``{"protein": g, "calories": kcal}`` remaining-gap
            dict for the target day. When given, eligible recipes are scored on
            how much of the gap one serving closes (``macro_fit``), which becomes
            a sort axis between waste and overlap. When ``None`` every recipe gets
            ``macro_fit == 0.0`` and the ordering is identical to the old
            (waste, overlap) behaviour.

    Returns:
        Sorted list of dicts with 'name', 'score', 'shared_ingredients',
        'waste_uses', 'rank_score' (overlap + waste bonus), plus 'nutrition'
        (per-serving macros or None), 'macro_fit' (0.0–1.0) and
        'nutrition_unknown' (True when the recipe's macros aren't trustworthy).
        Sorted by (waste count, macro_fit, overlap) — identical to the old score
        order when ``at_risk`` and ``macro_gap`` are both empty.
    """
    from lib.nutrition_quality import macro_eligible

    exclude = exclude_names or set()
    at_risk = at_risk or []
    scored = []

    for recipe in candidates:
        if recipe["name"] in exclude:
            continue
        items = recipe.get("ingredient_items", [])
        if not items:
            continue

        score, shared = score_overlap(items, planned_items, pantry)
        waste_uses = _waste_uses(items, at_risk)
        rank_score = round(score + WASTE_BONUS * len(waste_uses), 3)

        eligible, _reasons = macro_eligible(recipe)
        macros = _candidate_macros(recipe)
        if macro_gap and eligible and macros:
            macro_fit = _gap_fit(macros, macro_gap)
        else:
            macro_fit = 0.0

        scored.append({
            "name": recipe["name"],
            "score": round(score, 3),
            "shared_ingredients": sorted(shared),
            "waste_uses": waste_uses,
            "rank_score": rank_score,
            "ingredient_items": items,
            "nutrition": macros,
            "macro_fit": macro_fit,
            "nutrition_unknown": not eligible,
        })

    # Waste count is the primary axis; macro-fit (bucketed to 2dp so overlap stays
    # a meaningful tiebreak within a fit band) is second; overlap is the tiebreak.
    # Identical to the old pure-overlap order when nothing is at risk and no macro
    # gap is supplied (every macro_fit is 0.0).
    scored.sort(
        key=lambda r: (len(r["waste_uses"]), round(r["macro_fit"], 2), r["score"]),
        reverse=True,
    )
    return scored[:limit]


def normalize_ingredients_ollama(items: list[str]) -> list[str]:
    """Normalize ingredient names using Ollama, with fallback to simple normalization.

    Args:
        items: Raw ingredient item strings

    Returns:
        List of normalized ingredient names (same length as input)
    """
    from prompts.meal_suggestion import NORMALIZE_PROMPT

    prompt = NORMALIZE_PROMPT.format(
        ingredients=json.dumps(items)
    )

    try:
        response = requests.post(
            OLLAMA_URL,
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False, "format": "json"},
            timeout=60,
        )
        if response.status_code != 200:
            return [normalize_ingredient(item) for item in items]

        data = response.json()
        raw = data.get("response", "")

        parsed = json.loads(raw)
        if isinstance(parsed, list) and len(parsed) == len(items):
            return [str(n).lower().strip() for n in parsed]

        return [normalize_ingredient(item) for item in items]

    except (requests.RequestException, json.JSONDecodeError, ValueError):
        return [normalize_ingredient(item) for item in items]


def _macro_block(macro_gap: dict | None) -> str:
    """The remaining-macro-gap section for the Claude prompt, or '' if no gap.

    Always safe to interpolate: no gap yields an empty string, so the prompt
    degrades to the pre-macro wording rather than showing an empty header.
    """
    if not macro_gap:
        return ""
    p = macro_gap.get("protein") or 0
    c = macro_gap.get("calories") or 0
    if p <= 0 and c <= 0:
        return ""
    return ("\n## Remaining macro gap for the day "
            "(prefer candidates that help close it, protein first):\n"
            f"- Protein: {p} g left\n- Calories: {c} kcal left\n")


def _candidate_line(c: dict) -> str:
    """A candidate bullet for the Claude prompt, with macros when known."""
    line = (f"- **{c['name']}** (overlap: {c['score']:.0%}, "
            f"shared: {', '.join(c['shared_ingredients'])})")
    n = c.get("nutrition")
    if n and not c.get("nutrition_unknown"):
        line += f" — {n.get('protein', 0)}g protein, {n.get('calories', 0)} kcal"
    return line


def suggest_with_claude(
    planned_meals: list[dict],
    candidates: list[dict],
    day: str,
    meal: str,
    macro_gap: dict | None = None,
) -> Optional[dict]:
    """Ask Claude to pick the best candidate or suggest a new idea.

    Args:
        planned_meals: List of dicts with day, meal, name, ingredients
        candidates: Ranked list from rank_candidates()
        day: Target day (e.g., "Tuesday")
        meal: Target meal (e.g., "dinner")
        macro_gap: Optional ``{"protein", "calories"}`` remaining gap; when given,
            the prompt asks Claude to prefer candidates that help close it.

    Returns:
        Dict with name, reason, is_new_idea, new_ingredients_needed, or None on failure
    """
    if anthropic_client is None:
        return None

    from prompts.meal_suggestion import SUGGEST_PROMPT

    planned_text = "\n".join(
        f"- {m['day']} {m['meal']}: **{m['name']}** (ingredients: {', '.join(m['ingredients'])})"
        for m in planned_meals
    )

    candidate_text = "\n".join(_candidate_line(c) for c in candidates[:10])

    prompt = SUGGEST_PROMPT.format(
        profile=_profile_block(),
        planned_meals=planned_text,
        macro_block=_macro_block(macro_gap),
        candidates=candidate_text,
        day=day,
        meal=meal,
    )

    try:
        message = anthropic_client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=CLAUDE_MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = message.content[0].text
        json_start = raw.find("{")
        json_end = raw.rfind("}") + 1
        if json_start == -1 or json_end == 0:
            return None

        result = json.loads(raw[json_start:json_end])
        return {
            "name": result.get("name", ""),
            "reason": result.get("reason", ""),
            "is_new_idea": result.get("is_new_idea", False),
            "new_ingredients_needed": result.get("new_ingredients_needed", []),
        }

    except Exception:
        return None


def suggest_for_empty_week(
    recipe_summaries: list[dict],
    day: str,
    meal: str,
) -> Optional[dict]:
    """Ask Claude to suggest a starting recipe when the week is empty.

    Args:
        recipe_summaries: List of dicts with name, cuisine, protein
        day: Target day
        meal: Target meal

    Returns:
        Suggestion dict or None
    """
    if anthropic_client is None:
        return None

    from prompts.meal_suggestion import SUGGEST_EMPTY_WEEK_PROMPT

    summaries_text = "\n".join(
        f"- {r['name']} ({r.get('cuisine', 'unknown')} / {r.get('protein', 'unknown')})"
        for r in recipe_summaries[:50]
    )

    prompt = SUGGEST_EMPTY_WEEK_PROMPT.format(
        profile=_profile_block(),
        recipe_summaries=summaries_text,
        day=day,
        meal=meal,
    )

    try:
        message = anthropic_client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=CLAUDE_MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = message.content[0].text
        json_start = raw.find("{")
        json_end = raw.rfind("}") + 1
        if json_start == -1 or json_end == 0:
            return None

        result = json.loads(raw[json_start:json_end])
        return {
            "name": result.get("name", ""),
            "reason": result.get("reason", ""),
            "is_new_idea": result.get("is_new_idea", False),
            "new_ingredients_needed": result.get("new_ingredients_needed", []),
        }

    except Exception:
        return None


def _waste_reason(top: dict) -> str:
    """Reason string leading with the at-risk items a recipe uses up."""
    used = ", ".join(top["waste_uses"])
    reason = f"Uses up expiring {used}"
    extra = [s for s in top.get("shared_ingredients", []) if s not in top["waste_uses"]]
    if extra:
        reason += f"; also shares {', '.join(extra[:2])} with the week"
    return reason


def _macro_reason(top: dict, macro_gap: dict) -> str:
    """Reason string explaining how this recipe closes the day's macro gap."""
    nutrition = top.get("nutrition") or {}
    gap_p = (macro_gap or {}).get("protein") or 0
    if gap_p > 0:
        return (f"Adds {nutrition.get('protein', 0)}g protein toward your "
                f"remaining {gap_p}g today")
    gap_c = (macro_gap or {}).get("calories") or 0
    return (f"Adds {nutrition.get('calories', 0)} kcal toward your "
            f"remaining {gap_c} kcal today")


def _attach_macros(result: dict, source: dict | None) -> dict:
    """Copy the macro display fields from a ranked candidate onto ``result``.

    Keeps the returned suggestion carrying ``nutrition``/``macro_fit``/
    ``nutrition_unknown`` regardless of which tier produced it. Defaults are
    conservative (no nutrition, unknown) when the source isn't a ranked dict.
    """
    result.setdefault("nutrition", (source or {}).get("nutrition"))
    result.setdefault("macro_fit", (source or {}).get("macro_fit", 0.0))
    result.setdefault("nutrition_unknown",
                      (source or {}).get("nutrition_unknown", True))
    return result


def day_macro_gap(
    planned_meals: list[dict],
    day: str,
    targets,
    recipes_dir: Path,
) -> Optional[dict]:
    """The target day's remaining macro gap, or None when there are no targets.

    Sums the per-serving macros of every recipe already placed on ``day`` (scaled
    by each entry's ``servings`` multiplier) and subtracts from the daily target.
    Reads per-recipe macros from frontmatter via ``serving_ledger.recipe_macros``.
    Computed from the markdown plan on purpose: the suggester only runs on
    non-ledger weeks, where ``serving_ledger.day_totals`` is empty.

    Args:
        planned_meals: dicts with ``day``, ``name`` and optional ``servings``.
        day: the target day name to sum.
        targets: a ``NutritionData`` (daily target) or None.
        recipes_dir: Recipes folder, for per-recipe macro lookups.

    Returns:
        ``{"target": {...}, "current": {...}, "remaining": {...}}`` with
        ``protein/calories/carbs/fat`` keys (``remaining`` clamped at 0), or None.
    """
    if targets is None:
        return None

    from lib.serving_ledger import recipe_macros

    keys = ("protein", "calories", "carbs", "fat")
    current = {k: 0.0 for k in keys}
    for m in planned_meals:
        if m.get("day") != day:
            continue
        macros = recipe_macros(m["name"], recipes_dir)
        if not macros:
            continue
        mult = float(m.get("servings", 1) or 1)
        for k in keys:
            current[k] += macros[k] * mult

    target = {
        "protein": targets.protein,
        "calories": targets.calories,
        "carbs": targets.carbs,
        "fat": targets.fat,
    }
    remaining = {k: max(0, target[k] - current[k]) for k in keys}
    return {"target": target, "current": current, "remaining": remaining}


def suggest_meal(
    recipes_dir: Path,
    planned_meals: list[dict],
    day: str,
    meal: str,
    skip_index: int = 0,
    at_risk: list[tuple[str, frozenset]] | None = None,
    macro_gap: dict | None = None,
) -> Optional[dict]:
    """Top-level orchestrator: suggest a meal for an empty slot.

    Pipeline:
    1. If no meals planned -> ask Claude for a starting recipe (or return None)
    2. Collect planned ingredient names
    3. Load recipe library with ingredients
    4. Score and rank candidates, boosting recipes that use at-risk inventory
       and (when ``macro_gap`` is given) that help close the day's macro gap
    5. If the top candidate uses expiring food -> return it directly (waste wins)
    6. Else if it's a strong macro fit -> return it directly (macro tier)
    7. Else if top candidate score >= threshold -> return it directly
    8. Else -> ask Claude to pick from candidates
    9. skip_index allows cycling through candidates (for "try another")

    Args:
        recipes_dir: Path to Obsidian Recipes folder
        planned_meals: List of dicts with day, meal, name, ingredients
        day: Target day name
        meal: Target meal type
        skip_index: Skip this many top candidates (for retry)
        at_risk: Optional at-risk ``(name, token_set)`` pairs; loaded from live
            inventory when omitted so suggestions help use food before it spoils.
        macro_gap: Optional ``{"protein": g, "calories": kcal}`` remaining-gap
            dict for the target day (from :func:`day_macro_gap`). When omitted the
            macro tier is skipped and behaviour is identical to the pre-macro
            suggester.

    Returns:
        Dict with name, score, reason, shared_ingredients, is_new_idea,
        nutrition, macro_fit, nutrition_unknown; or None
    """
    from lib.recipe_index import get_recipe_index

    pantry = load_pantry_staples()
    if at_risk is None:
        at_risk = load_at_risk_index()

    # Load all recipes with ingredients
    all_recipes = get_recipe_index(recipes_dir, include_ingredients=True)

    # Names already in the plan
    planned_names = {m["name"] for m in planned_meals}

    # Empty week -- if something's expiring, lead with a recipe that uses it up;
    # otherwise ask Claude for a starting idea (or return None).
    if not planned_meals:
        waste_ranked = rank_candidates(
            all_recipes, set(), pantry,
            limit=20, exclude_names=planned_names, at_risk=at_risk,
            macro_gap=macro_gap,
        )
        waste_top = waste_ranked[skip_index] if skip_index < len(waste_ranked) else None
        if waste_top and waste_top["waste_uses"]:
            waste_top["reason"] = _waste_reason(waste_top)
            waste_top["is_new_idea"] = False
            waste_top["new_ingredients_needed"] = []
            return waste_top

        # Macro tier -- nothing planned yet, so the whole day's target is open;
        # if the best-ranked recipe is a strong, trustworthy macro fit, lead with
        # it rather than asking Claude for a generic starter.
        if (macro_gap and waste_top and not waste_top["nutrition_unknown"]
                and waste_top["macro_fit"] >= MACRO_FIT_THRESHOLD):
            waste_top["reason"] = _macro_reason(waste_top, macro_gap)
            waste_top["is_new_idea"] = False
            waste_top["new_ingredients_needed"] = []
            return waste_top

        summaries = [
            {"name": r["name"], "cuisine": r.get("cuisine"), "protein": r.get("protein")}
            for r in all_recipes
        ]
        claude_result = suggest_for_empty_week(summaries, day, meal)
        if claude_result:
            claude_result["score"] = 0.0
            claude_result["shared_ingredients"] = []
            match = next((r for r in waste_ranked
                          if r["name"] == claude_result["name"]), None)
            _attach_macros(claude_result, match)
        return claude_result

    # Collect all planned ingredient names (normalized)
    planned_items = set()
    for m in planned_meals:
        for item in m.get("ingredients", []):
            planned_items.add(normalize_ingredient(item))

    # Score and rank (waste-using recipes are boosted to the top; when a macro
    # gap is supplied, strong macro fits rank above plain overlap)
    ranked = rank_candidates(
        all_recipes, planned_items, pantry,
        limit=20, exclude_names=planned_names, at_risk=at_risk,
        macro_gap=macro_gap,
    )

    if not ranked:
        return None

    # Apply skip_index for "try another"
    if skip_index >= len(ranked):
        return None

    top = ranked[skip_index]

    # Waste tier -- the top pick uses food about to spoil; surface it directly.
    if top["waste_uses"]:
        top["reason"] = _waste_reason(top)
        top["is_new_idea"] = False
        top["new_ingredients_needed"] = []
        return top

    # Macro tier -- the ranker already floated the best macro fit to the top, so
    # when it's a trustworthy, strong fit, surface it without asking Claude. Only
    # fires when a macro gap was supplied (guard keeps no-target behaviour intact).
    if (macro_gap and not top["nutrition_unknown"]
            and top["macro_fit"] >= MACRO_FIT_THRESHOLD):
        top["reason"] = _macro_reason(top, macro_gap)
        top["is_new_idea"] = False
        top["new_ingredients_needed"] = []
        return top

    # Tier decision
    if top["score"] >= OVERLAP_THRESHOLD:
        # High overlap -- use directly
        reason_items = ", ".join(top["shared_ingredients"][:3])
        planned_names_str = ", ".join(
            f"{m['day']}'s {m['name']}" for m in planned_meals
            if set(normalize_ingredient(i) for i in m.get("ingredients", []))
            & set(top["shared_ingredients"])
        )
        top["reason"] = f"Shares {reason_items} with {planned_names_str}" if planned_names_str else f"Shares {reason_items}"
        top["is_new_idea"] = False
        top["new_ingredients_needed"] = []
        return top

    # Low overlap -- try Claude
    claude_result = suggest_with_claude(
        planned_meals, ranked[skip_index:], day, meal, macro_gap=macro_gap)
    if claude_result:
        match = next((r for r in ranked if r["name"] == claude_result["name"]), None)
        if match:
            claude_result["score"] = match["score"]
            claude_result["shared_ingredients"] = match["shared_ingredients"]
        else:
            claude_result["score"] = 0.0
            claude_result["shared_ingredients"] = []
        _attach_macros(claude_result, match)
        return claude_result

    # Claude unavailable -- fall back to top scored candidate
    top["reason"] = f"Shares {', '.join(top['shared_ingredients'][:3])}" if top["shared_ingredients"] else "Best available match"
    top["is_new_idea"] = False
    top["new_ingredients_needed"] = []
    return top
