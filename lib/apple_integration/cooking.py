"""Calendar writeback through the serving ledger's single scheduling authority.

A confirmed event deletion is apply(..., {'unscheduled': True}, ...). That
control is never a SourceItem/wire field. Borrowers must commit then call
recover_pending; owned calls render committed views before returning success.
"""

from __future__ import annotations

from datetime import datetime
import json
import re
from zoneinfo import ZoneInfo

from lib import inventory_db as db, serving_ledger as sl
from . import store
from .models import (
    InvalidPayload,
    RevisionConflict,
    SourceItem,
    SyncItem,
    canonical_hash,
    validate_fields,
    validate_scope,
)


def _cook_id(logical_id):
    if not re.fullmatch(r"cook:[1-9][0-9]*", logical_id):
        raise RevisionConflict("Invalid cooking identity")
    return int(logical_id[5:])


def _source(conn, cook_id, week, prior=None):
    row = conn.execute(
        "SELECT * FROM cooks WHERE id=? AND week=?", (cook_id, week)
    ).fetchone()
    schedule = conn.execute(
        "SELECT * FROM cook_schedule WHERE cook_id=?", (cook_id,)
    ).fetchone()
    placements = [
        dict(p)
        for p in conn.execute(
            "SELECT * FROM placements WHERE cook_id=? ORDER BY id", (cook_id,)
        )
    ]
    # A new eligible schedule replaces detached history; cooked rows stay frozen.
    state = (
        "history"
        if row and row["cooked_at"]
        else "active"
        if row and schedule and not row["bundle_id"]
        else "history"
        if prior and prior.state == "history"
        else "retired"
    )
    fields = (
        {k: schedule[k] for k in ("start", "timezone", "duration_minutes")}
        if schedule
        else {}
    )
    if state != "active" and prior:
        fields = dict(prior.fields)
    title = row["recipe"] if row else prior.title
    values = {
        "cook": dict(row) if row else None,
        "schedule": dict(schedule) if schedule else None,
        "placements": placements,
        "state": state,
        "fields": fields,
    }
    return SourceItem(
        f"cook:{cook_id}", "cooking", week, title, fields, canonical_hash(values), state
    )


def collect(week: str) -> list[SourceItem]:
    """Export scheduled rows only; retain removed/cooked exported identities."""
    validate_scope("cooking", week)
    conn = db.connect()
    try:
        conn.execute("BEGIN")  # One coherent snapshot across ledger and journal.
        latest = {
            i.logical_id: i
            for i in store.list_items(domain="cooking", week=week, conn=conn)
        }
        ids = {
            r["id"]
            for r in conn.execute(
                "SELECT c.id FROM cooks c JOIN cook_schedule s ON s.cook_id=c.id WHERE c.week=?",
                (week,),
            )
        }
        ids.update(_cook_id(key) for key in latest)
        return [
            _source(conn, cid, week, latest.get(f"cook:{cid}")) for cid in sorted(ids)
        ]
    finally:
        conn.close()


def apply(item: SyncItem, patch: dict, operation_id: str, *, conn=None) -> SourceItem:
    """CAS source, ledger and bridge journal atomically under BEGIN IMMEDIATE.

    IO failure after commit raises with the view job durable. Retry the exact
    operation/payload or recover_pending. No external/native work occurs here.
    """
    if item.domain != "cooking":
        raise RevisionConflict("Not a cooking item")
    cook_id = _cook_id(item.logical_id)
    deleting = patch == {"unscheduled": True} and type(patch.get("unscheduled")) is bool
    try:
        if not deleting:
            validate_fields(patch, "cooking")
            if not patch:
                raise InvalidPayload("Empty Calendar edit")
    except (ValueError, TypeError) as exc:
        raise RevisionConflict("Unsupported Calendar edit") from exc
    borrowed = conn is not None
    with db.write_transaction(conn) as tx:
        current = _source(tx, cook_id, item.week, item)
        journal = store.reserve_source_patch(item, patch, operation_id, conn=tx)
        live = store.get_item(item.token, conn=tx)
        # An exact retry may follow refresh_source's revision advance, but not
        # generation replacement, ordinary edits, or a different source result.
        latest = [
            i
            for i in store.list_items(domain="cooking", week=item.week, conn=tx)
            if i.logical_id == item.logical_id
        ][-1]
        if latest.token != item.token:
            raise RevisionConflict("Cooking generation replaced")
        if journal["status"] == "applied":
            result = SourceItem.from_dict(json.loads(journal["result"]))
            if (
                current.source_revision != result.source_revision
                or live.source_revision != result.source_revision
            ):
                raise RevisionConflict("Finished cooking operation has drifted")
        else:
            if (
                live != item
                or current.state != "active"
                or current.source_revision != item.source_revision
            ):
                raise RevisionConflict("Cooking source changed")
            if deleting:
                sl.unschedule_cook(cook_id, conn=tx)
            else:
                fields = dict(current.fields, **patch)
                try:
                    # Apple supplies an instant; the IANA zone supplies its local
                    # date and offset, including each side of a DST fold/gap.
                    local = datetime.fromisoformat(fields["start"]).astimezone(
                        ZoneInfo(fields["timezone"])
                    )
                    row = tx.execute(
                        "SELECT meal FROM cooks WHERE id=?", (cook_id,)
                    ).fetchone()
                    sl.schedule_cook(
                        cook_id,
                        date=local.date().isoformat(),
                        meal=row["meal"],
                        start=local.isoformat(),
                        timezone=fields["timezone"],
                        duration_minutes=fields["duration_minutes"],
                        servings_to_eat=1,
                        conn=tx,
                    )
                except (ValueError, TypeError) as exc:
                    raise RevisionConflict(
                        "Calendar time violates cooking constraints"
                    ) from exc
            result = _source(tx, cook_id, item.week, item)
            store.refresh_source(result, conn=tx)
            store.finish_source_patch(operation_id, result, conn=tx)
    if not borrowed:
        recover_pending()
    return result


def recover_pending() -> list[str]:
    """Drain committed view work before refresh/export; transient IO propagates.

    Cooking source mutations and their applied journals commit together, so
    there is no half-applied source patch to replay. The only crash boundary is
    DB commit -> generated Markdown. Pending week revisions survive that gap.
    Borrowers call this only after their outer transaction has committed.
    """
    sl.drain_schedule_views()
    return []
