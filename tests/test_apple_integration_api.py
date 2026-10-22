"""Bridge HTTP boundaries and real isolated note/SQLite round trips."""
from uuid import uuid4
import pytest
import api_server
from lib import inventory_db as db, paths
from lib.apple_integration import store
from lib.apple_integration.models import canonical_hash
from lib.shopping_note import save_shopping_note, read_shopping_note

BASE = '/api/apple-integration'
OWNER = '00000000-0000-4000-8000-000000000001'
WEEK = '2026-W41'
REMOTE = {'environ_base': {'REMOTE_ADDR': '100.64.0.5'}}
AUTH = {'Authorization': 'Bearer test-secret'}

@pytest.fixture
def client(tmp_db, tmp_vault, monkeypatch):
    monkeypatch.setenv('KITCHENOS_API_TOKEN', 'test-secret')
    with api_server.app.test_client() as client:
        yield client

def owner(client):
    response = client.post(BASE + '/owner', json={'owner_id': OWNER})
    assert response.status_code == 200
    return response.json['context']

def seed():
    paths.shopping_lists_dir().mkdir(parents=True, exist_ok=True)
    return save_shopping_note(WEEK, [{'item':'lime', 'needed': {'amount':2, 'unit':'whole'}, 'to_buy': {'amount':2,'unit':'whole'}}], [])

def activate(client):
    context = owner(client)
    seed()
    response = client.put(BASE + '/scopes/shopping/' + WEEK, json={'domain':'shopping','week':WEEK,'destination_id':'list','state':'active','expected_revision':0})
    assert response.status_code == 200
    return context

def work(client, context):
    response = client.get(BASE + '/work', query_string=context)
    assert response.status_code == 200, response.json
    return response.json

def observe(client, context, items, **extra):
    return client.post(BASE + '/observations', json={'context':context,'request_id':str(uuid4()),'complete':True,'observations':items, **extra})

def observation(item, **changes):
    values = dict(token=item['token'], generation=item['generation'], revision=item['revision'], availability='present', locator={'calendar_id':'list','item_id':'reminder','external_id':None},title=item['title'],fields=item['fields'],absence_confirmed=False,issue=None,has_user_notes=False)
    values.update(changes)
    return values

def saved(client, context, operation):
    return client.post(BASE + '/operations/' + operation['operation_id'] + '/ack', json={'context':context,'operation_id':operation['operation_id'],'outcome':'saved','locator':{'calendar_id':operation['destination_id'],'item_id':'reminder','external_id':None},'observed_fields':operation['fields'],'observed_hash':canonical_hash({'title':operation['title'],'fields':operation['fields']})})

@pytest.mark.parametrize('method,path', [('POST','/owner'),('DELETE','/owner'),('GET','/work'),('POST','/observations'),('POST','/operations/'+OWNER+'/ack')])
def test_local_writer_required_even_with_valid_bearer(client, method, path):
    assert client.open(BASE+path,method=method,json={},headers=AUTH,**REMOTE).status_code == 403
    assert client.open(BASE+path,method=method,json={},headers={'Authorization':'Bearer bad'},**REMOTE).status_code == 401

def test_existing_localhost_token_exemption_is_preserved(client):
    assert client.post(BASE+'/owner',json={'owner_id':OWNER},headers={'Authorization':'Bearer bad'}).status_code == 200

def test_malformed_and_oversized_json_are_rejected(client):
    assert client.post(BASE+'/owner',data='{',content_type='application/json').status_code == 400
    assert client.post(BASE+'/owner',json=[]).status_code == 400
    assert client.post(BASE+'/owner',json={'owner_id':OWNER,'padding':'x'*(2*1024*1024)}).status_code == 413

def test_scope_path_and_revision_validation(client):
    owner(client)
    request = dict(domain='shopping',week=WEEK,destination_id='list',state='active',expected_revision=0)
    assert client.put(BASE+'/scopes/prep/'+WEEK,json=request).status_code == 400
    assert client.put(BASE+'/scopes/shopping/'+WEEK,json=request).status_code == 200
    request['state']='paused'
    assert client.put(BASE+'/scopes/shopping/'+WEEK,json=request).status_code == 409

def test_queue_ack_and_completion_round_trip(client):
    context = activate(client)
    batch = work(client,context)
    assert len(batch['operations']) == 1
    assert store.list_items()[0].common_fields is None
    response = saved(client,context,batch['operations'][0])
    assert response.status_code == 200
    assert response.json['report']['created'] == 1
    item = work(client,context)['items'][0]
    response = observe(client,context,[observation(item,fields={'completed':True,'due':None})])
    assert response.status_code == 200, response.json
    assert read_shopping_note(WEEK).rows[0].completed is True
    assert store.get_item(item['token']).common_fields['completed'] is True

