"""Is a buffer food actually reachable tonight?

The Meal System note's premise is that when the urge hits in the evening,
something you genuinely like has to win a four-second race. That makes this a
**stock** question, not a recipe question. Most of the buffer menu — "apple +
nut butter", "handful of pistachios", "hummus, guac, mashed avocado" — is an
assembly of things that are either in the house or not, and no amount of recipe
acquisition fixes an empty fruit bowl.

Worth stating plainly, because the obvious metric misleads: only 17 of 232
recipes are tagged buffer-capable, which reads like a library gap and is not
one. Those 17 are the batch-cook entries (chia pudding, roasted chickpeas,
overnight oats). The rest of the menu never needed a recipe.

So this checks the menu against live inventory, lane by lane. The note says to
keep at least one per row stocked; a lane with nothing available is the
finding worth acting on.
"""
from __future__ import annotations

import re
from typing import Optional

# Words that carry no matching signal in an assembly line. Single words only:
# the tokenizer splits on [a-z]+, so a hyphenated entry like "low-fat" could
# never match a token and silently did nothing.
_NOISE = {"a", "an", "the", "of", "or", "and", "with", "handful", "batch",
          "jar", "jars", "plain", "low", "fat", "warm", "air", "popped",
          "pan", "crisped", "stuffed", "frozen", "roasted", "seedy",
          "whole", "grain", "sprouted", "steel", "cut", "rolled", "good"}


def _content_tokens(text: str) -> frozenset:
    from lib.recipe_matcher import _content_tokens as ct
    return ct(text)


def _ingredient_parts(item: str) -> list[list[str]]:
    """Split a buffer-menu line into ingredient groups.

    A parenthetical is the real ingredient list when present — "Chocolate chia
    pudding (chia + soy milk + cocoa)" is three things to have, not one dish to
    look up. Each group is a list of interchangeable alternatives, so
    "Apple/pear" is satisfied by either.
    """
    text = re.sub(r"\[\w+\]", " ", item)          # drop [heart]/[steady] tags
    paren = re.search(r"\(([^)]+)\)", text)
    if paren:
        text = paren.group(1)
    else:
        text = re.sub(r"\([^)]*\)", " ", text)

    groups = []
    for chunk in re.split(r"[+,]", text):
        alts = [a.strip(" .·") for a in chunk.split("/") if a.strip(" .·")]
        alts = [a for a in alts if _content_tokens(a) - _NOISE]
        if alts:
            groups.append(alts)
    return groups


# Generic categories the menu writes but the shelf never says. Kept explicit
# rather than inferred from the head noun: "milk" would then let whole milk
# satisfy "soy milk", which is exactly backwards for a dairy-reduction goal.
# Extend this as the note's vocabulary grows.
_ALIASES = {
    "nut butter": ("peanut butter", "almond butter", "cashew butter",
                   "sunflower butter", "tahini"),
    "nut butter walnut": ("peanut butter", "almond butter"),
    "soy nut": ("roasted soybean", "soy nuts", "edamame"),
    "seaweed snack": ("seaweed", "nori"),
}


def _covers(have: frozenset, want: frozenset) -> bool:
    """Does one stocked item satisfy every word of what's wanted?

    Suffix matching handles the menu's generic categories: it asks for "nut
    butter" and "berries", while the shelf holds "peanut butter" and
    "blueberries". Requiring an exact token match would report a stocked lane
    as bare, which is the one error that makes this whole check untrustworthy.
    """
    for w in want:
        if not any(h == w or h.endswith(w) for h in have):
            return False
    return True


def _have(alt: str, stock_tokens: list[frozenset], staple_tokens: list[frozenset]) -> bool:
    """True if this alternative is on hand (or is an assumed pantry staple)."""
    want = _content_tokens(alt) - _NOISE
    if not want:
        return True                     # pure noise ("a handful") — not a blocker

    wants = [want]
    for generic, concretes in _ALIASES.items():
        if _content_tokens(generic) - _NOISE == want:
            wants += [_content_tokens(c) - _NOISE for c in concretes]

    # Only a full cover counts. A subset match would let the pantry staple
    # "butter" satisfy a request for "nut butter", quietly reporting a lane as
    # stocked when there is no nut butter in the house.
    return any(_covers(have, w)
               for w in wants
               for have in stock_tokens + staple_tokens)


