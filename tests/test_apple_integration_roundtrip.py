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
                        title=obj['title'], fields=deepcopy(obj['fields']))
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
