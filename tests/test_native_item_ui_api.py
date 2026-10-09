"""Read-only native source views and exact checkbox updates in isolated data."""
from uuid import uuid4
import pytest
import api_server
from lib import paths, inventory_db as db
from lib.shopping_note import save_shopping_note, read_shopping_note
from lib.apple_integration import store

WEEK = '2026-W41'
BASE = '/api/shopping-list/saved/' + WEEK
REMOTE = {'environ_base': {'REMOTE_ADDR': '100.64.0.5'}}
AUTH = {'Authorization': 'Bearer test-secret'}

@pytest.fixture
def client(tmp_db, tmp_vault, monkeypatch):
    monkeypatch.setenv('KITCHENOS_API_TOKEN', 'test-secret')
    with api_server.app.test_client() as client:
        yield client

def seed():
    paths.shopping_lists_dir().mkdir(parents=True, exist_ok=True)
    return save_shopping_note(WEEK, [], [], selected_items=['2 limes', '2 limes'])

def test_saved_get_preserves_exact_distinct_ids_and_bytes(client):
    document=seed()
    path=paths.shopping_lists_dir() / (WEEK+'.md')
    before=path.read_bytes()
    result=client.get(BASE)
    assert result.status_code==200
    assert [r['id'] for r in result.json['rows']]==[r.id for r in document.rows]
    assert len(set(r['id'] for r in result.json['rows']))==2
    assert result.json['content_hash']==document.content_hash
    assert path.read_bytes()==before

def test_checkbox_changes_exact_id_and_never_spends_inventory(client, monkeypatch):
    doc=seed()
    monkeypatch.setattr(api_server.pantry_module, 'apply_decisions', lambda *a: pytest.fail('checkbox spent pantry'))
    body=dict(row_id=doc.rows[1].id,completed=True,expected_hash=doc.content_hash,operation_id=str(uuid4()))
    result=client.post(BASE+'/completion',json=body)
    assert result.status_code==200, result.json
    assert [r.completed for r in read_shopping_note(WEEK).rows]==[False,True]
    assert client.post(BASE+'/completion',json=body).status_code==200
    body['operation_id']=str(uuid4());body['completed']=False
    assert client.post(BASE+'/completion',json=body).status_code==409
    assert [r.completed for r in read_shopping_note(WEEK).rows]==[False,True]

def test_saved_routes_require_auth_and_validate_without_creating_notes(client):
    for method,path in [('GET',BASE),('POST',BASE+'/completion'),('GET','/api/apple-integration/items'),('GET','/api/apple-integration/conflicts/'+str(uuid4()))]:
        assert client.open(path,method=method,json={},**REMOTE).status_code==401
    assert client.get(BASE,headers=AUTH,**REMOTE).status_code==404
    assert client.get('/api/shopping-list/saved/2021-W53').status_code==400
    assert client.post(BASE+'/completion',json=[]).status_code==400
    assert client.post(BASE+'/completion',json=dict(row_id='manual:a',completed=1,expected_hash='a'*64,operation_id=str(uuid4()))).status_code==400
    assert not (paths.shopping_lists_dir()/(WEEK+'.md')).exists()

def test_item_read_is_bounded_and_conflict_detail_keeps_revision(client):
    from lib.apple_integration import service
    owner=str(uuid4())
    service.register_owner(owner)
    seed()
    client.put('/api/apple-integration/scopes/shopping/'+WEEK,json=dict(domain='shopping',week=WEEK,destination_id='list',state='active',expected_revision=0))
    item=store.list_items()[0]
    service._conflict(item,'completed',None)
    with db.connect() as conn:
        before=conn.total_changes
        conflict=dict(conn.execute('SELECT * FROM apple_conflicts').fetchone())
    result=client.get('/api/apple-integration/items?domain=shopping&week='+WEEK)
    assert result.status_code==200
    assert result.json['items'][0]['token']==item.token
    assert result.json['items'][0]['revision']==item.revision
    detail=client.get('/api/apple-integration/conflicts/'+conflict['conflict_id'])
    assert detail.status_code==200, detail.json
    assert detail.json['revision']==conflict['revision']
    assert detail.json['source']['title']==item.title
    assert detail.json['field']=='completed'
    assert client.get('/api/apple-integration/items?domain=nope&week='+WEEK).status_code==400
    with db.connect() as conn:
        assert conn.execute('SELECT COUNT(*) FROM apple_conflicts').fetchone()[0]==1


