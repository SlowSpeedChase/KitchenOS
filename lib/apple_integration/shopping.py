"""Markdown-authoritative shopping sync; completions never touch inventory.

Recover pending imports before refreshing source snapshots. The file and SQLite
cannot share one transaction: durable patch + exact file images permit replay;
source/file drift leaves a conflict rather than asserting synchronized success.
"""
from __future__ import annotations

import json
from uuid import uuid4

from lib import inventory_db as db, paths
from lib.note_mutation import mutate_note
from lib.safe_paths import shopping_list_path
from lib.shopping_note import _text_identity, read_shopping_note, set_completed
from . import store
from .models import (RevisionConflict, SourceItem, SourceUnavailable, SyncItem,
                     canonical_hash, canonical_json, validate_fields)


def _latest(week):
    latest = {}
    for item in store.list_items(domain='shopping', week=week):
        if item.logical_id not in latest or item.generation > latest[item.logical_id].generation:
            latest[item.logical_id] = item
    return latest


def _demand(snapshot):
    """The exact generated outcome offered by Keep KitchenOS, not edited text."""
    text = snapshot.get('text')
    removed = snapshot.get('retired', False)
    if (not isinstance(text, str) or not text.strip() or '\n' in text or '\r' in text
            or '<!--' in text or type(removed) is not bool):
        raise RevisionConflict('Generated shopping snapshot has no safe resolution target')
    # A visible edit can differ from the generated target, but that target must
    # still describe the ingredient bucket whose stable ID owns this row.
    if not removed and (snapshot.get('identity') != _text_identity(text)
                        or snapshot.get('text_identity') != _text_identity(text)):
        raise RevisionConflict('Generated shopping target changed ingredient identity')
    return {'state': 'removed' if removed else 'active',
            'text': None if removed else text}


def _source(week, row, document, prior=None, due=None):
    snapshot = document.metadata.get('rows', {}).get(row.id, {})
    state = 'conflict' if row.id in document.issues else 'history' if snapshot.get('retired') else 'active'
    fields = {'completed': row.completed, 'due': due}
    values = {'id': row.id, 'title': row.text, 'fields': fields, 'identity': row.identity, 'state': state,
              'shopping_demand': _demand(snapshot) if row.kind == 'gen' else None}
    return SourceItem(row.id, 'shopping', week, row.text, fields, canonical_hash(values), state)


def _record_conflict(item, field, source, snapshot):
    evidence = {**source.to_dict(), 'shopping_demand': _demand(snapshot)}
    payload = canonical_json(evidence)
    with db.write_transaction() as conn:
        # A generated row has one source-review decision, even when an amount
        # edit becomes an ingredient edit. Keep its ID and invalidate old choices
        # through the revision instead of accumulating unresolvable open rows.
        conflicts = conn.execute(
            "SELECT * FROM apple_conflicts WHERE token=? AND status='open' "
            "AND field IN ('shopping_amount_changed','shopping_identity_changed') "
            "ORDER BY created_at,rowid", (item.token,)).fetchall()
        if conflicts:
            current = conflicts[0]
            if current['field'] != field or current['source'] != payload:
                conn.execute('UPDATE apple_conflicts SET field=?,source=?,apple=NULL,revision=revision+1 WHERE conflict_id=?',
                             (field, payload, current['conflict_id']))
            # Repair duplicates already recorded by older code without claiming
            # a user chose an outcome or changing any source/Apple object.
            for stale in conflicts[1:]:
                conn.execute("UPDATE apple_conflicts SET status='resolved',resolution='superseded',revision=revision+1 WHERE conflict_id=?",
                             (stale['conflict_id'],))
                conn.execute("UPDATE apple_resolutions SET status='conflict' WHERE conflict_id=? AND status='pending'",
                             (stale['conflict_id'],))
        else:
            conn.execute('INSERT INTO apple_conflicts(conflict_id,token,field,base,source,apple) VALUES(?,?,?,?,?,?)',
                         (str(uuid4()), item.token, field, canonical_json(item.to_dict()), payload, None))


def prepare_activation(week: str) -> None:
    """Only an explicit activation may generate a missing note or assign IDs."""
    from lib import pantry
    from lib.shopping_list_generator import generate_shopping_list
    from lib.shopping_note import save_shopping_note
    try:
        try:
            document = read_shopping_note(week)
        except FileNotFoundError:
            document = None
        if document is not None and document.metadata and all(row.id for row in document.rows):
            return
        result = generate_shopping_list(week, pantry=pantry.load_pantry())
        if not result['success']:
            raise SourceUnavailable(result.get('error', 'Shopping generation unavailable'))
        lines = result.get('lines') or []
        save_shopping_note(week, lines, result.get('inventory_matches', []),
                           selected_items=None if lines else result.get('purchase_items', result['items']))
    except (OSError, UnicodeError, ValueError, RevisionConflict) as exc:
        raise SourceUnavailable('Shopping note could not be prepared safely') from exc