def test_incomplete_or_oversized_batch_has_no_imports(client):
    context = activate(client)
    batch = work(client,context)
    assert saved(client,context,batch['operations'][0]).status_code == 200
    item = work(client,context)['items'][0]
    obs = observation(item,fields={'completed':True,'due':None})
    assert observe(client,context,[obs],complete=False).status_code == 400
    assert observe(client,context,[obs]*5001).status_code == 413
    assert read_shopping_note(WEEK).rows[0].completed is False

def test_stale_or_invalid_later_observation_prevents_earlier_import(client):
    context = activate(client)
    batch = work(client,context)
    saved(client,context,batch['operations'][0])
    item = work(client,context)['items'][0]
    bad = observation(item,token=str(uuid4()))
    assert observe(client,context,[observation(item,fields={'completed':True,'due':None}),bad]).status_code == 409
    assert not read_shopping_note(WEEK).rows[0].completed

def test_moved_reminder_keeps_user_destination_on_source_update(client):
    context = activate(client)
    batch = work(client,context)
    saved(client,context,batch['operations'][0])
    item = work(client,context)['items'][0]
    moved = {'calendar_id':'user-list','item_id':'reminder','external_id':None}
    assert observe(client,context,[observation(item,locator=moved)]).status_code == 200
    seed_doc = read_shopping_note(WEEK)
    path = paths.shopping_lists_dir() / (WEEK+'.md')
    path.write_text(path.read_text().replace('- [ ]','- [x]'))
    item = work(client,context)['items'][0]
    response = observe(client,context,[observation(item,locator=moved,fields={'completed':False,'due':None})])
    assert response.status_code == 200
    assert response.json['operations'][0]['destination_id'] == 'user-list'

def test_native_paused_sender_never_runs_applescript(client,monkeypatch):
    context = activate(client)
    monkeypatch.setattr('lib.reminders.add_to_reminders',lambda *a,**k: pytest.fail('native mode ran AppleScript'))
    assert client.put(BASE+'/settings',json={'paused':True,'expected_revision':1}).status_code == 200
    response=client.post('/send-to-reminders',json={'week':WEEK})
    assert response.status_code == 200
    assert response.json['queued'] >= 1 and response.json['delivered'] == 0

@pytest.mark.parametrize('path', ['/send-to-reminders','/api/prep/reminders','/api/shopping-list/confirm','/api/tasks/'+WEEK+'/id/done'])
def test_touched_senders_and_source_mutations_require_token(client,path):
    assert client.post(path,json={},**REMOTE).status_code == 401

def test_archive_and_default_change_preserve_export_identity(client):
    context=activate(client);batch=work(client,context);saved(client,context,batch['operations'][0])
    original=work(client,context)['items'][0]
    for state,destination,revision in [('archived','list',1),('active','other-list',2)]:
        response=client.put(BASE+'/scopes/shopping/'+WEEK,json={'domain':'shopping','week':WEEK,'destination_id':destination,'state':state,'expected_revision':revision})
        assert response.status_code==200
    batch=work(client,context)
    assert batch['items'][0]['token']==original['token']
    assert batch['items'][0]['locator']['calendar_id']=='list'
    assert batch['operations']==[]

def test_owner_disconnect_requires_quiescence_and_invalidates_context(client):
    context=activate(client)
    assert client.delete(BASE+'/owner',json={'context':context}).status_code==409
    batch=work(client,context);saved(client,context,batch['operations'][0])
    assert client.delete(BASE+'/owner',json={'context':context}).status_code==200
    replacement=client.post(BASE+'/owner',json={'owner_id':str(uuid4())}).json['context']
    assert replacement['owner_generation']>context['owner_generation']
    assert client.get(BASE+'/work',query_string=context).status_code==403
    assert work(client,replacement)['operations']==[]

def test_confirmed_absence_suppresses_until_explicit_new_generation_restore(client):
    context=activate(client);batch=work(client,context);saved(client,context,batch['operations'][0]);item=work(client,context)['items'][0]
    response=observe(client,context,[observation(item,availability='missing',locator=None,title=None,fields={},absence_confirmed=True)])
    assert response.status_code==200
    suppressed=store.get_item(item['token'])
    assert suppressed.state=='suppressed'
    assert work(client,context)['operations']==[]
    restored=client.post(BASE+'/items/'+item['token']+'/restore',json={'expected_revision':suppressed.revision})
    assert restored.status_code==200,restored.json
    assert restored.json['item']['token']!=item['token']
    assert restored.json['item']['generation']==2
    assert len(work(client,context)['operations'])==1

