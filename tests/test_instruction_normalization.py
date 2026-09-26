"""Phases survive future extraction without changing legacy payloads."""
import pytest

from extract_recipe import normalize_instructions


@pytest.mark.parametrize(("value", "expected"), [
    ("prep_or_flavor_base", "prep_or_flavor_base"),
    ("Prep or Flavor Base", "prep_or_flavor_base"),
    ("Prep / Flavor Base", "prep_or_flavor_base"),
    (" COOK ", "cook"),
    ("finish_and_taste", "finish_and_taste"),
    ("Finish & Taste", "finish_and_taste"),
    ("Freeze and Store", "freeze_and_store"),
    ("freeze-and-store", "freeze_and_store"),
    ("Reheat", "reheat"),
    ("storage", None),
    ("unknown", None),
    ("", None),
    (None, None),
    ([], None),
    (1, None),
])
def test_instruction_phase_normalization_accepts_only_approved_phases(value, expected):
    from lib import recipe_parser

    normalize_phase = getattr(recipe_parser, "normalize_instruction_phase", None)
    assert callable(normalize_phase), "phase normalization interface is missing"
    assert normalize_phase(value) == expected


def test_extraction_normalization_preserves_canonical_and_nullable_phases():
    assert normalize_instructions([
        {"step": 1, "text": "Simmer.", "phase": "Cook"},
        {"step": 2, "description": "Taste.", "time": "1 min", "phase": "Finish & Taste"},
        {"step": 3, "text": "Check source.", "phase": None},
        {"step": 4, "text": "Other.", "phase": "made_up"},
    ]) == [
        {"step": 1, "text": "Simmer.", "time": None, "phase": "cook"},
        {"step": 2, "text": "Taste.", "time": "1 min", "phase": "finish_and_taste"},
        {"step": 3, "text": "Check source.", "time": None, "phase": None},
        {"step": 4, "text": "Other.", "time": None, "phase": None},
    ]


def test_legacy_extraction_payloads_keep_their_shape():
    assert normalize_instructions(["Mix.", {"description": "Bake.", "time": "10 min"}, None]) == [
        {"step": 1, "text": "Mix.", "time": None},
        {"step": 2, "text": "Bake.", "time": "10 min"},
    ]
    assert normalize_instructions([]) == []


@pytest.mark.parametrize("prompt_name", ["SYSTEM_PROMPT", "DESCRIPTION_EXTRACTION_PROMPT"])
def test_extraction_prompt_instruction_schema_exposes_nullable_approved_phases(prompt_name):
    from prompts import recipe_extraction

    prompt = getattr(recipe_extraction, prompt_name)
    instruction_schema = prompt.split('"instructions": [', 1)[1].split("]", 1)[0]
    assert '"phase"' in instruction_schema
    assert "null" in instruction_schema.split('"phase"', 1)[1]
    for phase in ("prep_or_flavor_base", "cook", "finish_and_taste", "freeze_and_store", "reheat"):
        assert phase in instruction_schema
