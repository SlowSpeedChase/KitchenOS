"""Ingredient food-data clients, normalized to per-100g.

The nutrition engine scales ``per_100g * grams / 100``, so every source here is
normalized to **per-100-grams** values and never pre-scaled to a serving. Two
sources:

- **USDA FoodData Central** (primary, whole/generic foods). ``usda_search``
  returns a *candidate list* (not just the first hit) so the engine — or the LLM
  — can pick the right match. ``usda_food_detail`` adds ``foodPortions`` (household
  measure → gram weight) used for count-unit conversion. Needs ``USDA_FDC_API_KEY``
  (free; falls back to ``DEMO_KEY`` for low volume).
- **Open Food Facts** (fallback, branded/packaged items USDA lacks). No key.

All functions degrade gracefully to ``[]`` / ``None`` on any network or parse
error — nutrition is best-effort and must never crash extraction.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Optional

import requests

from lib.nutrition import NutritionData

USDA_SEARCH_URL = "https://api.nal.usda.gov/fdc/v1/foods/search"
USDA_DETAIL_URL = "https://api.nal.usda.gov/fdc/v1/food/{fdc_id}"
OFF_SEARCH_URL = "https://world.openfoodfacts.org/cgi/search.pl"

# USDA nutrient IDs (per 100 g for Foundation / SR Legacy data).
NUTRIENT_CALORIES = 1008  # Energy, kcal (SR Legacy / classic)
# Foundation Foods & Survey (FNDDS) report energy under Atwater IDs instead of
# 1008, so a food otherwise fully populated (protein/fat/carbs share their IDs
# across datasets) comes back with 0 kcal unless we read these fallbacks.
NUTRIENT_ENERGY_ATWATER_GENERAL = 2047
NUTRIENT_ENERGY_ATWATER_SPECIFIC = 2048
NUTRIENT_PROTEIN = 1003
NUTRIENT_FAT = 1004
NUTRIENT_CARBS = 1005

_TIMEOUT = 10
# USDA FDC rate-limits (~1k req/hr) return HTTP 429. A silent [] there makes a
# throttled-but-resolvable food look "not found" and corrupts backfills, so retry
# transient 429s with exponential backoff before giving up.
_MAX_RETRIES = 3
_BACKOFF_BASE = 0.5


def _get_json(url: str, params: dict) -> Optional[dict]:
    """GET returning parsed JSON, or None. Retries HTTP 429 with backoff.

    Non-429 errors (4xx/5xx), request exceptions, and unparseable bodies return
    None immediately (no retry) -- only rate-limits are transient enough to retry.
    """
    for attempt in range(_MAX_RETRIES + 1):
        try:
            resp = requests.get(url, params=params, timeout=_TIMEOUT)
        except requests.RequestException:
            return None
        if resp.status_code == 429 and attempt < _MAX_RETRIES:
            time.sleep(_BACKOFF_BASE * (2 ** attempt))
            continue
        if resp.status_code != 200:
            return None
        try:
            return resp.json()
        except ValueError:
            return None
    return None


@dataclass
class FoodRecord:
    """A food matched from a data source, normalized to per-100g."""
    source: str                 # "usda" | "off"
    source_id: str
    description: str
    per_100g: NutritionData     # values per 100 grams (kept as floats)
    portions: list = field(default_factory=list)   # [{"label","gram_weight"}, ...]
    density_g_per_ml: Optional[float] = None


def _usda_api_key() -> str:
    return os.getenv("USDA_FDC_API_KEY") or "DEMO_KEY"


def _nutrient_map_from_search(food: dict) -> dict:
    """Extract {nutrientId: value} from a /foods/search result item."""
    out = {}
    for n in food.get("foodNutrients", []):
        nid = n.get("nutrientId")
        if nid is not None:
            out[nid] = n.get("value", 0) or 0
    return out


def _nutrient_map_from_detail(food: dict) -> dict:
    """Extract {nutrientId: amount} from a /food/{id} detail result."""
    out = {}
    for n in food.get("foodNutrients", []):
        nutrient = n.get("nutrient") or {}
        nid = nutrient.get("id")
        if nid is not None:
            out[nid] = n.get("amount", 0) or 0
    return out


def _energy_kcal(nutrients: dict) -> float:
    """Energy per 100 g, reading 1008 first then the Atwater fallbacks.

    Prefer classic Energy (1008); fall back to Atwater General (2047) then
    Specific (2048) for Foundation/Survey foods that omit 1008.
    """
    for nid in (NUTRIENT_CALORIES, NUTRIENT_ENERGY_ATWATER_GENERAL,
                NUTRIENT_ENERGY_ATWATER_SPECIFIC):
        val = nutrients.get(nid, 0) or 0
        if val:
            return val
    return 0


def _per_100g(nutrients: dict) -> NutritionData:
    return NutritionData(
        calories=_energy_kcal(nutrients),
        protein=nutrients.get(NUTRIENT_PROTEIN, 0),
        carbs=nutrients.get(NUTRIENT_CARBS, 0),
        fat=nutrients.get(NUTRIENT_FAT, 0),
    )


def _portions_from_detail(food: dict) -> list:
    """Normalize USDA foodPortions to [{label, gram_weight}]."""
    portions = []
    for p in food.get("foodPortions", []):
        gw = p.get("gramWeight")
        if not isinstance(gw, (int, float)) or gw <= 0:
            continue
        label = p.get("portionDescription") or p.get("modifier") or ""
        measure = (p.get("measureUnit") or {}).get("name", "")
        if not label and measure and measure != "undetermined":
            amount = p.get("amount", 1)
            label = f"{amount} {measure}"
        portions.append({"label": label, "gram_weight": float(gw)})
    return portions


def usda_search(query: str, page_size: int = 5) -> list[FoodRecord]:
    """Search USDA FDC, returning up to ``page_size`` candidate FoodRecords."""
    if not query:
        return []
    params = {
        "query": query,
        "pageSize": page_size,
        "dataType": ["Foundation", "SR Legacy"],
        "api_key": _usda_api_key(),
    }
    data = _get_json(USDA_SEARCH_URL, params)
    if data is None:
        return []
    foods = data.get("foods", [])

    records = []
    for food in foods:
        records.append(FoodRecord(
            source="usda",
            source_id=str(food.get("fdcId", "")),
            description=food.get("description", ""),
            per_100g=_per_100g(_nutrient_map_from_search(food)),
        ))
    return records


def usda_food_detail(fdc_id: str) -> Optional[FoodRecord]:
    """Fetch full USDA detail (per-100g nutrients + foodPortions)."""
    if not fdc_id:
        return None
    food = _get_json(
        USDA_DETAIL_URL.format(fdc_id=fdc_id),
        {"api_key": _usda_api_key()},
    )
    if food is None:
        return None

    return FoodRecord(
        source="usda",
        source_id=str(food.get("fdcId", fdc_id)),
        description=food.get("description", ""),
        per_100g=_per_100g(_nutrient_map_from_detail(food)),
        portions=_portions_from_detail(food),
    )


def off_search(query: str, page_size: int = 5) -> list[FoodRecord]:
    """Search Open Food Facts (branded/packaged fallback). No API key."""
    if not query:
        return []
    params = {
        "search_terms": query,
        "search_simple": 1,
        "action": "process",
        "json": 1,
        "page_size": page_size,
        "fields": "code,product_name,nutriments",
    }
    try:
        resp = requests.get(OFF_SEARCH_URL, params=params, timeout=_TIMEOUT)
        if resp.status_code != 200:
            return []
        products = resp.json().get("products", [])
    except (requests.RequestException, ValueError):
        return []

    records = []
    for p in products:
        nutr = p.get("nutriments") or {}
        cal = nutr.get("energy-kcal_100g")
        if cal is None and nutr.get("energy_100g") is not None:
            # energy_100g is kJ; convert to kcal.
            cal = nutr["energy_100g"] / 4.184
        per_100g = NutritionData(
            calories=cal or 0,
            protein=nutr.get("proteins_100g", 0) or 0,
            carbs=nutr.get("carbohydrates_100g", 0) or 0,
            fat=nutr.get("fat_100g", 0) or 0,
        )
        if per_100g.calories == 0 and per_100g.protein == 0:
            continue  # no usable data
        records.append(FoodRecord(
            source="off",
            source_id=str(p.get("code", "")),
            description=p.get("product_name", ""),
            per_100g=per_100g,
        ))
    return records
