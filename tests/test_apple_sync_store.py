"""Durable sync uses only real temporary SQLite stores, never Apple stores."""

from dataclasses import replace
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
import sqlite3

import pytest

from lib import inventory_db as db
from lib.apple_integration import store
from lib.apple_integration.models import (
    BridgeContext,
    InvalidPayload,
    Locator,
    OwnershipConflict,
    RevisionConflict,
    ScopeRequest,
    SourceItem,
    canonical_hash,
)

OWNER = "00000000-0000-4000-8000-000000000001"
LOCATOR = Locator("list", "apple-item", None)


def source(**changes):
    values = dict(
        logical_id="shopping-line-1",
        domain="shopping",
        week="2026-W41",
        title="2 limes",
        fields={"completed": False, "due": None},
        source_revision=canonical_hash({"title": "2 limes", "completed": False}),
        state="active",
    )
    values.update(changes)
    return SourceItem(**values)


@pytest.fixture
def active(tmp_db):
    context = store.register_owner(OWNER)
    scope = store.activate_scope("shopping", "2026-W41", "list")
    return context, scope, store.refresh_source(source())


def test_owner_cannot_be_silently_replaced(tmp_db):
    context = store.register_owner(OWNER)
    assert store.register_owner(OWNER) == context
    with pytest.raises(OwnershipConflict):
        store.register_owner(str(uuid4()))


def test_ack_retry_keeps_generation(active):
    context, _, item = active
    operation = store.reserve_operation(item, "upsert", None)
    assert store.reserve_operation(item, "upsert", None) == operation
    assert store.get_item(item.token).common_fields is None
    first = store.acknowledge(context, operation.operation_id, LOCATOR, item.fields)
    second = store.acknowledge(context, operation.operation_id, LOCATOR, item.fields)
    assert first == second
    assert first.generation == item.generation == 1
    assert first.common_fields == {"completed": False, "due": None}
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM apple_operations").fetchone()[0] == 1
    assert store.pending_operations() == []


def test_retry_payload_cannot_change_acknowledged_result(active):
    context, _, item = active
    operation = store.reserve_operation(item, "upsert", None)
    store.acknowledge(context, operation.operation_id, LOCATOR, item.fields)
    with pytest.raises(RevisionConflict):
        store.acknowledge(
            context, operation.operation_id, LOCATOR, {"completed": True, "due": None}
        )


def test_durable_pending_work_reconnects(active):
    _, _, item = active
    operation = store.reserve_operation(item, "upsert", None)
    assert store.pending_operations() == [operation]
    assert (
        store.reserve_operation(store.get_item(item.token), "upsert", None).operation_id
        == operation.operation_id
    )


def test_stale_revision_cannot_ack_or_reserve(active):
    context, _, old = active
    operation = store.reserve_operation(old, "upsert", None)
    updated = store.refresh_source(
        source(title="3 limes", source_revision=canonical_hash("3 limes"))
    )
    assert updated.revision == old.revision + 1
    with pytest.raises(RevisionConflict):
        store.acknowledge(context, operation.operation_id, LOCATOR, old.fields)
    with pytest.raises(RevisionConflict):
        store.reserve_operation(old, "upsert", None)
    assert store.get_item(old.token).common_fields is None


def test_old_owner_generation_rejected(active):
    context, _, item = active
    operation = store.reserve_operation(item, "upsert", None)
    for invalid in [
        BridgeContext(str(uuid4()), context.owner_generation),
        replace(context, owner_generation=2),
    ]:
        with pytest.raises(OwnershipConflict):
            store.acknowledge(invalid, operation.operation_id, LOCATOR, item.fields)


def test_destination_default_change_preserves_generation_but_rejects_old_operation(
    active,
):
    context, scope, item = active
    operation = store.reserve_operation(item, "upsert", None)
    store.activate_scope(
        "shopping", "2026-W41", "other-list", expected_revision=scope["revision"]
    )
    refreshed = store.refresh_source(source())
    assert refreshed.generation == 1 and refreshed.token == item.token
    assert refreshed.destination_id == "list"
    with pytest.raises(RevisionConflict):
        store.acknowledge(context, operation.operation_id, LOCATOR, item.fields)
    new_item = store.refresh_source(source(logical_id="new-row"))
    assert new_item.destination_id == "other-list"


