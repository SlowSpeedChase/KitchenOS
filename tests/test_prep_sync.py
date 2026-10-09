"""Prep reminder imports preserve task identity and the meal ledger."""
from dataclasses import replace
import json
import os
from uuid import uuid4

import pytest

from lib import inventory_db as db, paths, task_extractor
from lib.apple_integration import store
from lib.apple_integration.models import RevisionConflict, SourceUnavailable

WEEK = '2026-W41'
DUE = {'date': '2026-10-05', 'time': None, 'timezone': None}


def task(day='Monday', done=False):
    return {'id': task_extractor._stable_task_id('Soup', day, 'dinner', 1),
            'recipe': 'Soup', 'day': day, 'slot': 'dinner', 'step': 1,
            'text': 'Chop onion.', 'type': 'prep', 'time_minutes': 5,
            'can_do_ahead': True, 'depends_on': [], 'done': done}


@pytest.fixture
def active(tmp_vault, tmp_db):
    store.register_owner(str(uuid4()))
    store.activate_scope('prep', WEEK, 'list')
    root = paths.meal_plans_dir()
    root.mkdir()
    (root / f'{WEEK}.md').write_text('# Meal plan\n[[Soup]]\n')
    sidecar = root / f'{WEEK}.tasks.json'
    sidecar.write_text(json.dumps({'week': WEEK, 'generated_at': '2026-10-01', 'tasks': [task()]}))
    return sidecar


def export():
    from lib.apple_integration import prep
    return store.refresh_source(prep.collect(WEEK)[0])


def test_completion_and_undo_preserve_id(active):
    from lib.apple_integration import prep
    before = export()
    assert before.fields == {'completed': False, 'due': DUE}
    after = prep.apply(before, {'completed': True}, str(uuid4()))
    assert after.logical_id == before.logical_id
    assert task_extractor.load_cached_tasks(WEEK)['tasks'][0]['done'] is True
    current = store.refresh_source(after)
    undone = prep.apply(current, {'completed': False}, str(uuid4()))
    assert undone.logical_id == before.logical_id
    assert undone.fields['completed'] is False


def test_due_override_does_not_move_meal(active):
    from lib.apple_integration import prep
    item = export()
    plan = active.with_name(f'{WEEK}.md')
    plan_before = plan.read_bytes()
    with db.write_transaction() as conn:
        conn.execute("INSERT INTO inventory(name, quantity, unit, location_source) VALUES('onion',5,'whole','manual')")
        before_inventory = [tuple(row) for row in conn.execute('SELECT * FROM inventory')]
    due = {'date': '2026-11-01', 'time': None, 'timezone': None}
    source = prep.apply(item, {'completed': True, 'due': due}, str(uuid4()))
    assert source.logical_id == item.logical_id
    assert source.fields == {'completed': True, 'due': due}
    assert store.get_due_override(item.token) == (True, due)
    assert plan.read_bytes() == plan_before
    assert task_extractor.load_cached_tasks(WEEK)['tasks'][0]['day'] == 'Monday'
    with db.connect() as conn:
        assert [tuple(row) for row in conn.execute('SELECT * FROM inventory')] == before_inventory
        assert list(conn.execute('SELECT * FROM cooks')) == []


@pytest.mark.parametrize('due', [None, {'date': '2026-10-06', 'time': '09:15', 'timezone': 'America/Chicago'}])
def test_due_clear_and_timed_due_round_trip(active, due):
    from lib.apple_integration import prep
    item = export()
    source = prep.apply(item, {'due': due}, str(uuid4()))
    assert source.fields['due'] == due
    assert prep.collect(WEEK)[0].fields['due'] == due
    assert store.get_due_override(item.token) == (True, due)


def test_stale_source_hash_refuses_completion(active):
    from lib.apple_integration import prep
    item = export()
    payload = json.loads(active.read_text())
    payload['tasks'][0]['text'] = 'Slice onion.'
    active.write_text(json.dumps(payload))
    before = active.read_bytes()
    with pytest.raises(RevisionConflict):
        prep.apply(item, {'completed': True}, str(uuid4()))
    assert active.read_bytes() == before