def test_saved_prep_missing_does_not_generate_or_write(client, monkeypatch):
    monkeypatch.setattr(api_server.task_extractor, 'extract_tasks', lambda *a, **k: pytest.fail('link generated tasks'))
    assert client.get('/api/tasks/'+WEEK+'/saved', **REMOTE).status_code==401
    assert client.get('/api/tasks/'+WEEK+'/saved').status_code==404
    assert not api_server.task_extractor._sidecar_path(WEEK).exists()


def test_conflict_choices_do_not_offer_restore_for_active_item(client):
    from lib.apple_integration import service
    service.register_owner(str(uuid4())); seed()
    client.put('/api/apple-integration/scopes/shopping/'+WEEK,json=dict(domain='shopping',week=WEEK,destination_id='list',state='active',expected_revision=0))
    item=store.list_items()[0]
    conflict=service._conflict(item,'identity_ambiguous')
    result=client.get('/api/apple-integration/conflicts/'+conflict)
    assert result.status_code==200
    assert result.json['choices']==['keep_manual']
    shopping=service._conflict(item,'shopping_amount_changed')
    result=client.get('/api/apple-integration/conflicts/'+shopping)
    # Synthetic/older shopping evidence has no generated acceptance target.
    assert result.json['shopping_demand'] is None
    assert result.json['choices']==['keep_manual']


@pytest.mark.parametrize('field,expected', [
    ('source_recovery', ['keep_manual']),
    ('recovery', ['keep_kitchenos','keep_apple','keep_manual']),
    ('completed', ['keep_kitchenos','keep_apple','keep_manual']),
    ('due', ['keep_kitchenos','keep_apple','keep_manual']),
    ('retained_generation', ['keep_manual']),
])
def test_recovery_choices_follow_resolver_fields(client, field, expected):
    from lib.apple_integration import service
    from lib.apple_integration.models import Observation, Locator, RevisionConflict
    service.register_owner(str(uuid4())); seed()
    client.put('/api/apple-integration/scopes/shopping/'+WEEK,json=dict(domain='shopping',week=WEEK,destination_id='list',state='active',expected_revision=0))
    item=store.list_items()[0]
    observation=Observation(item.token,item.generation,item.revision,'present',Locator('list','reminder',None),
                            item.title,{'completed':True,'due':None},False,None)
    conflict=service._conflict(item,field,observation)
    detail=client.get('/api/apple-integration/conflicts/'+conflict)
    assert detail.status_code==200
    assert detail.json['choices']==expected
    if field=='source_recovery':
        # This is the resolver's actual rejection, not a presumed UI allowlist.
        with pytest.raises(RevisionConflict, match='No valid Apple value to keep'):
            service.resolve_conflict(conflict,'keep_apple',detail.json['revision'],_recover_first=False)