def test_history_is_detached_from_future_mutations(active):
    _, _, item = active
    history = store.refresh_source(source(state="history"))
    assert history.state == "history"
    with pytest.raises(RevisionConflict):
        store.reserve_operation(history, "upsert", None)
    new = store.refresh_source(
        source(title="new limes", source_revision=canonical_hash("new"))
    )
    assert new.generation == 2
    assert store.get_item(item.token).title == "2 limes"


def test_title_override_and_suppression_survive_source_refresh(active):
    _, _, item = active
    override = store.set_title_override(
        item.token, "My limes", expected_revision=item.revision
    )
    store.set_suppressed(item.token, True, expected_revision=override.revision)
    refreshed = store.refresh_source(
        source(title="4 limes", source_revision=canonical_hash("4"))
    )
    assert refreshed.title == "My limes" and refreshed.state == "suppressed"
    assert refreshed.fields == {"completed": False, "due": None}
    with db.connect() as conn:
        assert (
            "4 limes"
            in conn.execute(
                "SELECT source_payload FROM apple_items WHERE token=?", (item.token,)
            ).fetchone()[0]
        )
    with pytest.raises(RevisionConflict):
        store.reserve_operation(refreshed, "upsert", None)


def test_borrowed_transaction_rolls_back_whole_group(tmp_db):
    with pytest.raises(RuntimeError):
        with db.write_transaction() as conn:
            store.register_owner(OWNER, conn=conn)
            store.activate_scope("shopping", "2026-W41", "list", conn=conn)
            store.refresh_source(source(), conn=conn)
            raise RuntimeError("crash")
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM apple_bridge").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM apple_items").fetchone()[0] == 0


def test_concurrent_scope_writers_reject_stale_revision(active):
    _, scope, _ = active

    def write(destination):
        try:
            return store.activate_scope(
                "shopping", "2026-W41", destination, expected_revision=scope["revision"]
            )
        except RevisionConflict:
            return "stale"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(write, ["a", "b"]))
    assert results.count("stale") == 1
    with db.connect() as conn:
        assert conn.execute("SELECT revision FROM apple_scopes").fetchone()[0] == 2


def test_paused_scope_refuses_new_work(active):
    _, scope, item = active
    store.update_scope(
        ScopeRequest("shopping", "2026-W41", "list", "paused", scope["revision"])
    )
    with pytest.raises(RevisionConflict):
        store.reserve_operation(item, "upsert", None)


@pytest.mark.parametrize(
    "changes",
    [
        {"domain": "unknown"},
        {"week": "2026-W99"},
        {"fields": {"completed": "true"}},
        {"source_revision": "mtime:123"},
        {"fields": {"start": "2026-10-08T12:00:00+00:00"}},
    ],
)
def test_source_validation_before_db_write(active, changes):
    with pytest.raises(InvalidPayload):
        store.refresh_source(source(**changes))
    assert len(store.list_items()) == 1


def test_ack_locator_must_match_reserved_destination(active):
    context, _, item = active
    operation = store.reserve_operation(item, "upsert", None)
    with pytest.raises(OwnershipConflict):
        store.acknowledge(
            context,
            operation.operation_id,
            Locator("stranger-list", "item", None),
            item.fields,
        )
    assert store.get_item(item.token).common_fields is None


def test_ack_drift_cannot_advance_common(active):
    context, _, item = active
    operation = store.reserve_operation(item, "upsert", None)
    with pytest.raises(RevisionConflict):
        store.acknowledge(
            context, operation.operation_id, LOCATOR, {"completed": True, "due": None}
        )
    assert store.get_item(item.token).common_fields is None
    assert store.pending_operations() == [operation]


def test_reserved_payload_is_a_copy_not_mutable_callers_dict(active):
    _, _, item = active
    store.reserve_operation(item, "upsert", None)
    item.fields["completed"] = True
    assert store.pending_operations()[0].fields == {"completed": False, "due": None}
    assert store.get_item(item.token).fields == {"completed": False, "due": None}


def test_retirement_deletion_keeps_journal_and_can_be_retried(active):
    context, _, item = active
    saved = store.acknowledge(
        context,
        store.reserve_operation(item, "upsert", None).operation_id,
        LOCATOR,
        item.fields,
    )
    retired = store.refresh_source(source(state="retired"))
    operation = store.reserve_operation(retired, "delete", canonical_hash(saved.fields))
    deleted = store.acknowledge(context, operation.operation_id, None, {})
    assert (
        deleted.locator is None
        and deleted.common_fields is None
        and deleted.state == "retired"
    )
    assert store.acknowledge(context, operation.operation_id, None, {}) == deleted
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM apple_items").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM apple_operations").fetchone()[0] == 2


