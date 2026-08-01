"""Tests for lib.task_extractor."""
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from lib import llm_gate, task_extractor


SAMPLE_PLAN = """# Meal Plan - Week 18 (Apr 27 - May 3, 2026)

## Monday (Apr 27)
### Breakfast

### Lunch

### Dinner
[[Test Pasta]]
### Notes


## Tuesday (Apr 28)
### Breakfast

### Lunch

### Dinner

### Notes


## Wednesday (Apr 29)
### Breakfast

### Lunch

### Dinner

### Notes


## Thursday (Apr 30)
### Breakfast

### Lunch

### Dinner

### Notes


## Friday (May 1)
### Breakfast

### Lunch

### Dinner

### Notes


## Saturday (May 2)
### Breakfast

### Lunch

### Dinner

### Notes


## Sunday (May 3)
### Breakfast

### Lunch

### Dinner

### Notes
"""


SAMPLE_RECIPE = """---
type: recipe
title: "Test Pasta"
---

## Ingredients

| Amount | Unit | Item |
|--------|------|------|
| 1 | cup | flour |

## Instructions

1. Chop the onion into fine dice.
2. Boil the pasta in salted water until al dente.
3. Simmer the sauce for 20 minutes.
"""


@pytest.fixture
def vault(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("KITCHENOS_VAULT", str(tmp_path))
    (tmp_path / "Meal Plans").mkdir()
    (tmp_path / "Recipes").mkdir()
    (tmp_path / "Meal Plans" / "2026-W18.md").write_text(SAMPLE_PLAN)
    (tmp_path / "Recipes" / "Test Pasta.md").write_text(SAMPLE_RECIPE)
    # Reset module-level cached paths in shopping_list_generator (uses old vault path)
    from lib import shopping_list_generator
    monkeypatch.setattr(shopping_list_generator, "RECIPES_PATH", tmp_path / "Recipes")
    monkeypatch.setattr(shopping_list_generator, "MEAL_PLANS_PATH", tmp_path / "Meal Plans")
    return tmp_path


def test_collect_scheduled_steps_finds_recipe_instructions(vault: Path):
    steps = task_extractor._collect_scheduled_steps("2026-W18")
    assert len(steps) == 3
    assert steps[0].recipe == "Test Pasta"
    assert steps[0].day == "Monday"
    assert steps[0].slot == "dinner"
    assert "Chop the onion" in steps[0].text


def test_extract_tasks_uses_heuristic_when_no_models(vault: Path):
    """With both Claude and Ollama unavailable, heuristic classifier kicks in."""
    with patch.object(task_extractor, "_anthropic_client", None), \
         patch.object(task_extractor, "_classify_with_ollama", return_value=None):
        result = task_extractor.extract_tasks("2026-W18")

    assert result["week"] == "2026-W18"
    assert len(result["tasks"]) == 3
    types = [t["type"] for t in result["tasks"]]
    # "Chop" → prep, "Boil" → active, "Simmer" → passive
    assert types[0] == "prep"
    assert types[2] == "passive"
    # Sidecar saved
    sidecar = vault / "Meal Plans" / "2026-W18.tasks.json"
    assert sidecar.exists()


def test_stable_id_preserves_done_across_regeneration(vault: Path):
    with patch.object(task_extractor, "_anthropic_client", None), \
         patch.object(task_extractor, "_classify_with_ollama", return_value=None):
        first = task_extractor.extract_tasks("2026-W18")
        task_id = first["tasks"][0]["id"]
        task_extractor.mark_task_done("2026-W18", task_id, True)
        # Touch the meal plan to invalidate cache
        plan_path = vault / "Meal Plans" / "2026-W18.md"
        plan_path.write_text(plan_path.read_text() + "\n")
        # Force regeneration
        regenerated = task_extractor.extract_tasks("2026-W18", force=True)

    matched = next((t for t in regenerated["tasks"] if t["id"] == task_id), None)
    assert matched is not None
    assert matched["done"] is True


def test_cache_returned_when_fresh(vault: Path):
    with patch.object(task_extractor, "_anthropic_client", None), \
         patch.object(task_extractor, "_classify_with_ollama", return_value=None):
        first = task_extractor.extract_tasks("2026-W18")
        first_generated_at = first["generated_at"]

    # Second call without touching the plan should NOT regenerate.
    with patch.object(task_extractor, "_classify_with_claude") as claude_mock:
        second = task_extractor.extract_tasks("2026-W18")
        claude_mock.assert_not_called()

    assert second["generated_at"] == first_generated_at


def test_extract_tasks_uses_claude_output(vault: Path):
    fake_payload = [
        {
            "recipe": "Test Pasta", "day": "Monday", "slot": "dinner", "step": 1,
            "text": "Chop the onion into fine dice.",
            "type": "prep", "time_minutes": 3, "can_do_ahead": True, "depends_on": [],
        },
        {
            "recipe": "Test Pasta", "day": "Monday", "slot": "dinner", "step": 2,
            "text": "Boil the pasta in salted water until al dente.",
            "type": "active", "time_minutes": 12, "can_do_ahead": False, "depends_on": [],
        },
        {
            "recipe": "Test Pasta", "day": "Monday", "slot": "dinner", "step": 3,
            "text": "Simmer the sauce for 20 minutes.",
            "type": "passive", "time_minutes": 20, "can_do_ahead": True, "depends_on": [1],
        },
    ]
    with patch.object(task_extractor, "_classify_with_claude", return_value=fake_payload):
        result = task_extractor.extract_tasks("2026-W18", force=True)

    assert len(result["tasks"]) == 3
    last = result["tasks"][2]
    assert last["type"] == "passive"
    assert last["time_minutes"] == 20
    assert last["can_do_ahead"] is True
    assert len(last["depends_on"]) == 1


def test_mark_task_done_persists(vault: Path):
    with patch.object(task_extractor, "_anthropic_client", None), \
         patch.object(task_extractor, "_classify_with_ollama", return_value=None):
        first = task_extractor.extract_tasks("2026-W18")
        task_id = first["tasks"][0]["id"]
        task_extractor.mark_task_done("2026-W18", task_id, True)

    sidecar = vault / "Meal Plans" / "2026-W18.tasks.json"
    data = json.loads(sidecar.read_text())
    flagged = next(t for t in data["tasks"] if t["id"] == task_id)
    assert flagged["done"] is True


def test_mark_task_done_unknown_id_returns_error(vault: Path):
    with patch.object(task_extractor, "_anthropic_client", None), \
         patch.object(task_extractor, "_classify_with_ollama", return_value=None):
        task_extractor.extract_tasks("2026-W18")
    result = task_extractor.mark_task_done("2026-W18", "nope")
    assert result["success"] is False


# ---- lib/llm_gate: a page render may not hang on inference ----

class _FakeResponse:
    status_code = 200

    def json(self):
        return {"response": "[]"}


def _capture(seen):
    """Record the kwargs of a requests.post and answer with an empty JSON body."""
    def post(*args, **kwargs):
        seen.update(kwargs)
        return _FakeResponse()
    return post


def test_the_kill_switch_skips_the_ollama_tier(monkeypatch):
    """The e2e harness sets this. Blanking API keys can't stop Ollama — no key."""
    monkeypatch.setenv(llm_gate.DISABLE_ENV, "1")
    posted = []
    monkeypatch.setattr(task_extractor.requests, "post", lambda *a, **k: posted.append(k))

    assert task_extractor._classify_with_ollama("prompt") is None
    assert posted == [], "the kill switch must be checked before the request"


def test_a_script_keeps_the_long_ollama_timeout(monkeypatch):
    """Nobody is waiting on a nightly job; it may take its two minutes."""
    seen = {}
    monkeypatch.setattr(task_extractor.requests, "post", _capture(seen))

    task_extractor._classify_with_ollama("prompt")

    assert seen["timeout"] == 120


def test_a_page_render_bounds_the_ollama_timeout(monkeypatch):
    """/prep was a 120 s blocking call behind a 30 s browser timeout."""
    from flask import Flask

    seen = {}
    monkeypatch.setattr(task_extractor.requests, "post", _capture(seen))

    with Flask(__name__).test_request_context("/prep"):
        task_extractor._classify_with_ollama("prompt")

    assert seen["timeout"] <= llm_gate.WEB_BUDGET_S


def test_a_page_render_does_not_persist_a_budget_forced_heuristic(vault: Path):
    """A fallback the *clock* forced must not become the cached answer.

    `_is_cache_fresh` only compares mtimes, so persisting it would freeze the
    heuristic in place until the plan is edited. Falling back because no model
    exists at all is different and still caches — that is the real answer there.
    """
    from flask import Flask

    with patch.object(task_extractor, "_anthropic_client", None), \
         patch.object(task_extractor, "_classify_with_ollama", return_value=None), \
         Flask(__name__).test_request_context("/prep"):
        result = task_extractor.extract_tasks("2026-W18")

    assert result["tasks"], "the reader still gets an answer"
    assert not (vault / "Meal Plans" / "2026-W18.tasks.json").exists()