def _removed_source(item: SyncItem) -> SourceItem:
    completed = item.fields.get('completed') or (item.common_fields or {}).get('completed')
    state = 'history' if completed or item.state == 'history' else 'retired'
    return SourceItem(item.logical_id, 'shopping', item.week, item.title, item.fields,
                      canonical_hash({'id': item.logical_id, 'title': item.title,
                                      'fields': item.fields, 'state': state}), state)


def collect(week: str) -> list[SourceItem]:
    """Read valid notes, retaining removed completion history from the journal."""
    try:
        document = read_shopping_note(week)
        if not document.metadata or any(not row.id for row in document.rows):
            raise RevisionConflict('Shopping note needs explicit identity migration')
        # Validate the complete document before publishing any source/conflict
        # evidence. A malformed later row must not leave a partial review set.
        for row in document.rows:
            if row.kind == 'gen':
                _demand(document.metadata['rows'][row.id])
    except (OSError, UnicodeError, ValueError, RevisionConflict) as exc:
        raise SourceUnavailable('Shopping note is unavailable or unsafe') from exc
    latest = _latest(week)
    sources = []
    for row in document.rows:
        prior = latest.pop(row.id, None)
        # A reappearing row starts a replacement generation; detached metadata
        # must not enter the new source payload before refresh_source creates it.
        due = (store.get_due_override(prior.token)[1]
               if prior and prior.state not in {'retired', 'history'} else None)
        source = _source(week, row, document, prior, due)
        sources.append(source)
        if source.state == 'conflict' and prior:
            _record_conflict(prior, document.issues[row.id], source, document.metadata['rows'][row.id])
    for item in latest.values():
        sources.append(_removed_source(item))
    return sources


def apply(item: SyncItem, patch: dict, operation_id: str) -> SourceItem:
    """Import an exact-ID completion/due patch, with durable interruption replay."""
    validate_fields(patch, 'shopping')
    if item.domain != 'shopping':
        raise RevisionConflict('Not a shopping item')
    journal = store.reserve_source_patch(item, patch, operation_id)
    path = shopping_list_path(paths.shopping_lists_dir(), item.week)
    try:
        with db.connect() as conn:
            edit = conn.execute('SELECT * FROM apple_file_edits WHERE operation_id=?', (operation_id,)).fetchone()
        # Also validates latest generation before any possible file mutation.
        due = store.get_due_override(item.token)[1]
        if journal['status'] == 'applied':
            result = SourceItem.from_dict(json.loads(journal['result']))
            document = read_shopping_note(item.week)
            row = next((r for r in document.rows if r.id == item.logical_id), None)
            if (not edit or document.content_hash != edit['after_hash'] or row is None
                    or _source(item.week, row, document, item, due) != result
                    or store.get_item(item.token).state != 'active'):
                raise RevisionConflict('Applied source operation has since changed')
            return result
        current = store.get_item(item.token)
        if current != item:
            raise RevisionConflict('Sync generation or revision changed before source write')
        document = read_shopping_note(item.week)
        row = next((row for row in document.rows if row.id == item.logical_id), None)
        if row is None or any(not r.id for r in document.rows) or item.logical_id in document.issues:
            raise RevisionConflict('Shopping row is missing, unmigrated, or conflicted')
        if edit:
            # Only an observed before/after image may resume a split transaction.
            if document.content_hash not in {edit['before_hash'], edit['after_hash']}:
                raise RevisionConflict('Source drifted during interrupted patch')
            expected = edit['before_hash']
        else:
            source = _source(item.week, row, document, item, store.get_due_override(item.token)[1])
            if source.source_revision != item.source_revision or source.state != 'active':
                raise RevisionConflict('Shopping source changed')
            expected = document.content_hash
        transform = (lambda text: set_completed(text, item.logical_id, patch['completed'])) if 'completed' in patch else (lambda text: text)
        written_hash = mutate_note(path, expected, transform, operation_id)
        document = read_shopping_note(item.week)
        if document.content_hash != written_hash:
            raise RevisionConflict('Note changed after source write')
        row = next(r for r in document.rows if r.id == item.logical_id)
        with db.write_transaction() as conn:
            # Source stores are not held across file IO or native operations.
            if store.get_item(item.token, conn=conn) != item:
                raise RevisionConflict('Sync revision changed during source write')
            if 'due' in patch:
                store.set_due_override(item.token, patch['due'], expected_revision=item.revision, conn=conn)
            due = store.get_due_override(item.token, conn=conn)[1]
            result = _source(item.week, row, document, item, due)
            store.finish_source_patch(operation_id, result, conn=conn)
        return result
    except (RevisionConflict, OSError, UnicodeError, ValueError) as exc:
        # Transient IO/crashes stay pending. Semantic drift must be resolved.
        if isinstance(exc, (RevisionConflict, UnicodeError, ValueError)):
            store.conflict_source_patch(operation_id)
        raise


