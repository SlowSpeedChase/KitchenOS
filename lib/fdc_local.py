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
    # size words are portion modifiers, not food identity ("medium apple" → apple)
    "small", "medium", "large",
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

CREATE TABLE IF NOT EXISTS portion_ledger (
    item_norm      TEXT NOT NULL,
    unit           TEXT NOT NULL,
    grams_per_unit REAL NOT NULL,
    confidence     REAL,
    source         TEXT,
    rationale      TEXT,
    created_at     TEXT,
    PRIMARY KEY (item_norm, unit)
);
"""

# Band-check inputs. Volume units → ml, for the implied-density check.
_UNIT_ML = {"cup": 236.588, "tbsp": 14.79, "tsp": 4.93, "fl oz": 29.57,
            "pint": 473.2, "quart": 946.4, "gallon": 3785.4}
# Loose per-unit kcal ceilings — catch gross errors, not fine ones.
_UNIT_KCAL_MAX = {"tsp": 90, "tbsp": 220, "cup": 1400, "fl oz": 120}
_MAX_PORTION_GRAMS = 2000


def ensure_schema(conn) -> None:
    """Create the local FDC tables if absent (idempotent)."""
    conn.executescript(SCHEMA)
    conn.commit()


def validate_portion_grams(item: str, unit: str, grams_per_unit: float,
                           per_100g: dict) -> tuple[bool, str]:
    """Sanity-band an estimated grams-per-unit before it enters the ledger.

    Catches gross LLM errors (a tbsp weighing 200 g, a tsp of oil at 500 kcal)
    without pretending to be precise. Returns (ok, reason)."""
    try:
        g = float(grams_per_unit)
    except (TypeError, ValueError):
        return False, "non-numeric grams"
    if g <= 0:
        return False, "grams must be > 0"
    if g > _MAX_PORTION_GRAMS:
        return False, f"gram weight {g:.0f} implausibly large"
    u = (unit or "").strip().lower()
    ml = _UNIT_ML.get(u)
    if ml:
        density = g / ml
        if density < 0.1 or density > 2.0:
            return False, f"implied density {density:.1f} g/ml out of band"
    kcal_100 = (per_100g or {}).get("calories", 0) or 0
    ceiling = _UNIT_KCAL_MAX.get(u)
    if ceiling and kcal_100 and (g * kcal_100 / 100.0) > ceiling:
        return False, f"{g * kcal_100 / 100.0:.0f} kcal per {u} exceeds {ceiling}"
    return True, "ok"


def ledger_put(conn, item_norm: str, unit: str, grams_per_unit: float,
               confidence: float, source: str, rationale: str = "") -> None:
    """Upsert a portion estimate. Caller supplies a normalized item key."""
    from datetime import datetime, timezone
    conn.execute(
        "INSERT OR REPLACE INTO portion_ledger "
        "(item_norm,unit,grams_per_unit,confidence,source,rationale,created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (item_norm, (unit or "").strip().lower(), float(grams_per_unit),
         confidence, source, rationale, datetime.now(timezone.utc).isoformat()))
    conn.commit()


def ledger_grams(conn, item_norm: str, unit: str):
    """Grams for one ``unit`` of ``item_norm`` from the ledger, or None."""
    try:
        row = conn.execute(
            "SELECT grams_per_unit FROM portion_ledger WHERE item_norm=? AND unit=?",
            (item_norm, (unit or "").strip().lower())).fetchone()
    except Exception:
        return None
    return row[0] if row else None


def has_data(conn) -> bool:
    try:
        return conn.execute("SELECT 1 FROM fdc_foods LIMIT 1").fetchone() is not None
    except Exception:
        return False


def _fts_escape(query_norm: str) -> str:
    # OR the tokens for recall; quote each to avoid FTS operator parsing.
    toks = [t for t in query_norm.split() if t]
    return " OR ".join(f'"{t}"' for t in toks)


def search_candidates(conn, item: str, limit: int = 40):
    """FTS recall over the local store. Returns (query_norm, [candidate dicts])."""
    qn = normalize_food_name(item)
    if not qn:
        return qn, []
    match = _fts_escape(qn)
    if not match:
        return qn, []
    rows = conn.execute(
        """SELECT f.fdc_id, f.description, f.name_norm, f.kcal_100g, f.kcal_source,
                  f.protein_100g, f.carb_100g, f.fat_100g, f.dataset_rank,
                  bm25(fdc_foods_fts) AS bm
           FROM fdc_foods_fts fts JOIN fdc_foods f ON f.fdc_id = fts.rowid
           WHERE fdc_foods_fts MATCH ? ORDER BY bm LIMIT ?""",
        (match, limit),
    ).fetchall()
    return qn, [dict(r) for r in rows]


_RANK_BONUS = {0: 1.0, 1: 0.7, 2: 0.5}


def score_candidate(query_norm: str, cand: dict) -> float:
    """Legible ranking that replaces USDA's opaque one. Higher = better.

    coverage rewards matching the query; length_penalty punishes padded records
    ("Strudel, apple"); head-noun match is the strong signal that the query IS the
    food (not a dish containing it); dataset_rank prefers Foundation/SR/FNDDS over
    branded; kcal 'none' is deprioritized (don't strand a 0-kcal pick)."""
    q = set(query_norm.split())
    cw = set((cand.get("name_norm") or "").split())
    if not q:
        return 0.0
    coverage = len(q & cw) / len(q)
    length_penalty = max(0, len(cw) - len(q)) * 0.2
    exact = 3.0 if cand.get("name_norm") == query_norm else 0.0
    # Head noun: first token of the raw description (before the comma) is the food's
    # head. If a query token is the head, this is the food itself, not a dish.
    head = (cand.get("description") or "").split(",")[0].strip().lower()
    head_tok = normalize_food_name(head)
    head_bonus = 1.5 if head_tok and set(head_tok.split()) & q else 0.0
    rank_bonus = _RANK_BONUS.get(cand.get("dataset_rank"), 0.0)
    none_penalty = 1.5 if cand.get("kcal_source") == "none" else 0.0
    bm_bonus = -(cand.get("bm") or 0) * 0.05  # bm25 is negative; better match → larger
    return (coverage * 2 + exact + head_bonus + rank_bonus
            - length_penalty - none_penalty + bm_bonus)


def resolve_local(conn, item: str):
    """Resolve an ingredient to a local FDC record dict, or None. Shape matches the
    live engine's record: source/source_id/description/per_100g/portions/density."""
    qn, cands = search_candidates(conn, item)
    if not cands:
        return None
    best = max(cands, key=lambda c: score_candidate(qn, c))
    ports = conn.execute(
        "SELECT portion_label, gram_weight FROM fdc_portions WHERE fdc_id = ?",
        (best["fdc_id"],),
    ).fetchall()
    return {
        "query_norm": qn,
        "source": "fdc",
        "source_id": str(best["fdc_id"]),
        "description": best["description"],
        "per_100g": {
            "calories": best["kcal_100g"] or 0,
            "protein": best["protein_100g"] or 0,
            "carbs": best["carb_100g"] or 0,
            "fat": best["fat_100g"] or 0,
        },
        "portions": [{"label": p["portion_label"], "gram_weight": p["gram_weight"]}
                     for p in ports],
        "density_g_per_ml": None,
    }
