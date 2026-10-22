"""Real HTTP/source round trips with Apple persistence simulated in memory.

This exercises the Python boundary; Swift adapter/service tests cover native
orchestration. No EventKit, personal stores, network, or live server is used.
"""
from copy import deepcopy
import importlib
import json
from uuid import uuid4

import pytest

import api_server
from lib import inventory_db as db, paths, serving_ledger as ledger, task_extractor
from lib.apple_integration import service, store
from lib.apple_integration.models import canonical_hash
from lib.shopping_note import read_shopping_note, save_shopping_note

BASE = '/api/apple-integration'
WEEK = '2026-W41'


class FakeAppleStore:
    """Persist independent objects, including foreign objects, across restarts.

    Creation deliberately appends rather than upserting by token: an erroneous
    repeated create from the real API is observable as a duplicate.
    """
    def __init__(self):
        self.objects = []
        self.creations = 0
        self.destinations = {'shopping-list', 'prep-list', 'cooking-calendar'}

    def owned(self, token):
        return [obj for obj in self.objects if obj['token'] == token]

    def observation(self, item):
        base = dict(token=item['token'], generation=item['generation'],
                    revision=item['revision'], availability='unavailable',
                    locator=None, title=None, fields={}, absence_confirmed=False,
                    issue=None)
        if item['destination_id'] not in self.destinations:
            return base
        matches = self.owned(item['token'])
        assert len(matches) <= 1, 'API caused duplicate Apple objects'
        if matches:
            obj = matches[0]
            assert obj['generation'] == item['generation']
            return dict(base, availability='present', locator=deepcopy(obj['locator']),
                        title=obj['title'], fields=deepcopy(obj['fields']),
                        has_user_notes=obj.get('has_user_notes', False))
        # Like the native service, omit a never-linked uncertain no-match.
        if item['locator'] is None and item['common_fields'] is None:
            return None
        return base

    def apply(self, operation):
        matches = self.owned(operation['token'])
        expected = operation['expected_apple_hash']
        if operation['destination_id'] not in self.destinations:
            return dict(outcome='failed', locator=None, observed_fields={}, observed_hash=None)
        if expected is not None:
            assert len(matches) == 1
            obj = matches[0]
            assert canonical_hash({'title': obj['title'], 'fields': obj['fields']}) == expected
            assert obj['generation'] == operation['generation']
        else:
            assert not matches, 'Repeated first creation would duplicate an Apple object'
            self.creations += 1
            obj = dict(token=operation['token'], generation=operation['generation'],
                       locator={'calendar_id': operation['destination_id'],
                                'item_id': f'apple-{self.creations}', 'external_id': None})
            self.objects.append(obj)
        if operation['action'] == 'delete':
            self.objects.remove(obj)
            return dict(outcome='deleted', locator=None, observed_fields={}, observed_hash=None)
        obj.update(title=operation['title'], fields=deepcopy(operation['fields']))
        return dict(outcome='saved', locator=deepcopy(obj['locator']),
                    observed_fields=deepcopy(obj['fields']),
                    observed_hash=canonical_hash({'title': obj['title'], 'fields': obj['fields']}))


class Bridge:
    def __init__(self, apple=None, context=None):
        self.client = api_server.app.test_client()
        self.apple = apple if apple is not None else FakeAppleStore()
        self.context = context or self.ok('post', BASE + '/owner', json={'owner_id': str(uuid4())})['context']

    def ok(self, method, path, **kwargs):
        response = getattr(self.client, method)(path, **kwargs)
        assert response.status_code == 200, response.json
        return response.json

    def activate(self, domain):
        destination = {'shopping': 'shopping-list', 'prep': 'prep-list', 'cooking': 'cooking-calendar'}[domain]
        self.ok('put', f'{BASE}/scopes/{domain}/{WEEK}', json=dict(
            domain=domain, week=WEEK, destination_id=destination,
            state='active', expected_revision=0))

    def work(self):
        return self.ok('get', BASE + '/work', query_string=self.context)

    def observe(self, items):
        observations = [self.apple.observation(item) for item in items]
        return self.ok('post', BASE + '/observations', json=dict(
            context=self.context, request_id=str(uuid4()), complete=True,
            observations=[obs for obs in observations if obs is not None]))

    def ack(self, operation, result):
        return self.ok('post', f"{BASE}/operations/{operation['operation_id']}/ack",
                       json=dict(context=self.context, operation_id=operation['operation_id'], **result))

    def sync(self):
        batch = self.work()
        assert batch['retry_requests'] == []
        result = self.observe(batch['items'])
        for operation in result['operations']:
            self.ack(operation, self.apple.apply(operation))
        return self.work()

    def restart(self):
        importlib.reload(service)
        return Bridge(self.apple, self.context)

    def conflicts(self):
        return self.ok('get', BASE + '/status')['conflicts']


@pytest.fixture
def bridge(tmp_db, tmp_vault, monkeypatch):
    monkeypatch.setenv('KITCHENOS_NO_LLM', '1')
    for folder in (paths.meal_plans_dir(), paths.recipes_dir(), paths.shopping_lists_dir()):
        folder.mkdir(parents=True, exist_ok=True)
    return Bridge()


def shopping(amount=2):
    return save_shopping_note(WEEK, [dict(item='lime', needed={'amount': amount, 'unit': 'whole'},
                                        to_buy={'amount': amount, 'unit': 'whole'})], [])


def domain_snapshot():
    with db.connect() as conn:
        return {table: [tuple(row) for row in conn.execute('SELECT * FROM ' + table)]
                for table in ('inventory', 'purchases', 'trips', 'cooks', 'placements')}


def test_shopping_completion_reopening_and_source_edit_survive_restart(bridge):
    """Catch missing source import, inventory side effects, or repeated export."""
    shopping(); bridge.activate('shopping')
    with db.write_transaction() as conn:
        conn.execute("INSERT INTO inventory(name,quantity,unit) VALUES('lime',6,'whole')")
    before = domain_snapshot()
    item = bridge.sync()['items'][0]
    obj = bridge.apple.owned(item['token'])[0]
    for completed in (True, False):
        obj['fields']['completed'] = completed
        bridge = bridge.restart()
        bridge.sync()
        assert read_shopping_note(WEEK).rows[0].completed is completed
    path = paths.shopping_lists_dir() / f'{WEEK}.md'
    path.write_text(path.read_text().replace('- [ ]', '- [x]'))
    bridge.sync(); bridge.restart().sync()
    assert obj['fields']['completed'] is True
    assert read_shopping_note(WEEK).rows[0].id == item['logical_id']
    assert domain_snapshot() == before
    assert bridge.apple.creations == 1


