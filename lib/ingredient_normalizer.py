"""Deterministic cleanup of recipe ingredient item names for shopping lists.

Strips descriptor noise (parentheticals, prep clauses, "(inferred)", "to taste",
etc.) and applies a hand-editable synonym map so that descriptor variants of the
same ingredient collapse to one canonical grouping key. No LLM.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from functools import lru_cache

_CONFIG = Path(__file__).resolve().parent.parent / "config" / "shopping_aliases.json"

# Units that mean "an unmeasured amount" — treated as no quantity, never summed.
_NOISE_UNITS = {
    "to tastes", "to taste", "tastes", "taste", "to",
    "pinch", "pinches", "dash", "dashes", "splash", "as needed", "some",
}

# Leading qualifiers to drop when they precede the real noun.
_LEADING = re.compile(
    r"^(?:\d+(?:\.\d+)?\s+)?(?:of\s+)?(?:a\s+|an\s+)?"
    r"(?:large|small|medium|medium-large|whole|of a large|of a small)?\s*",
    re.IGNORECASE,
)
_NOISE_TOKENS = re.compile(
    r"\*+|\(inferred\)|\(optional\)|\(not shown\)|optional:?", re.IGNORECASE
)


@lru_cache(maxsize=1)
def load_aliases() -> dict:
    if not _CONFIG.exists():
        return {}
    try:
        return {k.lower().strip(): v for k, v in json.loads(_CONFIG.read_text()).items()}
    except (json.JSONDecodeError, OSError):
        return {}


def is_noise_unit(unit: str) -> bool:
    return bool(unit) and unit.lower().strip() in _NOISE_UNITS


def normalize_name(raw: str) -> str:
    if not raw:
        return ""
    s = raw.strip()
    # Drop parentheticals and their contents.
    s = re.sub(r"\([^)]*\)", "", s)
    # Drop explicit noise tokens (*, (inferred), optional:, ...).
    s = _NOISE_TOKENS.sub("", s)
    # Keep only the part before the first comma (prep clause: ", thinly sliced").
    s = s.split(",")[0]
    # Drop "to taste" / "as needed" trailing phrases.
    s = re.sub(r"\b(to taste|as needed)\b", "", s, flags=re.IGNORECASE)
    # Strip a leading count/size qualifier ("1 of a large ...").
    s = _LEADING.sub("", s)
    s = re.sub(r"\s+", " ", s).strip().lower().strip(" .-")
    # Alias map wins over the stripped form.
    return load_aliases().get(s, s)
