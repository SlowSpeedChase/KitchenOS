"""Short display titles for recipes whose real name is too long to render.

Recipe names come from the extractor, which historically echoed the video title:
``[감자치즈빵] 화덕에 구운 것 같은 감자치즈빵! (후라이팬으로 맛있는 빵 만들기, Pot`` and
``Maple Sweet Potato Salad - With Whipped Tahini And Crispy Chickpeas`` are both
real entries. 70 of 252 recipes are over 32 characters, and a planner card is
about 104px wide.

**The file name stays the identity.** ``cooks.recipe`` is a name string, meal
plans reference names, and ``task_extractor`` hashes ``recipe|day|slot|step`` so
that done-flags survive plan regeneration — renaming a recipe would orphan its
planned cooks and silently reset its task checkboxes. So this adds a
``short_title`` frontmatter field that display surfaces prefer, and changes
nothing about what the recipe *is*.

The LLM proposes; :func:`validate_short_title` disposes. That split is deliberate
and load-bearing: an LLM asked to shorten a title will occasionally rename the
dish, and the only reason the portion ledger stopped storing package weights was
a validator, not a better prompt.

This module stays dependency-free on purpose — ``recipe_index`` imports it, and
``recipe_index`` is imported by seven others, so pulling ``requests``/``anthropic``
in here would put a network client on the import path of the whole app. The LLM
call lives in ``scripts/backfill_short_titles.py``, its only caller.
"""
from __future__ import annotations

import re
import unicodedata

# Names at or above this get a short title; below it there is nothing to fix.
SHORTEN_THRESHOLD = 33

# What a short title must fit inside, chosen to match the threshold: anything at
# or over 33 chars gets shortened to at most 32. A tighter 28 rejected a stream of
# 29-31 char titles that were perfectly readable, which is a validator failing on
# its own arbitrary line rather than on anything real.
MAX_SHORT_LEN = 32

MIN_SHORT_LEN = 3

# Words a shortened title may introduce or drop freely — they carry no dish
# identity, so requiring them to match would reject good titles for no reason.
_STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "with", "without", "for", "of", "in", "on",
    "to", "from", "by", "at", "into", "over", "under", "best", "easy", "quick",
    "simple", "homemade", "perfect", "ultimate", "amazing", "delicious", "viral",
    "recipe", "recipes", "style", "inspired", "make", "how", "youtube", "shorts",
    "video", "minute", "minutes", "min", "ever", "my", "your", "this", "that",
    "is", "it", "you", "i", "very", "super", "really",
})

_WORD = re.compile(r"[0-9a-z]+")

# Two-word food names that stop naming a food when the second word is dropped.
# "Chocolate Peanut Butter Protein Pancake Bowl" came back as "Chocolate Peanut
# Protein Pancake", and "Cottage Cheese Cookie Dough" as "Cottage Cookie Dough" —
# both pass a subset-and-order check and both name something that doesn't exist.
_COMPOUND_FOODS = (
    ("peanut", "butter"), ("almond", "butter"), ("cashew", "butter"),
    ("cottage", "cheese"), ("cream", "cheese"), ("goat", "cheese"),
    ("sour", "cream"), ("heavy", "cream"), ("ice", "cream"),
    ("coconut", "milk"), ("almond", "milk"), ("oat", "milk"),
    ("greek", "yogurt"), ("maple", "syrup"), ("olive", "oil"), ("sesame", "oil"),
    ("soy", "sauce"), ("fish", "sauce"), ("hot", "sauce"), ("tomato", "sauce"),
    ("black", "beans"), ("green", "beans"), ("butter", "beans"),
    ("sweet", "potato"), ("sweet", "potatoes"), ("bell", "pepper"),
    ("brussels", "sprouts"), ("chia", "seeds"), ("puff", "pastry"),
)


