"""Measurement → grams conversion — the single source of truth for units.

The nutrition engine is gram-based: every macro is ``grams * per_100g / 100``.
That only works if we can turn "0.25 cup olive oil" or "1 medium shallot" into
grams reliably. This module does exactly that and nothing else — it is pure and
deterministic given its inputs (density / piece weight / USDA portions are passed
in by the caller), so it has no network or LLM dependency and is trivially
table-testable.

Resolution order in :func:`to_grams`:

1. **mass** unit (g, kg, oz, lb, mg) → exact, ``confidence 1.0``
2. **volume** unit (tsp…gallon, ml, l) + density → ``confidence 0.9``
3. **count** unit (clove, slice, head, whole…) + curated piece weight → ``0.85``
4. **count** unit + a matching USDA ``foodPortion`` gram weight → ``0.8``
5. **informal** (to taste, a pinch…) → negligible 0 g, ``confidence 1.0``
6. otherwise ``method="unresolved"`` (``needs_review``) → caller invokes the LLM

The conversion tables here are canonical (gram-based); ``ingredient_aggregator``
imports them so shopping aggregation and nutrition share one source of truth.

Density and piece-weight data live in hand-correctable JSON
(``config/food_density.json``, ``config/piece_weights.json``) matched the same
way ``lib/normalizer`` maps controlled vocab: normalize → exact key → ``_aliases``
→ longest substring. An optional ``"_aliases"`` map in either file lets a saved
alias win, mirroring ``config/item_aliases.json``.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from lib.ingredient_parser import (
    normalize_unit,
    parse_amount,
    INFORMAL_UNITS as _PARSER_INFORMAL_UNITS,
)

# --- Canonical conversion tables (everything resolves to grams) ---------------

# Volume units → millilitres. Density (g/ml) converts ml → grams.
# Common abbreviations sit alongside canonical spellings so units from
# receipts/inventory ("1 gal" milk, "qt" buttermilk) convert too.
VOLUME_ML = {
    "tsp": 4.92892,
    "tbsp": 14.7868,
    "cup": 236.588,
    "ml": 1.0,
    "l": 1000.0,
    "fl_oz": 29.5735,
    "fl oz": 29.5735,
    "floz": 29.5735,
    "pint": 473.176,
    "pt": 473.176,
    "quart": 946.353,
    "qt": 946.353,
    "gallon": 3785.41,
    "gal": 3785.41,
}

# Mass units → grams.
MASS_G = {
    "g": 1.0,
    "kg": 1000.0,
    "mg": 0.001,
    "oz": 28.3495,
    "lb": 453.592,
    "lbs": 453.592,
}

# Count-like units: a quantity of discrete items needing a per-piece weight.
COUNT_UNITS = {
    "clove", "slice", "piece", "bunch", "head", "can", "package", "pkg",
    "sprig", "stalk", "stick", "ct", "count", "each", "ea", "whole",
    "knob", "fillet", "filet", "leaf", "ear", "rib", "wedge",
}

# Informal measures that contribute negligible macros (don't block a recipe).
# Unioned with the parser's list so the two never drift apart again (the drift
# had dropped "a sprinkle"/"a smidge" here, sending them to 'unresolved').
INFORMAL_UNITS = {
    "pinch", "dash", "splash", "smidge", "sprinkle",
    "to taste", "as needed", "some", "a few", "a couple", "a pinch",
    "a dash", "a splash", "a handful",
} | set(_PARSER_INFORMAL_UNITS)

CONFIDENCE = {
    "mass": 1.0,
    "volume_density": 0.9,
    "piece_weight": 0.85,
    "usda_portion": 0.8,
    "negligible": 1.0,
    "llm": 0.5,
    "unresolved": 0.0,
}

_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
_DENSITY_PATH = _CONFIG_DIR / "food_density.json"
_PIECE_PATH = _CONFIG_DIR / "piece_weights.json"


@dataclass
class GramResult:
    """Outcome of a units→grams conversion."""
    grams: float
    method: str        # mass | volume_density | piece_weight | usda_portion |
    #                    negligible | llm | unresolved
    confidence: float  # 0.0–1.0
    needs_review: bool
    note: str = ""


# --- Amount parsing (canonical numeric parse) ---------------------------------

def parse_amount_to_float(amount) -> Optional[float]:
    """Convert an amount (str/number) to a float.

    Handles fractions ("1/2"→0.5), mixed fractions ("1 1/2"→1.5), word numbers
    ("two"→2.0) and ranges ("3-4"→3.5, averaged). Returns None when nothing
    numeric can be extracted. This is the one numeric parse shared by nutrition
    and shopping aggregation.
    """
    if amount is None or amount == "":
        return None
    if isinstance(amount, (int, float)):
        return float(amount)

    s = str(amount).strip()
    if not s:
        return None

    # Range like "3-4" or "1.5-2" → midpoint.
    rng = re.match(r"^(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)$", s)
    if rng:
        return (float(rng.group(1)) + float(rng.group(2))) / 2

    # Normalize fractions / mixed fractions / word numbers via the parser.
    normalized = parse_amount(s)  # returns a string, possibly a range
    rng2 = re.match(r"^(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)$", normalized)
    if rng2:
        return (float(rng2.group(1)) + float(rng2.group(2))) / 2
    try:
        return float(normalized)
    except ValueError:
        return None


# --- Unit families ------------------------------------------------------------

def get_unit_family(unit: str) -> str:
    """Classify a unit as 'mass', 'volume', 'count', 'informal' or 'other'."""
    if not unit:
        return "count"  # bare amount ("3 eggs") behaves like a count
    u = normalize_unit(unit)
    low = u.lower()
    if low in MASS_G:
        return "mass"
    if low in VOLUME_ML:
        return "volume"
    if low in COUNT_UNITS:
        return "count"
    if low in INFORMAL_UNITS or unit.lower().strip() in INFORMAL_UNITS:
        return "informal"
    return "other"


# --- Config-backed density / piece-weight lookup ------------------------------

def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _normalize_item(item: str) -> str:
    return (item or "").lower().strip().rstrip(",.;:")


def _match_table(item: str, table: dict):
    """Resolve an item name against a config table.

    Order: exact key → ``_aliases`` indirection → longest substring match
    (either direction). Returns the matched value or None. The ``_aliases``
    entry, if present, maps alias → canonical key.
    """
    if not table:
        return None
    norm = _normalize_item(item)
    if not norm:
        return None

    aliases = table.get("_aliases", {}) if isinstance(table.get("_aliases"), dict) else {}
    keys = [k for k in table if k != "_aliases"]

    if norm in table and norm != "_aliases":
        return table[norm]
    if norm in aliases and aliases[norm] in table:
        return table[aliases[norm]]

    # Longest substring match in either direction ("baby spinach" → "spinach",
    # "extra virgin olive oil" → "olive oil"). Prefer the most specific key.
    best = None
    best_len = 0
    for k in keys:
        if (k in norm or norm in k) and len(k) > best_len:
            best, best_len = k, len(k)
    return table[best] if best is not None else None


def lookup_density(item: str) -> Optional[float]:
    """Return g/ml for an item from ``config/food_density.json``, or None."""
    val = _match_table(item, _load_json(_DENSITY_PATH))
    return float(val) if isinstance(val, (int, float)) else None


def lookup_piece_weight(item: str, size: Optional[str] = None) -> Optional[float]:
    """Return grams-per-piece for an item from ``config/piece_weights.json``.

    Values may be a flat number or a dict keyed by size ("medium", "large")
    with a "default". ``size`` (e.g. a modifier like "medium") selects a
    variant when present.
    """
    val = _match_table(item, _load_json(_PIECE_PATH))
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, dict):
        if size and size.lower() in val:
            return float(val[size.lower()])
        if "default" in val:
            return float(val["default"])
        # Single-entry dict: take it.
        nums = [v for v in val.values() if isinstance(v, (int, float))]
        if len(nums) == 1:
            return float(nums[0])
    return None


def _match_portion(unit: str, item: str, portions: list) -> Optional[float]:
    """Find a USDA foodPortion gram weight matching this count unit/item.

    Conservative: only matches when a portion's label/modifier contains the
    unit word or a size descriptor in the item. Returns grams-per-piece or None.
    """
    if not portions:
        return None
    u = normalize_unit(unit).lower()
    item_norm = _normalize_item(item)
    descriptors = [u] + [w for w in ("small", "medium", "large") if w in item_norm]
    for p in portions:
        label = str(p.get("label", "")).lower()
        gw = p.get("gram_weight")
        if not isinstance(gw, (int, float)) or gw <= 0:
            continue
        if any(d and d in label for d in descriptors):
            return float(gw)
    return None


# --- Core conversion ----------------------------------------------------------

def to_grams(
    amount,
    unit: str,
    item: str,
    *,
    density_g_per_ml: Optional[float] = None,
    piece_weight_g: Optional[float] = None,
    usda_portions: Optional[list] = None,
) -> GramResult:
    """Convert an ingredient amount to grams.

    Deterministic given its inputs. The caller supplies ``density_g_per_ml`` /
    ``piece_weight_g`` (typically from the config tables or a resolved food
    record) and any USDA ``usda_portions``. When nothing resolves the result is
    ``method="unresolved"`` with ``needs_review=True`` so the engine can fall
    back to an LLM portion estimate.
    """
    qty = parse_amount_to_float(amount)
    if qty is None:
        qty = 1.0

    family = get_unit_family(unit)
    norm_unit = normalize_unit(unit).lower() if unit else ""

    if family == "mass":
        grams = qty * MASS_G[norm_unit]
        return GramResult(grams, "mass", CONFIDENCE["mass"], False)

    if family == "volume":
        density = density_g_per_ml if density_g_per_ml is not None else lookup_density(item)
        if density is not None and density > 0:
            grams = qty * VOLUME_ML[norm_unit] * density
            return GramResult(grams, "volume_density", CONFIDENCE["volume_density"], False)
        return GramResult(
            0.0, "unresolved", CONFIDENCE["unresolved"], True,
            note=f"no density for '{item}' ({unit})",
        )

    if family == "count":
        pw = piece_weight_g if piece_weight_g is not None else lookup_piece_weight(item)
        if pw is not None and pw > 0:
            return GramResult(qty * pw, "piece_weight", CONFIDENCE["piece_weight"], False)
        portion = _match_portion(unit, item, usda_portions or [])
        if portion is not None:
            return GramResult(qty * portion, "usda_portion", CONFIDENCE["usda_portion"], False)
        return GramResult(
            0.0, "unresolved", CONFIDENCE["unresolved"], True,
            note=f"no piece weight for '{item}' ({unit})",
        )

    if family == "informal":
        return GramResult(0.0, "negligible", CONFIDENCE["negligible"], False,
                          note="informal amount treated as negligible")

    # Unknown unit ("other"): can't convert deterministically.
    return GramResult(
        0.0, "unresolved", CONFIDENCE["unresolved"], True,
        note=f"unrecognized unit '{unit}' for '{item}'",
    )