def recover_pending() -> list[str]:
    """Replay pending imports before collect/refresh; return conflicting IDs."""
    conflicts = []
    for record in store.pending_source_patches('shopping'):
        try:
            apply(SyncItem.from_dict(json.loads(record['item_payload'])), json.loads(record['patch']), record['operation_id'])
        except (RevisionConflict, ValueError, UnicodeError):
            conflicts.append(record['operation_id'])
    return conflicts


def resolve(item: SyncItem, choice: str, operation_id: str) -> SourceItem | None:
    """Resolve note identity/amount conflicts inside the adapter, by exact hash.

    keep_kitchenos accepts generated quantity and reopens its checkbox; an
    ingredient identity edit restores the recorded ingredient instead.
    keep_manual keeps the visible edited line, under a NEW manual identity.
    Existing Apple objects for that old identity must be detached by the caller.
    """
    from lib import shopping_note as note
    from lib.note_mutation import mutation_lock
    if choice not in {'keep_kitchenos','keep_manual'}:
        raise RevisionConflict('Shopping source conflicts accept keep_kitchenos or keep_manual')
    path=shopping_list_path(paths.shopping_lists_dir(),item.week)
    with mutation_lock(path):
        document=read_shopping_note(item.week)
        row=next((r for r in document.rows if r.id==item.logical_id),None)
        issue=document.issues.get(item.logical_id)
        with db.connect() as conn:
            edit=conn.execute('SELECT * FROM apple_file_edits WHERE operation_id=?',(operation_id,)).fetchone()
        if edit and edit['after_hash']==document.content_hash and store.get_item(item.token)==item:
            if choice=='keep_manual' and row is None:
                return None
            if choice=='keep_kitchenos' and row is None:
                return _removed_source(item)
            if choice=='keep_kitchenos' and row is not None and issue is None:
                return _source(item.week,row,document,item,store.get_due_override(item.token)[1])
        if row is None or issue not in {'shopping_amount_changed','shopping_identity_changed'}:
            raise RevisionConflict('Shopping conflict changed')
        if _source(item.week,row,document,item,store.get_due_override(item.token)[1]).source_revision!=item.source_revision:
            raise RevisionConflict('Shopping source changed before resolution')
        if store.get_item(item.token)!=item:
            raise RevisionConflict('Shopping item changed')
        remove = choice == 'keep_kitchenos' and document.metadata['rows'][item.logical_id].get('retired', False)
        def transform(text):
            doc=note.parse_document(text)
            snap=dict(doc.metadata['rows'][item.logical_id])
            ident=item.logical_id
            replacement=row.text
            completed=row.completed
            if remove:
                del doc.metadata['rows'][item.logical_id]
            elif choice=='keep_manual':
                ident='manual:'+uuid4().hex
                snap={'identity':None,'text':replacement}
                del doc.metadata['rows'][item.logical_id]
            else:
                replacement=snap['text']
                completed=False
                snap.pop('conflict',None);snap.pop('previous_text',None)
                snap.update(text=replacement,text_identity=note._text_identity(replacement),retired=False)
            if not remove:
                doc.metadata['rows'][ident]=snap
            lines=text.splitlines(keepends=True)
            for index,line in enumerate(lines):
                marker=note._MARKER.search(line.rstrip('\r\n'))
                if marker and marker[1]==item.logical_id:
                    if remove:
                        lines[index] = ''
                        continue
                    ending='\r\n' if line.endswith('\r\n') else '\n' if line.endswith('\n') else ''
                    lines[index]=f"- [{'x' if completed else ' '}] {replacement} <!-- kitchenos-item:{ident} -->{ending}"
            return note._METADATA.sub(lambda match:'<!-- kitchenos-shopping-v3:'+note._encode(doc.metadata)+' -->',''.join(lines))
        written=mutate_note(path,document.content_hash,transform,operation_id)
        after=read_shopping_note(item.week)
        if after.content_hash!=written or store.get_item(item.token)!=item:
            raise RevisionConflict('Shopping conflict changed during resolution')
        if choice=='keep_manual':
            return None
        if remove:
            return _removed_source(item)
        changed=next(r for r in after.rows if r.id==item.logical_id)
        return _source(item.week,changed,after,item,store.get_due_override(item.token)[1])
