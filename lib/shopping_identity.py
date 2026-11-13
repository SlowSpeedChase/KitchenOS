"""Identity of an ingredient for shopping credit.

`ingredient_normalizer.normalize_name` keeps every adjective, so "freshly
ground black pepper" never equals the "black pepper" row and "salt" never
equals "Kosher salt". The shopping list then sends every owned staple to
"verify". This layer drops only descriptors that do not change which product
you buy. Anything that does change it (dried, smoked, garlic salt, pink curing
salt, pure vs imitation vanilla) stays. Keep this list closed and pinned by
tests/test_shopping_identity.py: a descriptor wrongly treated as noise
becomes a false credit, and a false credit means a missing ingredient at the
stove.

Every prefix is allowlist-gated, not just the ambiguous ones. "pure" separates
vanilla extract from imitation vanilla, and "freshly grated" or "freshly
ground" applies to ginger root or coffee beans, which are different products
to buy. A prefix is removed only when the remainder is a food whose prefixed
and bare forms share one shopping identity (see `_DESCRIPTOR_SAFE`).
"""
from __future__ import annotations

import re

from lib.ingredient_normalizer import normalize_name

_PREFIX = re.compile(
    r"^(?:(?:freshly|fresh)\s+(?:ground|grated|squeezed|cracked)|fresh|ground|pure)\s+"
)
_SUCH_AS = re.compile(r"\s+such as\b.*$")
# Foods whose descriptor-prefixed and bare forms are the same thing to buy.
_DESCRIPTOR_SAFE = {
    "parsley", "thyme", "basil", "cilantro", "dill", "rosemary", "sage",
    "mint", "chives", "tarragon", "cinnamon", "allspice", "cumin", "nutmeg",
    "black pepper", "white pepper", "cardamom", "turmeric",
    "lemon juice", "lime juice", "orange juice", "maple syrup", "honey",
    "parmesan", "parmesan cheese",
}
# Words that may precede "salt" and still mean plain salt.
_PLAIN_SALT_WORDS = {"kosher", "sea", "table", "fine", "flaky", "coarse",
                     "celtic", "diamond", "crystal", "morton", "himalayan",
                     "iodized", "flake"}


def shopping_identity(name: str | None) -> str:
    s = normalize_name(name or "")
    if not s:
        return ""
    s = re.sub(r"\s+", " ", s.replace("-", " ")).strip()
    s = _SUCH_AS.sub("", s)
    while True:
        candidate = _PREFIX.sub("", s, count=1)
        if candidate == s or candidate not in _DESCRIPTOR_SAFE:
            break
        s = candidate
    words = s.split()
    if words and words[-1] == "salt" and set(words[:-1]) <= _PLAIN_SALT_WORDS:
        return "salt"
    return " ".join(words)