@pytest.mark.parametrize('missing', [True, False])
def test_missing_or_stale_cache_requests_refresh_without_llm_or_retirement(active, missing, monkeypatch):
    from lib.apple_integration import prep
    export()
    if missing:
        active.unlink()
    else:
        old = active.stat().st_mtime - 10
        os.utime(active, (old, old))
    monkeypatch.setattr(task_extractor, 'extract_tasks', lambda *a, **k: pytest.fail('polling invoked extraction'))
    with pytest.raises(SourceUnavailable):
        prep.collect(WEEK)
    assert store.list_items(domain='prep', week=WEEK)[0].state == 'active'


def test_moved_task_retires_old_id_without_carrying_completion(active):
    from lib.apple_integration import prep
    item = export()
    source = prep.apply(item, {'completed': True}, str(uuid4()))
    store.refresh_source(source)
    task_extractor._save_sidecar(WEEK, {'week': WEEK, 'generated_at': 'later', 'tasks': [task('Tuesday')]})
    sources = {s.logical_id: s for s in prep.collect(WEEK)}
    moved = next(s for s in sources.values() if s.state == 'active')
    assert moved.logical_id != item.logical_id
    assert moved.fields['completed'] is False
    assert moved.fields['due'] == {'date': '2026-10-06', 'time': None, 'timezone': None}
    assert sources[item.logical_id].state == 'history'


@pytest.mark.parametrize('detached_state', ['retired', 'history'])
def test_reappearing_task_does_not_inherit_old_due(active, detached_state):
    from lib.apple_integration import prep
    item = export()
    due = {'date': '2026-11-01', 'time': None, 'timezone': None}
    source = prep.apply(item, {'due': due}, str(uuid4()))
    current = store.refresh_source(source)
    store.refresh_source(replace(source, state=detached_state))
    reappearing = prep.collect(WEEK)[0]
    assert reappearing.fields['due'] == DUE
    replacement = store.refresh_source(reappearing)
    assert replacement.generation == current.generation + 1
    assert replacement.token != current.token
    assert replacement.fields['due'] == DUE
    assert store.get_due_override(replacement.token) == (False, None)
    assert prep.collect(WEEK)[0].source_revision == replacement.source_revision


def test_interrupted_completion_due_recovers_before_refresh(active, monkeypatch):
    from lib.apple_integration import prep
    item = export()
    operation = str(uuid4())
    setter = store.set_due_override
    def interrupt(*a, **k):
        raise OSError('termination after replacement')
    monkeypatch.setattr(store, 'set_due_override', interrupt)
    with pytest.raises(OSError):
        prep.apply(item, {'completed': True, 'due': None}, operation)
    assert task_extractor.load_cached_tasks(WEEK)['tasks'][0]['done'] is True
    assert store.pending_source_patches('prep')[0]['operation_id'] == operation
    monkeypatch.setattr(store, 'set_due_override', setter)
    assert prep.recover_pending() == []
    assert store.pending_source_patches('prep') == []
    assert prep.collect(WEEK)[0].fields == {'completed': True, 'due': None}
    assert prep.apply(item, {'completed': True, 'due': None}, operation).fields['completed'] is True


def test_interrupted_patch_external_edit_conflicts(active, monkeypatch):
    from lib.apple_integration import prep
    item = export()
    operation = str(uuid4())
    setter = store.set_due_override
    monkeypatch.setattr(store, 'set_due_override', lambda *a, **k: (_ for _ in ()).throw(OSError('crash')))
    with pytest.raises(OSError):
        prep.apply(item, {'completed': True, 'due': None}, operation)
    active.write_text(active.read_text() + '\n')
    before = active.read_bytes()
    monkeypatch.setattr(store, 'set_due_override', setter)
    assert prep.recover_pending() == [operation]
    assert active.read_bytes() == before
    assert store.get_due_override(item.token) == (False, None)


def test_invalid_task_cache_is_unavailable(active):
    from lib.apple_integration import prep
    payload = json.loads(active.read_text())
    payload['tasks'].append(payload['tasks'][0])
    active.write_text(json.dumps(payload))
    with pytest.raises(SourceUnavailable):
        prep.collect(WEEK)


def test_unknown_task_day_stays_undated(active):
    from lib.apple_integration import prep
    payload = json.loads(active.read_text())
    payload['tasks'] = [task('Unknown')]
    active.write_text(json.dumps(payload))
    assert prep.collect(WEEK)[0].fields['due'] is None
