"""Conservative phase inference, prep compatibility and dependency scheduling."""
from copy import deepcopy

import pytest
from flask import Flask

from lib import recipe_phases as phases


def step(text, **extra):
    return {"step": 1, "text": text, **extra}


def bean(recipe="A", **extra):
    return {"recipe": recipe, "instructions": [step("Cook black-eyed peas", phase="cook", prep={
        "ingredient": "black-eyed peas", "amount": 1, "unit": "lb",
        "method": "pressure cook", "pressure_minutes": 10, "pressure_release": "natural",
        "liquid_ratio": "3:1", "outcome": "cooked beans", "storage": "use immediately",
        "raw_animal_protein": False, "needs_review": False, **extra})]}


def cook(**extra):
    return {"item_id": "schedule:cook:1", "cook_id": 1, "recipe": "A", "date": "2026-09-29",
            "start": "2026-09-29T18:00:00-05:00", "duration_minutes": 60,
            "source": "cook_schedule", **extra}


def task(item_id, **extra):
    return {"item_id": item_id, "recipes": ["A"], "can_do_ahead": True,
            "depends_on": [], "source_ids": [item_id], **extra}


def test_fallback_keeps_every_source_without_inventing_safety_or_dependencies():
    source = [step("Do the usual thing."), step("Chop onions.", step=2),
              step("Simmer for 20 minutes.", step=3)]
    before = deepcopy(source)
    result = phases.classify_legacy_steps("Soup", source)
    rows = result["instructions"]
    assert [r["phase"] for r in rows] == ["instructions", "prep_or_flavor_base", "cook"]
    assert [r["duration_minutes"] for r in rows] == [None, None, 20]
    assert [r["source_ordinal"] for r in rows] == [1, 2, 3]
    assert len({r["source_id"] for r in rows}) == 3
    assert all(r["needs_review"] and r["confidence"] <= 0.5 for r in rows)
    assert all(r["can_do_ahead"] is False and r["depends_on"] == [] for r in rows)
    assert source == before
    changed = phases.classify_legacy_steps("Soup", [step("New display wording.")])
    assert changed["instructions"][0]["source_id"] == rows[0]["source_id"]


