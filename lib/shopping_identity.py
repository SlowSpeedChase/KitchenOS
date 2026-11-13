"""Identity of an ingredient for shopping credit.

`ingredient_normalizer.normalize_name` keeps every adjective, so "freshly
ground black pepper" never equals the "black pepper" row and "salt" never
equals "Kosher salt". The shopping list then sends every owned staple to
"verify". This layer drops only descriptors that do not change which product
you buy. Anything that does change it (dried, smoked, garlic salt, pink curing
salt) stays. Keep this list closed and pinned by
tests/test_shopping_identity.py: a descriptor wrongly treated as noise
becomes a false credit, and a false credit means a missing ingredient at the
stove.

Both bare "fresh" and bare "ground" are allowlist-gated, not blanket strips.
A blanket strip merges products that are different to buy: "ground ginger"
with "fresh ginger" and "ginger", "ground mustard" with "mustard", "fresh
mozzarella" with "mozzarella". The prefix is removed only when the remainder
is a herb or spice whose fresh/ground forms share one shopping identity.
"""
from __future__ import annotations

import re

from lib.ingredient_normalizer import normalize_name

# Only the unambiguous prefixes are stripped unconditionally.
_LEADING = re.compile(
    r"^(?:freshly\s+(?:ground|grated|squeezed|cracked)|pure)\s+"
)
_SUCH_AS = re.compile(r"\s+such as\b.*$")
# Bare "fresh " / "ground " is removed only when what remains is one of these.
_HERBS_AND_SPICES = {
    "parsley", "thyme", "basil", "cilantro", "dill", "rosemary", "sage",
    "mint", "chives", "tarragon", "cinnamon", "allspice", "cumin", "nutmeg",
    "black pepper", "white pepper", "cardamom", "turmeric", "coriander seed",
}
_PREFIXED_HERB_OR_SPICE = re.compile(r"^(fresh|ground) (.+)$")
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
        stripped = _LEADING.sub("", s)
        if stripped == s:
            break
        s = stripped
    m = _PREFIXED_HERB_OR_SPICE.match(s)
    if m and m.group(2) in _HERBS_AND_SPICES:
        s = m.group(2)
    words = s.split()
    if words and words[-1] == "salt" and set(words[:-1]) <= _PLAIN_SALT_WORDS:
        return "salt"
    return " ".join(words)
