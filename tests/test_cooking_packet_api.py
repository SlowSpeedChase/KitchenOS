"""Saved packet HTTP contract; real isolated repository, controlled jobs."""
import importlib
import json
from copy import deepcopy

import pytest

from lib import cooking_packet_store as store, cooking_packet_builder as builder, paths, recipe_phases
from tests.test_cooking_packet_store import draft, change

BASE = '/api/cooking-packets/2026-W40'


@pytest.fixture
def client(monkeypatch):
    import api_server
    monkeypatch.delenv('KITCHENOS_API_TOKEN', raising=False)
    return api_server.app.test_client()


@pytest.fixture
def queued(monkeypatch):
    jobs = importlib.import_module('lib.cooking_packet_jobs')
    jobs.clear_operations()
    pending = []
    monkeypatch.setattr(jobs, '_launch', pending.append)
    yield pending
    jobs.clear_operations()


@pytest.fixture
def packet():
    return store.replace_generated('2026-W40', draft())


def test_get_missing_and_saved_packet_with_freshness(client, packet):
    assert client.get('/api/cooking-packets/2026-W41').status_code == 404
    response = client.get(BASE)
    assert response.status_code == 200 and response.is_json
    saved = response.json
    assert saved['schedule'] == packet['schedule'] and saved['revision'] == 1
    assert saved['freshness']['generated_at'] == packet['generated_at']
    assert saved['freshness']['source_changes_checked'] is False


def test_patch_conflict_never_overwrites(client, packet):
    first = client.patch(BASE, json={'revision': 1, 'changes': [change()]})
    assert first.status_code == 200 and first.json['revision'] == 2
    conflict = client.patch(BASE, json={'revision': 1, 'changes': [change(value='Lost')]})
    assert conflict.status_code == 409 and conflict.json['revision'] == 2
    assert store.get_packet('2026-W40')['schedule'][0]['text'] == 'Mine'


@pytest.mark.parametrize('body', [None, [], {}, {'revision': 1}, {'revision': 1, 'changes': [], 'extra': 1},
    {'expected_revision': 1, 'changes': []}, {'revision': True, 'changes': []},
    {'revision': 1, 'changes': [], 'status': 'bad'}, {'revision': 1, 'changes': [change(field='recipe')]},
    {'revision': 1, 'changes': [], 'status': None}])
def test_patch_rejects_invalid_body_atomically(client, packet, body):
    response = client.patch(BASE, data=json.dumps(body), content_type='application/json')
    assert response.status_code == 400
    assert store.get_packet('2026-W40') == packet


def test_json_content_type_and_missing_packet(client):
    assert client.patch(BASE, data='{"revision":1,"changes":[]}').status_code == 415
    assert client.patch(BASE, json={'revision': 1, 'changes': []}).status_code == 404
    assert client.post(BASE+'/refresh', data='{"request_id":"a"}').status_code == 415


def test_review_status_and_stage_repartition(client):
    from tests.test_cooking_packet_builder import partition_fixture
    saved = store.replace_generated('2026-W40', partition_fixture('bag_now', True))
    assert client.get(BASE).json['pull_list'] == []
    updated = client.patch(BASE, json={'revision': saved['revision'], 'changes': [
        change(item_id='ingredient:test', field='prep_stage', value='bag_now')], 'status': 'reviewed'})
    assert updated.status_code == 200 and updated.json['status'] == 'reviewed'
    assert len(updated.json['pull_list']) == 1 and updated.json['cook_day_pull'] == []
    assert client.get(BASE).json == updated.json


def test_refresh_commits_then_replay_after_operation_loss_preserves_edits(client, queued, monkeypatch, packet):
    from lib import cooking_packet_jobs as jobs
    def build(week, recipe_dir):
        assert week == '2026-W40' and recipe_dir == paths.recipes_dir()
        assert recipe_phases._REFRESH.get() is not None
        return draft(('cook:58', 'cook:59'))
    monkeypatch.setattr(builder, 'build_week_draft', build)
    start = client.post(BASE+'/refresh', json={'request_id': 'request-1'})
    assert start.status_code == 202
    operation_id = start.json['id']
    assert client.post(BASE+'/refresh', json={'request_id': 'request-1'}).json['id'] == operation_id
    assert client.post(BASE+'/refresh', json={'request_id': 'request-2'}).status_code == 409
    assert client.get(BASE+'/refresh/'+operation_id).json['status'] == 'pending'
    assert store.get_packet('2026-W40') == packet
    queued.pop()()
    done = client.get(BASE+'/refresh/'+operation_id)
    assert done.json['status'] == 'complete' and done.json['revision'] == 2
    assert client.post(BASE+'/refresh', json={'request_id': 'request-1'}).json['id'] == operation_id
    edited = client.patch(BASE, json={'revision': 2, 'changes': [change()]})
    jobs.clear_operations()
    assert client.get(BASE+'/refresh/'+operation_id).status_code == 404
    retry = client.post(BASE+'/refresh', json={'request_id': 'request-1'})
    queued.pop()()
    assert client.get(BASE+'/refresh/'+retry.json['id']).json['status'] == 'complete'
    assert store.get_packet('2026-W40')['revision'] == edited.json['revision']
    assert store.get_packet('2026-W40')['schedule'][0]['text'] == 'Mine'


@pytest.mark.parametrize('failure', ['exception', 'schema'])
def test_failed_refresh_keeps_old_packet_and_sanitizes(client, queued, monkeypatch, packet, failure):
    def build(*args):
        if failure == 'exception':
            raise RuntimeError('PRIVATE_TOKEN <script>')
        return {'version': 999}
    monkeypatch.setattr(builder, 'build_week_draft', build)
    started = client.post(BASE+'/refresh', json={'request_id': 'bad'})
    queued.pop()()
    response = client.get(BASE+'/refresh/'+started.json['id'])
    assert response.json['status'] == 'failed' and 'PRIVATE_TOKEN' not in response.text
    assert store.get_packet('2026-W40') == packet


