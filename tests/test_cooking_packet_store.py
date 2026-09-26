"""Packet repository contracts against an isolated, real SQLite database."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import importlib
import threading

import pytest

from lib import inventory_db


@pytest.fixture
def store(tmp_db):
    return importlib.import_module("lib.cooking_packet_store")


def draft(ids=("cook:58",)):
    return {
        "version": 1,
        "week": "2026-W40",
        "schedule": [{"item_id": key, "text": "Generated", "done": False} for key in ids],
        "recipe_cards": [{"item_id": "recipe:Soup", "recipe": "Soup", "notes": ""}],
    }


def change(item_id="cook:58", field="text", value="Mine"):
    return {"item_id": item_id, "field": field, "value": value}


def test_missing_packet_returns_none(store):
    assert store.get_packet("2026-W40") is None


def test_replace_reads_committed_packet_and_does_not_mutate_input(store):
    generated = draft()
    original = deepcopy(generated)
    saved = store.replace_generated("2026-W40", generated)
    assert saved == store.get_packet("2026-W40")
    assert saved["revision"] == 1
    assert saved["status"] == "draft"
    assert saved["generated_at"] and saved["updated_at"]
    assert generated == original


def test_sparse_edits_follow_stable_id_after_reordering(store):
    first = store.replace_generated("2026-W40", draft(("cook:58", "cook:59")))
    store.patch_packet("2026-W40", first["revision"], [change(), change(field="done", value=True)])
    saved = store.replace_generated("2026-W40", draft(("cook:59", "cook:58")))
    assert saved["schedule"][0]["text"] == "Generated"
    assert saved["schedule"][1]["text"] == "Mine"
    assert saved["schedule"][1]["done"] is True
    assert saved["needs_review"] == []
    with inventory_db.connect() as conn:
        raw = conn.execute("SELECT generated_json FROM cooking_packets").fetchone()[0]
    assert '"Mine"' not in raw


def test_replace_preserves_orphan_edits_until_source_returns(store):
    first = store.replace_generated("2026-W40", draft())
    store.patch_packet("2026-W40", first["revision"], [change()])
    saved = store.replace_generated("2026-W40", draft(("cook:59",)))
    assert saved["needs_review"][0]["item_id"] == "cook:58"
    assert saved["needs_review"][0]["value"] == "Mine"
    assert saved["schedule"][0]["text"] == "Generated"
    again = store.replace_generated("2026-W40", draft(("cook:59",)))
    assert again["needs_review"] == saved["needs_review"]
    restored = store.replace_generated("2026-W40", draft())
    assert restored["schedule"][0]["text"] == "Mine"
    assert restored["needs_review"] == []


def test_stale_revision_cannot_overwrite_newer_edit(store):
    first = store.replace_generated("2026-W40", draft())
    latest = store.patch_packet("2026-W40", first["revision"], [change()])
    with pytest.raises(store.RevisionConflict):
        store.patch_packet("2026-W40", first["revision"], [change(value="Stale")])
    assert store.get_packet("2026-W40") == latest


def test_two_concurrent_edits_with_same_revision_have_one_winner(store):
    first = store.replace_generated("2026-W40", draft())
    barrier = threading.Barrier(2)

    def edit(text):
        barrier.wait(timeout=5)
        try:
            return store.patch_packet("2026-W40", first["revision"], [change(value=text)])
        except store.RevisionConflict:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(edit, ["First", "Second"]))
    winners = [result for result in results if result is not None]
    assert len(winners) == 1
    assert store.get_packet("2026-W40") == winners[0]
    assert winners[0]["revision"] == first["revision"] + 1


def test_review_applies_to_current_revision_and_refresh_clears_it(store):
    packet = store.replace_generated("2026-W40", draft())
    reviewed = store.patch_packet("2026-W40", packet["revision"], [], status="reviewed")
    assert reviewed["status"] == "reviewed" and reviewed["reviewed_at"]
    regenerated = store.replace_generated("2026-W40", draft())
    assert regenerated["status"] == "draft" and regenerated["reviewed_at"] is None
    reviewed = store.patch_packet("2026-W40", regenerated["revision"], [], status="reviewed")
    edited = store.patch_packet("2026-W40", reviewed["revision"], [change()])
    assert edited["status"] == "draft" and edited["reviewed_at"] is None


def test_store_snapshot_preserves_edits_and_checks_revision(store):
    packet = store.replace_generated("2026-W40", draft())
    edited = store.patch_packet("2026-W40", packet["revision"], [change()], status="reviewed")
    snapshot = {"version": 1, "heb": {"products": [{"name": "H-E-B rice"}]}}
    saved = store.replace_store_snapshot("2026-W40", edited["revision"], snapshot)
    assert saved["store_snapshot"] == snapshot
    assert saved["schedule"][0]["text"] == "Mine"
    assert saved["status"] == "draft" and saved["reviewed_at"] is None
    assert saved["store_refreshed_at"]
    with pytest.raises(store.RevisionConflict):
        store.replace_store_snapshot("2026-W40", edited["revision"], {"version": 1})
    assert store.get_packet("2026-W40") == saved
    assert store.replace_generated("2026-W40", draft())["store_snapshot"] == snapshot


def test_repeated_generation_request_does_not_discard_later_edit(store):
    packet = store.replace_generated("2026-W40", draft(), request_id="request-1")
    edited = store.patch_packet("2026-W40", packet["revision"], [change()])
    assert store.replace_generated("2026-W40", draft(("cook:59",)), request_id="request-1") == edited


def test_request_id_stays_idempotent_after_other_refreshes(store):
    store.replace_generated("2026-W40", draft(), request_id="request-1")
    latest = store.replace_generated("2026-W40", draft(("cook:59",)), request_id="request-2")
    assert store.replace_generated("2026-W40", draft(), request_id="request-1") == latest


def test_identical_replacements_do_not_increment_revision(store):
    packet = store.replace_generated("2026-W40", draft())
    assert store.replace_generated("2026-W40", draft()) == packet
    snapshot = {"version": 1, "heb": {"products": []}}
    saved = store.replace_store_snapshot("2026-W40", packet["revision"], snapshot)
    assert store.replace_store_snapshot("2026-W40", saved["revision"], snapshot) == saved


@pytest.mark.parametrize("week", ["2026-W00", "2026-W54", "2021-W53", "2026-W4", "2026-w40", "../2026-W40", None])
def test_invalid_week_is_rejected_before_access(store, week):
    with pytest.raises(ValueError):
        store.get_packet(week)
    with pytest.raises(ValueError):
        store.replace_generated(week, draft())
    assert store.get_packet("2026-W40") is None


@pytest.mark.parametrize("generated", [
    {"version": 2}, {"version": True}, {}, {"version": 1, "week": "2026-W41"},
    {"version": 1, "status": "approved"},
    {"version": 1, "schedule": [{"item_id": "same"}, {"item_id": "same"}]},
    {"version": 1, "notes": "a" * 10001},
    {"version": 1, "schedule": [{"item_id": f"task:{i}"} for i in range(2001)]},
    {"version": 1, "notes": ["a" * 10000] * 220},
    {"version": 1, "amount": float("nan")},
    {"version": 1, "revision": 8},
    {"version": 1, "schedule": [{"item_id": ""}]},
])
def test_invalid_generated_document_rolls_back(store, generated):
    before = store.replace_generated("2026-W40", draft())
    with pytest.raises(ValueError):
        store.replace_generated("2026-W40", generated)
    assert store.get_packet("2026-W40") == before


@pytest.mark.parametrize("changes", [
    [change(field="recipe", value="Another recipe")],
    [change(field="text.html")], [change(field="__proto__")],
    [change(item_id="missing")], [dict(change(), extra=True)],
    [{"item_id": "cook:58", "field": "text"}],
    [change(field="done", value="yes")], [change(value="a" * 10001)],
    [change(value=float("inf"))], [change(field="duration_minutes", value=-1)],
    [change(field="phase", value="unknown")],
])
def test_invalid_patch_rolls_back_all_changes(store, changes):
    before = store.replace_generated("2026-W40", draft())
    with pytest.raises(ValueError):
        store.patch_packet("2026-W40", before["revision"], [change(value="Must roll back")] + changes)
    assert store.get_packet("2026-W40") == before


def test_total_document_size_includes_edits_and_snapshot(store):
    generated = draft()
    generated["notes"] = ["a" * 10000] * 110
    before = store.replace_generated("2026-W40", generated)
    with pytest.raises(ValueError):
        store.replace_store_snapshot("2026-W40", before["revision"], {"version": 1, "notes": ["b" * 10000] * 110})
    assert store.get_packet("2026-W40") == before


@pytest.mark.parametrize("revision", [True, 0, -1, "1", None])
def test_invalid_revision_rejected(store, revision):
    before = store.replace_generated("2026-W40", draft())
    with pytest.raises(ValueError):
        store.patch_packet("2026-W40", revision, [])
    assert store.get_packet("2026-W40") == before


def test_invalid_status_and_snapshot_roll_back(store):
    before = store.replace_generated("2026-W40", draft())
    with pytest.raises(ValueError):
        store.patch_packet("2026-W40", before["revision"], [], status="approved")
    with pytest.raises(ValueError):
        store.replace_store_snapshot("2026-W40", before["revision"], {"version": 2})
    assert store.get_packet("2026-W40") == before


def test_quantity_date_and_phase_edits_are_packet_only(store):
    packet = store.replace_generated("2026-W40", draft())
    saved = store.patch_packet("2026-W40", packet["revision"], [
        change(field="quantity", value=1.5), change(field="date", value="2026-09-27"),
        change(field="phase", value="cook"), change(field="duration_minutes", value=30),
    ])
    assert saved["schedule"][0]["quantity"] == 1.5
    assert saved["schedule"][0]["date"] == "2026-09-27"
    assert saved["schedule"][0]["phase"] == "cook"
    with inventory_db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM cook_schedule").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM inventory").fetchone()[0] == 0


def test_editing_missing_packet_does_not_create_one(store):
    with pytest.raises(KeyError):
        store.patch_packet("2026-W40", 1, [])
    with pytest.raises(KeyError):
        store.replace_store_snapshot("2026-W40", 1, {"version": 1})
    assert store.get_packet("2026-W40") is None


def test_retailer_preferences_expose_explicit_policy(store):
    prefs = store.retailer_preferences()
    assert prefs["heb"]["location_id"] == "425"
    assert prefs["costco"]["location_id"] == "681"
    assert prefs["heb"]["policy"]["prefer_owned_brand"] is True
    assert prefs["heb"]["policy"]["reason"] == "cashback"
    assert prefs["costco"]["policy"]["require_bulk_suitability"] is True
    assert prefs["heb"]["preference_rank"] < prefs["costco"]["preference_rank"]