def test_prep_completion_due_override_and_reopening_preserve_meal(bridge):
    """Catch prep identity drift or treating reminder due dates as meal moves."""
    plan = paths.meal_plans_dir() / f'{WEEK}.md'
    plan.write_text('# Meal plan\n[[Soup]]\n')
    task = dict(id=task_extractor._stable_task_id('Soup', 'Monday', 'dinner', 1),
                recipe='Soup', day='Monday', slot='dinner', step=1, text='Chop onion.',
                type='prep', time_minutes=5, can_do_ahead=True, depends_on=[], done=False)
    task_extractor._save_sidecar(WEEK, dict(week=WEEK, generated_at='2026-10-01', tasks=[task]))
    bridge.activate('prep')
    before = domain_snapshot(); markdown = plan.read_bytes()
    item = bridge.sync()['items'][0]; obj = bridge.apple.owned(item['token'])[0]
    assert obj['fields']['due'] == {'date': '2026-10-05', 'time': None, 'timezone': None}
    obj['fields'] = {'completed': True, 'due': {'date': '2026-10-07', 'time': None, 'timezone': None}}
    bridge.sync(); bridge = bridge.restart(); bridge.sync()
    saved = bridge.ok('get', f'/api/tasks/{WEEK}/saved')
    assert saved['tasks'][0]['id'] == task['id'] and saved['tasks'][0]['done'] is True
    detail = bridge.ok('get', BASE + '/items', query_string={'domain': 'prep', 'week': WEEK})['items'][0]
    assert detail['due_override'] == {'date': '2026-10-07', 'time': None, 'timezone': None}
    bridge.ok('post', f"/api/tasks/{WEEK}/{task['id']}/done", json={'done': False})
    bridge.sync()
    assert obj['fields']['completed'] is False
    assert plan.read_bytes() == markdown and domain_snapshot() == before
    assert bridge.apple.creations == 1


def test_calendar_move_resize_and_source_reschedule_preserve_ledger(bridge):
    """Catch Calendar imports bypassing ledger placement and view updates."""
    cook = ledger.create_cook(recipe='Soup', week=WEEK, servings_produced=8, scale=1.5)
    schedule = dict(date='2026-10-06', meal='dinner', start='2026-10-06T19:00:00-05:00',
                    timezone='America/Chicago', duration_minutes=90, servings_to_eat=2)
    bridge.ok('post', f"/api/cooks/{cook['id']}/schedule", json=schedule)
    ledger.add_placement(cook['id'], 'slot', 1, date='2026-10-09', meal='lunch')
    before = ledger.get_cook(cook['id']); inventory = domain_snapshot()['inventory']
    bridge.activate('cooking')
    item = bridge.sync()['items'][0]; obj = bridge.apple.owned(item['token'])[0]
    obj['fields'].update(start='2026-10-07T19:30:00-05:00', duration_minutes=60)
    bridge.sync(); bridge = bridge.restart(); bridge.sync()
    after = bridge.ok('get', f"/api/cooks/{cook['id']}")
    assert after['date'] == '2026-10-07' and after['meal'] == 'dinner'
    assert {(p['date'], p['count']) for p in after['placements']} == {('2026-10-07', 2), ('2026-10-09', 1)}
    for field in ('scale', 'cooked_at', 'servings_produced', 'unassigned'):
        assert after[field] == before[field]
    assert ledger.schedules_for_week(WEEK)[0]['duration_minutes'] == 60
    markdown = (paths.meal_plans_dir() / f'{WEEK}.md').read_text()
    assert '[[Soup]]' in markdown.split('## Wednesday')[1].split('## Thursday')[0]
    bridge.ok('post', f"/api/cooks/{cook['id']}/schedule", json=dict(schedule, date='2026-10-08', start='2026-10-08T18:00:00-05:00'))
    bridge.sync(); bridge.restart().sync()
    assert obj['fields']['start'] == '2026-10-08T18:00:00-05:00'
    assert domain_snapshot()['inventory'] == inventory
    assert bridge.apple.creations == 1


def test_independent_due_edits_conflict_then_explicit_apple_choice_converges(bridge):
    """Catch last-writer-wins or a conflict choice that fails to reach source."""
    shopping(); bridge.activate('shopping'); item = bridge.sync()['items'][0]
    store.set_due_override(item['token'], {'date': '2026-10-08', 'time': None, 'timezone': None}, expected_revision=item['revision'])
    obj = bridge.apple.owned(item['token'])[0]
    obj['fields']['due'] = {'date': '2026-10-09', 'time': None, 'timezone': None}
    bridge.sync()
    conflict = next(c for c in bridge.conflicts() if c['field'] == 'due')
    detail = bridge.ok('get', f"{BASE}/conflicts/{conflict['conflict_id']}")
    assert 'keep_apple' in detail['choices']
    assert store.get_item(item['token']).common_fields['due'] is None
    bridge.ok('post', f"{BASE}/conflicts/{conflict['conflict_id']}/resolve", json={'choice': 'keep_apple', 'expected_revision': conflict['revision']})
    bridge.restart().sync()
    assert not bridge.conflicts()
    assert store.get_item(item['token']).fields['due'] == {'date': '2026-10-09', 'time': None, 'timezone': None}
    assert bridge.apple.creations == 1


def test_missing_destination_blocks_delivery_without_deleting_or_substitution(bridge):
    """Catch unavailable reads being mistaken for deletion or alternate export."""
    shopping(); bridge.activate('shopping'); item = bridge.sync()['items'][0]
    before = deepcopy(bridge.apple.objects)
    bridge.apple.destinations.remove('shopping-list')
    path = paths.shopping_lists_dir() / f'{WEEK}.md'
    path.write_text(path.read_text().replace('- [ ]', '- [x]'))
    result = bridge.observe(bridge.work()['items'])
    assert result['report']['unavailable'] == 1 and result['operations'] == []
    bridge = bridge.restart(); bridge.sync()
    assert bridge.apple.objects == before
    assert store.get_item(item['token']).state == 'active'
    bridge.apple.destinations.add('shopping-list'); bridge.sync()
    assert bridge.apple.owned(item['token'])[0]['fields']['completed'] is True
    assert bridge.apple.creations == 1


def test_first_save_lost_ack_and_owner_replacement_recover_same_object(bridge):
    """Catch duplicate exports after durable save or stale-owner acceptance."""
    shopping(); bridge.activate('shopping')
    first = bridge.work(); operation = first['operations'][0]
    result = bridge.apple.apply(operation)  # Crash before acknowledgement.
    bridge = bridge.restart(); bridge.sync(); bridge.sync()
    assert bridge.apple.creations == 1 and not bridge.conflicts()
    old_context = bridge.context
    bridge.ok('delete', BASE + '/owner', json={'context': old_context})
    bridge = Bridge(bridge.apple)
    assert bridge.context['owner_generation'] > old_context['owner_generation']
    assert bridge.client.get(BASE + '/work', query_string=old_context).status_code == 403
    assert bridge.client.post(f"{BASE}/operations/{operation['operation_id']}/ack", json=dict(context=old_context, operation_id=operation['operation_id'], **result)).status_code == 403
    bridge.sync(); bridge.restart().sync()
    assert bridge.apple.creations == 1
    assert store.get_item(operation['token']).locator.item_id == 'apple-1'