def test_unavailable_does_not_suppress_or_advance_common(client):
    context=activate(client);batch=work(client,context);saved(client,context,batch['operations'][0]);item=work(client,context)['items'][0]
    response=observe(client,context,[observation(item,availability='unavailable',locator=None,title=None,fields={})])
    assert response.status_code==200 and response.json['report']['unavailable']==1
    assert store.get_item(item['token']).state=='active'
    assert store.get_item(item['token']).common_fields=={'completed':False,'due':None}

def test_status_retains_only_current_active_unavailability(client):
    context=activate(client)
    batch=work(client,context)
    assert saved(client,context,batch['operations'][0]).status_code==200
    item=work(client,context)['items'][0]
    assert client.get(BASE+'/status').json['report']['unavailable']==0

    response=observe(client,context,[observation(item,availability='unavailable',locator=None,title=None,fields={})])
    assert response.status_code==200
    assert response.json['report']['unavailable']==1
    assert client.get(BASE+'/status').json['report']['unavailable']==1
    assert work(client,context)['report']['unavailable']==1

    save_shopping_note(WEEK,[{'item':'lime','needed':{'amount':3,'unit':'whole'},'to_buy':{'amount':3,'unit':'whole'}}],[])
    refreshed=work(client,context)['items'][0]
    assert refreshed['revision']>item['revision']
    assert client.get(BASE+'/status').json['report']['unavailable']==0

    assert observe(client,context,[observation(refreshed,availability='unavailable',locator=None,title=None,fields={})]).status_code==200
    assert client.get(BASE+'/status').json['report']['unavailable']==1
    paused=client.put(BASE+'/scopes/shopping/'+WEEK,json={'domain':'shopping','week':WEEK,'destination_id':'list','state':'paused','expected_revision':1})
    assert paused.status_code==200
    assert client.get(BASE+'/status').json['report']['unavailable']==0

    save_shopping_note(WEEK,[],[])
    resumed=client.put(BASE+'/scopes/shopping/'+WEEK,json={'domain':'shopping','week':WEEK,'destination_id':'list','state':'active','expected_revision':2})
    assert resumed.status_code==200
    assert work(client,context)['items'][0]['state']=='retired'
    assert client.get(BASE+'/status').json['report']['unavailable']==0

def test_retained_reappearance_blocks_duplicate_until_explicit_detach(client):
    context=activate(client);batch=work(client,context);saved(client,context,batch['operations'][0]);item=work(client,context)['items'][0]
    save_shopping_note(WEEK,[],[])
    retired=work(client,context)['items'][0]
    assert retired['state']=='retired'
    seed(); batch=work(client,context)
    assert batch['items'][0]['generation']==2
    assert batch['operations']==[]
    status=client.get(BASE+'/status').json
    conflict=next(c for c in status['conflicts'] if c['field']=='retained_generation')
    response=client.post(BASE+'/conflicts/'+conflict['conflict_id']+'/resolve',json={'choice':'keep_manual','expected_revision':conflict['revision']})
    assert response.status_code==200,response.json
    assert store.get_item(item['token']).locator is None
    assert len(work(client,context)['operations'])==1

def test_retained_explicit_deletion_ack_never_mutates_replacement(client):
    context=activate(client);batch=work(client,context);saved(client,context,batch['operations'][0]);old=work(client,context)['items'][0]
    save_shopping_note(WEEK,[],[]);work(client,context);seed();replacement=work(client,context)['items'][0]
    retained=store.get_item(old['token']).to_dict()
    request={'context':context,'request_id':str(uuid4()),'items':[{'token':old['token'],'expected_revision':retained['revision'],'observation':observation(retained)}]}
    response=client.post(BASE+'/items/remove-owned',json=request)
    assert response.status_code==200,response.json
    op=response.json['operations'][0]
    response=client.post(BASE+'/operations/'+op['operation_id']+'/ack',json={'context':context,'operation_id':op['operation_id'],'outcome':'deleted','locator':None,'observed_fields':{},'observed_hash':None})
    assert response.status_code==200,response.json
    assert store.get_item(replacement['token']).to_dict()==replacement
    assert store.get_item(old['token']).locator is None
    assert len(work(client,context)['operations'])==1

