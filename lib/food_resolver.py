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
import os
import re
from typing import Optional

import requests

from prompts.food_resolution import FOOD_RESOLUTION_PROMPT, PORTION_GRAMS_PROMPT

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "mistral:7b"

CLAUDE_MODEL = "claude-haiku-4-5-20251001"
try:
    import anthropic
    _anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    _anthropic_client = anthropic.Anthropic(api_key=_anthropic_key) if _anthropic_key else None
except ImportError:
    _anthropic_client = None


def claude_available() -> bool:
    return _anthropic_client is not None


def _claude_json(prompt: str):
    """Call Claude and return the parsed JSON object, or None."""
    if _anthropic_client is None:
        return None
    try:
        resp = _anthropic_client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text
        start, end = text.find("{"), text.rfind("}") + 1
        if start == -1 or end == 0:
            return None
        return json.loads(text[start:end])
    except Exception:
        # Anthropic/network/parse errors — degrade to no answer, never crash.
        return None

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


def _resolution_prompt(ingredient: str, candidates: list) -> str:
    listing = "\n".join(
        f"{i}. {getattr(c, 'description', '') or c.get('description', '')}"
        for i, c in enumerate(candidates)
    )
    return FOOD_RESOLUTION_PROMPT.format(ingredient=ingredient, candidates=listing)


def _validate_resolution(data, n: int) -> Optional[tuple[int, float]]:
    if not isinstance(data, dict):
        return None
    idx = data.get("choice_index")
    if not isinstance(idx, int) or idx < 0 or idx >= n:
        return None
    return idx, _clamp_confidence(data.get("confidence"))


def _portion_prompt(unit: str, item: str, portion_labels: Optional[list]) -> str:
    hint = ""
    if portion_labels:
        hint = "Reference portions: " + "; ".join(str(p) for p in portion_labels) + "\n"
    return PORTION_GRAMS_PROMPT.format(unit=unit or "unit", item=item, portion_hint=hint)


def _validate_portion(data) -> Optional[tuple[float, float]]:
    if not isinstance(data, dict):
        return None
    try:
        grams = float(data.get("grams_per_unit"))
    except (TypeError, ValueError):
        return None
    if not (_MIN_GRAMS_PER_UNIT <= grams <= _MAX_GRAMS_PER_UNIT):
        return None
    return grams, _clamp_confidence(data.get("confidence"))


# --- Ollama (local) implementations -----------------------------------------

def resolve_food_llm(ingredient: str, candidates: list) -> Optional[tuple[int, float]]:
    """Pick the best candidate food (Ollama). Returns (index, confidence) or None."""
    if not candidates:
        return None
    return _validate_resolution(_ollama_json(_resolution_prompt(ingredient, candidates)),
                                len(candidates))


def estimate_portion_grams_llm(
    unit: str, item: str, portion_labels: Optional[list] = None
) -> Optional[tuple[float, float]]:
    """Estimate grams for one ``unit`` of ``item`` (Ollama)."""
    return _validate_portion(_ollama_json(_portion_prompt(unit, item, portion_labels)))


# --- Claude implementations --------------------------------------------------

def resolve_food_claude(ingredient: str, candidates: list) -> Optional[tuple[int, float]]:
    """Pick the best candidate food (Claude). Returns (index, confidence) or None."""
    if not candidates:
        return None
    return _validate_resolution(_claude_json(_resolution_prompt(ingredient, candidates)),
                                len(candidates))


def estimate_portion_grams_claude(
    unit: str, item: str, portion_labels: Optional[list] = None
) -> Optional[tuple[float, float]]:
    """Estimate grams for one ``unit`` of ``item`` (Claude)."""
    return _validate_portion(_claude_json(_portion_prompt(unit, item, portion_labels)))


# --- Provider dispatchers ----------------------------------------------------

def resolve_food(ingredient: str, candidates: list, provider: str) -> Optional[tuple[int, float]]:
    if provider == "claude":
        return resolve_food_claude(ingredient, candidates)
    if provider == "ollama":
        return resolve_food_llm(ingredient, candidates)
    return None


def estimate_portion_grams(
    unit: str, item: str, portion_labels: Optional[list], provider: str
) -> Optional[tuple[float, float]]:
    if provider == "claude":
        return estimate_portion_grams_claude(unit, item, portion_labels)
    if provider == "ollama":
        return estimate_portion_grams_llm(unit, item, portion_labels)
    return None