@pytest.mark.parametrize('suppressed', [False,True])
def test_source_recovery_choices_do_not_probe_or_claim_unavailable_source(client, monkeypatch, suppressed):
    from lib.apple_integration import service, shopping
    from lib.apple_integration.models import Observation, Locator
    service.register_owner(str(uuid4())); seed()
    client.put('/api/apple-integration/scopes/shopping/'+WEEK,json=dict(domain='shopping',week=WEEK,destination_id='list',state='active',expected_revision=0))
    item=store.list_items()[0]
    if suppressed:
        item=store.set_suppressed(item.token,True,expected_revision=item.revision)
    observation=Observation(item.token,item.generation,item.revision,'present',Locator('list','reminder',None),
                            item.title,{'completed':True,'due':None},False,None)
    conflict=service._conflict(item,'source_recovery',observation)
    monkeypatch.setattr(shopping,'collect',lambda *a: pytest.fail('read-only detail probed source recovery'))
    before=(paths.shopping_lists_dir()/(WEEK+'.md')).read_bytes()
    detail=client.get('/api/apple-integration/conflicts/'+conflict)
    assert detail.status_code==200
    assert detail.json['choices']==(['keep_manual','restore'] if suppressed else ['keep_manual'])
    service.resolve_conflict(conflict,'keep_manual',detail.json['revision'],_recover_first=False)
    assert (paths.shopping_lists_dir()/(WEEK+'.md')).read_bytes()==before


def test_item_details_reads_retained_and_replacement_generations(client):
    """A historical generation must not make the whole native detail view 409."""
    from dataclasses import replace
    from lib.apple_integration import service, shopping
    service.register_owner(str(uuid4()))
    seed()
    store.activate_scope('shopping', WEEK, 'list')
    source = shopping.collect(WEEK)[0]
    first = store.refresh_source(source)
    store.refresh_source(replace(source, state='retired'))
    replacement = store.refresh_source(source)
    assert replacement.generation == first.generation + 1

    response = client.get('/api/apple-integration/items?domain=shopping&week=' + WEEK)

    assert response.status_code == 200, response.json
    assert {entry['token'] for entry in response.json['items']} >= {first.token, replacement.token}


@pytest.mark.parametrize('state', ['suppressed', 'conflict'])
def test_inactive_item_conflict_offers_only_available_choices(client, state):
    from dataclasses import replace
    from lib.apple_integration import service, shopping
    from lib.apple_integration.models import Observation, Locator
    service.register_owner(str(uuid4())); seed()
    store.activate_scope('shopping', WEEK, 'list')
    item = store.refresh_source(shopping.collect(WEEK)[0])
    if state == 'suppressed':
        item = store.set_suppressed(item.token, True, expected_revision=item.revision)
    else:
        item = store.refresh_source(replace(shopping.collect(WEEK)[0], state='conflict'))
    observation = Observation(item.token, item.generation, item.revision, 'present',
                              Locator('list', 'reminder', None), item.title,
                              {'completed': True, 'due': None}, False, None)
    conflict = service._conflict(item, 'completed', observation)
    detail = client.get('/api/apple-integration/conflicts/' + conflict)
    assert detail.status_code == 200
    assert detail.json['choices'] == (['keep_manual', 'restore'] if state == 'suppressed' else ['keep_manual'])
    for choice in ('keep_kitchenos', 'keep_apple'):
        response = client.post('/api/apple-integration/conflicts/' + conflict + '/resolve',
                               json={'choice': choice, 'expected_revision': detail.json['revision']})
        assert response.status_code == 409


def test_stale_source_conflict_hides_values_that_cannot_be_accepted(client):
    from dataclasses import replace
    from lib.apple_integration import service, shopping
    from lib.apple_integration.models import Observation, Locator
    service.register_owner(str(uuid4())); seed()
    store.activate_scope('shopping', WEEK, 'list')
    item = store.refresh_source(shopping.collect(WEEK)[0])
    observation = Observation(item.token, item.generation, item.revision, 'present',
                              Locator('list', 'reminder', None), item.title,
                              {'completed': True, 'due': None}, False, None)
    conflict = service._conflict(item, 'completed', observation)
    store.refresh_source(replace(shopping.collect(WEEK)[0], source_revision='b' * 64))
    detail = client.get('/api/apple-integration/conflicts/' + conflict)
    assert detail.status_code == 200
    assert detail.json['choices'] == ['keep_manual']