def test_request_retry_is_inert_and_changed_payload_rejected(client):
    context=activate(client);batch=work(client,context);saved(client,context,batch['operations'][0]);item=work(client,context)['items'][0]
    payload={'context':context,'request_id':str(uuid4()),'complete':True,'observations':[observation(item,fields={'completed':True,'due':None})]}
    first=client.post(BASE+'/observations',json=payload)
    assert first.status_code==200
    current=store.get_item(item['token'])
    assert client.post(BASE+'/observations',json=payload).status_code==200
    assert store.get_item(item['token'])==current
    payload['observations'][0]['fields']['completed']=False
    assert client.post(BASE+'/observations',json=payload).status_code==409

def test_due_conflict_requires_explicit_choice(client):
    context=activate(client);batch=work(client,context);saved(client,context,batch['operations'][0]);item=work(client,context)['items'][0]
    store.set_due_override(item['token'],{'date':'2026-10-09','time':None,'timezone':None},expected_revision=item['revision'])
    item=work(client,context)['items'][0]
    apple_due={'date':'2026-10-10','time':None,'timezone':None}
    assert observe(client,context,[observation(item,fields={'completed':False,'due':apple_due})]).status_code==200
    assert store.get_item(item['token']).common_fields['due'] is None
    conflict=client.get(BASE+'/status').json['conflicts'][0]
    url=BASE+'/conflicts/'+conflict['conflict_id']+'/resolve'
    assert client.post(url,json={'choice':'keep_apple','expected_revision':99}).status_code==409
    result=client.post(url,json={'choice':'keep_apple','expected_revision':conflict['revision']})
    assert result.status_code==200,result.json
    assert store.get_item(item['token']).fields['due']==apple_due
    assert client.get(BASE+'/status').json['conflicts']==[]

def test_shopping_quantity_conflict_resolution_keeps_choice_and_identity(client):
    context=activate(client);batch=work(client,context);saved(client,context,batch['operations'][0]);item=work(client,context)['items'][0]
    path=paths.shopping_lists_dir()/(WEEK+'.md')
    path.write_text(path.read_text().replace('- [ ]','- [x]'))
    save_shopping_note(WEEK,[{'item':'lime','needed':{'amount':3,'unit':'whole'},'to_buy':{'amount':3,'unit':'whole'}}],[])
    work(client,context)
    conflict=next(c for c in client.get(BASE+'/status').json['conflicts'] if c['field']=='shopping_amount_changed')
    response=client.post(BASE+'/conflicts/'+conflict['conflict_id']+'/resolve',json={'choice':'keep_kitchenos','expected_revision':conflict['revision']})
    assert response.status_code==200,response.json
    doc=read_shopping_note(WEEK)
    assert not doc.issues and not doc.rows[0].completed
    assert doc.rows[0].id==item['logical_id']

@pytest.mark.parametrize('state', ['paused','offline','active'])
def test_cli_native_mode_never_calls_legacy_clear_or_send(client,monkeypatch,state,capsys):
    import shopping_list as cli
    context=activate(client)
    if state=='paused':
        client.put(BASE+'/settings',json={'paused':True,'expected_revision':1})
    elif state=='offline':
        batch=work(client,context);saved(client,context,batch['operations'][0])
        assert client.delete(BASE+'/owner',json={'context':context}).status_code==200
    monkeypatch.setattr(cli,'resolve_meal_plan_path',lambda args:paths.meal_plans_dir()/(WEEK+'.md'))
    monkeypatch.setattr(cli,'generate_shopping_list_from_path',lambda *a,**k:{'success':True,'recipes':[],'items':['2 limes'],'lines':[{'item':'lime','needed':{'amount':2,'unit':'whole'},'to_buy':{'amount':2,'unit':'whole'}}],'inventory_matches':[]})
    for name in ['create_reminders_list','clear_reminders_list','add_to_reminders']:
        monkeypatch.setattr(cli,name,lambda *a,**k:pytest.fail('Native CLI ran AppleScript'))
    monkeypatch.setattr('sys.argv',['shopping_list.py','--week',WEEK,'--no-pantry','--no-interactive'])
    cli.main()
    assert 'queued' in capsys.readouterr().out.lower()

def test_partial_present_fields_rejected_before_import(client):
    context=activate(client);batch=work(client,context);saved(client,context,batch['operations'][0]);item=work(client,context)['items'][0]
    assert observe(client,context,[observation(item,fields={'completed':True})]).status_code==400
    assert not read_shopping_note(WEEK).rows[0].completed

def test_missing_source_blocks_stale_pending_export(client):
    context=activate(client)
    (paths.shopping_lists_dir()/(WEEK+'.md')).unlink()
    batch=work(client,context)
    assert batch['operations']==[] and batch['report']['unavailable']==1

