"""Pre-match ingredient text cleanup ("Phase B") + alias table.

USDA descriptions are terse ("Oil, olive, salad or cooking"); recipe lines
are chatty ("extra-virgin olive oil (plus more for serving)"). Stripping the
chat before word-overlap matching is the cheapest accuracy win available.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import yaml

_ALIASES_PATH = Path(__file__).resolve().parent.parent / "config" / "food_aliases.yml"

# Trailing prep/serving phrases introduced by a comma.
_PREP_TAIL = re.compile(
    r",\s*(plus more[^,]*|finely [a-z]+|coarsely [a-z]+|roughly [a-z]+"
    r"|thinly [a-z]+|chopped|minced|diced|sliced|grated|shredded|melted"
    r"|softened|divided|to serve|for serving|for garnish|optional"
    r"|at room temperature)\b.*$",
    re.IGNORECASE,
)


def clean_for_matching(item: str) -> str:
    text = item or ""
    text = re.sub(r"\*\(inferred\)\*", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\([^)]*\)", " ", text)          # parentheticals
    text = _PREP_TAIL.sub("", text)
    # collapse immediately doubled words ("garlic garlic cloves")
    text = re.sub(r"\b(\w+)( \1\b)+", r"\1", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip(" ,.*")


@lru_cache(maxsize=1)
def _aliases() -> dict:
    if not _ALIASES_PATH.exists():
        return {}
    data = yaml.safe_load(_ALIASES_PATH.read_text(encoding="utf-8")) or {}
    return {str(k).lower(): str(v) for k, v in data.items()}


def apply_aliases(item: str) -> str:
    return _aliases().get((item or "").lower(), item)