def _clean_label(item: str) -> str:
    return re.sub(r"\s*\[\w+\]", "", item).strip()


def lane_readiness(profile, items: Optional[list] = None,
                   staples: Optional[set] = None) -> dict:
    """Per craving lane, which buffer foods are makeable from current stock.

    Returns ``{lane: {"ready": [labels], "missing": [{"item", "needs"}]}}``.
    """
    if profile is None or not getattr(profile, "buffer_menu", None):
        return {}

    if items is None:
        from lib.inventory import read_inventory
        items = read_inventory()
    if staples is None:
        from lib.meal_suggester import load_pantry_staples
        staples = load_pantry_staples()

    stock_tokens = [t for t in (_content_tokens(i.name) for i in items) if t]
    staple_tokens = [t for t in (_content_tokens(s) for s in staples) if t]

    out: dict = {}
    for lane, entries in profile.buffer_menu.items():
        ready, missing = [], []
        for entry in entries:
            label = _clean_label(entry)
            groups = _ingredient_parts(entry)
            absent = [g[0] for g in groups
                      if not any(_have(a, stock_tokens, staple_tokens) for a in g)]
            if absent:
                missing.append({"item": label, "needs": ", ".join(absent)})
            else:
                ready.append(label)
        out[lane] = {"ready": ready, "missing": missing}
    return out


def bare_lanes(readiness: dict) -> list[str]:
    """Lanes with nothing available — the note says keep one per row stocked."""
    return [lane for lane, r in readiness.items() if not r["ready"]]


def shopping_targets(readiness: dict, per_lane: int = 1) -> list[str]:
    """What to buy to light up each bare lane.

    Only bare lanes contribute. Padding the list with things for lanes that are
    already covered is how a shopping list stops being read.
    """
    targets: list[str] = []
    for lane in bare_lanes(readiness):
        for entry in readiness[lane]["missing"][:per_lane]:
            targets.append(f"{entry['needs']} — for {lane.lower()} ({entry['item']})")
    return targets


def block_gaps(profile, items: Optional[list] = None) -> dict:
    """Building-block staples from the profile that aren't currently stocked.

    The note frames these as the base layer: "stock these, then meals are
    assembly". A gap here is upstream of every buffer food that uses it.
    """
    if profile is None or not getattr(profile, "building_blocks", None):
        return {}
    if items is None:
        from lib.inventory import read_inventory
        items = read_inventory()
    stock_tokens = [t for t in (_content_tokens(i.name) for i in items) if t]

    gaps: dict = {}
    for category, blocks in profile.building_blocks.items():
        absent = [b for b in blocks if not _block_stocked(b, stock_tokens)]
        if absent:
            gaps[category] = absent
    return gaps


def _block_stocked(block: str, stock_tokens: list[frozenset]) -> bool:
    """Is this building block on hand?

    Unlike a buffer-menu line, a block's parenthetical is an annotation rather
    than an ingredient list — "nutritional yeast (cheesy)" is one item, and
    treating "cheesy" as something to shop for reports a stocked staple as
    missing. Slashes and "or" mark interchangeable options.
    """
    text = re.sub(r"\([^)]*\)", " ", block)
    alts = [a.strip() for a in re.split(r"/|\bor\b", text) if a.strip()]
    if len(alts) > 1:
        # "plain soy or low-fat Greek yogurt" shares one head noun across both
        # options; splitting alone leaves "plain soy", which matches soy sauce.
        head = alts[-1].split()[-1]
        alts = [a if a.endswith(head) else f"{a} {head}" for a in alts]
    return any(_have(a, stock_tokens, []) for a in alts or [text])