def test_native_phases_keep_source_order_and_bypass_model(monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail("native phases must not invoke a model")
    source = [step("An unusual instruction", phase="finish_and_taste")]
    with phases.classification_refresh(proposer=fail):
        result = phases.classify_legacy_steps("Soup", source)
    assert result["instructions"][0]["phase"] == "finish_and_taste"
    assert result["instructions"][0]["source"] == "native_phase"


@pytest.mark.parametrize("blocked", ["no_refresh", "request", "disabled", "zero_budget"])
def test_model_is_never_called_without_refresh_and_positive_gate(monkeypatch, blocked):
    def fail(*args, **kwargs):
        pytest.fail("model called through a closed gate")
    monkeypatch.setattr(phases, "_model_propose", fail)
    monkeypatch.setattr(phases.llm_gate, "allowed", lambda: blocked != "disabled")
    monkeypatch.setattr(phases.llm_gate, "budget_s", lambda default: 0 if blocked == "zero_budget" else default)
    if blocked == "no_refresh":
        result = phases.classify_legacy_steps("Soup", [step("Chop onions.")])
    elif blocked == "request":
        with Flask(__name__).test_request_context(), phases.classification_refresh():
            result = phases.classify_legacy_steps("Soup", [step("Chop onions.")])
    else:
        with phases.classification_refresh():
            result = phases.classify_legacy_steps("Soup", [step("Chop onions.")])
    assert result["instructions"][0]["needs_review"] is True


def test_validated_model_cannot_add_steps_time_dependencies_or_freezing_claims(monkeypatch):
    monkeypatch.setattr(phases.llm_gate, "allowed", lambda: True)
    def propose(payload, *, timeout):
        assert 0 < timeout <= 30
        row = payload["instructions"][0]
        return {"instructions": [{"source_id": row["source_id"], "phase": "freeze_and_store",
                "duration_minutes": 120, "can_do_ahead": True, "depends_on": ["fake"],
                "confidence": 1.0, "text": "Freeze raw food safely forever"}]}
    with phases.classification_refresh(proposer=propose):
        result = phases.classify_legacy_steps("Soup", [step("Chop onions.")])
    row = result["instructions"][0]
    assert row["text"] == "Chop onions."
    assert row["phase"] == "prep_or_flavor_base"
    assert row["duration_minutes"] is None and row["depends_on"] == []
    assert row["can_do_ahead"] is False and row["needs_review"] is True


def test_matching_beans_merge_convert_quantities_and_keep_source_links():
    recipes = [bean(), bean("B", amount=8, unit="oz")]
    before = deepcopy(recipes)
    rows = phases.build_shared_prep(recipes)
    assert len(rows) == 1
    assert rows[0]["amount"] == 1.5 and rows[0]["unit"] == "lb"
    assert rows[0]["recipes"] == ["A", "B"]
    assert len(rows[0]["source_ids"]) == len(rows[0]["contributions"]) == 2
    assert recipes == before
    recipes[0]["instructions"][0]["text"] = "Display changed"
    assert phases.build_shared_prep(list(reversed(recipes)))[0]["item_id"] == rows[0]["item_id"]


@pytest.mark.parametrize("change", [
    {"pressure_minutes": 12}, {"pressure_release": "quick"}, {"liquid_ratio": "2:1"},
    {"storage": "refrigerate"}, {"outcome": "puree"}, {"unit": "cup"},
    {"pressure_release": None}, {"needs_review": True}, {"raw_animal_protein": None},
])
def test_incompatible_or_uncertain_safety_attributes_do_not_merge(change):
    assert len(phases.build_shared_prep([bean(), bean("B", **change)])) == 2


def test_raw_chicken_never_merges_even_if_model_proposes_it(monkeypatch):
    monkeypatch.setattr(phases.llm_gate, "allowed", lambda: True)
    recipes = [bean(name, ingredient="raw chicken", raw_animal_protein=False) for name in ["A", "B"]]
    with phases.classification_refresh():
        rows = phases.build_shared_prep(recipes, proposer=lambda payload, timeout: {"groups": [payload["source_ids"]]})
    assert all(len(row["recipes"]) == 1 for row in rows)


def test_dependency_chain_walks_back_from_earliest_cook_and_keeps_schedule():
    cooks = [cook(), cook(item_id="schedule:cook:2", cook_id=2, date="2026-10-01")]
    tasks = [task("beans", depends_on=["soak"]), task("soak")]
    before = deepcopy(cooks)
    rows = phases.build_production_schedule(cooks, tasks, [])
    assert [(r["source_ids"], r["date"]) for r in rows[:2]] == [(["soak"], "2026-09-27"), (["beans"], "2026-09-28")]
    assert [r for r in rows if r.get("source") == "cook_schedule"] == before
    assert cooks == before


def test_time_sensitive_prep_stays_on_cook_day_and_storage_follows_freeze():
    storage = [task("freeze", phase="freeze_and_store", action="freeze", depends_on=[]),
               task("bag", phase="freeze_and_store", action="bag", depends_on=["freeze"])]
    rows = phases.build_production_schedule([cook()], [task("chop", time_sensitive=True)], storage)
    dates = {r.get("task_id"): r["date"] for r in rows if r.get("task_id")}
    assert dates == {"chop": "2026-09-29", "freeze": "2026-09-29", "bag": "2026-09-30"}


def test_cycles_and_missing_dependencies_remain_visible_without_dates():
    rows = phases.build_production_schedule([cook()], [task("a", depends_on=["b"]),
        task("b", depends_on=["a"]), task("c", depends_on=["absent"])], [])
    affected = [r for r in rows if r.get("task_id")]
    assert len(affected) == 3
    assert all(r["needs_review"] and r["date"] is None for r in affected)


def test_schedule_without_cook_date_does_not_invent_one():
    rows = phases.build_production_schedule([], [task("soak")], [])
    assert rows[0]["date"] is None and rows[0]["needs_review"] is True


def test_source_text_can_supply_complete_bean_prep_without_synthetic_metadata():
    a = {"recipe": "A", "instructions": [step("Pressure cook 1 lb black-eyed peas for 10 minutes with a 3:1 water-to-bean ratio; natural release; use immediately.", phase="cook")]}
    b = {"recipe": "B", "instructions": [step("Pressure cook 8 oz black-eyed peas for 10 minutes with a 3:1 water-to-bean ratio; natural release; use immediately.", phase="cook")]}
    rows = phases.build_shared_prep([a, b])
    assert len(rows) == 1
    assert rows[0]["amount"] == 1.5 and rows[0]["recipes"] == ["A", "B"]


def test_missing_release_in_source_text_keeps_pressure_prep_separate():
    text = "Pressure cook 1 lb black-eyed peas for 10 minutes with a 3:1 water-to-bean ratio; use immediately."
    rows = phases.build_shared_prep([{"recipe": name, "instructions": [step(text, phase="cook")]} for name in ["A", "B"]])
    assert len(rows) == 2 and all(row["needs_review"] for row in rows)


def test_same_day_prep_precedes_cook_and_storage_follows_it():
    rows = phases.build_production_schedule([cook()], [task("chop", time_sensitive=True)], [task("freeze", action="freeze")])
    assert [r.get("task_id", "cook") for r in rows] == ["chop", "cook", "freeze"]


def test_merge_preserves_internal_dependency_instead_of_swallowing_it():
    a, b = bean(), bean("B")
    a["instructions"][0]["source_id"] = "a"
    b["instructions"][0].update(source_id="b", depends_on=["a"])
    assert len(phases.build_shared_prep([a, b])) == 2


def test_two_same_recipe_preparations_do_not_merge():
    a = bean()
    a["instructions"].append(deepcopy(a["instructions"][0]))
    assert len(phases.build_shared_prep([a])) == 2


def test_duplicate_model_ids_and_oversized_response_fall_back(monkeypatch):
    monkeypatch.setattr(phases.llm_gate, "allowed", lambda: True)
    for payload in [{"instructions": [{"source_id": "fake"}]}, {"instructions": "x" * 60001}]:
        with phases.classification_refresh(proposer=lambda data, timeout: payload):
            result = phases.classify_legacy_steps("A", [step("Chop onions.")])
        assert result["instructions"][0]["source"] == "heuristic"


def test_prep_amounts_follow_total_recipe_scale():
    a = bean()
    a["scale"] = 2
    b = bean("B", amount=8, unit="oz")
    rows = phases.build_shared_prep([a, b])
    assert rows[0]["amount"] == 2.5
    assert rows[0]["contributions"][0]["amount"] == 2


@pytest.mark.parametrize("ratio", ["unknown", "0:1", "1:0", "-1:2"])
def test_invalid_ratio_is_not_evidence_of_safe_compatibility(ratio):
    assert len(phases.build_shared_prep([bean("A", liquid_ratio=ratio), bean("B", liquid_ratio=ratio)])) == 2


def test_negated_and_multiple_actions_are_uncertain():
    result = phases.classify_legacy_steps("A", [step("Freeze? No, do not freeze this."),
        step("Chop the onions then simmer the sauce.", step=2)])
    assert all(row["phase"] == "instructions" for row in result["instructions"])


def test_model_proposal_cannot_ignore_prompt_input_bound(monkeypatch):
    monkeypatch.setattr(phases.llm_gate, "allowed", lambda: True)
    def fail(*args, **kwargs):
        pytest.fail("oversized input reached model")
    with phases.classification_refresh(proposer=fail):
        result = phases.classify_legacy_steps("A", [step("Chop " + "x" * 60000)])
    assert result["instructions"][0]["source"] == "heuristic"


def test_valid_shared_proposal_selects_only_compatible_source_groups(monkeypatch):
    monkeypatch.setattr(phases.llm_gate, "allowed", lambda: True)
    recipes = [bean(name) for name in ["A", "B", "C"]]
    def proposer(payload, *, timeout):
        assert payload["kind"] == "shared_prep"
        assert all("text" in row for row in payload["candidates"])
        return {"groups": [[row["source_id"] for row in payload["candidates"][:2]]]}
    with phases.classification_refresh():
        rows = phases.build_shared_prep(recipes, proposer=proposer)
    assert [row["recipes"] for row in rows] == [["A", "B"], ["C"]]


def test_shared_model_proposal_cannot_merge_incompatible_pressure_times(monkeypatch):
    monkeypatch.setattr(phases.llm_gate, "allowed", lambda: True)
    def proposer(payload, *, timeout):
        return {"groups": [payload["source_ids"]]}
    with phases.classification_refresh():
        rows = phases.build_shared_prep([bean(), bean("B", pressure_minutes=30)], proposer=proposer)
    assert len(rows) == 2


def test_storage_dependencies_can_reference_authoritative_cook_ids():
    source = cook()
    rows = phases.build_production_schedule([source], [], [task("freeze", action="freeze", depends_on=[source["item_id"]])])
    frozen = next(row for row in rows if row.get("task_id") == "freeze")
    assert frozen["date"] == "2026-09-29" and not frozen["needs_review"]


def test_merge_does_not_mislabel_amount_when_durations_differ():
    a, b = bean(), bean("B")
    a["instructions"][0]["duration_minutes"] = 10
    b["instructions"][0]["duration_minutes"] = 60
    assert len(phases.build_shared_prep([a, b])) == 2
