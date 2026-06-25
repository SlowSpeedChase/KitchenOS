"""Optional ML ingredient parser (opt-in fast-path).

Wraps ``ingredient-parser-nlp`` to parse a freeform ingredient line into
``{amount, unit, item, preparation, confidence}``. This is used only when
``KITCHENOS_ML_INGREDIENTS`` is enabled (see
``ingredient_parser.parse_ingredient_best``); the rule-based parser in
``ingredient_parser.py`` stays the default and the fallback for low-confidence
or edge-case lines — the two approaches are complementary (probabilistic vs.
defensive rules).

The ML dependency is intentionally NOT in the core requirements; install it via
``requirements-ml.txt``. Importing it triggers a one-time NLTK model download,
so this module imports the parser lazily inside ``parse_ingredient_ml``.
"""
from __future__ import annotations

from fractions import Fraction
from typing import Optional

# ML results below this confidence fall back to the rule-based parser.
CONFIDENCE_THRESHOLD = 0.8


def is_available() -> bool:
    """True if the optional ML parser package is importable."""
    try:
        import ingredient_parser  # noqa: F401
        return True
    except Exception:
        return False


def _fmt_quantity(q) -> str:
    """Format a quantity (Fraction/number) as the pipeline's amount string."""
    if q in (None, ""):
        return "1"
    try:
        f = Fraction(q)
        if f.denominator == 1:
            return str(f.numerator)
        return f"{float(f):.2f}".rstrip("0").rstrip(".")
    except (ValueError, TypeError, ZeroDivisionError):
        return str(q)


def parse_ingredient_ml(text: str) -> Optional[dict]:
    """Parse one ingredient line with the ML model.

    Returns ``{amount, unit, item, preparation, confidence}`` or ``None`` if the
    package is missing, the parse errors, or no item name is found.
    ``confidence`` is the min of the name and amount confidences.
    """
    try:
        from ingredient_parser import parse_ingredient as _ml_parse
        parsed = _ml_parse(text)
    except Exception:
        return None

    if not parsed.name:
        return None
    name = parsed.name[0].text
    name_conf = parsed.name[0].confidence

    amount_str, unit_str, amt_conf = "1", "whole", 1.0
    if parsed.amount:
        amt = parsed.amount[0]
        amount_str = _fmt_quantity(amt.quantity)
        unit_str = str(amt.unit) if amt.unit else "whole"
        amt_conf = amt.confidence

    if not name:
        return None

    return {
        "amount": amount_str,
        "unit": unit_str or "whole",
        "item": name,
        "preparation": parsed.preparation.text if parsed.preparation else None,
        "confidence": round(min(name_conf, amt_conf), 4),
    }
