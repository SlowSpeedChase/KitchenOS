"""Deterministic, gram-based recipe nutrition engine.

Replaces the old "search an API and trust whatever number comes back" cascade.
Every macro is computed as ``per_100g * grams / 100``:

    for each ingredient:
        food   = resolve to a USDA/OFF record (cache → search → LLM pick → OFF)
        grams  = units.to_grams(...)            (density / piece weight / portion / LLM)
        line   = food.per_100g * grams / 100    (kept as floats)
    total      = sum(lines)                      (no per-ingredient rounding)
    per_serving= round(total / servings)          (rounded once, at the end)

The LLM is confined to two narrow, validated jobs (food pick + portion grams) via
``lib/food_resolver``. Results are cached in ``inventory_db`` so an ingredient is
resolved once across all recipes. Every line carries an audit trail (grams,
source, per-100g, contribution) so any stored macro can be re-derived.

The public :func:`calculate_recipe_nutrition` returns a
:class:`RecipeNutritionResult` whose ``.nutrition`` / ``.source`` properties keep
the previous call sites (``extract_recipe``, ``backfill_nutrition``) working.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from lib import food_db, food_resolver, inventory_db, units
from lib.ingredient_text import apply_aliases, clean_for_matching
from lib.nutrition import NutritionData

# Below this line confidence, a recipe is flagged needs_review.
REVIEW_CONFIDENCE = 0.5

# Below this resolved-fraction, a recipe is flagged needs_review. Must match
# lib.serving_ledger.COVERAGE_REVIEW_THRESHOLD.
COVERAGE_REVIEW_THRESHOLD = 0.8
# Per-serving calorie range outside of which a recipe is almost certainly a
# parse/resolution error (e.g. a single-ingredient recipe resolving to an
# implausible energy density).
KCAL_SANITY_RANGE = (50, 2500)          # per serving
# One ingredient line contributing more than this fraction of total recipe
# grams is flagged for review (only when there is more than one resolved line).
DOMINANT_LINE_FRACTION = 0.5            # one line > 50% of recipe grams

# A single ingredient line over this many grams (~24 lb) is almost certainly a
# parse error (e.g. a stray oven temperature parsed as an ingredient). Treat it
# as unresolved rather than letting an absurd weight pollute the recipe.
MAX_INGREDIENT_GRAMS = 11000.0


@dataclass
class IngredientNutrition:
    """Per-ingredient audit line."""
    item: str
    amount: object
    unit: str
    grams: float
    grams_method: str
    food_source: str          # usda | off | "" (unresolved)
    food_id: str
    per_100g: dict
    contribution: dict        # {calories, protein, carbs, fat} as floats
    confidence: float
    needs_review: bool
    note: str = ""


@dataclass
class RecipeNutritionResult:
    """Recipe-level result with a backward-compatible adapter."""
    per_serving: NutritionData
    total: NutritionData
    source: str
    servings_used: int
    servings_inferred: bool
    needs_review: bool
    confidence: float
    line_items: list = field(default_factory=list)
    coverage: float = 1.0
    unmatched: list = field(default_factory=list)
    sanity_flags: list = field(default_factory=list)

    # --- backward-compat: old call sites use .nutrition and .source ---
    @property
    def nutrition(self) -> NutritionData:
        return self.per_serving


_EMPTY_CONTRIB = {"calories": 0.0, "protein": 0.0, "carbs": 0.0, "fat": 0.0}


def _words(text: str) -> set:
    return set(re.findall(r"[a-z]+", (text or "").lower()))


def _deterministic_pick(item_norm: str, candidates: list) -> Optional[int]:
    """Pick the candidate with the most word overlap with the item.

    Returns an index when there is a clear best match, else None (→ let the LLM
    decide). Keeps common, unambiguous ingredients fully offline.
    """
    item_words = _words(item_norm)
    if not item_words:
        return None
    scored = [(len(item_words & _words(c.description)), i) for i, c in enumerate(candidates)]
    scored.sort(reverse=True)
    best_score, best_idx = scored[0]
    if best_score == 0:
        return None
    # Unique winner that covers at least half the item's words → confident.
    runner_up = scored[1][0] if len(scored) > 1 else -1
    if best_score > runner_up and best_score >= max(1, len(item_words) // 2):
        return best_idx
    return None


def normalize_ingredient_key(item: str) -> str:
    """Canonical normalization for an ingredient name used as a cache/lookup key.

    Shared by ``_resolve_food`` and the nutrition-review API (pinning a human
    match / recompute) so both sides of a resolution cache entry line up on
    exactly the same key.
    """
    return units._normalize_item(apply_aliases(clean_for_matching(item)))


def _resolve_food(item: str, *, use_cache: bool, resolution_provider: str):
    """Resolve an ingredient to a FoodRecord-like object + (confidence, resolver).

    Returns (record_dict, confidence, resolver) or (None, 0.0, "unresolved").
    record_dict has keys: source, source_id, description, per_100g(dict),
    portions(list), density_g_per_ml.
    """
    norm = normalize_ingredient_key(item)
    if not norm:
        return None, 0.0, "unresolved"

    # 1. Resolution cache → cached food record.
    if use_cache:
        res = inventory_db.get_food_resolution(norm)
        if res and res.get("resolver") == "human-negligible":
            record = {"query_norm": norm, "source": "none", "source_id": "0",
                      "description": "negligible (human)", "per_100g":
                      {"calories": 0, "protein": 0, "carbs": 0, "fat": 0},
                      "portions": [], "density_g_per_ml": None}
            return record, 1.0, "human-negligible"
        if res and res.get("resolver") != "llm-portion":
            cached = inventory_db.get_food_cache(norm, res["source"])
            if cached:
                return cached, res["confidence"], "cache"

    # 2. USDA candidates.
    candidates = food_db.usda_search(norm)
    chosen_idx = None
    confidence = 0.4
    resolver = "fallback"
    if candidates:
        idx = _deterministic_pick(norm, candidates)
        if idx is not None:
            chosen_idx, confidence, resolver = idx, 0.8, "match"
        elif resolution_provider != "none":
            picked = food_resolver.resolve_food(norm, candidates, resolution_provider)
            if picked is not None:
                chosen_idx, confidence, resolver = picked[0], picked[1], f"llm-{resolution_provider}"
        if chosen_idx is None:
            chosen_idx, confidence, resolver = 0, 0.4, "fallback"

        fdc_id = candidates[chosen_idx].source_id
        detail = food_db.usda_food_detail(fdc_id)
        rec_obj = detail or candidates[chosen_idx]
        record = {
            "query_norm": norm,
            "source": "usda",
            "source_id": rec_obj.source_id,
            "description": rec_obj.description,
            "per_100g": rec_obj.per_100g.to_dict(),
            "portions": rec_obj.portions,
            "density_g_per_ml": rec_obj.density_g_per_ml,
        }
    else:
        # 3. Open Food Facts fallback (branded/packaged).
        off = food_db.off_search(norm)
        if not off:
            return None, 0.0, "unresolved"
        rec_obj = off[0]
        confidence, resolver = 0.6, "off"
        record = {
            "query_norm": norm,
            "source": "off",
            "source_id": rec_obj.source_id,
            "description": rec_obj.description,
            "per_100g": rec_obj.per_100g.to_dict(),
            "portions": rec_obj.portions,
            "density_g_per_ml": rec_obj.density_g_per_ml,
        }

    if use_cache:
        inventory_db.put_food_cache(record)
        inventory_db.put_food_resolution(
            norm, record["source"], record["source_id"], confidence, resolver
        )
    return record, confidence, resolver


def _resolve_grams(amount, unit, item, record, *, use_cache: bool, portion_provider: str):
    """Convert to grams, falling back to a cached/LLM portion estimate."""
    density = (record or {}).get("density_g_per_ml")
    portions = (record or {}).get("portions") or []
    gr = units.to_grams(
        amount, unit, item,
        density_g_per_ml=density,
        piece_weight_g=None,
        usda_portions=portions,
    )
    if gr.method != "unresolved":
        return gr

    # Deterministic conversion failed. If a portion provider is configured, try a
    # cached (provider-keyed) estimate, then a live one. With provider "none" we
    # leave it unresolved rather than returning a stale estimate — keeping the
    # cache read gated avoids one provider's bad estimate polluting another run.
    if portion_provider == "none":
        return gr

    qty = units.parse_amount_to_float(amount) or 1.0
    norm_key = f"{units._normalize_item(item)}|{(unit or '').lower()}|{portion_provider}"
    if use_cache:
        cached = inventory_db.get_food_resolution(norm_key)
        if cached and cached.get("resolver") == "llm-portion":
            try:
                grams_per_unit = float(cached["source_id"])
                return units.GramResult(
                    qty * grams_per_unit, "llm", cached["confidence"], True,
                    note=f"cached {portion_provider} portion estimate",
                )
            except (ValueError, KeyError):
                pass

    labels = [p.get("label") for p in portions if p.get("label")]
    est = food_resolver.estimate_portion_grams(unit, item, labels or None, portion_provider)
    if est is not None:
        grams_per_unit, conf = est
        if use_cache:
            inventory_db.put_food_resolution(
                norm_key, "llm", str(grams_per_unit), conf, "llm-portion"
            )
        return units.GramResult(
            qty * grams_per_unit, "llm", units.CONFIDENCE["llm"], True,
            note=f"{portion_provider} portion estimate",
        )
    return gr  # still unresolved


def calculate_recipe_nutrition(
    ingredients: list[dict],
    servings,
    *,
    use_cache: bool = True,
    use_llm: bool = True,
    resolution_provider: Optional[str] = None,
    portion_provider: Optional[str] = None,
) -> Optional[RecipeNutritionResult]:
    """Compute per-serving nutrition for a recipe, gram-based and auditable.

    The two LLM jobs are selected independently via ``resolution_provider`` and
    ``portion_provider`` ("ollama" | "claude" | "none"). Both default from
    ``use_llm`` to "ollama"/"none" for backward compatibility. Validation showed
    Ollama food-resolution is reliable (~100%) but Ollama portion estimation is
    not (~52% error), so callers should prefer portion_provider="claude" or
    "none".

    Returns None when no ingredient could be resolved at all (matching the old
    contract so backfill skips). Otherwise returns a RecipeNutritionResult; a
    partially-resolved recipe is returned with ``needs_review=True``.
    """
    if resolution_provider is None:
        resolution_provider = "ollama" if use_llm else "none"
    if portion_provider is None:
        # Portion estimation defaults OFF. On real recipes the rows that need it
        # are usually unquantified in the source ("1 whole maple syrup" = a
        # drizzle), where an LLM estimates a full serving and overshoots
        # catastrophically (700–1700 kcal blowups). Curated piece-weight tables +
        # USDA portions cover legitimate count items; the rest stay unresolved and
        # flagged (a modest undercount beats a wild overcount). Opt in explicitly
        # with portion_provider="claude" for well-posed count items.
        portion_provider = "none"
    total = dict(_EMPTY_CONTRIB)
    line_items: list[IngredientNutrition] = []
    sources: set = set()
    confidences: list[float] = []
    any_resolved = False

    # Coverage/sanity bookkeeping. "to taste" (and similarly negligible informal
    # amounts) are excluded from the denominator — they legitimately carry no
    # meaningful macro contribution, so failing to resolve them shouldn't ding
    # coverage.
    countable = 0
    resolved_count = 0
    resolved_confs: list[float] = []
    unmatched: list[str] = []
    grams_list: list[float] = []

    for ing in ingredients:
        item = (ing.get("item") or "").strip()
        amount = ing.get("amount", "1")
        unit = ing.get("unit", "") or ""
        if not item:
            continue

        is_negligible = (unit or "").strip().lower() == "to taste"
        if not is_negligible:
            countable += 1

        record, food_conf, resolver = _resolve_food(
            item, use_cache=use_cache, resolution_provider=resolution_provider)

        if resolver == "human-negligible":
            # A human explicitly pinned this line as contributing nothing (e.g.
            # a joke/garnish ingredient with no meaningful macros). Treat it as
            # fully resolved with a zero contribution rather than routing it
            # through grams resolution, where a volume/count unit with no
            # density/piece-weight would fall into "unresolved" and keep
            # dragging coverage down even after a human confirmed it.
            confidences.append(1.0)
            line_items.append(IngredientNutrition(
                item=item, amount=amount, unit=unit,
                grams=0.0, grams_method="negligible",
                food_source=record["source"], food_id=str(record["source_id"]),
                per_100g=record["per_100g"], contribution=dict(_EMPTY_CONTRIB),
                confidence=1.0, needs_review=False, note="human-confirmed negligible",
            ))
            any_resolved = True
            if not is_negligible:
                resolved_count += 1
                resolved_confs.append(1.0)
            continue

        if record is None:
            line_items.append(IngredientNutrition(
                item, amount, unit, 0.0, "unresolved", "", "",
                {}, dict(_EMPTY_CONTRIB), 0.0, True, note="food not found",
            ))
            confidences.append(0.0)
            if not is_negligible:
                unmatched.append(item)
            continue

        gr = _resolve_grams(amount, unit, item, record, use_cache=use_cache,
                            portion_provider=portion_provider)
        per_100g = record["per_100g"]
        if gr.method == "unresolved" or gr.grams <= 0 or gr.grams > MAX_INGREDIENT_GRAMS:
            contribution = dict(_EMPTY_CONTRIB)
            line_review = True
            line_conf = 0.0
            if gr.grams > MAX_INGREDIENT_GRAMS:
                note = f"implausible weight {gr.grams:.0f}g — skipped"
            else:
                note = gr.note
            if not is_negligible:
                unmatched.append(item)
        else:
            factor = gr.grams / 100.0
            contribution = {k: float(per_100g.get(k, 0) or 0) * factor for k in _EMPTY_CONTRIB}
            for k in total:
                total[k] += contribution[k]
            line_review = gr.needs_review or food_conf < REVIEW_CONFIDENCE
            line_conf = min(food_conf, gr.confidence)
            note = gr.note
            any_resolved = True
            sources.add(record["source"])
            if not is_negligible:
                resolved_count += 1
                resolved_confs.append(line_conf)
                grams_list.append(gr.grams)

        confidences.append(line_conf)
        line_items.append(IngredientNutrition(
            item=item, amount=amount, unit=unit,
            grams=round(gr.grams, 1), grams_method=gr.method,
            food_source=record["source"], food_id=str(record["source_id"]),
            per_100g=per_100g, contribution=contribution,
            confidence=round(line_conf, 2), needs_review=line_review, note=note,
        ))

    if not any_resolved:
        return None

    # Servings: None/0 → default 1 but flag (stops the 1639-cal "serving" bug).
    servings_inferred = False
    try:
        servings_used = int(servings)
    except (TypeError, ValueError):
        servings_used = 0
    if servings_used < 1:
        servings_used = 1
        servings_inferred = True

    total_nd = NutritionData(
        calories=round(total["calories"]),
        protein=round(total["protein"]),
        carbs=round(total["carbs"]),
        fat=round(total["fat"]),
    )
    per_serving = NutritionData(
        calories=round(total["calories"] / servings_used),
        protein=round(total["protein"] / servings_used),
        carbs=round(total["carbs"] / servings_used),
        fat=round(total["fat"] / servings_used),
    )

    source = next(iter(sources)) if len(sources) == 1 else "mixed"
    coverage = round(resolved_count / countable, 2) if countable else 0.0
    confidence = round(sum(resolved_confs) / len(resolved_confs), 2) \
        if resolved_confs else 0.0

    sanity_flags: list[str] = []
    lo, hi = KCAL_SANITY_RANGE
    if not (lo <= per_serving.calories <= hi):
        sanity_flags.append("kcal_out_of_range")
    total_grams = sum(grams_list)
    if total_grams and max(grams_list) / total_grams > DOMINANT_LINE_FRACTION \
            and len(grams_list) > 1:
        sanity_flags.append("dominant_line")

    needs_review = (
        servings_inferred
        or coverage < COVERAGE_REVIEW_THRESHOLD
        or bool(sanity_flags)
        or confidence < REVIEW_CONFIDENCE
    )

    return RecipeNutritionResult(
        per_serving=per_serving,
        total=total_nd,
        source=source,
        servings_used=servings_used,
        servings_inferred=servings_inferred,
        needs_review=needs_review,
        confidence=confidence,
        line_items=line_items,
        coverage=coverage,
        unmatched=unmatched,
        sanity_flags=sanity_flags,
    )