def test_retired_generation_cleanup_does_not_delete_foreign_or_replacement(bridge):
    """Catch generation confusion, premature recreation, or whole-list cleanup."""
    shopping(); bridge.activate('shopping'); old = bridge.sync()['items'][0]
    foreign = dict(token=None, title='2 whole lime', fields={'completed': False, 'due': None})
    bridge.apple.objects.append(foreign)
    save_shopping_note(WEEK, [], []); bridge.work(); shopping()
    batch = bridge.work(); replacement = batch['items'][0]
    assert replacement['generation'] == 2 and replacement['token'] != old['token']
    assert batch['operations'] == []
    retained = next(i for i in batch['retained_items'] if i['token'] == old['token'])
    removal = bridge.ok('post', BASE + '/items/remove-owned', json=dict(
        context=bridge.context, request_id=str(uuid4()), items=[dict(
            token=old['token'], expected_revision=retained['revision'], observation=bridge.apple.observation(retained))]))
    deletion = removal['operations'][0]
    bridge = bridge.restart()
    assert bridge.work()['operations'] == [deletion]
    bridge.ack(deletion, bridge.apple.apply(deletion))
    bridge.sync(); bridge.restart().sync()
    assert foreign in bridge.apple.objects and not bridge.apple.owned(old['token'])
    assert len(bridge.apple.owned(replacement['token'])) == 1
    assert bridge.apple.creations == 2
    assert not read_shopping_note(WEEK).rows[0].completed


def test_completed_shopping_quantity_change_stays_visible_until_choice(bridge):
    """Catch silently reopening a purchase or hiding increased demand."""
    shopping(); bridge.activate('shopping'); item = bridge.sync()['items'][0]
    obj = bridge.apple.owned(item['token'])[0]; obj['fields']['completed'] = True
    bridge.sync(); shopping(amount=3); bridge.sync(); bridge = bridge.restart(); bridge.sync()
    assert read_shopping_note(WEEK).rows[0].completed and obj['fields']['completed']
    saved = bridge.ok('get', f'/api/shopping-list/saved/{WEEK}')
    assert saved['rows'][0]['issue'] is not None
    conflict = next(c for c in bridge.conflicts() if c['field'] == 'shopping_amount_changed')
    bridge.ok('post', f"{BASE}/conflicts/{conflict['conflict_id']}/resolve", json={'choice': 'keep_kitchenos', 'expected_revision': conflict['revision']})
    bridge.sync(); bridge.restart().sync()
    assert not read_shopping_note(WEEK).rows[0].completed
    assert not obj['fields']['completed'] and '3' in obj['title']
    assert bridge.apple.creations == 1 and not bridge.conflicts()


def _retirement_source(bridge, domain):
    if domain == 'shopping':
        shopping()
        return lambda: save_shopping_note(WEEK, [], [])
    if domain == 'prep':
        (paths.meal_plans_dir() / f'{WEEK}.md').write_text('# Plan\n[[Soup]]\n')
        task = dict(id=task_extractor._stable_task_id('Soup', 'Monday', 'dinner', 1),
                    recipe='Soup', day='Monday', slot='dinner', step=1, text='Chop onion.', done=False)
        task_extractor._save_sidecar(WEEK, dict(week=WEEK, tasks=[task]))
        return lambda: task_extractor._save_sidecar(WEEK, dict(week=WEEK, tasks=[]))
    cook = ledger.create_cook(recipe='Soup', week=WEEK, servings_produced=4, scale=1)
    bridge.ok('post', f"/api/cooks/{cook['id']}/schedule", json=dict(
        date='2026-10-06', meal='dinner', start='2026-10-06T19:00:00-05:00',
        timezone='America/Chicago', duration_minutes=60, servings_to_eat=1))
    return lambda: ledger.delete_cook(cook['id'])


@pytest.mark.parametrize('domain', ['shopping', 'prep', 'cooking'])
@pytest.mark.parametrize('edit', ['title', 'fields', 'unchanged'])
def test_source_retirement_requires_unchanged_apple_object(bridge, domain, edit):
    """Catch deletion using a fresh hash that silently authorizes concurrent edits."""
    retire = _retirement_source(bridge, domain)
    bridge.activate(domain)
    item = bridge.sync()['items'][0]
    obj = bridge.apple.owned(item['token'])[0]
    if edit == 'title':
        obj['title'] = 'My edited title'
    elif edit == 'fields':
        if domain == 'cooking':
            obj['fields']['duration_minutes'] = 120
        else:
            obj['fields']['due'] = {'date': '2026-10-09', 'time': None, 'timezone': None}
    retire()
    bridge.restart().sync()
    if edit == 'unchanged':
        assert not bridge.apple.owned(item['token'])
        assert not bridge.conflicts()
    else:
        assert bridge.apple.owned(item['token']) == [obj]
        assert any(c['token'] == item['token'] for c in bridge.conflicts())


@pytest.mark.parametrize('domain', ['shopping', 'prep'])
def test_retirement_preserves_just_completed_apple_history(bridge, domain):
    retire = _retirement_source(bridge, domain)
    bridge.activate(domain)
    item = bridge.sync()['items'][0]
    obj = bridge.apple.owned(item['token'])[0]
    obj['fields']['completed'] = True
    retire()
    bridge.restart().sync()
    assert bridge.apple.owned(item['token']) == [obj]
    assert not bridge.conflicts()


@pytest.mark.parametrize('new_apple_change', [False, True])
def test_keep_kitchenos_survives_fresh_scan_but_rechecks_new_apple_edit(bridge, new_apple_change):
    """Catch a resolution being superseded by the mandatory scan before apply."""
    shopping(); bridge.activate('shopping'); item = bridge.sync()['items'][0]
    desired = {'date': '2026-10-08', 'time': None, 'timezone': None}
    store.set_due_override(item['token'], desired, expected_revision=item['revision'])
    obj = bridge.apple.owned(item['token'])[0]
    obj['fields']['due'] = {'date': '2026-10-09', 'time': None, 'timezone': None}
    bridge.sync()
    conflict = next(c for c in bridge.conflicts() if c['field'] == 'due')
    bridge.ok('post', f"{BASE}/conflicts/{conflict['conflict_id']}/resolve", json={
        'choice': 'keep_kitchenos', 'expected_revision': conflict['revision']})
    if new_apple_change:
        obj['fields']['due']['date'] = '2026-10-10'
    bridge.restart().sync()
    if new_apple_change:
        assert obj['fields']['due']['date'] == '2026-10-10'
        assert bridge.conflicts()
    else:
        assert obj['fields']['due'] == desired
        assert not bridge.conflicts()
        assert store.get_item(item['token']).common_fields['due'] == desired