@pytest.mark.parametrize('body', [{}, [], {'request_id': ''}, {'request_id': 'a', 'extra': 1},
                                    {'request_id': 'x'*129}, {'request_id': '<script>'}])
def test_refresh_rejects_invalid_payload(client, queued, body):
    assert client.post(BASE+'/refresh', json=body).status_code == 400
    assert queued == []


@pytest.mark.parametrize('week', ['2021-W53', '2026-W00', '2026-W4', '2026-W40\n', '<script>', 'x'*200])
def test_all_routes_validate_week(client, queued, week):
    from urllib.parse import quote
    url = '/api/cooking-packets/'+quote(week, safe='')
    assert client.get(url).status_code == 400
    assert client.patch(url, json={'revision': 1, 'changes': []}).status_code == 400
    assert client.post(url+'/refresh', json={'request_id': 'a'}).status_code == 400
    assert client.get(url+'/refresh/unknown').status_code == 400
    for path in ('/cooking-packet', '/print/cooking-packet'):
        response = client.get(path, query_string={'week': week})
        assert response.status_code == 400 and '<script>' not in response.text
    assert queued == []


def test_remote_token_enforced_without_header_bypasses(client, queued, monkeypatch):
    monkeypatch.setenv('KITCHENOS_API_TOKEN', 'a-secret')
    for method, path, body in [('get', BASE, None), ('patch', BASE, {'revision': 1, 'changes': []}),
        ('post', BASE+'/refresh', {'request_id': 'a'}), ('get', BASE+'/refresh/unknown', None)]:
        response = getattr(client, method)(path, json=body, environ_base={'REMOTE_ADDR': '100.64.0.2'},
            headers={'Origin': 'http://localhost', 'Sec-Fetch-Site': 'same-origin'})
        assert response.status_code == 401 and 'a-secret' not in response.text
    assert client.get(BASE, environ_base={'REMOTE_ADDR': '100.64.0.2'},
                      headers={'Authorization': 'Bearer a-secret'}).status_code == 404
    assert client.get(BASE).status_code == 404  # Existing localhost exemption.


def test_pages_only_read_saved_packet(client, monkeypatch, packet):
    def forbidden(*args, **kwargs):
        raise AssertionError('page attempted generation or classification')
    monkeypatch.setattr(builder, 'build_week_draft', forbidden)
    monkeypatch.setattr(recipe_phases, 'classification_refresh', forbidden)
    page = client.get('/cooking-packet?week=2026-W40')
    assert page.status_code == 200 and 'data-week="2026-W40"' in page.text
    assert '{{ week' not in page.text
    printed = client.get('/print/cooking-packet?week=2026-W40')
    assert printed.status_code == 200 and printed.mimetype == 'text/html'
    assert store.get_packet('2026-W40') == packet


def test_print_missing_links_to_builder_and_requires_single_week(client):
    missing = client.get('/print/cooking-packet?week=2026-W40')
    assert missing.status_code == 404 and 'Build cooking packet' in missing.text
    assert '/cooking-packet?week=2026-W40' in missing.text
    for path in ('/cooking-packet', '/print/cooking-packet'):
        assert client.get(path).status_code == 400
        assert client.get(path+'?week=2026-W40&week=2026-W41').status_code == 400


def test_real_builder_refresh_preserves_source_edits(client, queued, monkeypatch):
    monkeypatch.setenv('KITCHENOS_NO_LLM', '1')
    first = client.post(BASE+'/refresh', json={'request_id': 'build-1'})
    queued.pop()()
    assert client.get(BASE+'/refresh/'+first.json['id']).json['revision'] == 1
    assert client.get(BASE).json['week'] == '2026-W40'
    assert client.get(BASE).json['recipe_cards'] == []
    assert client.get('/print/cooking-packet?week=2026-W40').status_code == 200


def test_new_source_refresh_preserves_edit_and_reports_removed_source(client, queued, monkeypatch, packet):
    client.patch(BASE, json={'revision': 1, 'changes': [change()]})
    monkeypatch.setattr(builder, 'build_week_draft', lambda *args: draft(('cook:59', 'cook:58')))
    operation = client.post(BASE+'/refresh', json={'request_id': 'new-source'})
    queued.pop()()
    assert client.get(BASE+'/refresh/'+operation.json['id']).json['status'] == 'complete'
    assert client.get(BASE).json['schedule'][1]['text'] == 'Mine'
    monkeypatch.setattr(builder, 'build_week_draft', lambda *args: draft(('cook:59',)))
    client.post(BASE+'/refresh', json={'request_id': 'removed-source'})
    queued.pop()()
    assert client.get(BASE).json['needs_review'][0]['value'] == 'Mine'


def test_hostile_saved_text_is_escaped_in_print(client):
    source = draft()
    source['title'] = '<script>alert(1)</script>'
    source['recipe_cards'][0]['notes'] = '<img src=x onerror=alert(2)>'
    store.replace_generated('2026-W40', source)
    response = client.get('/print/cooking-packet?week=2026-W40')
    assert response.status_code == 200
    assert '<script>alert(1)' not in response.text and '<img src=x' not in response.text
    assert '&lt;script&gt;' in response.text and '&lt;img' in response.text


def test_operation_status_rejects_oversized_identifier_and_unknown_is_json(client):
    assert client.get(BASE+'/refresh/'+('a'*129)).status_code == 400
    response = client.get(BASE+'/refresh/unknown')
    assert response.status_code == 404 and response.is_json