def test_concurrent_reservations_reuse_single_uuid(active):
    _, _, item = active
    with ThreadPoolExecutor(max_workers=2) as executor:
        reserved = list(
            executor.map(
                lambda _: store.reserve_operation(item, "upsert", None), range(2)
            )
        )
    assert reserved[0].operation_id == reserved[1].operation_id
    assert len(store.pending_operations()) == 1


def test_stale_nested_mutation_rolls_back_metadata_and_scope(active):
    _, scope, item = active
    with pytest.raises(RevisionConflict):
        with db.write_transaction() as conn:
            store.set_title_override(
                item.token, "Changed", expected_revision=item.revision, conn=conn
            )
            store.activate_scope(
                "shopping", "2026-W41", "different", expected_revision=99, conn=conn
            )
    assert store.get_item(item.token) == item
    assert store.activate_scope("shopping", "2026-W41", "list") == scope


def test_file_edit_and_conflict_journals_survive_reconnect(active):
    _, _, item = active
    operation_id = str(uuid4())
    with db.write_transaction() as conn:
        conn.execute(
            "INSERT INTO apple_file_edits(operation_id,path,before_hash,after_hash,before_text,after_text,status) VALUES(?,?,?,?,?,?,?)",
            (
                operation_id,
                "/isolated/shopping.md",
                canonical_hash("before"),
                canonical_hash("after"),
                "before",
                "after",
                "pending",
            ),
        )
        conn.execute(
            "INSERT INTO apple_conflicts(conflict_id,token,field,base,source,apple) VALUES(?,?,?,?,?,?)",
            (str(uuid4()), item.token, "due", "null", '"2026-10-08"', '"2026-10-09"'),
        )
    with db.connect() as conn:
        journal = conn.execute("SELECT * FROM apple_file_edits").fetchone()
        assert (
            journal["status"] == "pending"
            and journal["before_text"] == "before"
            and journal["after_text"] == "after"
        )
        assert (
            conn.execute("SELECT status FROM apple_conflicts").fetchone()[0] == "open"
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO apple_file_edits SELECT * FROM apple_file_edits")


def test_reappearing_source_supersedes_pending_old_generation_deletion(active):
    """A replaced generation must not leave unacknowledgeable pending work."""
    context, _, original = active
    export = store.reserve_operation(original, "upsert", None)
    saved = store.acknowledge(context, export.operation_id, LOCATOR, original.fields)
    retired = store.refresh_source(source(state="retired"))
    deletion = store.reserve_operation(retired, "delete", canonical_hash(saved.fields))
    assert store.pending_operations() == [deletion]

    replacement = store.refresh_source(source())
    assert replacement.generation == original.generation + 1
    assert replacement.token != original.token
    assert store.pending_operations() == []
    with db.connect() as conn:
        assert (
            conn.execute(
                "SELECT status FROM apple_operations WHERE operation_id=?",
                (deletion.operation_id,),
            ).fetchone()[0]
            == "superseded"
        )
    assert store.get_item(original.token).locator == LOCATOR
    with pytest.raises(RevisionConflict):
        store.acknowledge(context, deletion.operation_id, None, {})
    # A previously committed exact save is an inert retry even after the source
    # generation changes; altered callback evidence must still be rejected.
    assert (
        store.acknowledge(context, export.operation_id, LOCATOR, original.fields)
        == saved
    )
    with pytest.raises(RevisionConflict):
        store.acknowledge(
            context, export.operation_id, LOCATOR, {"completed": True, "due": None}
        )
    assert store.get_item(replacement.token) == replacement

    new_export = store.reserve_operation(replacement, "upsert", None)
    assert store.reserve_operation(replacement, "upsert", None) == new_export
    assert store.pending_operations() == [new_export]
    new_locator = Locator("list", "replacement-item", None)
    new_saved = store.acknowledge(
        context, new_export.operation_id, new_locator, replacement.fields
    )
    assert (
        store.acknowledge(
            context, new_export.operation_id, new_locator, replacement.fields
        )
        == new_saved
    )
    assert new_saved.generation == replacement.generation
    assert store.pending_operations() == []
