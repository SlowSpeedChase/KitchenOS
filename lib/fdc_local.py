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

# Substances you cannot have "one whole" of — they are poured, spooned or scooped,
# and are sold in packages. `whole` is the unit the extractor emits when a recipe
# stated NO amount, so asking an LLM for "one whole olive oil" invites the answer
# "a bottle": the ledger held olive oil at 965 g, all-purpose flour at 1000 g and
# honey at 800 g, and one such line contributed 8,685 kcal to a single recipe.
#
# A deterministic check can't tell "a whole chicken" (legitimately 1400 g) from "a
# whole bottle of oil" by weight alone, so the discrimination is lexical and
# explicit here, in the same spirit as the controlled vocabularies in
# normalizer.py. Anything not on this list keeps the old, looser treatment.
_BULK_SUBSTANCES = (
    "oil", "water", "flour", "honey", "syrup", "mayo", "mayonnaise", "sauce",
    "milk", "cream", "juice", "vinegar", "broth", "stock", "yogurt", "sugar",
    "salt", "powder", "mustard", "ketchup", "butter", "granola", "rice",
)
# A recipe line that states no amount should not out-weigh a main protein.
_MAX_WHOLE_BULK_GRAMS = 300.0


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
    if u == "whole" and g > _MAX_WHOLE_BULK_GRAMS:
        low = (item or "").lower()
        hit = next((w for w in _BULK_SUBSTANCES
                    if re.search(rf"\b{re.escape(w)}\b", low)), None)
        if hit:
            return False, (f"{g:.0f} g for one 'whole' {hit} is a package, "
                           f"not a recipe amount")
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
    """FTS recall over the local store. Returns (query_norm, [candidate dicts]).

    Recall is the all-tokens OR query plus one query for the ingredient's head
    noun (``query_head``). The OR query alone ranks by bm25, which favours the
    *rarer* token: for "cherry tomatoes" all 40 slots went to cherry pies and
    juices, so no tomato was ever a candidate and the scorer could only choose
    between cherries. Only the head gets its own query — recalling every token
    separately pulls in junk for words like "plus" and "choice". Every
    candidate's ``bm`` is re-read from the OR query so scores stay comparable
    however the row was recalled.
    """
    qn = normalize_food_name(item)
    if not qn:
        return qn, []
    match = _fts_escape(qn)
    if not match:
        return qn, []
    head, _ = query_head(item)
    queries = [match] + ([f'"{head}"'] if head and len(qn.split()) > 1 else [])
    ids: list[int] = []
    # The head query goes deeper: bm25 on one common word ranks the shortest
    # records first, and "Corn, sweet, yellow, raw" sat behind 40 shorter corns.
    for q, lim in zip(queries, (limit, limit * 4)):
        for (rid,) in conn.execute(
                "SELECT rowid FROM fdc_foods_fts WHERE fdc_foods_fts MATCH ? "
                "ORDER BY bm25(fdc_foods_fts) LIMIT ?", (q, lim)):
            if rid not in ids:
                ids.append(rid)
    if not ids:
        return qn, []
    marks = ",".join("?" * len(ids))
    rows = conn.execute(
        f"""SELECT f.fdc_id, f.description, f.name_norm, f.kcal_100g, f.kcal_source,
                  f.protein_100g, f.carb_100g, f.fat_100g, f.dataset_rank,
                  bm25(fdc_foods_fts) AS bm
           FROM fdc_foods_fts fts JOIN fdc_foods f ON f.fdc_id = fts.rowid
           WHERE fdc_foods_fts MATCH ? AND fts.rowid IN ({marks}) ORDER BY bm""",
        (match, *ids),
    ).fetchall()
    return qn, [dict(r) for r in rows]


# Words that describe treatment, packaging or measure rather than which food it
# is. A candidate missing one of these is not a different food; a candidate
# missing any OTHER query word may be ("pinto" is not "garbanzo").
_TREATMENT_EXTRA = {
    "drained", "rinsed", "ounce", "oz", "can", "diced", "cubed", "crushed",
    "trimmed", "divided", "packed", "finely", "roughly", "thinly", "coarsely",
    "cut", "piece", "inch", "cup", "tablespoon", "teaspoon", "pound", "lb",
    "gram", "no", "added", "sodium", "reduced", "into", "about", "rough",
    "choice", "plus", "puree", "pureed", "paste",
}

# Legumes sold both dry and canned. A recipe that means the dry form says so
# ("dried chickpeas", "cannellini beans, dry"); the bare name is the can — the
# dry record is ~3x the calories per gram, so guessing dry silently triples a
# salad. Lentils are deliberately absent, and "split" counts as saying dry:
# recipes measure lentils and split peas dry far more often than not.
_CANNED_BY_DEFAULT = {"bean", "chickpea", "garbanzo", "pea"}
_DRY_QUERY = {"dry", "dried", "split"}  # split peas are sold dry
_DRY_RECORD = re.compile(r"\b(?<!from )(dry|dried)\b|0% moisture|mature seeds, raw")


