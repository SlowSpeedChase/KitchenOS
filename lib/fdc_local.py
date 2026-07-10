"""Local USDA FoodData Central store — schema, name normalization, and lookups.

Component B of the nutrition-batch-ledger plan: bulk FDC data is materialized into
local SQLite tables so food resolution needs no runtime API. This module owns:

- ``normalize_food_name`` — the ONE normalizer used at both bulk-load time (to build
  ``fdc_foods.name_norm``) and query time. Load/query must agree or nothing matches.
- ``unit_from_portion`` — map an FDC portion (measure unit + modifier) to a canonical
  unit where possible.
- the ``fdc_foods`` / ``fdc_portions`` / ``fdc_foods_fts`` / ``fdc_meta`` schema.

Loader: ``scripts/load_fdc_bulk.py``. All macros are pre-computed at load via the same
energy cascade as the live path (``food_db._energy_kcal``): 1008 → 2047 → 2048 →
Atwater(4·protein + 4·carb + 9·fat).
"""
from __future__ import annotations

import re

# Filler words that carry no matching signal in a food name. Deliberately small —
# only unambiguous noise. Structural words ("with", "without", "skin") are kept
# because they change meaning.
_STOPWORDS = {
    "raw", "fresh", "organic", "granulated", "prepared", "unprepared",
    "commercial", "commercially", "ns", "nfs", "variety", "types", "type",
    "all", "includes", "food",
}

# FDC measure-unit names (or modifier words) → the engine's canonical unit tokens.
_UNIT_MAP = {
    "cup": "cup", "cups": "cup",
    "tablespoon": "tbsp", "tablespoons": "tbsp", "tbsp": "tbsp",
    "teaspoon": "tsp", "teaspoons": "tsp", "tsp": "tsp",
    "quart": "quart", "pint": "pint", "gallon": "gallon",
    "fl oz": "fl oz", "fluid ounce": "fl oz",
    "slice": "slice", "slices": "slice",
    "piece": "piece", "pieces": "piece",
}


def _singularize(word: str) -> str:
    if len(word) <= 3:
        return word
    if word.endswith("ies"):
        return word[:-3] + "y"
    if word.endswith(("sses", "us", "is", "ss")):
        return word  # molasses, cactus, basis, glass — not plurals to strip
    if word.endswith("s"):
        return word[:-1]
    return word


def normalize_food_name(text: str) -> str:
    """Canonical, order-independent food key. Lowercase, drop punctuation/numbers/
    stopwords, singularize, sort tokens. Used at load AND query so they agree."""
    if not text:
        return ""
    tokens = re.findall(r"[a-z]+", text.lower())
    out = []
    for t in tokens:
        if t in _STOPWORDS:
            continue
        out.append(_singularize(t))
    return " ".join(sorted(out))


def unit_from_portion(measure_unit_name: str, modifier: str) -> str | None:
    """Canonical unit for an FDC portion. ``measure_unit_name`` is often the literal
    'undetermined'; then the real unit is buried in the modifier text ('1 cup')."""
    name = (measure_unit_name or "").strip().lower()
    if name and name != "undetermined" and name in _UNIT_MAP:
        return _UNIT_MAP[name]
    if name in ("undetermined", ""):
        for tok in re.findall(r"[a-z]+", (modifier or "").lower()):
            if tok in _UNIT_MAP:
                return _UNIT_MAP[tok]
    return None


# --- Schema -------------------------------------------------------------------

# data_type → priority rank (lower wins) for candidate ranking.
DATASET_RANK = {
    "foundation_food": 0,
    "sr_legacy_food": 1,
    "survey_fndds_food": 2,
    "branded_food": 3,
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS fdc_foods (
    fdc_id        INTEGER PRIMARY KEY,
    data_type     TEXT    NOT NULL,
    description   TEXT    NOT NULL,
    name_norm     TEXT    NOT NULL,
    kcal_100g     REAL,
    kcal_source   TEXT    NOT NULL,
    protein_100g  REAL,
    carb_100g     REAL,
    fat_100g      REAL,
    brand_owner   TEXT,
    dataset_rank  INTEGER NOT NULL,
    loaded_at     TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fdc_foods_namenorm ON fdc_foods(name_norm);
CREATE INDEX IF NOT EXISTS idx_fdc_foods_rank ON fdc_foods(dataset_rank, kcal_source);

CREATE TABLE IF NOT EXISTS fdc_portions (
    fdc_id        INTEGER NOT NULL,
    portion_label TEXT    NOT NULL,
    unit_norm     TEXT,
    gram_weight   REAL    NOT NULL,
    amount        REAL    NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_fdc_portions_fdc ON fdc_portions(fdc_id);

CREATE TABLE IF NOT EXISTS fdc_meta (
    dataset      TEXT PRIMARY KEY,
    release_date TEXT,
    loaded_at    TEXT,
    row_count    INTEGER
);

CREATE VIRTUAL TABLE IF NOT EXISTS fdc_foods_fts USING fts5(
    description, name_norm,
    content='fdc_foods', content_rowid='fdc_id',
    tokenize='porter unicode61 remove_diacritics 2'
);
"""


def ensure_schema(conn) -> None:
    """Create the local FDC tables if absent (idempotent)."""
    conn.executescript(SCHEMA)
    conn.commit()
