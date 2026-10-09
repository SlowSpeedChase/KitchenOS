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
                if row['destination_id'] != request.destination_id or request.state == 'archived':
                    tx.execute(
                        "UPDATE apple_items SET state='retired', revision=revision+1 WHERE domain=? AND week=? AND state NOT IN ('retired','history')",
                        (request.domain, request.week),
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
            row['destination_id'] != scope['destination_id'] or
            (row['state'] in {'retired', 'history'} and item.state == 'active')
        )
        if row is None or replacement:
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
        if row['destination_id'] != scope['destination_id'] or row['state'] == 'history':
            raise RevisionConflict('Item is detached')
        if action == 'upsert' and row['state'] != 'active':
            raise RevisionConflict('Item is not exportable')
        if action == 'delete' and row['state'] not in {'retired', 'suppressed'}:
            raise RevisionConflict('Only retired or suppressed items may be deleted')
        operation = AppleOperation(str(uuid4()), item.token, item.generation, item.revision, action,
                                   item.destination_id, item.locator, item.title, item.fields, expected_apple_hash)
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
        _current(tx, row)
        scope = _scope(tx, row['domain'], row['week'])
        if scope['revision'] != operation['scope_revision']:
            raise RevisionConflict('Scope changed since reservation')
        validate_fields(observed_fields, row['domain'])
        ack_payload = canonical_json({'locator': locator.to_dict() if locator else None, 'observed_fields': observed_fields})
        if operation['status'] == 'acknowledged':
            if operation['acknowledged_payload'] != ack_payload or row['revision'] != operation['revision'] + 1:
                raise RevisionConflict('Acknowledgement no longer matches')
            return SyncItem.from_dict(json.loads(operation['result']))
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
            'UPDATE apple_items SET common_payload=?, locator=?, revision=revision+1 WHERE token=?',
            (common, canonical_json(locator.to_dict()) if locator else None, row['token']),
        )
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
