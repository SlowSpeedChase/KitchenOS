"""LLM-backed food resolution and portion estimation (the constrained jobs).

Wraps Ollama (``mistral:7b``, JSON mode — same pattern as
``meal_suggester.normalize_ingredients_ollama``) behind two validated functions
the nutrition engine calls only as a fallback:

- :func:`resolve_food_llm` — choose the best candidate food by index.
- :func:`estimate_portion_grams_llm` — grams for one count unit.

Both validate the model's output (index in range, grams within sane bounds,
confidence clamped) and return ``None`` on any failure, so the engine degrades to
``needs_review`` rather than trusting garbage. Claude is intentionally not used
here yet — see the Ollama viability test in ``scripts/validate_nutrition.py``;
if Ollama underperforms, swap in the ``anthropic`` client already wired in
``lib/meal_suggester.py``.
"""
from __future__ import annotations

import json
from typing import Optional

import requests

from prompts.food_resolution import FOOD_RESOLUTION_PROMPT, PORTION_GRAMS_PROMPT

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "mistral:7b"

# Sane bounds for a single count unit's weight (grams). Outside → reject.
_MIN_GRAMS_PER_UNIT = 0.1
_MAX_GRAMS_PER_UNIT = 5000.0


def _ollama_json(prompt: str, timeout: int = 60):
    """Call Ollama in JSON mode and return the parsed object, or None."""
    try:
        resp = requests.post(
            OLLAMA_URL,
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False, "format": "json"},
            timeout=timeout,
        )
        if resp.status_code != 200:
            return None
        return json.loads(resp.json().get("response", ""))
    except (requests.RequestException, json.JSONDecodeError, ValueError, KeyError):
        return None


def _clamp_confidence(value, default: float = 0.5) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def resolve_food_llm(ingredient: str, candidates: list) -> Optional[tuple[int, float]]:
    """Pick the best candidate food for an ingredient.

    ``candidates`` is a list of FoodRecord-like objects with ``.description``.
    Returns ``(choice_index, confidence)`` or None if the model fails / the index
    is out of range.
    """
    if not candidates:
        return None
    listing = "\n".join(
        f"{i}. {getattr(c, 'description', '') or c.get('description', '')}"
        for i, c in enumerate(candidates)
    )
    prompt = FOOD_RESOLUTION_PROMPT.format(ingredient=ingredient, candidates=listing)
    data = _ollama_json(prompt)
    if not isinstance(data, dict):
        return None
    idx = data.get("choice_index")
    if not isinstance(idx, int) or idx < 0 or idx >= len(candidates):
        return None
    return idx, _clamp_confidence(data.get("confidence"))


def estimate_portion_grams_llm(
    unit: str, item: str, portion_labels: Optional[list] = None
) -> Optional[tuple[float, float]]:
    """Estimate grams for a single ``unit`` of ``item``.

    Returns ``(grams_per_unit, confidence)`` or None if the model fails or returns
    an out-of-bounds weight.
    """
    hint = ""
    if portion_labels:
        hint = "Reference portions: " + "; ".join(str(p) for p in portion_labels) + "\n"
    prompt = PORTION_GRAMS_PROMPT.format(unit=unit or "unit", item=item, portion_hint=hint)
    data = _ollama_json(prompt)
    if not isinstance(data, dict):
        return None
    try:
        grams = float(data.get("grams_per_unit"))
    except (TypeError, ValueError):
        return None
    if not (_MIN_GRAMS_PER_UNIT <= grams <= _MAX_GRAMS_PER_UNIT):
        return None
    return grams, _clamp_confidence(data.get("confidence"))
