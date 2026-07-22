"""Assess how each recipe fits the personal food profile.

Turns a 235-recipe pile into something retrievable: which craving a recipe
serves, whether it could work as a zero-prep buffer food, how hard it leans on
the dairy zone, and whether it plausibly supports the LDL / blood-sugar goals.

Tiering matches the receipt parser: Claude Haiku when a key is configured,
local Ollama otherwise, and None if neither answers — a failed assessment
leaves the recipe untagged rather than guessing.

Everything written here is *inference*. Fields carry `fit_source` and
`fit_needs_review: true` so a later pass backed by real fibre and saturated-fat
data can overwrite them without ambiguity about which values were guessed.
"""
from __future__ import annotations

import json
import os
from typing import Optional

import requests

try:
    import anthropic
    _api_key = os.getenv("ANTHROPIC_API_KEY")
    anthropic_client = anthropic.Anthropic(api_key=_api_key) if _api_key else None
except ImportError:  # pragma: no cover - anthropic is a hard dependency in practice
    anthropic_client = None

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "mistral:7b"
CLAUDE_MODEL = "claude-haiku-4-5-20251001"
CLAUDE_MAX_TOKENS = 300

CRAVING_LANES = {"sweet", "carby", "salty", "rich", "none"}
DAIRY_LOADS = {"none", "low", "medium", "high"}
EFFORTS = {"assembly", "quick", "project"}

# Frontmatter keys this module owns.
MANAGED_KEYS = frozenset({
    "fit_craving_lane", "fit_buffer_candidate", "fit_dairy_load", "fit_effort",
    "fit_heart", "fit_steady", "fit_note", "fit_source", "fit_needs_review",
})


def _coerce(raw: dict) -> Optional[dict]:
    """Validate a model response into the tag vocabulary, or None if unusable.

    Vocabulary drift is the common LLM failure here ("medium-high", "very
    quick"). Silently storing those would poison every downstream filter, so an
    out-of-vocabulary value is rejected rather than normalized by guesswork.
    """
    if not isinstance(raw, dict):
        return None
    lane = str(raw.get("craving_lane", "")).strip().lower()
    dairy = str(raw.get("dairy_load", "")).strip().lower()
    effort = str(raw.get("effort", "")).strip().lower()
    if lane not in CRAVING_LANES or dairy not in DAIRY_LOADS or effort not in EFFORTS:
        return None
    if not isinstance(raw.get("heart"), bool) or not isinstance(raw.get("steady"), bool):
        return None

    note = str(raw.get("note", "")).strip().replace("\n", " ")
    return {
        "craving_lane": lane,
        "buffer_candidate": bool(raw.get("buffer_candidate", False)),
        "dairy_load": dairy,
        "effort": effort,
        "heart": raw["heart"],
        "steady": raw["steady"],
        "note": note[:120],
    }


def _extract_json(text: str) -> Optional[dict]:
    start, end = text.find("{"), text.rfind("}") + 1
    if start == -1 or end == 0:
        return None
    try:
        return json.loads(text[start:end])
    except json.JSONDecodeError:
        return None


def _build_prompt(name: str, ingredients: list[str], profile) -> str:
    from prompts.recipe_fit import FIT_PROMPT
    return FIT_PROMPT.format(
        profile=profile.prompt_context(),
        name=name,
        ingredients="\n".join(f"- {i}" for i in ingredients[:40]) or "- (none listed)",
    )


def _assess_with_claude(prompt: str) -> Optional[dict]:
    if anthropic_client is None:
        return None
    try:
        message = anthropic_client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=CLAUDE_MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
        return _extract_json(message.content[0].text)
    except Exception:
        return None


def _assess_with_ollama(prompt: str) -> Optional[dict]:
    try:
        resp = requests.post(
            OLLAMA_URL,
            json={"model": OLLAMA_MODEL, "prompt": prompt,
                  "stream": False, "format": "json"},
            timeout=120,
        )
        if resp.status_code != 200:
            return None
        return _extract_json(resp.json().get("response", ""))
    except Exception:
        return None


def assess(name: str, ingredients: list[str], profile) -> Optional[dict]:
    """Assess one recipe. Returns validated tags, or None if no model answered."""
    prompt = _build_prompt(name, ingredients, profile)
    for backend in (_assess_with_claude, _assess_with_ollama):
        raw = backend(prompt)
        if raw is None:
            continue
        tags = _coerce(raw)
        if tags is not None:
            tags["source"] = "claude" if backend is _assess_with_claude else "ollama"
            return tags
    return None


def to_frontmatter(tags: dict) -> dict:
    """Map an assessment onto the recipe frontmatter keys.

    `fit_needs_review` is always true: every value here is a judgement made
    from an ingredient list, not a measurement.
    """
    return {
        "fit_craving_lane": tags["craving_lane"],
        "fit_buffer_candidate": "true" if tags["buffer_candidate"] else "false",
        "fit_dairy_load": tags["dairy_load"],
        "fit_effort": tags["effort"],
        "fit_heart": "true" if tags["heart"] else "false",
        "fit_steady": "true" if tags["steady"] else "false",
        "fit_note": f'"{tags["note"]}"' if tags["note"] else '""',
        "fit_source": tags.get("source", "llm"),
        "fit_needs_review": "true",
    }