# Words naming a part or a portion of a food, never the food: "garlic cloves" is
# garlic (not the spice), "leek tops" is leek, "thyme sprigs" is thyme.
_PART_WORDS = {
    "clove", "sprig", "leaf", "leave", "stem", "stalk", "head", "bunch", "top",
    "round", "wedge", "rib", "ear", "strip", "chunk", "cube", "floret",
    "handful", "pinch", "dash", "sheet", "jar", "package", "bag", "box",
    "half", "quarter", "segment", "spear", "fillet", "piece", "slice",
    "stick", "steak", "heart", "bar", "crumb", "puff", "flake",
}

# FDC files some foods under a class word: "Spices, onion powder", "Nuts,
# almonds". For those the class plus the next field is the head, or "onion
# powder" never finds its own record and "Baobab powder" wins on the head.
_CLASS_HEADS = {"spice", "nut", "seed", "beverage", "agent leavening",
                "sweetener", "soup", "cereal", "snack"}


def query_head(item: str) -> tuple[str, str]:
    """(head noun, the qualifier right before it) of an ingredient as written,
    or ("", "") when the line is too noisy to say.

    The head is the last food word of the first comma segment: "cherry
    tomatoes, raw" -> (tomato, cherry), "tomatoes, cherry" -> (tomato, "").
    English puts the head last; FDC puts it first and then a comma, so the first
    segment's last word is the head in both spellings. Of "chives or
    scallions" the last word still wins (either is a fair answer); a leading
    comma list ("green, brown, or french lentils") has no head at all. Only
    short segments (at
    most three food words) qualify: on "fine sea salt and freshly ground black
    pepper" there is no single head, and guessing one did real damage.
    """
    text = re.sub(r"\([^)]*\)?", " ", item or "")  # asides first: they hold commas
    segs = text.split(",")
    if len(segs) > 1 and len(segs[0].split()) <= 1 and \
            re.search(r"\b(or|and)\b", ",".join(segs[1:])):
        return "", ""  # "green, brown, or french green lentils": a list, no head
    # "tomatoes with green chiles", "cilantro leaves and tender stems"
    seg = re.split(r"\bwith\b|\band\b|&", segs[0])[0]
    skip = _treatment_words() | _PART_WORDS
    words = [_singularize(w) for w in re.findall(r"[a-z]+", seg.lower())
             if w not in _STOPWORDS]
    words = [w for w in words if w not in skip]
    if not words or len(words) > 3:
        return "", ""
    return words[-1], (words[-2] if len(words) > 1 else "")


def _treatment_words() -> set:
    from lib.resolution_guard import MODIFIERS  # lazy: resolution_guard imports us
    return MODIFIERS | _TREATMENT_EXTRA


_RANK_BONUS = {0: 1.0, 1: 0.7, 2: 0.5}


def score_candidate(query_norm: str, cand: dict, q_head=("", ""),
                    fresh: bool = False) -> float:
    """Legible ranking that replaces USDA's opaque one. Higher = better.

    coverage rewards matching the query; length_penalty punishes padded records
    ("Strudel, apple"); head-noun match is the strong signal that the query IS the
    food (not a dish containing it); dataset_rank prefers Foundation/SR/FNDDS over
    branded; kcal 'none' is deprioritized (don't strand a 0-kcal pick).
    ``q_head`` is the ingredient's own head noun (``query_head``); pass it so a
    qualifier word cannot become the matched food."""
    q = set(query_norm.split())
    cw = set((cand.get("name_norm") or "").split())
    if not q:
        return 0.0
    coverage = len(q & cw) / len(q)
    length_penalty = max(0, len(cw) - len(q)) * 0.2
    exact = 3.0 if cand.get("name_norm") == query_norm else 0.0
    # Head noun: first token of the raw description (before the comma) is the food's
    # head. If a query token is the head, this is the food itself, not a dish.
    head_tok = " ".join(sorted(_cand_head(cand)))
    # Filler and treatment words don't count: "Hearts of palm" is not the head
    # of "of fine sea salt" just because both contain "of".
    neutral = _treatment_words() | _PART_WORDS
    head_bonus = 1.5 if head_tok and (set(head_tok.split()) & q) - neutral else 0.0
    rank_bonus = _RANK_BONUS.get(cand.get("dataset_rank"), 0.0)
    none_penalty = 1.5 if cand.get("kcal_source") == "none" else 0.0
    bm_bonus = -(cand.get("bm") or 0) * 0.05  # bm25 is negative; better match → larger
    # A qualifier must not let a different food win. Two shapes of the same bug:
    # "cherry tomatoes" -> "Cherries, sweet, raw" (the modifier became the head
    # and the real head is missing), and "garbanzo beans" -> "Beans, pinto"
    # (the head matches but the word that says WHICH bean is missing).
    identity_penalty = 0.0
    h, qual = q_head if isinstance(q_head, tuple) else (q_head, "")
    if h:
        cand_head = set(head_tok.split()) if head_tok else set()
        # (1) the qualifier became the head: the candidate's head is a query
        # food word but not the query's head, and the real head is nowhere in
        # the candidate ("cherry tomatoes" -> "Cherries, sweet, raw").
        if h not in cw and (cand_head & q) - neutral:
            identity_penalty += 2.5
        # (2) right family, named variety, wrong one: the candidate's head IS the
        # query head and FDC's second field names a variety the query does not
        # ("garbanzo beans" -> "Beans, pinto, canned"). Keyed on that second
        # field rather than on any missing word: "flat-leaf parsley" must still
        # match "Parsley, fresh".
        fields = [f.strip() for f in (cand.get("description") or "").split(",")]
        variety = normalize_food_name(fields[1]).split() if len(fields) > 1 else []
        if (qual and h in cand_head and qual not in cw and len(variety) == 1
                and variety[0] not in q and variety[0] not in neutral):
            identity_penalty += 1.5
    dry_penalty = 0.0
    if q & _CANNED_BY_DEFAULT and not q & _DRY_QUERY and \
            _DRY_RECORD.search((cand.get("description") or "").lower()):
        dry_penalty = 3.0
    elif fresh and re.search(r"\b(dry|dried|dehydrated|grain)\b",
                             (cand.get("description") or "").lower()):
        dry_penalty = 2.0  # "ears fresh corn" is not "Corn, dried (Navajo)"
    elif fresh and re.search(r"\b(raw|fresh)\b", (cand.get("description") or "").lower()):
        dry_penalty = -0.5  # ...and a record that says raw beats "Corn bran, crude"
    return (coverage * 2 + exact + head_bonus + rank_bonus
            - length_penalty - none_penalty + bm_bonus
            - identity_penalty - dry_penalty)


