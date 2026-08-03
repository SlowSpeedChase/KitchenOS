"""Pre-match ingredient text cleanup ("Phase B") + alias table.

USDA descriptions are terse ("Oil, olive, salad or cooking"); recipe lines
are chatty ("extra-virgin olive oil (plus more for serving)"). Stripping the
chat before word-overlap matching is the cheapest accuracy win available.
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import yaml

_ALIASES_PATH = Path(__file__).resolve().parent.parent / "config" / "food_aliases.yml"

# The unit `ingredient_parser` invents when it cannot read one. Only a row
# carrying exactly this is a candidate for range recovery — a row with a real
# unit parsed fine and must not be rewritten.
_FABRICATED_UNIT = "whole"

# "to 2 teaspoons ...", "to 1 1/2 cups ..." — the tail of a range whose low end
# was captured as the row's amount. The number may be a mixed fraction.
_RANGE_REMNANT = re.compile(
    r"^to\s+(\d+(?:\.\d+)?(?:\s+\d+\s*/\s*\d+)?|\d+\s*/\s*\d+)\s+([A-Za-z]+)\s+(.*)$",
    re.I | re.S,
)

# Prep/serving vocabulary for trailing-segment stripping (see _strip_prep_tail).
# Adverbs/participles that describe *how* an ingredient is prepped, not what
# it is, plus filler words from serving/timing asides ("plus more for
# serving", "at room temperature", "if using").
_PREP_WORDS = {
    "finely", "coarsely", "roughly", "thinly", "freshly", "chopped", "minced",
    "diced", "sliced", "grated", "shredded", "melted", "softened", "divided",
    "drained", "rinsed", "peeled", "seeded", "trimmed", "halved", "quartered",
    "crushed", "toasted", "cubed", "julienned", "packed", "sifted", "beaten",
    "whisked", "cooled", "chilled", "warmed", "cooked",
    "plus", "more", "for", "to", "serving", "serve", "garnish", "taste",
    "optional", "at", "room", "temperature", "as", "needed", "if", "using",
    "about", "approximately", "or", "and",
}


def _strip_prep_tail(text: str) -> str:
    """Strip trailing comma-separated segments that are pure prep/filler.

    Splits on commas and, scanning right to left, drops each trailing segment
    only when *every* word in it is in ``_PREP_WORDS``. Stops at the first
    segment containing a word outside that vocabulary, since that word is
    food identity, not prep — e.g. "salt, chopped nuts" is left untouched
    ("nuts" isn't prep) while "tomatoes, diced" strips to "tomatoes".
    """
    segments = text.split(",")
    while len(segments) > 1:
        words = re.findall(r"[a-z]+", segments[-1].lower())
        if words and all(w in _PREP_WORDS for w in words):
            segments.pop()
        else:
            break
    return ",".join(segments)


def _strip_accents(text: str) -> str:
    """Drop diacritics so accented food names match the ASCII USDA/OFF database
    ('jalapeños' → 'jalapenos', 'crème' → 'creme'). Accents never carry food
    identity for matching, and the DB descriptions are ASCII."""
    return "".join(
        c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
    )


def clean_for_matching(item: str) -> str:
    text = _strip_accents(item or "")
    text = re.sub(r"\*\(inferred\)\*", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\([^)]*\)", " ", text)          # parentheticals
    text = _strip_prep_tail(text)
    # collapse immediately doubled words ("garlic garlic cloves")
    text = re.sub(r"\b(\w+)( \1\b)+", r"\1", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip(" ,.*")


def _aliases() -> dict:
    """Load the food-alias table fresh on every call.

    No caching: edits to config/food_aliases.yml take effect immediately
    (matching lib.item_aliases's live-reload behavior). Resolution results
    are already cached in the DB and USDA calls dominate cost, so re-reading
    this small file per call is negligible.
    """
    if not _ALIASES_PATH.exists():
        return {}
    try:
        data = yaml.safe_load(_ALIASES_PATH.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k).lower(): str(v) for k, v in data.items()}


def apply_aliases(item: str) -> str:
    return _aliases().get((item or "").lower(), item)


def recover_range_remnant(amount, unit: str, item: str):
    """Rebuild a row whose amount range was split across the amount and the name.

    `ingredient_parser` reads "1 1/2 to 2 teaspoons dijon mustard" as amount
    `1.5`, unit `whole` (its default for an unreadable unit) and item
    "to 2 teaspoons dijon mustard" — so the real unit is stranded in the name and
    `to_grams` has nothing to convert. Returns `(amount, unit, item)` repaired, or
    the inputs unchanged when this is not that defect.

    Deliberately narrow. It fires only when the stored unit is exactly the
    fabricated `whole`, only when the stranded word is a unit this system knows,
    and only when both ends of the range parse — anything else is left for the
    normal estimation path, which is the same posture as `gram_equivalent`.

    The recovered amount is the **midpoint**, matching
    `units.parse_amount_to_float`, which already averages "3-4" to 3.5. This is
    the same range; it just happens to be split across two columns.
    """
    from lib import units

    if (unit or "").strip().lower() != _FABRICATED_UNIT:
        return amount, unit, item

    match = _RANGE_REMNANT.match((item or "").strip())
    if not match:
        return amount, unit, item

    high_text, candidate_unit, rest = match.groups()
    rest = rest.strip()
    if not rest:
        return amount, unit, item

    # A bare count range ("to 2 chipotle peppers") strands a *food* word, not a
    # unit. Recovering it would invent a unit the recipe never gave.
    if units.get_unit_family(candidate_unit) in ("count", "other"):
        return amount, unit, item

    low = units.parse_amount_to_float(amount)
    high = units.parse_amount_to_float(high_text)
    if low is None or high is None or high < low:
        return amount, unit, item

    midpoint = (low + high) / 2
    return (f"{midpoint:g}", candidate_unit, rest)
