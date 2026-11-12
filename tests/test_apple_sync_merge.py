"""Three-way merge must never silently choose between competing edits."""

import pytest

from lib.apple_integration.merge import merge_fields
from lib.apple_integration.models import (
    InvalidPayload,
    Observation,
    validate_observations,
)


def due(day):
    return {"date": day, "time": None, "timezone": None}


def test_source_completion_moves_only_to_apple():
    result = merge_fields(
        {"completed": False}, {"completed": True}, {"completed": False}
    )
    assert result.apple_patch == {"completed": True}
    assert result.source_patch == {} and result.conflicts == []


def test_apple_due_override_and_explicit_clear():
    result = merge_fields(
        {"due": due("2026-10-08")}, {"due": due("2026-10-08")}, {"due": None}
    )
    assert result.source_patch == {"due": None}
    assert result.apple_patch == {} and result.conflicts == []


def test_divergent_due_dates_conflict():
    result = merge_fields(
        {"due": due("2026-10-08")},
        {"due": due("2026-10-09")},
        {"due": due("2026-10-10")},
    )
    assert result.conflicts == ["due"]
    assert result.source_patch == result.apple_patch == {}


def test_equal_edits_need_no_patch():
    result = merge_fields(
        {"completed": False}, {"completed": True}, {"completed": True}
    )
    assert result.conflicts == [] and result.source_patch == result.apple_patch == {}


def test_first_export_has_no_common_and_existing_marker_is_recovery():
    assert merge_fields(None, {"completed": False}, None).apple_patch == {
        "completed": False
    }
    assert merge_fields(None, {"completed": False}, {"completed": False}).conflicts == [
        "recovery"
    ]


@pytest.mark.parametrize(
    "fields",
    [
        {"surprise": 3},
        {"completed": 1},
        {"due": {"date": "2026-02-30", "time": None, "timezone": None}},
        {"due": {"date": "2026-10-08", "time": "12:00", "timezone": None}},
        {"duration_minutes": float("nan")},
        {"duration_minutes": float("inf")},
        {"start": "2026-10-08T12:00:00"},
        {"timezone": "Not/AZone"},
        {"due": {"date": "2026-10-08", "time": None, "timezone": None, "extra": True}},
    ],
)
def test_invalid_fields_fail_closed(fields):
    with pytest.raises(InvalidPayload):
        merge_fields({}, fields, {})


def test_duplicate_observation_tokens_fail_closed():
    observation = Observation.from_dict(
        {
            "token": "00000000-0000-4000-8000-000000000001",
            "generation": 1,
            "revision": 1,
            "availability": "missing",
            "locator": None,
            "title": None,
            "fields": {},
            "absence_confirmed": True,
            "issue": None,
        }
    )
    with pytest.raises(InvalidPayload):
        validate_observations([observation, observation])


def test_observation_unknown_keys_rejected():
    with pytest.raises(InvalidPayload):
        Observation.from_dict({"token": "x", "unknown": True})


@pytest.mark.parametrize(
    "change",
    [
        {"domain": []},
        {"state": []},
        {"week": None},
        {"fields": {"duration_minutes": True}},
    ],
)
def test_direct_source_construction_has_typed_validation_errors(change):
    from lib.apple_integration.models import SourceItem, canonical_hash

    payload = dict(
        logical_id="one",
        domain="cooking",
        week="2026-W41",
        title="Limes",
        fields={},
        source_revision=canonical_hash("one"),
        state="active",
    )
    payload.update(change)
    with pytest.raises(InvalidPayload):
        SourceItem(**payload)


def test_wire_batch_roundtrip_retains_nested_locators_and_null_due():
    from lib.apple_integration.models import WorkBatch

    context = {
        "owner_id": "00000000-0000-4000-8000-000000000001",
        "owner_generation": 1,
    }
    operation = {
        "operation_id": "00000000-0000-4000-8000-000000000002",
        "token": "00000000-0000-4000-8000-000000000003",
        "generation": 2,
        "revision": 4,
        "action": "upsert",
        "destination_id": "list",
        "locator": {"calendar_id": "list", "item_id": "item", "external_id": None},
        "title": "Limes",
        "fields": {"due": None, "completed": False},
        "expected_apple_hash": None,
    }
    payload = {
        "context": context,
        "items": [],
        "operations": [operation],
        "model_version": 1,
        "scopes": [],
        "report": {
            "created": 0,
            "updated": 0,
            "deleted": 0,
            "queued": 0,
            "conflicts": 0,
            "unavailable": 0,
            "last_success": None,
        },
        "paused": False,
        "retry_requests": [],
        "retained_items": [],
    }
    batch = WorkBatch.from_dict(payload)
    assert batch.to_dict() == payload
    assert batch.operations[0].locator.item_id == "item"
    operation["unknown"] = True
    with pytest.raises(InvalidPayload):
        WorkBatch.from_dict(payload)


def test_canonical_revision_ignores_dict_order_not_contents():
    from lib.apple_integration.models import canonical_hash

    assert canonical_hash({"a": 1, "b": 2}) == canonical_hash({"b": 2, "a": 1})
    assert canonical_hash({"a": 1}) != canonical_hash({"a": 2})


def test_merge_missing_is_not_explicit_due_clear():
    result = merge_fields({"due": due("2026-10-08")}, {}, {"due": due("2026-10-08")})
    assert result.conflicts == ["due"]
    assert result.source_patch == result.apple_patch == {}
