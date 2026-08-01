"""Refuse a food match that shares no word with the ingredient.

The LLM resolver latches onto a *modifier* instead of the food and then caches
the result at high confidence, so nothing ever re-examines it. Real entries
found in the cache:

    blueberries, fresh   -> Basil, fresh                    confidence 1.0
    chicken mince        -> Ham, minced                     confidence 0.95
    aleppo pepper        -> Frankfurter, beef, heated        confidence 0.9
    breadcrumbs          -> Abiyuch, raw                     confidence 0.95

"fresh", "minced" and "canned" are the hinges. This is worse than any unit bug:
a silly unit produces a visibly silly line, whereas this produces a plausible
recipe whose calories were computed from basil instead of blueberries.

The rule is deliberately weak — share *one* food word — because it must never
reject a correct-but-differently-worded match. ``normalize_food_name`` already
singularizes and drops filler, so "blueberries" and "Blueberries, dried" agree.
It exists to catch the catastrophic case, not to grade matches.
"""

from __future__ import annotations

from lib.fdc_local import normalize_food_name

# Words that describe *treatment*, not identity. A match resting only on one of
# these is exactly the failure this module exists to stop.
MODIFIERS = {
    "fresh", "dried", "raw", "cooked", "minced", "chopped", "sliced", "ground",
    "canned", "frozen", "roasted", "toasted", "smoked", "salted", "unsalted",
    "sweetened", "unsweetened", "whole", "halved", "peeled", "shredded",
    "grated", "melted", "softened", "boiled", "baked", "prepared", "instant",
    "plain", "light", "dark", "hot", "cold", "warm", "large", "medium", "small",
    "additional", "optional", "estimated", "inferred", "for", "of", "and", "or",
    "with", "without", "extra", "more", "less", "free", "low", "high", "style",
}


def _fold(word: str) -> str:
    """Absorb a stray trailing 'e' left by the shared singularizer.

    ``normalize_food_name._singularize`` strips a trailing "s" without handling
    "-oes"/"-ves"/"-xes", so "tomatoes" becomes "tomatoe" and never matches
    "tomato" — which made this guard reject a perfectly good
    "cherry tomatoes" -> "Tomato, roma". Folding here, for comparison only,
    because that function also builds ``fdc_foods.name_norm`` at load time and
    load/query must agree: fixing it properly means re-normalizing that column.
    """
    return word[:-1] if len(word) > 3 and word.endswith("e") else word


def _content_words(text: str) -> set[str]:
    """Identity-bearing words only — modifiers and filler removed."""
    return {_fold(w) for w in normalize_food_name(text or "").split()
            if w not in MODIFIERS}


def shares_a_food_word(ingredient: str, description: str) -> bool:
    """Whether the match rests on anything more than a shared modifier."""
    ing = _content_words(ingredient)
    if not ing:
        # Nothing identifying in the ingredient ("*(inferred)*", "(sweetener)").
        # Nothing to agree with, so no match can be justified.
        return False
    return bool(ing & _content_words(description))


def vet(ingredient: str, description: str, confidence: float,
        resolver: str) -> tuple[float, str, str]:
    """Return (confidence, resolver, note) after vetting a proposed match.

    A match sharing no food word is not rejected outright — the ingredient may
    genuinely have no USDA equivalent and a weak number can beat none. It is
    stripped of its confidence and relabelled, so it stops masquerading as
    settled, is excluded from the high-confidence cache, and surfaces for review
    instead of silently setting a recipe's calories.
    """
    if shares_a_food_word(ingredient, description):
        return confidence, resolver, ""
    return (
        0.2,
        f"{resolver}-unvetted",
        f"'{description}' shares no food word with '{ingredient}'",
    )