def test_work_replays_split_completion_due_import_before_refresh(client,monkeypatch):
    from lib.apple_integration import shopping
    context=activate(client);batch=work(client,context);saved(client,context,batch['operations'][0]);item=store.get_item(work(client,context)['items'][0]['token'])
    original=store.finish_source_patch
    monkeypatch.setattr(store,'finish_source_patch',lambda *a,**k:(_ for _ in ()).throw(OSError('disk')))
    with pytest.raises(OSError):
        shopping.apply(item,{'completed':True,'due':{'date':'2026-10-11','time':None,'timezone':None}},str(uuid4()))
    assert read_shopping_note(WEEK).rows[0].completed
    monkeypatch.setattr(store,'finish_source_patch',original)
    response=work(client,context)
    assert response['items'][0]['fields']=={'completed':True,'due':{'date':'2026-10-11','time':None,'timezone':None}}
    assert store.pending_source_patches('shopping')==[]

def test_restore_of_missing_source_does_not_retire_suppressed_item(client):
    context=activate(client);batch=work(client,context);saved(client,context,batch['operations'][0]);item=work(client,context)['items'][0]
    observe(client,context,[observation(item,availability='missing',locator=None,title=None,fields={},absence_confirmed=True)])
    current=store.get_item(item['token'])
    (paths.shopping_lists_dir()/(WEEK+'.md')).unlink()
    response=client.post(BASE+'/items/'+item['token']+'/restore',json={'expected_revision':current.revision})
    assert response.status_code==503
    assert store.get_item(item['token'])==current

def test_source_title_change_exports_unless_user_changed_apple_title(client):
    context=activate(client);batch=work(client,context);saved(client,context,batch['operations'][0]);old=work(client,context)['items'][0]
    save_shopping_note(WEEK,[{'item':'lime','needed':{'amount':3,'unit':'whole'},'to_buy':{'amount':3,'unit':'whole'}}],[])
    item=work(client,context)['items'][0]
    response=observe(client,context,[observation(item,title=old['title'])])
    assert response.status_code==200,response.json
    assert len(response.json['operations'])==1
    assert response.json['operations'][0]['title']==item['title']
    saved(client,context,response.json['operations'][0])
    item=work(client,context)['items'][0]
    response=observe(client,context,[observation(item,title='My fruit')])
    assert response.status_code==200
    assert store.get_item(item['token']).title=='My fruit'
    assert read_shopping_note(WEEK).rows[0].text!='My fruit'

@pytest.mark.parametrize('path,payload', [('/owner',{'owner_id':OWNER,'permissions':{'shopping':[]}}),('/conflicts/'+OWNER+'/resolve',{'choice':[],'expected_revision':1}),('/items/remove-owned',{'context':{'owner_id':OWNER,'owner_generation':1},'request_id':OWNER,'items':[{'token':[],'expected_revision':1,'observation':{}}]})])
def test_nested_malformed_values_return_400_not_500(client,path,payload):
    assert client.post(BASE+path,json=payload).status_code==400

def test_recovery_conflict_is_visible_in_status(client,monkeypatch):
    from lib.apple_integration import shopping
    context=activate(client);batch=work(client,context);saved(client,context,batch['operations'][0]);item=store.get_item(work(client,context)['items'][0]['token'])
    original=store.finish_source_patch
    monkeypatch.setattr(store,'finish_source_patch',lambda *a,**k:(_ for _ in ()).throw(OSError('disk')))
    with pytest.raises(OSError):
        shopping.apply(item,{'completed':True,'due':None},str(uuid4()))
    path=paths.shopping_lists_dir()/(WEEK+'.md');path.write_text(path.read_text()+'\nIndependent edit\n')
    monkeypatch.setattr(store,'finish_source_patch',original)
    work(client,context)
    assert any(c['field']=='source_recovery' for c in client.get(BASE+'/status').json['conflicts'])