@pytest.mark.parametrize('legacy', [False, True])
def test_explicit_shopping_activation_prepares_missing_or_v2_note(bridge, monkeypatch, legacy):
    """Catch unusable first activation; real generation must credit pantry without spending."""
    from lib import shopping_list_generator as generator
    from lib.shopping_note import _encode
    for name, directory in [('MEAL_PLANS_PATH', paths.meal_plans_dir()),
                            ('RECIPES_PATH', paths.recipes_dir())]:
        monkeypatch.setattr(generator, name, directory)
    (paths.meal_plans_dir() / f'{WEEK}.md').write_text('# Plan\n[[Soup]]\n')
    (paths.recipes_dir() / 'Soup.md').write_text(
        '---\nservings: 1\n---\n# Soup\n## Ingredients\n\n'
        '| Amount | Unit | Ingredient |\n| --- | --- | --- |\n'
        '| 2 | whole | lime |\n| 2 | whole | carrot |\n\n## Instructions\nCook.\n')
    with db.write_transaction() as conn:
        conn.execute("INSERT INTO inventory(name,quantity,unit) VALUES('lime',6,'whole')")
    note = paths.shopping_lists_dir() / f'{WEEK}.md'
    if legacy:
        note.write_text('- [x] 2 carrot\n- [ ] foil\n- [ ] foil\n'
                        '<!-- kitchenos-generated-items-v2:' + _encode(['2 carrot']) + ' -->\n')
    before = domain_snapshot()
    bridge.activate('shopping')
    batch = bridge.sync()
    document = read_shopping_note(WEEK)
    assert document.metadata and all(row.id for row in document.rows)
    assert any('carrot' in row.text for row in document.rows)
    assert not any('lime' in row.text for row in document.rows)
    assert 'lime' in note.read_text()
    if legacy:
        assert next(row for row in document.rows if 'carrot' in row.text).completed
        assert len({row.id for row in document.rows if row.text == 'foil'}) == 2
    assert len(batch['items']) == len(document.rows)
    assert domain_snapshot() == before



def test_removed_hand_edited_demand_can_accept_removal_without_reexporting(bridge):
    """Catch keeping an edited amount resurrecting demand that regeneration removed."""
    shopping(); bridge.activate('shopping'); item = bridge.sync()['items'][0]
    path = paths.shopping_lists_dir() / f'{WEEK}.md'
    original = read_shopping_note(WEEK).rows[0].text
    path.write_text(path.read_text().replace(original, '3 lime'))
    save_shopping_note(WEEK, [], [])
    bridge.work()
    conflict = next(c for c in bridge.conflicts() if c['field'] == 'shopping_amount_changed')
    bridge.ok('post', f"{BASE}/conflicts/{conflict['conflict_id']}/resolve", json={
        'choice': 'keep_kitchenos', 'expected_revision': conflict['revision']})
    bridge.restart().sync()
    assert read_shopping_note(WEEK).rows == []
    assert not bridge.apple.owned(item['token'])
    assert not bridge.conflicts()


@pytest.mark.parametrize('domain', ['shopping', 'prep'])
def test_retired_completed_apple_object_is_frozen_and_reappearance_exports_new_generation(bridge, domain):
    """Catch preserved-but-not-frozen completion blocking replacement or later deletion."""
    retire = _retirement_source(bridge, domain)
    bridge.activate(domain)
    item = bridge.sync()['items'][0]
    old = bridge.apple.owned(item['token'])[0]
    retire()
    # The delete is queued but not applied before the user completes in Apple.
    pending = bridge.observe(bridge.work()['items'])['operations']
    assert len(pending) == 1 and pending[0]['action'] == 'delete'
    old['fields']['completed'] = True
    bridge.restart().sync()
    assert store.get_item(item['token']).state == 'history'
    assert not store.pending_operations()
    # Even reopening the historical object cannot resume the old deletion.
    old['fields']['completed'] = False
    bridge.restart().sync()
    assert bridge.apple.owned(item['token']) == [old]
    _retirement_source(bridge, domain)
    batch = bridge.restart().sync()
    replacement = next(value for value in batch['items'] if value['logical_id'] == item['logical_id'])
    assert replacement['token'] != item['token'] and replacement['generation'] == 2
    assert replacement['fields']['completed'] is False
    assert bridge.apple.owned(replacement['token'])
    assert bridge.apple.owned(item['token']) == [old]
    assert not bridge.conflicts()


@pytest.mark.parametrize('availability', ['unavailable', 'missing'])
def test_retired_cooking_uncertain_observation_requires_explicit_detach(bridge, availability):
    """An uncertain EventKit read must leave a linked retired event reviewable, then unblock completion."""
    retire = _retirement_source(bridge, 'cooking')
    bridge.activate('cooking')
    exported = bridge.sync()['items'][0]
    apple_before = deepcopy(bridge.apple.objects)
    retire()
    ledger_before = domain_snapshot()
    with db.write_transaction() as conn:
        conn.execute("UPDATE apple_bridge SET last_success='2000-01-01T00:00:00+00:00'")

    def observe_uncertain():
        item = next(i for i in bridge.work()['items'] if i['token'] == exported['token'])
        observation = dict(bridge.apple.observation(item), availability=availability,
                           locator=None, title=None, fields={}, absence_confirmed=False)
        request_id = str(uuid4())
        bridge.ok('post', BASE + '/observations', json=dict(context=bridge.context,
            request_id=request_id, complete=True, observations=[observation]))
        return request_id

    observe_uncertain()
    conflict = next(c for c in bridge.conflicts() if c['token'] == exported['token'])
    detail = bridge.ok('get', f"{BASE}/conflicts/{conflict['conflict_id']}")
    assert detail['field'] == 'retired_unavailable'
    assert detail['choices'] == ['keep_manual']
    report = service.status()['report']
    assert report['conflicts'] == 1 and report['unavailable'] == 0
    assert store.get_item(exported['token']).locator is not None
    assert bridge.work()['operations'] == []
    assert bridge.apple.objects == apple_before
    assert domain_snapshot() == ledger_before

    second_request = observe_uncertain()
    assert bridge.conflicts() == [conflict]
    proof = dict(context=bridge.context, scopes=bridge.work()['scopes'], request_ids=[second_request])
    assert bridge.client.post(BASE + '/sync/complete', json=proof).status_code == 409
    assert service.status()['report']['last_success'] == '2000-01-01T00:00:00+00:00'
    stale = bridge.client.post(f"{BASE}/conflicts/{conflict['conflict_id']}/resolve",
        json=dict(choice='keep_manual', expected_revision=detail['revision'] + 1))
    assert stale.status_code == 409
    assert store.get_item(exported['token']).locator is not None

    bridge.ok('post', f"{BASE}/conflicts/{conflict['conflict_id']}/resolve",
              json=dict(choice='keep_manual', expected_revision=detail['revision']))
    detached = store.get_item(exported['token'])
    assert detached.state == 'history' and detached.locator is None
    assert bridge.apple.objects == apple_before
    assert domain_snapshot() == ledger_before
    assert bridge.work()['items'] == []
    result = bridge.ok('post', BASE + '/sync/complete', json=_pass_evidence(bridge))
    assert result['report']['last_success'] > '2000-01-01T00:00:00+00:00'


