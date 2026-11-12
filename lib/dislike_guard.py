"""Catch disliked ingredients in a recipe — deterministically, with no model.

The dislikes come from the hand-authored ``My Meal System.md``
(:meth:`lib.profile.Profile.dislikes`). They used to reach the meal suggester
only as prose inside an LLM prompt, which is a request, not a guard: a
bell-pepper salad landed on three consecutive weeks. Whether a recipe contains
an ingredient is a string question, so it is answered here with regexes over
the parsed ingredient rows, and every consumer — extraction frontmatter, the
placement APIs, the suggester's candidate pool — asks this module.

Matching rules, each pinned by ``tests/test_dislike_guard.py``:

- **The ingredient row only.** Rows come from
  ``recipe_parser.extract_ingredients_section`` + ``parse_ingredient_table``
  (the only allowed extractors), never the instructions — "garnish with bell
  pepper rings" in a method step is not a reason to flag, and scanning prose
  invites false positives.
- **Whole words, simple variants.** A term matches on word boundaries, its last
  word may take a plural ``s``/``es``, words may be joined by space or hyphen,
  a doubled letter may be single ("pepperoncini" ↔ "peperoncini"), and accents
  are folded.
- **"Do not infer that all other peppers are disliked."** So "pepper" alone is
  never a term, and red pepper flakes, aleppo, urfa, jalapeño and black pepper
  must not match. The boundary is what keeps "green peppercorns" clean.
- **Synonyms are opt-in per dislike.** ``SYNONYMS`` lists other names for the
  *same* food (``capsicum``, ``roasted red pepper``…); they apply only while
  their dislike is listed in the note. Ambiguous names — bare "red pepper",
  which may mean flakes — are deliberately absent: a missed flag is caught by
  the human, a false flag silently removes a recipe from suggestions.
"""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Optional

# Other names for the same food. Keyed by the dislike as the profile writes it
# (lowercase, singular). Only unambiguous names belong here.
SYNONYMS: dict[str, tuple[str, ...]] = {
    "bell pepper": (
        "capsicum", "sweet pepper", "green pepper", "roasted red pepper", "ajvar",
    ),
}


def _fold(text: str) -> str:
    """Lowercase, strip accents and markdown emphasis."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text.replace("*", "").replace("_", " ").lower()


def _word_pattern(word: str) -> str:
    # A doubled letter may be written single: pepperoncini / peperoncini.
    return re.sub(r"([a-z])\1", r"\1\1?", re.escape(word))


@lru_cache(maxsize=256)
def _term_regex(term: str) -> re.Pattern:
    words = _fold(term).split()
    parts = [_word_pattern(w) for w in words]
    parts[-1] += r"(?:e?s)?"
    return re.compile(r"(?<![a-z])" + r"[\s-]+".join(parts) + r"(?![a-z])")


def _patterns(dislikes: Iterable[str]) -> list[tuple[str, re.Pattern]]:
    out: list[tuple[str, re.Pattern]] = []
    for dislike in dislikes:
        d = _fold(dislike).strip()
        if not d:
            continue
        for term in (d, *SYNONYMS.get(d, ())):
            out.append((d, _term_regex(term)))
    return out


def match_item(item: str, dislikes: Iterable[str]) -> Optional[str]:
    """The dislike ``item`` contains, or None."""
    text = _fold(item or "")
    for dislike, rx in _patterns(dislikes):
        if rx.search(text):
            return dislike
    return None


def scan_items(items: Iterable[str], dislikes: Iterable[str]) -> list[dict]:
    """``[{"item", "dislike"}]`` for every ingredient row that hits a dislike."""
    dislikes = list(dislikes)
    if not dislikes:
        return []
    hits = []
    for item in items:
        d = match_item(item, dislikes)
        if d:
            hits.append({"item": item, "dislike": d})
    return hits


def scan_recipe(content: str, dislikes: Iterable[str]) -> list[dict]:
    """Scan a recipe note's (frontmatter-and-all) text."""
    from lib.recipe_parser import (extract_ingredients_section,
                                   parse_ingredient_table, parse_recipe_file)
    body = parse_recipe_file(content).get("body", content)
    rows = parse_ingredient_table(extract_ingredients_section(body))
    return scan_items([r.get("item", "") for r in rows], dislikes)