def _cand_head(cand: dict) -> set:
    """Head tokens of an FDC description: its first comma field. Under a class
    word ("Spices, onion powder", "Seeds, pumpkin seeds") the second field is a
    name in English order, so ITS last word is the head — powder, seed — and
    "pumpkin" must not take "Seeds, pumpkin seeds" for the pumpkin itself."""
    fields = (cand.get("description") or "").split(",")
    head = normalize_food_name(fields[0])
    if head in _CLASS_HEADS and len(fields) > 1:
        words = [_singularize(w) for w in
                 re.findall(r"[a-z]+", re.sub(r"\([^)]*\)?", " ", fields[1]).lower())
                 if w not in _STOPWORDS]
        return {words[-1]} if words else set()
    return set(head.split())


def _available_head(q_head: tuple, cands: list) -> tuple:
    """Keep only the head rules the store can satisfy. Penalising every
    candidate for lacking a head no candidate has, or a variety the store does
    not carry, only reshuffles the wrong answers: "kosher salt" has no kosher
    salt record, so "Salt, table" must not lose to "Pickles, ... kosher dill"."""
    h, qual = q_head
    # The head must head some record: "unsweetened thick, creamy vegan yogurt"
    # yields "thick", which heads nothing, and acting on it sank every yogurt.
    if not h or not any(h in _cand_head(c) for c in cands):
        return "", ""
    if qual and not any(h in _cand_head(c) and qual in (c.get("name_norm") or "").split()
                        for c in cands):
        qual = ""
    return h, qual


def resolve_local(conn, item: str):
    """Resolve an ingredient to a local FDC record dict, or None. Shape matches the
    live engine's record: source/source_id/description/per_100g/portions/density."""
    qn, cands = search_candidates(conn, item)
    if not cands:
        return None
    q_head = _available_head(query_head(item), cands)
    # "fresh" is a stopword (it carries no identity) but it does rule out dried.
    fresh = bool(re.search(r"\bfresh\b", (item or "").lower()))
    best = max(cands, key=lambda c: score_candidate(qn, c, q_head, fresh))
    # Portions are pooled across every record with the same description:
    # Foundation and SR Legacy often both carry a food, Foundation outranks SR,
    # and Foundation's copy usually ships no household portions at all — so
    # "1 cup cucumber" failed for want of a cup the SR twin had all along.
    # gram_weight is per ``amount`` units ("0.5 cup = 129 g"); divide it out so
    # every consumer can read gram_weight as grams per ONE unit.
    ports = conn.execute(
        """SELECT p.portion_label, p.unit_norm, p.gram_weight, p.amount
           FROM fdc_portions p JOIN fdc_foods f ON f.fdc_id = p.fdc_id
           WHERE f.description = ?
           ORDER BY (p.fdc_id = ?) DESC, f.dataset_rank""",
        (best["description"], best["fdc_id"]),
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
        "portions": [{"label": p["portion_label"], "unit": p["unit_norm"],
                      "gram_weight": p["gram_weight"] / (p["amount"] or 1)}
                     for p in ports if (p["amount"] or 1) > 0],
        "density_g_per_ml": None,
    }
