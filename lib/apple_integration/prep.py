"""Fresh-cache-only prep sync with recoverable exact-ID completion imports.

The service must recover_pending before collecting/refreshing sources. Due
changes are journal metadata only: they never move cooks, plans or task IDs.
"""
from __future__ import annotations

from datetime import date
import json

from lib import inventory_db as db, task_extractor
from lib.note_mutation import content_hash, mutate_note, mutation_lock
from . import store
from .models import (RevisionConflict, SourceItem, SourceUnavailable, SyncItem,
                     canonical_hash, validate_fields, validate_scope)

_WEEKDAYS = ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')


def _read(week: str) -> tuple[dict, str]:
    """Read an unambiguous fresh sidecar, never triggering inference on polling."""
    validate_scope('prep', week)
    path = task_extractor._sidecar_path(week)
    text = path.read_bytes().decode('utf-8')
    payload = json.loads(text)
    if (not isinstance(payload, dict) or payload.get('week') != week
            or not isinstance(payload.get('tasks'), list)
            or not task_extractor._is_cache_fresh(week, payload)):
        raise SourceUnavailable('Prep tasks need explicit refresh')
    seen = set()
    for task in payload['tasks']:
        if (not isinstance(task, dict) or not isinstance(task.get('id'), str)
                or not task['id'] or task['id'] in seen
                or not isinstance(task.get('recipe'), str) or not task['recipe'].strip()
                or not isinstance(task.get('text'), str) or not task['text'].strip()
                or not isinstance(task.get('day'), str)
                or not isinstance(task.get('slot'), str) or not task['slot'].strip()
                or type(task.get('step')) is not int or task['step'] < 0
                or type(task.get('done', False)) is not bool
                or task['id'] != task_extractor._stable_task_id(task['recipe'], task['day'], task['slot'], task['step'])):
            raise SourceUnavailable('Prep task identity is unsafe')
        seen.add(task['id'])
    return payload, content_hash(text)


def _initial_due(week, task):
    if task.get('day') not in _WEEKDAYS:
        return None
    actual = date.fromisocalendar(int(week[:4]), int(week[-2:]), _WEEKDAYS.index(task['day']) + 1)
    return {'date': actual.isoformat(), 'time': None, 'timezone': None}


def _effective_due(week, task, prior=None, *, conn=None):
    if prior and prior.state not in {'retired', 'history'}:
        is_set, due = store.get_due_override(prior.token, conn=conn)
        if is_set:
            return due
    return _initial_due(week, task)


def _source(week, task, due):
    fields = {'completed': task.get('done', False), 'due': due}
    title = f"{task['recipe']}: {task['text']}"
    return SourceItem(task['id'], 'prep', week, title, fields,
                      canonical_hash({'task': task, 'fields': fields, 'state': 'active'}), 'active')


def _latest(week):
    latest = {}
    for item in store.list_items(domain='prep', week=week):
        if item.logical_id not in latest or item.generation > latest[item.logical_id].generation:
            latest[item.logical_id] = item
    return latest


def collect(week: str) -> list[SourceItem]:
    """Collect a fresh cache; missing/stale data is unavailable, never empty."""
    try:
        with mutation_lock(task_extractor._sidecar_path(week)):
            payload, _ = _read(week)
            latest = _latest(week)
            sources = []
            for task in payload['tasks']:
                prior = latest.pop(task['id'], None)
                sources.append(_source(week, task, _effective_due(week, task, prior)))
            for item in latest.values():
                completed = item.fields.get('completed') or (item.common_fields or {}).get('completed')
                state = 'history' if completed or item.state == 'history' else 'retired'
                values = {'id': item.logical_id, 'title': item.title, 'fields': item.fields, 'state': state}
                sources.append(SourceItem(item.logical_id, 'prep', week, item.title, item.fields, canonical_hash(values), state))
            return sources
    except (OSError, UnicodeError, ValueError, RevisionConflict) as exc:
        raise SourceUnavailable('Prep tasks are unavailable or need refresh') from exc


def apply(item: SyncItem, patch: dict, operation_id: str) -> SourceItem:
    """Apply completion/due atomically per store after a recoverable file edit."""
    validate_fields(patch, 'prep')
    if item.domain != 'prep':
        raise RevisionConflict('Not a prep item')
    journal = store.reserve_source_patch(item, patch, operation_id)
    path = task_extractor._sidecar_path(item.week)
    try:
        with mutation_lock(path):
            with db.connect() as conn:
                edit = conn.execute('SELECT * FROM apple_file_edits WHERE operation_id=?', (operation_id,)).fetchone()
            payload, current_hash = _read(item.week)
            task = next((t for t in payload['tasks'] if t['id'] == item.logical_id), None)
            if task is None:
                raise RevisionConflict('Prep task was removed or moved')
            due = _effective_due(item.week, task, item)
            if journal['status'] == 'applied':
                result = SourceItem.from_dict(json.loads(journal['result']))
                if (not edit or current_hash != edit['after_hash']
                        or _source(item.week, task, due) != result
                        or store.get_item(item.token).state != 'active'):
                    raise RevisionConflict('Applied prep source has since changed')
                return result
            if store.get_item(item.token) != item:
                raise RevisionConflict('Sync generation or revision changed')
            if edit:
                if current_hash not in {edit['before_hash'], edit['after_hash']}:
                    raise RevisionConflict('Prep source drifted during interrupted patch')
                expected = edit['before_hash']
            else:
                if _source(item.week, task, due).source_revision != item.source_revision:
                    raise RevisionConflict('Prep source changed')
                expected = current_hash
            plan_path = task_extractor._meal_plan_path(item.week)
            plan_before = plan_path.read_bytes()
            if 'completed' in patch:
                result = task_extractor.mark_task_done(item.week, item.logical_id, patch['completed'],
                                                        expected_hash=expected, operation_id=operation_id)
                if not result['success']:
                    raise RevisionConflict('Prep task was removed')
                with db.connect() as conn:
                    written_hash = conn.execute('SELECT after_hash FROM apple_file_edits WHERE operation_id=?', (operation_id,)).fetchone()[0]
            else:
                written_hash = mutate_note(path, expected, lambda text: text, operation_id)
            payload, after_hash = _read(item.week)
            if after_hash != written_hash or plan_path.read_bytes() != plan_before:
                raise RevisionConflict('Prep source changed after write')
            task = next(t for t in payload['tasks'] if t['id'] == item.logical_id)
            with db.write_transaction() as conn:
                if store.get_item(item.token, conn=conn) != item:
                    raise RevisionConflict('Sync revision changed during source write')
                if 'due' in patch:
                    store.set_due_override(item.token, patch['due'], expected_revision=item.revision, conn=conn)
                due = _effective_due(item.week, task, item, conn=conn)
                result = _source(item.week, task, due)
                store.finish_source_patch(operation_id, result, conn=conn)
            return result
    except (RevisionConflict, SourceUnavailable, OSError, UnicodeError, ValueError) as exc:
        if isinstance(exc, (RevisionConflict, SourceUnavailable, UnicodeError, ValueError)):
            store.conflict_source_patch(operation_id)
        if isinstance(exc, SourceUnavailable):
            raise RevisionConflict('Prep source needs refresh') from exc
        raise


def recover_pending() -> list[str]:
    """Replay original patches before snapshot refresh; IO failures stay pending."""
    conflicts = []
    for record in store.pending_source_patches('prep'):
        try:
            apply(SyncItem.from_dict(json.loads(record['item_payload'])), json.loads(record['patch']), record['operation_id'])
        except (RevisionConflict, ValueError, UnicodeError):
            conflicts.append(record['operation_id'])
    return conflicts
