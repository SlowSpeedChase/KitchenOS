"""Recover the exact weight a recipe author already wrote down.

71 ingredient lines across the corpus carry a metric equivalent inside the
ingredient *name* — "light brown sugar (165 g)", "unsalted butter (28.5 g)",
"oyster sauce (30 g)" — where it sits as inert text. Everything downstream then
ignores it and estimates the weight from a volume and a density table, or asks
an LLM, when the recipe already said so exactly.

This is the only class of audit finding where fixing it ADDS precision rather
than removing noise, so it is deliberately conservative: a value is recovered
only when it is unambiguous, and anything doubtful is left alone for the normal
estimation path. A wrong weight here would silently corrupt nutrition, which is
worse than not recovering it at all.

The value is ABSOLUTE, not per-unit. "0.75 cup light brown sugar (165 g)" means
the line totals 165 g — not 0.75 x 165.
"""

from __future__ import annotations

import re

# To grams. Volume units are deliberately absent: without a density "(300 ml)"
# is not a weight, and guessing one is what this module exists to avoid.
_MASS_G = {
    "g": 1.0, "gram": 1.0, "grams": 1.0, "gr": 1.0,
    "kg": 1000.0, "kilogram": 1000.0, "kilograms": 1000.0,
    "oz": 28.3495, "ounce": 28.3495, "ounces": 28.3495,
    "lb": 453.592, "lbs": 453.592, "pound": 453.592, "pounds": 453.592,
}
_UNIT_ALT = "|".join(sorted(_MASS_G, key=len, reverse=True))

# One number then one mass unit, e.g. "165 g", "28.5 grams", "about 450 g".
_QTY = rf"(?:about\s+|approx\.?\s+|~\s*)?(\d+(?:\.\d+)?)\s*({_UNIT_ALT})\b"
_PAREN = re.compile(r"\(([^)]*)\)")
_SINGLE = re.compile(rf"^\s*{_QTY}\s*$", re.I)
# A range ("600-650g") or an arithmetic join ("1 1/2") means the author gave a
# span, not a figure; and a slash pair ("15-ounce/440g") mixes two systems.
_RANGE = re.compile(r"\d\s*(?:-|–|—|to)\s*\d")
_FRACTION = re.compile(r"\d\s*/\s*\d")

# Words that re-point the weight at something other than the ingredient itself:
# "(about 600-650g of corn kernels)" weighs the kernels, not the six ears.
_REFERENT_SHIFT = re.compile(r"\bof\b|\bper\b|\beach\b|\byield\b|\bcooked\b|\bdrained\b",
                             re.I)
# Source-page price noise, e.g. "$0.82" — discardable without losing meaning.
_PRICE_ONLY = re.compile(r"^\$\s?\d+(?:\.\d+)?$")


def extract(item: str) -> tuple[str, float | None]:
    """Return (item without the weight aside, grams) — grams None if unrecoverable.

    Only a parenthetical that is *entirely* one mass quantity is trusted. That
    rejects "(15-ounce/440g)" and "(about 600-650g of corn kernels)" along with
    anything carrying prep words, which is the intended trade: recovering 60 of
    71 correctly beats recovering 71 with a few silently wrong.
    """
    if not item:
        return item, None

    for m in _PAREN.finditer(item):
        inner = m.group(1).strip()
        if not inner or _RANGE.search(inner) or _FRACTION.search(inner):
            continue
        if _REFERENT_SHIFT.search(inner):
            continue
        hit = _SINGLE.match(inner)
        if not hit:
            # A price scraped from the source page often rides along in the same
            # aside — "(130g, $0.82)". The weight is still unambiguous once the
            # price clause is dropped, so split and retry rather than decline.
            parts = [p.strip() for p in inner.split(",") if p.strip()]
            masses = [p for p in parts if _SINGLE.match(p)]
            others = [p for p in parts if not _SINGLE.match(p)]
            if len(masses) == 1 and all(_PRICE_ONLY.match(o) for o in others):
                hit = _SINGLE.match(masses[0])
            else:
                continue
        qty, unit = float(hit.group(1)), hit.group(2).lower()
        grams = qty * _MASS_G[unit]
        if not 0 < grams <= 5000:
            continue
        cleaned = (item[:m.start()] + item[m.end():])
        cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ,;")
        return cleaned, round(grams, 2)

    return item, None
