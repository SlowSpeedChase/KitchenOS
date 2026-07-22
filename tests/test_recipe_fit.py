"""Fit assessment: validating what the model returns before it reaches a note.

The assessment is inference, so the guard rails matter more than the happy
path. An out-of-vocabulary value stored silently would poison every downstream
filter, and a recipe tagged from a failed call would look assessed when it
wasn't.
"""
import pytest

from lib import recipe_fit
from lib.profile import Profile

GOOD = {
    "craving_lane": "sweet", "buffer_candidate": True, "dairy_load": "low",
    "effort": "assembly", "heart": True, "steady": True,
    "note": "oats and nuts, no added sugar",
}


@pytest.fixture
def profile():
    return Profile(prose="Loves sweet food. Lowering LDL.")


# --- validation -----------------------------------------------------------

def test_accepts_a_well_formed_assessment():
    assert recipe_fit._coerce(GOOD)["craving_lane"] == "sweet"


@pytest.mark.parametrize("field,bad", [
    ("craving_lane", "savoury"),      # not in the vocabulary
    ("dairy_load", "medium-high"),    # the classic LLM hedge
    ("effort", "very quick"),
])
def test_rejects_out_of_vocabulary_values(field, bad):
    """Storing a hedge would quietly break every filter built on these."""
    assert recipe_fit._coerce({**GOOD, field: bad}) is None


@pytest.mark.parametrize("value", ["true", 1, None])
def test_rejects_non_boolean_health_flags(value):
    """A string "true" would read as truthy forever after."""
    assert recipe_fit._coerce({**GOOD, "heart": value}) is None


def test_rejects_a_non_dict_response():
    assert recipe_fit._coerce(["sweet"]) is None


def test_truncates_a_runaway_note():
    out = recipe_fit._coerce({**GOOD, "note": "x" * 500})
    assert len(out["note"]) <= 120


def test_flattens_newlines_in_the_note():
    """A newline would corrupt the single-line frontmatter value."""
    assert "\n" not in recipe_fit._coerce({**GOOD, "note": "a\nb"})["note"]


def test_defaults_buffer_candidate_when_absent():
    raw = {k: v for k, v in GOOD.items() if k != "buffer_candidate"}
    assert recipe_fit._coerce(raw)["buffer_candidate"] is False


# --- json extraction ------------------------------------------------------

def test_extracts_json_wrapped_in_prose():
    """Models add a preamble no matter how firmly they are told not to."""
    got = recipe_fit._extract_json('Sure!\n```json\n{"craving_lane": "sweet"}\n```')
    assert got == {"craving_lane": "sweet"}


def test_extract_json_returns_none_on_garbage():
    assert recipe_fit._extract_json("no json here") is None


# --- frontmatter mapping --------------------------------------------------

def test_frontmatter_always_flags_needing_review():
    """Every value is judged from an ingredient list, never measured."""
    assert recipe_fit.to_frontmatter({**GOOD, "source": "claude"})["fit_needs_review"] == "true"


def test_frontmatter_records_which_model_answered():
    fm = recipe_fit.to_frontmatter({**GOOD, "source": "ollama"})
    assert fm["fit_source"] == "ollama"


def test_frontmatter_writes_yaml_booleans_not_python():
    fm = recipe_fit.to_frontmatter({**GOOD, "source": "claude"})
    assert fm["fit_heart"] == "true" and fm["fit_buffer_candidate"] == "true"


def test_frontmatter_quotes_the_note():
    """Unquoted, a note containing ':' would break the YAML."""
    fm = recipe_fit.to_frontmatter({**GOOD, "note": "good: but rich", "source": "claude"})
    assert fm["fit_note"] == '"good: but rich"'


# --- backend orchestration ------------------------------------------------

def test_assess_returns_none_when_no_backend_answers(monkeypatch, profile):
    """A dead Ollama and no API key must leave the recipe untagged."""
    monkeypatch.setattr(recipe_fit, "_assess_with_claude", lambda p: None)
    monkeypatch.setattr(recipe_fit, "_assess_with_ollama", lambda p: None)
    assert recipe_fit.assess("Chili", ["beans"], profile) is None


def test_assess_falls_back_to_ollama(monkeypatch, profile):
    monkeypatch.setattr(recipe_fit, "_assess_with_claude", lambda p: None)
    monkeypatch.setattr(recipe_fit, "_assess_with_ollama", lambda p: GOOD)
    assert recipe_fit.assess("Chili", ["beans"], profile)["source"] == "ollama"


def test_assess_rejects_a_malformed_claude_reply_rather_than_storing_it(
        monkeypatch, profile):
    """Falls through to Ollama instead of writing an invalid tag."""
    monkeypatch.setattr(recipe_fit, "_assess_with_claude",
                        lambda p: {**GOOD, "dairy_load": "sort of"})
    monkeypatch.setattr(recipe_fit, "_assess_with_ollama", lambda p: GOOD)
    assert recipe_fit.assess("Chili", ["beans"], profile)["source"] == "ollama"