def test_cooking_reschedule_after_keep_manual_exports_new_generation(bridge):
    """Explicit scheduling must publish again without touching detached history."""
    cook = ledger.create_cook(recipe='Soup', week=WEEK, servings_produced=4)
    schedule = dict(date='2026-10-06', meal='dinner', start='2026-10-06T19:00:00-05:00',
                    timezone='America/Chicago', duration_minutes=60, servings_to_eat=1)
    route = f"/api/cooks/{cook['id']}/schedule"
    bridge.ok('post', route, json=schedule)
    bridge.activate('cooking')
    exported = bridge.sync()['items'][0]
    old_event = deepcopy(bridge.apple.owned(exported['token'])[0])

    bridge.ok('delete', route)
    retired = bridge.work()['items'][0]
    observation = dict(bridge.apple.observation(retired), availability='unavailable',
                       locator=None, title=None, fields={}, absence_confirmed=False)
    bridge.ok('post', BASE + '/observations', json=dict(context=bridge.context,
        request_id=str(uuid4()), complete=True, observations=[observation]))
    conflict = bridge.conflicts()[0]
    assert conflict['field'] == 'retired_unavailable'
    bridge.ok('post', f"{BASE}/conflicts/{conflict['conflict_id']}/resolve",
              json=dict(choice='keep_manual', expected_revision=conflict['revision']))
    history = store.get_item(exported['token'])
    assert history.state == 'history' and history.locator is None
    assert bridge.work()['items'] == []

    bridge.ok('post', route, json=dict(schedule, date='2026-10-08',
                                     start='2026-10-08T18:00:00-05:00'))
    batch = bridge.restart().sync()
    assert len(batch['items']) == 1
    replacement = batch['items'][0]
    assert replacement['state'] == 'active'
    assert replacement['generation'] == exported['generation'] + 1
    assert replacement['token'] != exported['token']
    assert bridge.apple.owned(replacement['token'])[0]['fields']['start'] == '2026-10-08T18:00:00-05:00'
    bridge.restart().sync()
    assert bridge.apple.creations == 2
    assert bridge.apple.owned(exported['token']) == [old_event]
    assert store.get_item(exported['token']) == history
    assert not bridge.conflicts()


def test_retired_unavailable_conflict_rejects_changed_item_evidence(bridge):
    """A review of one retired locator cannot detach a subsequently changed link."""
    retire = _retirement_source(bridge, 'cooking')
    bridge.activate('cooking')
    exported = bridge.sync()['items'][0]
    retire()
    item = bridge.work()['items'][0]
    observation = dict(bridge.apple.observation(item), availability='unavailable',
                       locator=None, title=None, fields={}, absence_confirmed=False)
    bridge.ok('post', BASE + '/observations', json=dict(context=bridge.context,
        request_id=str(uuid4()), complete=True, observations=[observation]))
    conflict = bridge.conflicts()[0]
    changed_locator = dict(item['locator'], item_id='apple-relocated')
    with db.write_transaction() as conn:
        conn.execute('UPDATE apple_items SET locator=?,revision=revision+1 WHERE token=?',
                     (json.dumps(changed_locator), item['token']))
    before = store.get_item(item['token'])
    response = bridge.client.post(f"{BASE}/conflicts/{conflict['conflict_id']}/resolve",
        json=dict(choice='keep_manual', expected_revision=conflict['revision']))
    assert response.status_code == 409
    assert store.get_item(item['token']) == before
    assert bridge.conflicts() == [conflict]


def test_retired_unavailable_detach_closes_prior_retirement_review(bridge):
    """An older retirement edit review must not keep a detached event blocking sync."""
    retire = _retirement_source(bridge, 'cooking')
    bridge.activate('cooking')
    exported = bridge.sync()['items'][0]
    retire()
    bridge.apple.owned(exported['token'])[0]['title'] = 'Edited retired event'
    bridge.sync()
    assert [c['field'] for c in bridge.conflicts()] == ['retirement']
    item = bridge.work()['items'][0]
    observation = dict(bridge.apple.observation(item), availability='unavailable',
                       locator=None, title=None, fields={}, absence_confirmed=False)
    bridge.ok('post', BASE + '/observations', json=dict(context=bridge.context,
        request_id=str(uuid4()), complete=True, observations=[observation]))
    conflict = next(c for c in bridge.conflicts() if c['field'] == 'retired_unavailable')
    bridge.ok('post', f"{BASE}/conflicts/{conflict['conflict_id']}/resolve",
              json=dict(choice='keep_manual', expected_revision=conflict['revision']))
    assert bridge.conflicts() == []
    assert bridge.ok('post', BASE + '/sync/complete', json=_pass_evidence(bridge))['report']['last_success']


def test_retired_unavailable_review_blocks_later_present_delete(bridge):
    """A later readable EventKit object cannot bypass an unresolved separation choice."""
    retire = _retirement_source(bridge, 'cooking')
    bridge.activate('cooking')
    exported = bridge.sync()['items'][0]
    apple_before = deepcopy(bridge.apple.objects)
    retire()
    ledger_before = domain_snapshot()
    item = bridge.work()['items'][0]
    uncertain = dict(bridge.apple.observation(item), availability='unavailable',
                     locator=None, title=None, fields={}, absence_confirmed=False)
    bridge.ok('post', BASE + '/observations', json=dict(context=bridge.context,
        request_id=str(uuid4()), complete=True, observations=[uncertain]))
    conflict = bridge.conflicts()[0]

    result = bridge.observe(bridge.work()['items'])
    assert result['operations'] == []
    assert bridge.work()['operations'] == []
    assert bridge.conflicts() == [conflict]
    assert store.get_item(item['token']).locator.to_dict() == item['locator']
    assert bridge.apple.objects == apple_before
    assert domain_snapshot() == ledger_before


def test_older_retirement_choice_cannot_detach_changed_unavailable_link(bridge):
    """Either review choice must fence the current retired export and locator."""
    retire = _retirement_source(bridge, 'cooking')
    bridge.activate('cooking')
    exported = bridge.sync()['items'][0]
    retire()
    bridge.apple.owned(exported['token'])[0]['title'] = 'Edited retired event'
    bridge.sync()
    older = next(c for c in bridge.conflicts() if c['field'] == 'retirement')
    item = bridge.work()['items'][0]
    uncertain = dict(bridge.apple.observation(item), availability='unavailable',
                     locator=None, title=None, fields={}, absence_confirmed=False)
    bridge.ok('post', BASE + '/observations', json=dict(context=bridge.context,
        request_id=str(uuid4()), complete=True, observations=[uncertain]))
    assert {c['field'] for c in bridge.conflicts()} == {'retirement', 'retired_unavailable'}
    changed_locator = dict(item['locator'], item_id='apple-relocated')
    with db.write_transaction() as conn:
        conn.execute('UPDATE apple_items SET locator=?,revision=revision+1 WHERE token=?',
                     (json.dumps(changed_locator), item['token']))
    before = store.get_item(item['token'])
    response = bridge.client.post(f"{BASE}/conflicts/{older['conflict_id']}/resolve",
        json=dict(choice='keep_manual', expected_revision=older['revision']))
    assert response.status_code == 409
    assert store.get_item(item['token']) == before
    assert {c['field'] for c in bridge.conflicts()} == {'retirement', 'retired_unavailable'}


