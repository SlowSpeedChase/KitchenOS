"""Phase B: make an ingredient line read the way a cook would write it.

``lib/ingredient_cleaner`` (Phase A) gets the *numbers* right — decimals,
embedded amounts, dropped non-food rows. It deliberately left item-text
presentation for later, and later never came, so 153 lines across the corpus
still read as things no cook could act on:

    | 2  | whole | % milk                      |   -> should be "2% milk"
    | 1  | lemon | lemon                        |   -> the ingredient is in the unit column
    | 1  | whole | whole dark chocolate         |   -> renders "1 whole whole dark chocolate"
    | 1  | whole | salt salt                    |
    | 8  | oz    | cream cheese, softened ($1.89) |  -> a price from the source page

Every repair here is deterministic and reversible by eye. Anything needing
judgement is left alone and flagged, on the same principle as
``lib/gram_equivalent``: a silent wrong answer is worse than an obvious gap.
"""

from __future__ import annotations

import re

# Vague but genuine units. Without this list they look like unrecognized units
# and the repair below would mistake them for a misplaced ingredient name,
# turning "1 handful | fresh cilantro" into "1 whole | handful fresh cilantro".
INFORMAL_UNITS = {
    "handful", "handfuls", "pinch", "pinches", "splash", "splashes", "dash",
    "dashes", "bunch", "bunches", "sprig", "sprigs", "stick", "sticks",
    "packet", "packets", "strip", "strips", "quarter", "quarters", "head",
    "heads", "stalk", "stalks", "clove", "cloves", "slice", "slices", "can",
    "cans", "jar", "jars", "block", "blocks", "bundle", "bundles", "sheet",
    "sheets", "ear", "ears", "piece", "pieces", "wedge", "wedges", "knob",
    "drizzle", "squeeze", "squirt", "sqirt", "loaf", "bag", "box", "tub",
    "container", "bottle", "pint", "quart", "scoop", "scoops",
}

# Words after which a leading "whole" is part of the product name, not a unit
# echo. Dropping it would silently change the ingredient: whole milk is not
# milk, whole wheat flour is not flour.
PROTECTED_AFTER_WHOLE = {
    "milk", "wheat", "grain", "grains", "kernel", "kernels", "bean", "beans",
    "berry", "berries",
}

_PRICE_NUM = r"\$\s?\d+(?:\.\d+)?"
# Ordered narrowest-first. A single pattern with an optional trailing "\)?" ate
# the closing paren of "(130g, $0.82)" and left "(130g" — the price must only
# take a paren it also opened.
_PRICE_PATTERNS = (
    re.compile(rf"\s*\(\s*{_PRICE_NUM}\s*\)"),   # the aside is only a price
    re.compile(rf"\s*,\s*{_PRICE_NUM}"),         # a price clause beside real content
    re.compile(rf"\s*{_PRICE_NUM}"),             # a bare trailing price
)
_XREF = re.compile(r"\s*\([^)]*\b(?:see note|see notes|original recipe)\b[^)]*\)", re.I)
_SPONSOR = re.compile(r"\s*\([^)]*\bcode:[^)]*\)", re.I)
_PCT_START = re.compile(r"^\s*%\s*")


def strip_source_noise(item: str) -> tuple[str, list[str]]:
    """Remove artefacts of the page the recipe was scraped from.

    Prices, affiliate codes, and cross-references to notes that were never kept
    ("see note 5 for subs") are not properties of the food and cannot be acted
    on from the recipe as stored.
    """
    notes = []
    out = item
    for pattern, label in ((_SPONSOR, "sponsor code"), (_XREF, "dead cross-reference")):
        new = pattern.sub("", out)
        if new != out:
            notes.append(f"stripped {label}")
            out = new
    for pattern in _PRICE_PATTERNS:
        new = pattern.sub("", out)
        if new != out:
            if "stripped source price" not in notes:
                notes.append("stripped source price")
            out = new
    # Tidy what removal left behind: "(130g, )" -> "(130g)", and drop asides that
    # held nothing but the price. Parentheses are NOT stripped wholesale here —
    # doing so truncated "light brown sugar (165 g)" to "...(165 g", destroying
    # the most accurate weight the recipe has (see lib/gram_equivalent).
    out = re.sub(r",\s*\)", ")", out)
    out = re.sub(r"\(\s*,\s*", "(", out)
    out = re.sub(r"\(\s*\)", "", out)
    out = re.sub(r"\s{2,}", " ", out).strip(" ,;")
    return (out or item), notes