def recipe_hits(name: str, dislikes: Iterable[str],
                recipes_dir: Optional[Path] = None) -> list[dict]:
    """Scan the recipe file called ``name`` (no ``.md``); [] if it's missing."""
    from lib import paths
    stem = name[:-3] if name.endswith(".md") else name
    path = (recipes_dir or paths.recipes_dir()) / f"{stem}.md"
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, ValueError):
        return []
    return scan_recipe(content, dislikes)


def current_dislikes() -> list[str]:
    """Dislikes from the vault's profile note; [] when there is no note.

    Never raises — the guard is an enhancement, and a broken profile must not
    take down a placement or an extraction.
    """
    try:
        from lib import profile as profile_mod
        p = profile_mod.load_profile()
        return p.dislikes() if p else []
    except Exception:
        return []


def warning_for(names: Iterable[str], recipes_dir: Optional[Path] = None,
                dislikes: Optional[list[str]] = None) -> list[dict]:
    """Hits across several recipes, each tagged with its ``recipe``.

    The shape the placement APIs return as ``dislike_hits``. Warn, don't block:
    the user may have already swapped the ingredient by hand.
    """
    dislikes = current_dislikes() if dislikes is None else dislikes
    if not dislikes:
        return []
    out = []
    for name in names:
        for hit in recipe_hits(name, dislikes, recipes_dir):
            out.append({"recipe": name, **hit})
    return out


# --- optional swap ideas: local Ollama only ---------------------------------

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "mistral:7b"
SWAP_TIMEOUT_S = 60.0


def _swap_prompt(hits: list[dict], profile_text: str) -> str:
    rows = "\n".join(f'- "{h["item"]}" (disliked: {h["dislike"]})' for h in hits)
    return (
        "You suggest ingredient substitutions for a home cook.\n"
        "For each ingredient below, propose ONE substitute that keeps the "
        "ingredient's role in the dish (crunch, tang, sweetness, colour, heat) "
        "and supports their health goals: lowering LDL cholesterol and "
        "preventing type 2 diabetes (favour fibre, legumes, vegetables; avoid "
        "added sugar and saturated fat). Never suggest another disliked food.\n\n"
        f"Their food profile:\n{profile_text}\n\n"
        f"Ingredients:\n{rows}\n\n"
        'Reply with JSON only: {"swaps": [{"item": "<exact ingredient text>", '
        '"role": "<what it does in the dish>", "swap": "<substitute>"}]}'
    )


def suggest_swaps(hits: list[dict], profile_text: str = "",
                  timeout: float = SWAP_TIMEOUT_S) -> list[dict]:
    """Substitute ideas for ``hits`` from local Ollama; [] when unavailable.

    Optional and advisory: nothing here edits a recipe file. Detection never
    depends on it. Gated by ``lib/llm_gate`` like every tier — refused under
    ``KITCHENOS_NO_LLM``, and bounded by the request budget if a page render
    ever calls it (none does today; ``scripts/scan_dislikes.py --swaps`` is the
    only caller). Never Claude: this is meant to cost no API tokens.
    """
    from lib import llm_gate
    if not hits or not llm_gate.allowed():
        return []
    budget = llm_gate.budget_s(timeout)
    if budget <= 0:
        return []
    try:
        import json
        import requests
        resp = requests.post(
            OLLAMA_URL,
            json={"model": OLLAMA_MODEL, "prompt": _swap_prompt(hits, profile_text),
                  "stream": False, "format": "json"},
            timeout=budget,
        )
        if resp.status_code != 200:
            return []
        data = json.loads(resp.json().get("response", "") or "{}")
    except Exception:
        return []
    known = {h["item"] for h in hits}
    out = []
    for s in (data.get("swaps") if isinstance(data, dict) else None) or []:
        if not isinstance(s, dict):
            continue
        item, swap = str(s.get("item", "")).strip(), str(s.get("swap", "")).strip()
        # A model echoing a disliked food back as the "fix" is worse than nothing.
        if item in known and swap and not match_item(swap, [h["dislike"] for h in hits]):
            out.append({"item": item, "role": str(s.get("role", "")).strip(), "swap": swap})
    return out