@pytest.mark.parametrize('removed', [False, True])
def test_shopping_conflict_detail_shows_generated_resolution_target(bridge, removed):
    """Catch edited row title hiding the generated quantity or removal to be accepted."""
    shopping(); bridge.activate('shopping'); bridge.sync()
    path = paths.shopping_lists_dir() / f'{WEEK}.md'
    original = read_shopping_note(WEEK).rows[0].text
    path.write_text(path.read_text().replace(original, '9 lime'))
    if removed:
        save_shopping_note(WEEK, [], [])
    else:
        shopping(3)
    before = path.read_bytes()
    bridge.work()
    conflict = next(c for c in bridge.conflicts() if c['field'] == 'shopping_amount_changed')
    detail = bridge.ok('get', f"{BASE}/conflicts/{conflict['conflict_id']}")
    assert detail['source']['title'] == '9 lime'
    assert detail['shopping_demand'] == {'state': 'removed' if removed else 'active',
                                         'text': None if removed else '3 lime'}
    assert path.read_bytes() == before
    bridge.ok('post', f"{BASE}/conflicts/{conflict['conflict_id']}/resolve", json={
        'choice': 'keep_kitchenos', 'expected_revision': detail['revision']})
    document = read_shopping_note(WEEK)
    if removed:
        assert not document.rows
    else:
        assert document.rows[0].text == '3 lime' and not document.rows[0].completed


def test_changed_generated_target_invalidates_presented_shopping_resolution(bridge):
    """Catch accepting an undisclosed generated quantity when edited text stayed the same."""
    shopping(); bridge.activate('shopping'); bridge.sync()
    path = paths.shopping_lists_dir() / f'{WEEK}.md'
    path.write_text(path.read_text().replace(read_shopping_note(WEEK).rows[0].text, '9 lime'))
    shopping(3); bridge.work()
    conflict = next(c for c in bridge.conflicts() if c['field'] == 'shopping_amount_changed')
    detail = bridge.ok('get', f"{BASE}/conflicts/{conflict['conflict_id']}")
    shopping(4)
    before = path.read_bytes()
    response = bridge.client.post(f"{BASE}/conflicts/{conflict['conflict_id']}/resolve", json={
        'choice': 'keep_kitchenos', 'expected_revision': detail['revision']})
    assert response.status_code == 409
    assert path.read_bytes() == before


def test_changed_shopping_target_revises_one_conflict_and_resolution_clears_it(bridge):
    """Catch every regeneration leaving an older, permanently unresolvable conflict."""
    shopping(); bridge.activate('shopping'); bridge.sync()
    path = paths.shopping_lists_dir() / f'{WEEK}.md'
    path.write_text(path.read_text().replace(read_shopping_note(WEEK).rows[0].text, '9 lime'))
    shopping(3); bridge.work()
    first = bridge.conflicts()[0]
    shopping(4); bridge.work()
    conflicts = bridge.conflicts()
    assert len(conflicts) == 1
    latest = conflicts[0]
    assert latest['conflict_id'] == first['conflict_id']
    assert latest['revision'] > first['revision']
    detail = bridge.ok('get', f"{BASE}/conflicts/{latest['conflict_id']}")
    assert detail['shopping_demand'] == {'state': 'active', 'text': '4 lime'}
    stale = bridge.client.post(f"{BASE}/conflicts/{first['conflict_id']}/resolve", json={
        'choice': 'keep_kitchenos', 'expected_revision': first['revision']})
    assert stale.status_code == 409
    bridge.work()
    assert bridge.conflicts() == conflicts  # unchanged evidence does not churn revisions
    bridge.ok('post', f"{BASE}/conflicts/{latest['conflict_id']}/resolve", json={
        'choice': 'keep_kitchenos', 'expected_revision': latest['revision']})
    bridge.restart().sync()
    assert read_shopping_note(WEEK).rows[0].text == '4 lime'
    assert not bridge.conflicts()


def test_shopping_identity_change_replaces_amount_conflict_without_stale_open_row(bridge):
    """Catch an ingredient edit leaving the previous amount conflict open forever."""
    shopping(); bridge.activate('shopping'); bridge.sync()
    path = paths.shopping_lists_dir() / f'{WEEK}.md'
    path.write_text(path.read_text().replace(read_shopping_note(WEEK).rows[0].text, '9 lime'))
    shopping(3); bridge.work()
    first = bridge.conflicts()[0]
    path.write_text(path.read_text().replace('- [ ] 9 lime', '- [ ] 9 carrot'))
    bridge.work()
    conflicts = bridge.conflicts()
    assert len(conflicts) == 1
    latest = conflicts[0]
    assert latest['field'] == 'shopping_identity_changed'
    assert latest['conflict_id'] == first['conflict_id'] and latest['revision'] > first['revision']
    bridge.ok('post', f"{BASE}/conflicts/{latest['conflict_id']}/resolve", json={
        'choice': 'keep_kitchenos', 'expected_revision': latest['revision']})
    bridge.restart().sync()
    assert read_shopping_note(WEEK).rows[0].text == '3 lime'
    assert not bridge.conflicts()


def _pass_evidence(bridge):
    batch = bridge.work()
    request_id = str(uuid4())
    bridge.ok('post', BASE + '/observations', json=dict(context=bridge.context, request_id=request_id,
        complete=True, observations=[bridge.apple.observation(item) for item in batch['items']]))
    return dict(context=bridge.context, scopes=batch['scopes'], request_ids=[request_id])


@pytest.mark.parametrize('empty', [False, True])
def test_successful_noop_pass_updates_success_but_reads_do_not(bridge, empty):
    save_shopping_note(WEEK, [], []) if empty else shopping()
    bridge.activate('shopping'); bridge.sync()
    with db.write_transaction() as conn:
        conn.execute("UPDATE apple_bridge SET last_success='2000-01-01T00:00:00+00:00'")
    bridge.work(); bridge.ok('get', BASE + '/status')
    assert service.status()['report']['last_success'] == '2000-01-01T00:00:00+00:00'
    proof = _pass_evidence(bridge)
    result = bridge.ok('post', BASE + '/sync/complete', json=proof)
    assert result['report']['last_success'] > '2000-01-01T00:00:00+00:00'
    repeated = bridge.ok('post', BASE + '/sync/complete', json=proof)
    assert repeated['report']['last_success'] == result['report']['last_success']