def _splits_a_compound(cand: list[str], orig: list[str]) -> str | None:
    """The first compound food the candidate broke apart, if any."""
    for head, tail in _COMPOUND_FOODS:
        for i in range(len(orig) - 1):
            if orig[i] == head and orig[i + 1] == tail:
                if head in cand and tail not in cand:
                    return f"{head} {tail}"
    return None


def _content_word_list(text: str) -> list[str]:
    """Lowercased, accent-folded, stopword-free tokens of ``text``, in order."""
    folded = unicodedata.normalize("NFKD", text.lower())
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    # Single characters count. They are how "Chicken Caldo A" differs from
    # "Chicken Caldo B", and dropping them let the abbreviation "w/" through the
    # subset check as an invisible token.
    return [w for w in _WORD.findall(folded) if w not in _STOPWORDS]


def _content_words(text: str) -> set[str]:
    return set(_content_word_list(text))


def _is_subsequence(candidate: list[str], original: list[str]) -> bool:
    """True when ``candidate``'s words appear in ``original`` in the same order."""
    it = iter(original)
    return all(word in it for word in candidate)


def is_latin(text: str) -> bool:
    """True when the name is written in Latin script.

    Decides which validation rule applies. A Latin-script title can only be
    shortened by *removing* words, so the result must be a subset of the
    original — that is what stops "Beef Birria" becoming "Chicken Tacos". A
    Korean or Thai title has to be *translated* to be shorter and readable, which
    legitimately introduces words the original never contained, so subsetting
    would reject exactly the cases that need this most.
    """
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return True
    latin = sum(1 for c in letters if "LATIN" in unicodedata.name(c, ""))
    return latin / len(letters) >= 0.5


def needs_shortening(name: str) -> bool:
    return len(name) >= SHORTEN_THRESHOLD


def validate_short_title(
    original: str, candidate: str, taken: set[str] | None = None
) -> tuple[bool, str]:
    """Check a proposed short title. Returns ``(ok, reason)``.

    ``taken`` is the set of names/short titles already in use. Collisions matter
    more than they look: the corpus really contains ``Chicken Caldo A`` next to
    ``Chicken Caldo B``, and ``High-Protein Bean Lentil Dip (Crouton)`` next to
    ``High-Protein Bean Lentil Dip`` — in both cases the part an LLM would call
    redundant is the only thing telling them apart.
    """
    candidate = (candidate or "").strip()

    if len(candidate) < MIN_SHORT_LEN:
        return False, "empty or too short to be a name"
    if len(candidate) > MAX_SHORT_LEN:
        return False, f"{len(candidate)} chars, over the {MAX_SHORT_LEN} limit"
    if len(candidate) >= len(original):
        return False, "not shorter than the name it replaces"
    if not _content_words(candidate):
        return False, "no content words — all filler"

    if taken:
        lowered = {t.casefold() for t in taken}
        lowered.discard(original.casefold())
        if candidate.casefold() in lowered:
            return False, f"collides with an existing recipe ({candidate!r})"

    # A Latin-script shortening deletes words. Deleting preserves both membership
    # and order, so the result must be a *subsequence* of the original. Membership
    # alone stops "Beef Birria" becoming "Chicken Tacos"; order additionally stops
    # the reshuffles the model actually produced — "19 Calorie Fudgy Brownies
    # (Crouton)" came back as "Fudgy (Crouton) Brownies", which passes a set check
    # and still reads like a different, slightly broken dish.
    if is_latin(original):
        cand_words = _content_word_list(candidate)
        orig_words = _content_word_list(original)
        invented = set(cand_words) - set(orig_words)
        if invented:
            return False, ("introduces words the recipe name never had: "
                           + ", ".join(sorted(invented)))
        if not _is_subsequence(cand_words, orig_words):
            return False, "reorders the words of the recipe name"
        split = _splits_a_compound(cand_words, orig_words)
        if split:
            return False, f"splits the compound ingredient {split!r}"

    return True, ""


def display_name(name: str, short: str | None) -> str:
    """What a surface should render. The name is the fallback, always."""
    short = (short or "").strip()
    return short if short else name
