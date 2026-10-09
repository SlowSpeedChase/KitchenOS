"""SQLite sync journal. Transactions end before any external/native work.

All mutations may borrow an existing ``write_transaction`` through ``conn``.
Source/common/operation payloads are separate: a reservation is never delivery.
Old generations remain addressable but cannot accept replacement callbacks.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
from uuid import uuid4

from lib import inventory_db as db
from .models import (
    AppleOperation, BridgeContext, InvalidPayload, Locator, OwnershipConflict,
    RevisionConflict, ScopeRequest, SourceItem, SourceUnavailable, SyncItem,
    canonical_json, validate_fields, validate_scope,
)


@contextmanager
def _read(conn=None):
    if conn is not None:
        yield conn
    else:
        owned = db.connect()
        try:
            yield owned
        finally:
            owned.close()


def _item(row) -> SyncItem:
    payload = json.loads(row['source_payload'])
    payload.update(
        title=row['title_override'] if row['title_override'] is not None else payload['title'],
        state=row['state'], revision=row['revision'], generation=row['generation'],
        token=row['token'], destination_id=row['destination_id'],
        locator=json.loads(row['locator']) if row['locator'] else None,
        common_fields=json.loads(row['common_payload']) if row['common_payload'] else None,
    )
    return SyncItem.from_dict(payload)


def _row(conn, token):
    row = conn.execute('SELECT * FROM apple_items WHERE token=?', (token,)).fetchone()
    if row is None:
        raise RevisionConflict('Unknown item token')
    return row


def _current(conn, row):
    generation = conn.execute(
        'SELECT MAX(generation) FROM apple_items WHERE domain=? AND week=? AND logical_id=?',
        (row['domain'], row['week'], row['logical_id']),
    ).fetchone()[0]
    if row['generation'] != generation:
        raise RevisionConflict('Item generation was replaced')


def _bridge(conn):
    row = conn.execute('SELECT * FROM apple_bridge WHERE id=1').fetchone()
    if row is None:
        raise OwnershipConflict('No designated Mac')
    if not row['connected']:
        raise OwnershipConflict('Bridge is disconnected')
    if row['paused']:
        raise OwnershipConflict('Bridge is paused')
    return row


def _scope(conn, domain, week):
    row = conn.execute('SELECT * FROM apple_scopes WHERE domain=? AND week=?', (domain, week)).fetchone()
    if row is None or row['status'] != 'active':
        raise RevisionConflict('Scope is not active')
    return row


def _supersede(conn, token):
    conn.execute("UPDATE apple_operations SET status='superseded' WHERE token=? AND status='pending'", (token,))


def register_owner(owner_id: str, *, conn=None) -> BridgeContext:
    context = BridgeContext(owner_id, 1)
    with db.write_transaction(conn) as tx:
        row = tx.execute('SELECT * FROM apple_bridge WHERE id=1').fetchone()
        if row is None:
            tx.execute('INSERT INTO apple_bridge(id, owner_id, owner_generation) VALUES(1, ?, 1)', (owner_id,))
        elif not row['connected']:
            tx.execute('UPDATE apple_bridge SET owner_id=?, connected=1, revision=revision+1 WHERE id=1', (owner_id,))
            context = BridgeContext(owner_id, row['owner_generation'])
        elif row['owner_id'] != owner_id:
            raise OwnershipConflict('Another Mac already owns the integration')
        else:
            context = BridgeContext(owner_id, row['owner_generation'])
        return context


def activate_scope(domain: str, week: str, destination_id: str, *, expected_revision: int | None = None, conn=None) -> dict:
    """Create a scope or explicitly compare-and-set an existing destination."""
    validate_scope(domain, week)
    with db.write_transaction(conn) as tx:
        existing = tx.execute('SELECT * FROM apple_scopes WHERE domain=? AND week=?', (domain, week)).fetchone()
        if expected_revision is None:
            if existing and (existing['destination_id'] != destination_id or existing['status'] != 'active'):
                raise RevisionConflict('Changing a scope requires expected_revision')
            expected_revision = existing['revision'] if existing else 0
        return update_scope(ScopeRequest(domain, week, destination_id, 'active', expected_revision), conn=tx)


def update_scope(request: ScopeRequest, *, conn=None) -> dict:
    with db.write_transaction(conn) as tx:
        _bridge(tx)
        row = tx.execute('SELECT * FROM apple_scopes WHERE domain=? AND week=?', (request.domain, request.week)).fetchone()
        if (row['revision'] if row else 0) != request.expected_revision:
            raise RevisionConflict('Scope revision changed')
        unchanged = row and row['destination_id'] == request.destination_id and row['status'] == request.state
        if not unchanged:
            tx.execute(
                'INSERT INTO apple_scopes(domain, week, destination_id, status, revision) VALUES(?,?,?,?,?) '
                'ON CONFLICT(domain, week) DO UPDATE SET destination_id=excluded.destination_id, status=excluded.status, revision=excluded.revision',
                (request.domain, request.week, request.destination_id, request.state, request.expected_revision + 1),
            )
            if row:
                tx.execute(
                    "UPDATE apple_operations SET status='superseded' WHERE status='pending' AND token IN "
                    '(SELECT token FROM apple_items WHERE domain=? AND week=?)', (request.domain, request.week),
                )
        return dict(tx.execute('SELECT * FROM apple_scopes WHERE domain=? AND week=?', (request.domain, request.week)).fetchone())


def refresh_source(item: SourceItem, *, conn=None) -> SyncItem:
    # Revalidate mutable nested dicts even if the caller constructed this earlier.
    item = SourceItem.from_dict(item.to_dict())
    with db.write_transaction(conn) as tx:
        _bridge(tx)
        scope = _scope(tx, item.domain, item.week)
        row = tx.execute(
            'SELECT * FROM apple_items WHERE domain=? AND week=? AND logical_id=? ORDER BY generation DESC LIMIT 1',
            (item.domain, item.week, item.logical_id),
        ).fetchone()
        replacement = row is not None and (
            (row['state'] in {'retired', 'history'} and item.state == 'active')
        )
        if row is None or replacement:
            if replacement:
                # Once replaced, this generation cannot acknowledge any work.
                # Retain its journal, but stop returning those operations forever.
                _supersede(tx, row['token'])
            token = str(uuid4())
            tx.execute(
                'INSERT INTO apple_items(token, logical_id, domain, week, generation, destination_id, source_payload, state, revision) VALUES(?,?,?,?,?,?,?,?,1)',
                (token, item.logical_id, item.domain, item.week, row['generation'] + 1 if row else 1,
                 scope['destination_id'], canonical_json(item.to_dict()), item.state),
            )
            return _item(_row(tx, token))
        if row['state'] == 'history':
            return _item(row)
        payload = canonical_json(item.to_dict())
        state = 'suppressed' if row['suppressed'] and item.state == 'active' else item.state
        if payload != row['source_payload'] or state != row['state']:
            tx.execute('UPDATE apple_items SET source_payload=?, state=?, revision=revision+1 WHERE token=?', (payload, state, row['token']))
            _supersede(tx, row['token'])
        return _item(_row(tx, row['token']))


def get_item(token: str, *, conn=None) -> SyncItem:
    with _read(conn) as tx:
        return _item(_row(tx, token))


def list_items(*, domain: str | None = None, week: str | None = None, conn=None) -> list[SyncItem]:
    """Return retained generations too; consumers must inspect state/generation."""
    with _read(conn) as tx:
        return [_item(r) for r in tx.execute(
            'SELECT * FROM apple_items WHERE (? IS NULL OR domain=?) AND (? IS NULL OR week=?) ORDER BY domain, week, logical_id, generation',
            (domain, domain, week, week),
        )]


def pending_operations(*, conn=None) -> list[AppleOperation]:
    with _read(conn) as tx:
        rows = tx.execute("SELECT payload FROM apple_operations WHERE status='pending' ORDER BY created_at, operation_id")
        return [AppleOperation.from_dict(json.loads(r['payload'])) for r in rows]


def reserve_operation(item: SyncItem, action: str, expected_apple_hash: str | None, *, conn=None) -> AppleOperation:
    with db.write_transaction(conn) as tx:
        owner = _bridge(tx)
        row = _row(tx, item.token)
        _current(tx, row)
        current = _item(row)
        if current != item:
            raise RevisionConflict('Item snapshot changed')
        scope = _scope(tx, row['domain'], row['week'])
        if row['state'] == 'history':
            raise RevisionConflict('Item is detached')
        if action == 'upsert' and row['state'] != 'active':
            raise RevisionConflict('Item is not exportable')
        if action == 'delete' and row['state'] not in {'retired', 'suppressed'}:
            raise RevisionConflict('Only retired or suppressed items may be deleted')
        operation = AppleOperation(str(uuid4()), item.token, item.generation, item.revision, action,
                                   item.locator.calendar_id if item.locator else item.destination_id, item.locator, item.title, item.fields, expected_apple_hash)
        existing = tx.execute(
            "SELECT payload FROM apple_operations WHERE token=? AND generation=? AND revision=? AND action=? AND expected_apple_hash IS ? AND status='pending'",
            (item.token, item.generation, item.revision, action, expected_apple_hash),
        ).fetchone()
        if existing:
            return AppleOperation.from_dict(json.loads(existing['payload']))
        tx.execute(
            'INSERT INTO apple_operations(operation_id, token, generation, revision, owner_id, owner_generation, scope_revision, action, expected_apple_hash, payload, status) '
            "VALUES(?,?,?,?,?,?,?,?,?,?,'pending')",
            (operation.operation_id, item.token, item.generation, item.revision, owner['owner_id'], owner['owner_generation'], scope['revision'], action, expected_apple_hash, canonical_json(operation.to_dict())),
        )
        return operation


def acknowledge(context: BridgeContext, operation_id: str, locator: Locator | None, observed_fields: dict, *, conn=None) -> SyncItem:
    """Commit only an unchanged reservation; identical callback retries are inert.

    This low-level helper handles saved/deleted outcomes. The service handles
    changed/failed outcomes without calling it, preserving the common snapshot.
    """
    context = BridgeContext.from_dict(context.to_dict())
    if isinstance(locator, dict):
        locator = Locator.from_dict(locator)
    if locator is not None and not isinstance(locator, Locator):
        raise InvalidPayload('Invalid locator')
    with db.write_transaction(conn) as tx:
        owner = _bridge(tx)
        if context.owner_id != owner['owner_id'] or context.owner_generation != owner['owner_generation']:
            raise OwnershipConflict('Stale bridge owner')
        operation = tx.execute('SELECT * FROM apple_operations WHERE operation_id=?', (operation_id,)).fetchone()
        if operation is None:
            raise RevisionConflict('Unknown operation')
        if operation['owner_id'] != context.owner_id or operation['owner_generation'] != context.owner_generation:
            raise OwnershipConflict('Operation belongs to an older owner')
        row = _row(tx, operation['token'])
        validate_fields(observed_fields, row['domain'])
        ack_payload = canonical_json({'locator': locator.to_dict() if locator else None, 'observed_fields': observed_fields})
        if operation['status'] == 'acknowledged':
            if operation['acknowledged_payload'] != ack_payload or not operation['result']:
                raise RevisionConflict('Acknowledgement no longer matches')
            return SyncItem.from_dict(json.loads(operation['result']))
        if not operation['retained_cleanup']:
            _current(tx, row)
            scope = _scope(tx, row['domain'], row['week'])
        else:
            scope = tx.execute('SELECT * FROM apple_scopes WHERE domain=? AND week=?', (row['domain'],row['week'])).fetchone()
        if scope['revision'] != operation['scope_revision']:
            raise RevisionConflict('Scope changed since reservation')
        if operation['status'] != 'pending' or row['revision'] != operation['revision'] or row['generation'] != operation['generation']:
            raise RevisionConflict('Stale operation')
        payload = AppleOperation.from_dict(json.loads(operation['payload']))
        if payload.action == 'upsert':
            if locator is None or locator.calendar_id != payload.destination_id:
                raise OwnershipConflict('Saved item must be in its owned destination')
            if observed_fields != payload.fields:
                raise RevisionConflict('Observed Apple fields changed')
            common = canonical_json(observed_fields)
        else:
            if locator is not None or observed_fields:
                raise InvalidPayload('Deleted acknowledgement must have no locator or fields')
            common = None
        tx.execute(
            'UPDATE apple_items SET common_payload=?, locator=?, common_title=?, revision=revision+1 WHERE token=?',
            (common, canonical_json(locator.to_dict()) if locator else None, payload.title if payload.action == 'upsert' else None, row['token']),
        )
        if operation['retained_cleanup']:
            tx.execute("UPDATE apple_items SET suppressed=1,state=CASE WHEN state='active' THEN 'suppressed' ELSE state END WHERE token=?",(row['token'],))
            tx.execute("UPDATE apple_conflicts SET status='resolved',resolution='remove_owned' WHERE token=? AND status='open'",(row['token'],))
        result = _item(_row(tx, row['token']))
        tx.execute(
            "UPDATE apple_operations SET status='acknowledged', result=?, acknowledged_payload=? WHERE operation_id=?",
            (canonical_json(result.to_dict()), ack_payload, operation_id),
        )
        _supersede(tx, row['token'])
        return result


def _edit_metadata(token, expected_revision, *, title_override=None, suppressed=None, conn=None):
    with db.write_transaction(conn) as tx:
        row = _row(tx, token)
        _current(tx, row)
        if row['revision'] != expected_revision or row['state'] in {'retired', 'history'}:
            raise RevisionConflict('Item is stale or detached')
        if suppressed is None:
            tx.execute('UPDATE apple_items SET title_override=?, revision=revision+1 WHERE token=?', (title_override, token))
        else:
            state = 'suppressed' if suppressed else json.loads(row['source_payload'])['state']
            tx.execute('UPDATE apple_items SET suppressed=?, state=?, revision=revision+1 WHERE token=?', (int(suppressed), state, token))
        _supersede(tx, token)
        return _item(_row(tx, token))


def set_title_override(token: str, title: str | None, *, expected_revision: int, conn=None) -> SyncItem:
    """Native title preference is independent of authoritative source content."""
    if title is not None and (not isinstance(title, str) or not title.strip()):
        raise InvalidPayload('Title override must be nonempty or null')
    return _edit_metadata(token, expected_revision, title_override=title, conn=conn)


def set_suppressed(token: str, suppressed: bool, *, expected_revision: int, conn=None) -> SyncItem:
    if type(suppressed) is not bool:
        raise InvalidPayload('suppressed must be boolean')
    return _edit_metadata(token, expected_revision, suppressed=suppressed, conn=conn)


def get_due_override(token: str, *, conn=None) -> tuple[bool, dict | None]:
    """Return (is_set, due); SQL NULL is unset, JSON null explicitly clears."""
    with _read(conn) as tx:
        row = _row(tx, token)
        _current(tx, row)
        value = row['due_override']
        return (value is not None, json.loads(value) if value is not None else None)


def set_due_override(token: str, due: dict | None, *, expected_revision: int, conn=None) -> SyncItem:
    """Set latest-generation reminder metadata with compare-and-set semantics.

    The returned item has the new journal revision; adapters must collect and
    refresh_source to update its source payload/revision with the effective due.
    """
    validate_fields({'due': due}, 'shopping')
    with db.write_transaction(conn) as tx:
        row = _row(tx, token)
        _current(tx, row)
        if row['domain'] not in {'shopping', 'prep'} or row['revision'] != expected_revision or row['state'] in {'retired', 'history'}:
            raise RevisionConflict('Due override item changed or is detached')
        tx.execute('UPDATE apple_items SET due_override=?, revision=revision+1 WHERE token=?',
                   (canonical_json(due), token))
        _supersede(tx, token)
        return _item(_row(tx, token))


def reserve_source_patch(item: SyncItem, patch: dict, operation_id: str, *, conn=None) -> dict:
    """Persist the entire retry contract before a source adapter touches a file."""
    # Explicit Calendar absence is lifecycle control, never a wire field.
    if not (item.domain == 'cooking' and patch == {'unscheduled': True}
            and type(patch['unscheduled']) is bool):
        validate_fields(patch, item.domain)
    if not isinstance(operation_id, str) or not operation_id or len(operation_id) > 128:
        raise InvalidPayload('Invalid operation ID')
    with db.write_transaction(conn) as tx:
        _bridge(tx)
        scope = _scope(tx, item.domain, item.week)
        old = tx.execute('SELECT * FROM apple_source_patches WHERE operation_id=?', (operation_id,)).fetchone()
        if old:
            if old['item_payload'] != canonical_json(item.to_dict()) or old['patch'] != canonical_json(patch) or old['status'] == 'conflict':
                raise RevisionConflict('Source operation payload changed or conflicted')
            return dict(old)
        row = _row(tx, item.token)
        _current(tx, row)
        if _item(row) != item or row['state'] != 'active':
            raise RevisionConflict('Source patch item changed or is inactive')
        # Do not allow a second import to interleave a pending file/DB update.
        if tx.execute("SELECT 1 FROM apple_source_patches WHERE token=? AND status='pending'", (item.token,)).fetchone():
            raise RevisionConflict('A source patch is awaiting recovery')
        tx.execute("INSERT INTO apple_source_patches(operation_id,token,domain,expected_revision,item_payload,patch,status) VALUES(?,?,?,?,?,?,'pending')",
                   (operation_id, item.token, item.domain, item.revision, canonical_json(item.to_dict()), canonical_json(patch)))
        return dict(tx.execute('SELECT * FROM apple_source_patches WHERE operation_id=?', (operation_id,)).fetchone())


def pending_source_patches(domain: str, *, conn=None) -> list[dict]:
    """Adapters recover these before the service refreshes any source snapshots."""
    with _read(conn) as tx:
        return [dict(row) for row in tx.execute("SELECT * FROM apple_source_patches WHERE domain=? AND status='pending' ORDER BY created_at,rowid", (domain,))]


def finish_source_patch(operation_id: str, result: SourceItem, *, conn=None) -> None:
    """Commit with the override transaction; pending alone is never delivery."""
    with db.write_transaction(conn) as tx:
        changed = tx.execute("UPDATE apple_source_patches SET status='applied', result=? WHERE operation_id=? AND status='pending'",
                             (canonical_json(result.to_dict()), operation_id)).rowcount
        if changed != 1:
            raise RevisionConflict('Source patch is not pending')


def conflict_source_patch(operation_id: str, *, conn=None) -> None:
    with db.write_transaction(conn) as tx:
        tx.execute("UPDATE apple_source_patches SET status='conflict' WHERE operation_id=? AND status='pending'", (operation_id,))


def reserve_cleanup(item: SyncItem, expected_apple_hash: str, *, conn=None) -> AppleOperation:
    """Explicit per-object deletion, including retained generations; no adoption.

    Separate from ordinary lifecycle work: its callback can clear only this row,
    even when a newer generation exists. The service validates fresh observation.
    """
    with db.write_transaction(conn) as tx:
        owner = _bridge(tx)
        if get_item(item.token, conn=tx) != item or item.locator is None:
            raise RevisionConflict('Cleanup snapshot changed or has no owned locator')
        scope = tx.execute('SELECT * FROM apple_scopes WHERE domain=? AND week=?', (item.domain,item.week)).fetchone()
        old=tx.execute("SELECT payload FROM apple_operations WHERE token=? AND revision=? AND expected_apple_hash=? AND retained_cleanup=1 AND status='pending'",(item.token,item.revision,expected_apple_hash)).fetchone()
        if old:
            return AppleOperation.from_dict(json.loads(old['payload']))
        _supersede(tx,item.token)
        operation=AppleOperation(str(uuid4()),item.token,item.generation,item.revision,'delete',item.locator.calendar_id,item.locator,item.title,item.fields,expected_apple_hash)
        tx.execute("INSERT INTO apple_operations(operation_id,token,generation,revision,owner_id,owner_generation,scope_revision,action,expected_apple_hash,payload,status,retained_cleanup) VALUES(?,?,?,?,?,?,?,'delete',?,?,'pending',1)",(operation.operation_id,item.token,item.generation,item.revision,owner['owner_id'],owner['owner_generation'],scope['revision'],expected_apple_hash,canonical_json(operation.to_dict())))
        return operation