@pytest.mark.parametrize('failure', ['no_scopes', 'unavailable', 'pending', 'conflict', 'owner', 'scope', 'item', 'coverage'])
def test_incomplete_or_stale_pass_never_updates_success(bridge, failure):
    shopping(); bridge.activate('shopping'); bridge.sync()
    proof = _pass_evidence(bridge)
    with db.write_transaction() as conn:
        conn.execute("UPDATE apple_bridge SET last_success='2000-01-01T00:00:00+00:00'")
    item = store.list_items()[0]
    if failure in {'no_scopes', 'scope'}:
        scope = proof['scopes'][0]
        bridge.ok('put', f'{BASE}/scopes/shopping/{WEEK}', json=dict(domain='shopping', week=WEEK,
            destination_id=scope['destination_id'], state='archived', expected_revision=scope['revision']))
        if failure == 'no_scopes':
            proof['scopes'] = bridge.work()['scopes']
    elif failure == 'unavailable':
        (paths.shopping_lists_dir() / f'{WEEK}.md').unlink()
    elif failure == 'pending':
        store.reserve_operation(item, 'upsert', canonical_hash({'title': item.title, 'fields': item.fields}))
    elif failure == 'conflict':
        service._conflict(item, 'due')
    elif failure == 'owner':
        proof['context'] = dict(proof['context'], owner_generation=proof['context']['owner_generation'] + 1)
    elif failure == 'item':
        shopping(4)
    elif failure == 'coverage':
        request_id = str(uuid4())
        bridge.ok('post', BASE + '/observations', json=dict(context=bridge.context, request_id=request_id, complete=True, observations=[]))
        proof['request_ids'] = [request_id]
    response = bridge.client.post(BASE + '/sync/complete', json=proof)
    assert response.status_code in {400, 403, 409, 503}
    assert service.status()['report']['last_success'] == '2000-01-01T00:00:00+00:00'


@pytest.mark.parametrize('change', ['source', 'scope'])
def test_committed_ack_retry_survives_later_source_or_scope_revision(bridge, change):
    shopping(); bridge.activate('shopping')
    operation = bridge.observe(bridge.work()['items'])['operations'][0]
    ack = bridge.apple.apply(operation)
    bridge.ack(operation, ack)
    if change == 'source':
        shopping(3); bridge.work()
    else:
        scope = bridge.work()['scopes'][0]
        bridge.ok('put', f'{BASE}/scopes/shopping/{WEEK}', json=dict(domain='shopping',week=WEEK,
            destination_id=scope['destination_id'],state='archived',expected_revision=scope['revision']))
    before = store.get_item(operation['token'])
    bridge.ack(operation, ack)
    assert store.get_item(operation['token']) == before
    altered = dict(ack, observed_fields=dict(ack['observed_fields'], completed=True))
    altered['observed_hash'] = canonical_hash({'title': operation['title'], 'fields': altered['observed_fields']})
    response = bridge.client.post(f"{BASE}/operations/{operation['operation_id']}/ack", json=dict(
        context=bridge.context, operation_id=operation['operation_id'], **altered))
    assert response.status_code == 409


def test_superseded_saved_proof_recovers_locator_to_explicit_conflict_without_import(bridge):
    shopping(); bridge.activate('shopping')
    operation = bridge.observe(bridge.work()['items'])['operations'][0]
    ack = bridge.apple.apply(operation)
    shopping(3)
    item = bridge.work()['items'][0]
    proof = dict(context=bridge.context, ack=dict(operation_id=operation['operation_id'], **ack),
                 observation=bridge.apple.observation(item))
    before = (paths.shopping_lists_dir() / f'{WEEK}.md').read_bytes()
    recovered = bridge.ok('post', f"{BASE}/operations/{operation['operation_id']}/recover-saved", json=proof)
    assert recovered['report']['conflicts'] == 1
    assert store.get_item(item['token']).locator.to_dict() == proof['observation']['locator']
    assert store.get_item(item['token']).common_fields is None
    bridge.restart().sync()
    assert (paths.shopping_lists_dir() / f'{WEEK}.md').read_bytes() == before
    assert len(bridge.conflicts()) == 1
    bridge.ok('post', f"{BASE}/operations/{operation['operation_id']}/recover-saved", json=proof)
    assert len(bridge.conflicts()) == 1
    conflict = bridge.conflicts()[0]
    bridge.ok('post', f"{BASE}/conflicts/{conflict['conflict_id']}/resolve", json=dict(
        choice='keep_kitchenos', expected_revision=conflict['revision']))
    bridge.sync()
    assert bridge.apple.owned(item['token'])[0]['title'] == '3 lime'
    assert bridge.apple.creations == 1 and not bridge.conflicts()


def test_recovered_save_conflict_refreshes_apple_evidence_before_resolution(bridge):
    shopping(); bridge.activate('shopping')
    operation = bridge.observe(bridge.work()['items'])['operations'][0]
    ack = bridge.apple.apply(operation)
    shopping(3)
    item = bridge.work()['items'][0]
    proof = dict(context=bridge.context, ack=dict(operation_id=operation['operation_id'], **ack),
                 observation=bridge.apple.observation(item))
    bridge.ok('post', f"{BASE}/operations/{operation['operation_id']}/recover-saved", json=proof)
    conflict = bridge.conflicts()[0]
    old = bridge.ok('get', f"{BASE}/conflicts/{conflict['conflict_id']}")
    obj = bridge.apple.owned(item['token'])[0]
    obj['title'] = 'Edited again in Apple'
    obj['fields']['completed'] = True

    bridge.sync()

    current = bridge.ok('get', f"{BASE}/conflicts/{conflict['conflict_id']}")
    assert current['revision'] > old['revision']
    assert current['apple']['title'] == 'Edited again in Apple'
    assert current['apple']['fields']['completed'] is True
    stale = bridge.client.post(f"{BASE}/conflicts/{conflict['conflict_id']}/resolve",
                               json=dict(choice='keep_apple', expected_revision=old['revision']))
    assert stale.status_code == 409


@pytest.mark.parametrize('invalid', ['missing', 'owner', 'generation', 'tampered_ack'])
def test_saved_proof_recovery_rejects_unverified_or_stale_evidence(bridge, invalid):
    shopping(); bridge.activate('shopping')
    operation = bridge.observe(bridge.work()['items'])['operations'][0]
    ack = bridge.apple.apply(operation)
    shopping(3); item = bridge.work()['items'][0]
    observation = bridge.apple.observation(item)
    context = dict(bridge.context)
    if invalid == 'tampered_ack':
        ack['observed_fields']['completed'] = True
    elif invalid == 'missing':
        observation.update(availability='missing', locator=None, title=None, fields={})
    elif invalid == 'owner':
        context['owner_generation'] += 1
    else:
        observation['generation'] += 1
    before = store.get_item(item['token'])
    response = bridge.client.post(f"{BASE}/operations/{operation['operation_id']}/recover-saved", json=dict(
        context=context, ack=dict(operation_id=operation['operation_id'], **ack), observation=observation))
    assert response.status_code in {400, 403, 409}
    assert store.get_item(item['token']) == before