def rejoin_percentage(amount: str, item: str) -> tuple[str, str, list[str]]:
    """Put "2% milk" back together.

    The extractor reads the leading digits of "2% milk" as the amount and leaves
    a naked "% milk" behind, which then renders as "2 whole % milk". The digits
    are part of the name, so the line has no stated amount at all.
    """
    if not _PCT_START.match(item):
        return amount, item, []
    digits = (amount or "").strip()
    if not re.fullmatch(r"\d+(?:\.\d+)?", digits):
        return amount, item, []
    rest = _PCT_START.sub("", item).strip()
    if not rest:
        return amount, item, []
    if digits.endswith(".0"):
        digits = digits[:-2]
    return "1", f"{digits}% {rest}", ["rejoined percentage into the name"]


def collapse_repeats(item: str) -> tuple[str, list[str]]:
    """Collapse "salt salt" and "egg whites egg whites".

    Handles a repeated phrase as well as a repeated word, because the corpus
    contains both and a word-only rule leaves "egg whites egg whites" intact.
    """
    words = item.split()
    if not words:
        return item, []
    n = len(words)
    for size in range(n // 2, 0, -1):
        for start in range(0, n - 2 * size + 1):
            a = [w.lower() for w in words[start:start + size]]
            b = [w.lower() for w in words[start + size:start + 2 * size]]
            if a == b:
                out = words[:start + size] + words[start + 2 * size:]
                return " ".join(out), ["collapsed a repeated phrase"]
    return item, []


def drop_unit_echo(unit: str, item: str) -> tuple[str, list[str]]:
    """Drop a leading word in the item that merely repeats the unit.

    "1 | whole | whole lemons" renders as "1 whole whole lemons". Guarded by
    PROTECTED_AFTER_WHOLE so "whole milk" and "whole wheat flour" survive — the
    word is the product there, not an echo of the unit.
    """
    u = (unit or "").strip().lower()
    words = item.split()
    if not u or not words or words[0].lower() != u:
        return item, []
    rest = words[1:]
    if not rest:
        return item, []
    if u == "whole" and rest[0].lower() in PROTECTED_AFTER_WHOLE:
        return item, []
    return " ".join(rest), ["dropped a unit echo from the name"]


def unit_column_holds_the_ingredient(unit: str, item: str) -> tuple[str, str, list[str]]:
    """Recover a line whose ingredient landed in the Unit column.

    "1 | lemon | lemon" and "0.5 | onion | onion" are the extractor writing the
    food into both columns; "15 | corn | tortillas" split one name across them.
    Only fires on a unit that is neither canonical nor an informal measure, so
    "1 handful | fresh cilantro" is untouched.
    """
    u = (unit or "").strip()
    low = u.lower()
    if not u or low in INFORMAL_UNITS:
        return unit, item, []
    from lib.units import get_unit_family, normalize_unit
    if get_unit_family(normalize_unit(low)) != "other":
        return unit, item, []

    item_low = item.lower()
    if item_low == low or item_low.startswith(low + " "):
        # The food is duplicated across both columns — keep the item, fix the unit.
        return "whole", item, ["ingredient name was duplicated into the unit column"]

    # A name split across the two columns ("corn" + "tortillas") is NOT rejoined.
    # Telling "corn" from "blorp" needs a food vocabulary this module doesn't
    # have, and merging blindly turns an obviously-broken row into a plausible
    # ingredient called "blorp flour" — trading a visible defect for a silent
    # one. These rows are already flagged needs_review by the caller's A3 check,
    # so they reach a human either way. Revisit once ingredient_facts exists.
    return unit, item, []


def repair(amount: str, unit: str, item: str) -> tuple[str, str, str, list[str]]:
    """Apply every Phase B repair. Returns (amount, unit, item, notes)."""
    notes: list[str] = []

    amount, item, n = rejoin_percentage(amount, item)
    notes += n
    item, n = strip_source_noise(item)
    notes += n
    unit, item, n = unit_column_holds_the_ingredient(unit, item)
    notes += n
    item, n = drop_unit_echo(unit, item)
    notes += n
    item, n = collapse_repeats(item)
    notes += n

    return amount, unit, item, notes