def test_interrupted_multi_item_request_resumes_without_overtaking(client,monkeypatch):
    from lib.apple_integration import service
    context=activate(client)
    save_shopping_note(WEEK,[{'item':'lime','needed':{'amount':2,'unit':'whole'},'to_buy':{'amount':2,'unit':'whole'}}],[],selected_items=[read_shopping_note(WEEK).rows[0].text,'Tea'])
    batch=work(client,context)
    for op in batch['operations']:
        assert saved(client,context,op).status_code==200
    batch=work(client,context)
    observations=[observation(i,fields={'completed':True,'due':None},locator={'calendar_id':'list','item_id':i['token'],'external_id':None}) for i in batch['items']]
    payload={'context':context,'request_id':str(uuid4()),'complete':True,'observations':observations}
    original=store.finish_source_patch
    attempts=[]
    def fail_second(*args,**kwargs):
        attempts.append(1)
        if len(attempts)==2:
            raise OSError('interruption after second file write')
        return original(*args,**kwargs)
    monkeypatch.setattr(store,'finish_source_patch',fail_second)
    response=client.post(BASE+'/observations',json=payload)
    assert response.status_code==503
    monkeypatch.setattr(store,'finish_source_patch',original)
    # A new service module instance has no in-memory retry information.
    import importlib
    importlib.reload(service)
    response=observe(client,context,[])
    assert response.status_code==409
    batch=work(client,context)
    assert batch['retry_requests']==[{'request_id':payload['request_id'],'observations':observations}]
    assert client.post(BASE+'/observations',json=payload).status_code==200
    assert work(client,context)['retry_requests']==[]
    assert all(r.completed for r in read_shopping_note(WEEK).rows)
    assert all(i.common_fields['completed'] for i in store.list_items())

def test_cleanup_request_retry_is_bound_to_exact_payload(client):
    context=activate(client);batch=work(client,context);saved(client,context,batch['operations'][0]);item=work(client,context)['items'][0]
    payload={'context':context,'request_id':str(uuid4()),'items':[{'token':item['token'],'expected_revision':item['revision'],'observation':observation(item)}]}
    first=client.post(BASE+'/items/remove-owned',json=payload)
    assert first.status_code==200
    assert client.post(BASE+'/items/remove-owned',json=payload).json==first.json
    payload['items'][0]['observation']['title']='changed'
    assert client.post(BASE+'/items/remove-owned',json=payload).status_code==409

def test_shopping_resolution_retry_after_file_db_split_recovers(client,monkeypatch):
    context=activate(client);batch=work(client,context);saved(client,context,batch['operations'][0]);item=work(client,context)['items'][0]
    path=paths.shopping_lists_dir()/(WEEK+'.md');path.write_text(path.read_text().replace('- [ ]','- [x]'))
    save_shopping_note(WEEK,[{'item':'lime','needed':{'amount':3,'unit':'whole'},'to_buy':{'amount':3,'unit':'whole'}}],[])
    work(client,context);conflict=client.get(BASE+'/status').json['conflicts'][0]
    original=store.refresh_source
    monkeypatch.setattr(store,'refresh_source',lambda *a,**k:(_ for _ in ()).throw(OSError('journal unavailable')))
    url=BASE+'/conflicts/'+conflict['conflict_id']+'/resolve'
    payload={'choice':'keep_kitchenos','expected_revision':conflict['revision']}
    assert client.post(url,json=payload).status_code==503
    monkeypatch.setattr(store,'refresh_source',original)
    assert client.post(url,json=payload).status_code==200
    assert not read_shopping_note(WEEK).issues

def test_calendar_confirmed_absence_unschedules_without_cooking_or_retained_block(client):
    from tests.test_cook_schedule import cook,args
    from lib import serving_ledger as sl
    context=owner(client)
    c=cook();sl.schedule_cook(c['id'],**args())
    week=c['week']
    response=client.put(BASE+'/scopes/cooking/'+week,json={'domain':'cooking','week':week,'destination_id':'calendar','state':'active','expected_revision':0})
    assert response.status_code==200
    batch=work(client,context);assert saved(client,context,batch['operations'][0]).status_code==200
    item=work(client,context)['items'][0];before=sl.get_cook(c['id'])
    response=observe(client,context,[observation(item,availability='missing',locator=None,title=None,fields={},absence_confirmed=True)])
    assert response.status_code==200,response.json
    assert sl.get_cook(c['id'])==before
    assert sl.schedules_for_week(week)==[]
    assert store.get_item(item['token']).locator is None
    sl.schedule_cook(c['id'],**args())
    assert len(work(client,context)['operations'])==1

def test_shared_models_decode_full_work_and_status_envelopes(client):
    from lib.apple_integration.models import WorkBatch,IntegrationStatus,OwnedRemovalItem
    context=activate(client)
    batch=WorkBatch.from_dict(work(client,context))
    assert len(batch.items)==1 and batch.retry_requests==[]
    status=IntegrationStatus.from_dict(client.get(BASE+'/status').json)
    assert status.configured and status.settings_revision==1
    item=batch.items[0].to_dict()
    removal=OwnedRemovalItem.from_dict({'token':item['token'],'expected_revision':item['revision'],'observation':observation(item)})
    assert removal.observation.generation==1