def test_enqueue_counts_actual_scope_work_and_archived_scope_needs_activation(bridge):
    shopping(); bridge.activate('shopping')
    first = bridge.ok('post', '/send-to-reminders', json={'week': WEEK})
    assert first['queued'] == 1 and first['delivered'] == 0
    bridge.sync()
    settled = bridge.ok('post', '/send-to-reminders', json={'week': WEEK})
    assert settled['queued'] == 0 and settled['delivered'] == 0
    scope = bridge.work()['scopes'][0]
    bridge.ok('put', f'{BASE}/scopes/shopping/{WEEK}', json=dict(domain='shopping', week=WEEK,
        destination_id=scope['destination_id'],state='archived',expected_revision=scope['revision']))
    rejected = bridge.client.post('/send-to-reminders', json={'week': WEEK})
    assert rejected.status_code == 409
    assert not store.pending_operations()


@pytest.mark.parametrize('domain', ['shopping', 'prep'])
def test_completed_retirement_closes_only_obsolete_retirement_conflict(bridge, domain):
    retire = _retirement_source(bridge, domain)
    bridge.activate(domain); item = bridge.sync()['items'][0]
    obj = bridge.apple.owned(item['token'])[0]
    retire(); obj['title'] = 'An edited retired reminder'; bridge.sync()
    assert any(c['field'] == 'retirement' for c in bridge.conflicts())
    service._conflict(store.get_item(item['token']), 'source_recovery')
    obj['fields']['completed'] = True
    bridge.sync()
    assert store.get_item(item['token']).state == 'history'
    assert [c['field'] for c in bridge.conflicts()] == ['source_recovery']
    assert bridge.apple.owned(item['token']) == [obj]



def test_enqueue_counts_unfinished_observation_request_for_its_scope(bridge):
    """Catch zero queued while a durable request for this scope blocks reconciliation."""
    shopping(); bridge.activate('shopping'); bridge.sync()
    item = bridge.work()['items'][0]
    with db.write_transaction() as conn:
        conn.execute('INSERT INTO apple_requests(request_id,owner_id,owner_generation,payload) VALUES(?,?,?,?)',
                     (str(uuid4()), bridge.context['owner_id'], bridge.context['owner_generation'],
                      json.dumps([bridge.apple.observation(item)])))
    result = bridge.ok('post', '/send-to-reminders', json={'week': WEEK})
    assert result['queued'] == 1 and result['delivered'] == 0


def test_suppressed_export_is_terminal_for_work_and_completed_pass(bridge):
    """Suppression needs no impossible Apple observation after its locator is cleared."""
    shopping(); bridge.activate('shopping'); bridge.sync()
    item = store.list_items()[0]
    store.set_suppressed(item.token, True, expected_revision=item.revision)
    with db.write_transaction() as conn:
        conn.execute('UPDATE apple_items SET locator=NULL,common_payload=NULL WHERE token=?', (item.token,))
    batch = bridge.work()
    assert batch['items'] == []
    proof = _pass_evidence(bridge)
    result = bridge.ok('post', BASE + '/sync/complete', json=proof)
    assert result['report']['last_success'] is not None


def test_retirement_preserves_user_note_even_without_supported_field_edit(bridge):
    """Note-only edits are user content and must stop automatic deletion."""
    retire = _retirement_source(bridge, 'shopping')
    bridge.activate('shopping'); item = bridge.sync()['items'][0]
    obj = bridge.apple.owned(item['token'])[0]
    obj['has_user_notes'] = True
    retire()
    bridge.sync()
    assert bridge.apple.owned(item['token']) == [obj]
    assert any(c['token'] == item['token'] and c['field'] == 'retirement' for c in bridge.conflicts())


@pytest.mark.parametrize('later_state', ['changed_apple', 'history', 'archived', 'replaced'])
def test_superseded_saved_recovery_survives_changed_or_inactive_source(bridge, later_state):
    """A saved but unacknowledged object must reach durable review after source drift."""
    shopping(); bridge.activate('shopping')
    initial = bridge.work()['items'][0]
    operation = bridge.observe([initial])['operations'][0]
    ack = bridge.apple.apply(operation)
    obj = bridge.apple.owned(initial['token'])[0]
    if later_state == 'changed_apple':
        shopping(3)
        obj['title'] = 'My Apple title'
        obj['fields']['completed'] = True
    elif later_state == 'history':
        path = paths.shopping_lists_dir() / f'{WEEK}.md'
        path.write_text(path.read_text().replace('- [ ]', '- [x]'))
        save_shopping_note(WEEK, [], [])
    elif later_state == 'archived':
        scope = bridge.work()['scopes'][0]
        bridge.ok('put', f'{BASE}/scopes/shopping/{WEEK}', json=dict(domain='shopping', week=WEEK,
            destination_id=scope['destination_id'], state='archived', expected_revision=scope['revision']))
    else:
        save_shopping_note(WEEK, [], [])
        bridge.work()
        shopping()
    bridge.work()
    assert store.get_item(initial['token']).revision != initial['revision'] or later_state == 'archived'
    observation = bridge.apple.observation(initial)
    proof = dict(context=bridge.context, ack=dict(operation_id=operation['operation_id'], **ack),
                 observation=observation)

    result = bridge.ok('post', f"{BASE}/operations/{operation['operation_id']}/recover-saved", json=proof)

    assert result['report']['conflicts'] >= 1
    assert store.get_item(initial['token']).locator.to_dict() == observation['locator']
    with db.connect() as conn:
        row = conn.execute('SELECT result FROM apple_operations WHERE operation_id=?',
                           (operation['operation_id'],)).fetchone()
        assert json.loads(row['result'])['recovered_saved'] == {
            'ack': proof['ack'], 'observation': proof['observation']}
    assert bridge.apple.owned(initial['token']) == [obj]
    bridge.ok('post', f"{BASE}/operations/{operation['operation_id']}/recover-saved", json=proof)
    assert bridge.apple.creations == 1
    if later_state == 'archived':
        conflict = next(c for c in bridge.conflicts() if c['token'] == initial['token'])
        detail = bridge.ok('get', f"{BASE}/conflicts/{conflict['conflict_id']}")
        assert detail['choices'] == ['keep_manual']
        for choice in ('keep_kitchenos', 'keep_apple'):
            denied = bridge.client.post(f"{BASE}/conflicts/{conflict['conflict_id']}/resolve",
                                        json=dict(choice=choice, expected_revision=detail['revision']))
            assert denied.status_code == 409
        current_scope = bridge.work()['scopes'][0]
        bridge.ok('put', f'{BASE}/scopes/shopping/{WEEK}', json=dict(domain='shopping', week=WEEK,
            destination_id=current_scope['destination_id'], state='active',
            expected_revision=current_scope['revision']))
        detail = bridge.ok('get', f"{BASE}/conflicts/{conflict['conflict_id']}")
        assert {'keep_kitchenos', 'keep_apple', 'keep_manual'} <= set(detail['choices'])
