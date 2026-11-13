"""Identity of an ingredient for shopping credit.

`ingredient_normalizer.normalize_name` keeps every adjective, so "freshly
ground black pepper" never equals the "black pepper" row and "salt" never
equals "Kosher salt". The shopping list then sends every owned staple to
"verify". This layer drops only descriptors that do not change which product
you buy. Anything that does change it (dried, smoked, garlic salt, ground
*meat*) stays. Keep this list closed and pinned by
tests/test_shopping_identity.py: a descriptor wrongly treated as noise
becomes a false credit, and a false credit means a missing ingredient at the
stove.
"""
from __future__ import annotations

import re

from lib.ingredient_normalizer import normalize_name

_LEADING = re.compile(
    r"^(?:freshly\s+(?:ground|grated|squeezed|cracked)|fresh|pure)\s+"
)
_SUCH_AS = re.compile(r"\s+such as\b.*$")
# "ground" is a descriptor for spices but the cut itself for meat.
_MEATS = {"beef", "pork", "turkey", "chicken", "lamb", "veal", "bison",
          "meat", "sausage", "venison"}
# Words that may precede "salt" and still mean plain salt.
_PLAIN_SALT_WORDS = {"kosher", "sea", "table", "fine", "flaky", "coarse",
                     "celtic", "diamond", "crystal", "morton", "himalayan",
                     "pink", "iodized", "flake"}


def shopping_identity(name: str | None) -> str:
    s = normalize_name(name or "")
    if not s:
        return ""
    s = re.sub(r"\s+", " ", s.replace("-", " ")).strip()
    s = _SUCH_AS.sub("", s)
    while True:
        stripped = _LEADING.sub("", s)
        if stripped == s:
            break
        s = stripped
    words = s.split()
    if len(words) > 1 and words[0] == "ground" and words[-1] not in _MEATS:
        words = words[1:]
    if words and words[-1] == "salt" and set(words[:-1]) <= _PLAIN_SALT_WORDS:
        return "salt"
    return " ".join(words)