def test_work_recovers_resolution_before_refreshing_source(client,monkeypatch):
    context=activate(client);batch=work(client,context);saved(client,context,batch['operations'][0])
    path=paths.shopping_lists_dir()/(WEEK+'.md');path.write_text(path.read_text().replace('- [ ]','- [x]'))
    save_shopping_note(WEEK,[{'item':'lime','needed':{'amount':3,'unit':'whole'},'to_buy':{'amount':3,'unit':'whole'}}],[])
    work(client,context);conflict=client.get(BASE+'/status').json['conflicts'][0]
    original=store.refresh_source
    monkeypatch.setattr(store,'refresh_source',lambda *a,**k:(_ for _ in ()).throw(OSError('journal unavailable')))
    assert client.post(BASE+'/conflicts/'+conflict['conflict_id']+'/resolve',json={'choice':'keep_kitchenos','expected_revision':conflict['revision']}).status_code==503
    monkeypatch.setattr(store,'refresh_source',original)
    batch=work(client,context)
    assert batch['items'][0]['state']=='active'
    assert client.get(BASE+'/status').json['conflicts']==[]

def test_retained_work_is_separate_and_combined_bounds_fail_without_truncation(client,monkeypatch):
    from lib.apple_integration import service
    context=activate(client);batch=work(client,context);saved(client,context,batch['operations'][0]);old=batch['items'][0]
    save_shopping_note(WEEK,[],[]);work(client,context);seed()
    batch=work(client,context)
    assert len(batch['items'])==1 and batch['retained_items'][0]['token']==old['token']
    monkeypatch.setattr(service,'MAX_ITEMS',1)
    assert client.get(BASE+'/work',query_string=context).status_code==413

def test_native_title_override_is_stable_across_repeated_observations(client):
    context=activate(client);batch=work(client,context);saved(client,context,batch['operations'][0]);item=work(client,context)['items'][0]
    assert observe(client,context,[observation(item,title='My fruit')]).status_code==200
    renamed=store.get_item(item['token'])
    for _ in range(3):
        current=work(client,context)['items'][0]
        assert observe(client,context,[observation(current,title='My fruit')]).status_code==200
    assert store.get_item(item['token'])==renamed

@pytest.mark.parametrize('changes', [dict(availability='unavailable',locator=None,title=None,fields={}),dict(issue='identity_ambiguous')])
def test_unavailable_or_conflicted_observation_withholds_pending_create(client,changes):
    context=activate(client);item=work(client,context)['items'][0]
    response=observe(client,context,[observation(item,**changes)])
    assert response.status_code==200
    assert response.json['operations']==[]
    assert work(client,context)['operations']==[]

def test_conflict_restore_uses_single_recovery_pass(client):
    from lib.apple_integration.models import canonical_json
    context=activate(client);batch=work(client,context);saved(client,context,batch['operations'][0]);item=work(client,context)['items'][0]
    observe(client,context,[observation(item,availability='missing',locator=None,title=None,fields={},absence_confirmed=True)])
    suppressed=store.get_item(item['token']);conflict_id=str(uuid4())
    with db.write_transaction() as conn:
        conn.execute('INSERT INTO apple_conflicts(conflict_id,token,field,source) VALUES(?,?,?,?)',(conflict_id,item['token'],'source_recovery',canonical_json(suppressed.to_dict())))
    response=client.post(BASE+'/conflicts/'+conflict_id+'/resolve',json={'choice':'restore','expected_revision':1})
    assert response.status_code==200,response.json
    assert len(work(client,context)['operations'])==1

def test_owner_change_before_request_reservation_rejects_old_import(client,monkeypatch):
    from lib.apple_integration import service
    context=activate(client);batch=work(client,context);saved(client,context,batch['operations'][0]);item=work(client,context)['items'][0]
    original=service._refresh
    def owner_changes_after_refresh():
        result=original()
        service.disconnect(service.BridgeContext.from_dict(context))
        service.register_owner(str(uuid4()))
        return result
    monkeypatch.setattr(service,'_refresh',owner_changes_after_refresh)
    response=observe(client,context,[observation(item,fields={'completed':True,'due':None})])
    assert response.status_code==403,response.json
    assert not read_shopping_note(WEEK).rows[0].completed
    with db.connect() as conn:
        assert conn.execute('SELECT COUNT(*) FROM apple_requests').fetchone()[0]==0


def test_lost_first_save_ack_recovers_from_exact_journal_after_restart(client):
    from lib.apple_integration import service
    import importlib
    context=activate(client)
    first=work(client,context)
    operation=first['operations'][0]
    # EventKit saved the reserved title/fields, but its acknowledgement was lost.
    importlib.reload(service)
    fresh=work(client,context)
    response=observe(client,context,[observation(fresh['items'][0])])
    assert response.status_code==200,response.json
    assert response.json['operations']==[]
    recovered=store.get_item(operation['token'])
    assert recovered.common_fields=={'completed':False,'due':None}
    assert recovered.locator.item_id=='reminder'
    assert client.get(BASE+'/status').json['conflicts']==[]
    assert work(client,context)['operations']==[]
    with db.connect() as conn:
        rows=conn.execute('SELECT operation_id,status FROM apple_operations').fetchall()
    assert [(r['operation_id'],r['status']) for r in rows]==[(operation['operation_id'],'acknowledged')]


@pytest.mark.parametrize('change', ['title','fields','unexplained'])
def test_first_present_object_without_exact_pending_save_still_conflicts(client,change):
    context=activate(client);batch=work(client,context);item=batch['items'][0]
    changes={}
    if change=='title':
        changes['title']='Unexplained changed title'
    elif change=='fields':
        changes['fields']={'completed':True,'due':None}
    else:
        with db.write_transaction() as conn:
            conn.execute("UPDATE apple_operations SET status='superseded'")
    response=observe(client,context,[observation(item,**changes)])
    assert response.status_code==200
    assert store.get_item(item['token']).common_fields is None
    assert any(c['field']=='recovery' for c in client.get(BASE+'/status').json['conflicts'])
    assert not read_shopping_note(WEEK).rows[0].completed


def test_retained_cleanup_survives_work_polls_and_restart_until_ack(client):
    from lib.apple_integration import service
    import importlib
    context=activate(client);batch=work(client,context);saved(client,context,batch['operations'][0]);old=batch['items'][0]
    save_shopping_note(WEEK,[],[]);work(client,context);seed();replacement=work(client,context)['items'][0]
    retained=store.get_item(old['token']).to_dict()
    response=client.post(BASE+'/items/remove-owned',json={'context':context,'request_id':str(uuid4()),'items':[{'token':retained['token'],'expected_revision':retained['revision'],'observation':observation(retained)}]})
    assert response.status_code==200
    deletion=response.json['operations'][0]
    for _ in range(2):
        assert work(client,context)['operations']==[deletion]
    importlib.reload(service)
    assert work(client,context)['operations']==[deletion]
    response=client.post(BASE+'/operations/'+deletion['operation_id']+'/ack',json={'context':context,'operation_id':deletion['operation_id'],'outcome':'deleted','locator':None,'observed_fields':{},'observed_hash':None})
    assert response.status_code==200,response.json
    assert store.get_item(replacement['token']).to_dict()==replacement
    assert store.get_item(retained['token']).locator is None
    assert len(work(client,context)['operations'])==1


@pytest.mark.parametrize('empty', [False,True])
def test_observation_response_filters_pending_operations_from_unavailable_scope(client,empty):
    context=activate(client)
    other_week='2026-W42'
    save_shopping_note(other_week,[{'item':'tea','needed':{'amount':1,'unit':'whole'},'to_buy':{'amount':1,'unit':'whole'}}],[])
    assert client.put(BASE+'/scopes/shopping/'+other_week,json={'domain':'shopping','week':other_week,'destination_id':'list','state':'active','expected_revision':0}).status_code==200
    batch=work(client,context)
    healthy=next(i for i in batch['items'] if i['week']==WEEK)
    unavailable=next(i for i in batch['items'] if i['week']==other_week)
    (paths.shopping_lists_dir()/(other_week+'.md')).unlink()
    observations=[] if empty else [observation(healthy,availability='missing',locator=None,title=None,fields={},absence_confirmed=True)]
    payload={'context':context,'request_id':str(uuid4()),'complete':True,'observations':observations}
    response=client.post(BASE+'/observations',json=payload)
    assert response.status_code==200,response.json
    assert {o['token'] for o in response.json['operations']}=={healthy['token']}
    assert unavailable['token'] not in {o['token'] for o in client.post(BASE+'/observations',json=payload).json['operations']}


def test_completed_observation_replay_rechecks_scope_availability(client):
    context=activate(client)
    payload={'context':context,'request_id':str(uuid4()),'complete':True,'observations':[]}
    response=client.post(BASE+'/observations',json=payload)
    assert response.status_code==200 and len(response.json['operations'])==1
    (paths.shopping_lists_dir()/(WEEK+'.md')).unlink()
    response=client.post(BASE+'/observations',json=payload)
    assert response.status_code==200
    assert response.json['operations']==[]
