"""Native bridge orchestration; source recovery precedes every refresh/export.

No transaction spans a note adapter, EventKit, or network request. The native
writer verifies per-object ownership and the exact title/fields hash at apply.
"""
from __future__ import annotations
from datetime import datetime, timezone
import json
from threading import RLock
from uuid import uuid4, uuid5, NAMESPACE_URL

from lib import inventory_db as db
from lib.note_mutation import recover_note_edits
from . import store, shopping, prep, cooking
from .merge import merge_fields
from .models import (AppleOperation, BatchTooLarge, BridgeContext, InvalidPayload, Locator, Observation,
                     OperationAck, OwnedRemovalItem, OwnershipConflict, RevisionConflict, ScopeRequest,
                     SourceUnavailable, SyncReport, canonical_hash, canonical_json,
                     validate_fields, validate_observations, validate_scope, _uuid)

MAX_ITEMS = 5000
_LOCK = RLock()
ADAPTERS = {'shopping': shopping, 'prep': prep, 'cooking': cooking}


def _owner(context=None, *, active=False, conn=None):
    with store._read(conn) as tx:
        row = tx.execute('SELECT * FROM apple_bridge WHERE id=1').fetchone()
        if row is None or not row['connected']:
            raise OwnershipConflict('No connected designated Mac')
        if context and (context.owner_id != row['owner_id'] or context.owner_generation != row['owner_generation']):
            raise OwnershipConflict('Stale bridge owner')
        if active and row['paused']:
            raise OwnershipConflict('Bridge is paused')
        return dict(row)


def configured() -> bool:
    """Disconnected/paused native integrations remain configured; no fallback."""
    with db.connect() as conn:
        return conn.execute('SELECT 1 FROM apple_bridge WHERE id=1').fetchone() is not None


def register_owner(owner_id, permissions=None, destinations=None):
    for values in (permissions, destinations):
        if values is not None and (not isinstance(values, dict) or values.keys() - ADAPTERS.keys()):
            raise InvalidPayload('Unknown permission/destination domain')
    if permissions is not None and any(not isinstance(v,str) or v not in {'unknown','not_determined','denied','restricted','authorized','write_only','unavailable'} for v in permissions.values()):
        raise InvalidPayload('Unknown permission')
    if destinations is not None:
        for values in destinations.values():
            if not isinstance(values,list) or len(values)>MAX_ITEMS or any(not isinstance(v,dict) or set(v)!={'id','title'} or any(not isinstance(t,str) or not t for t in v.values()) for v in values):
                raise InvalidPayload('Invalid destinations')
    with db.write_transaction() as conn:
        context = store.register_owner(owner_id, conn=conn)
        for name, value in [('permissions',permissions),('destinations',destinations)]:
            if value is not None:
                conn.execute(f'UPDATE apple_bridge SET {name}=? WHERE id=1',(canonical_json(value),))
    return context


def disconnect(context):
    with db.write_transaction() as conn:
        _owner(context, conn=conn)
        if conn.execute("SELECT 1 FROM apple_operations WHERE status='pending'").fetchone() or conn.execute("SELECT 1 FROM apple_source_patches WHERE status='pending'").fetchone() or conn.execute('SELECT 1 FROM apple_requests WHERE result IS NULL').fetchone() or conn.execute("SELECT 1 FROM apple_resolutions WHERE status='pending'").fetchone():
            raise RevisionConflict('Writer must finish outstanding work before disconnect')
        conn.execute('UPDATE apple_bridge SET connected=0, owner_generation=owner_generation+1, revision=revision+1 WHERE id=1')
    return status()


def settings(paused, expected_revision):
    if type(paused) is not bool or type(expected_revision) is not int or expected_revision < 1:
        raise InvalidPayload('Invalid settings revision or paused state')
    with db.write_transaction() as conn:
        owner = _owner(conn=conn)
        if owner['revision'] != expected_revision:
            raise RevisionConflict('Settings changed')
        conn.execute('UPDATE apple_bridge SET paused=?, revision=revision+1 WHERE id=1',(int(paused),))
    return status()


def _recover():
    conflicts = recover_note_edits()
    for adapter in ADAPTERS.values():
        conflicts.extend(adapter.recover_pending())
    with db.connect() as conn:
        records=[dict(r) for r in conn.execute("SELECT token FROM apple_source_patches WHERE status='conflict'")]
    for record in records:
        item=store.get_item(record['token'])
        with db.connect() as conn:
            resolved=conn.execute("SELECT 1 FROM apple_conflicts WHERE token=? AND field='source_recovery' AND status='resolved'",(item.token,)).fetchone()
        if not resolved:
            _conflict(item,'source_recovery')
    with db.connect() as conn:
        resolutions=[dict(r) for r in conn.execute("SELECT * FROM apple_resolutions WHERE status='pending'")]
    for resolution in resolutions:
        try:
            resolve_conflict(resolution['conflict_id'],resolution['choice'],resolution['expected_revision'],_recover_first=False)
        except RevisionConflict:
            with db.write_transaction() as conn:
                conn.execute("UPDATE apple_resolutions SET status='conflict' WHERE conflict_id=?",(resolution['conflict_id'],))
    return conflicts


def _scopes():
    with db.connect() as conn:
        return [dict(r) for r in conn.execute('SELECT * FROM apple_scopes ORDER BY domain,week')]


def _latest(items):
    result = {}
    for item in items:
        key = (item.domain,item.week,item.logical_id)
        if key not in result or item.generation > result[key].generation:
            result[key] = item
    return list(result.values())


def _conflict(item, field, observation=None, *, conn=None):
    evidence = observation.to_dict() if observation else None
    with db.write_transaction(conn) as tx:
        if field=='retained_generation':
            # Repeated discovery must not cancel the explicit cleanup that is
            # resolving this very conflict. Its ack still checks the reservation.
            tx.execute("UPDATE apple_operations SET status='superseded' "
                       "WHERE token=? AND status='pending' AND retained_cleanup=0",
                       (item.token,))
        else:
            store._supersede(tx,item.token)
        old = tx.execute("SELECT * FROM apple_conflicts WHERE token=? AND field=? AND status='open'",(item.token,field)).fetchone()
        payload = canonical_json(evidence)
        if old:
            if old['apple'] != payload or old['source'] != canonical_json(item.to_dict()):
                tx.execute('UPDATE apple_conflicts SET apple=?,source=?,revision=revision+1 WHERE conflict_id=?',(payload,canonical_json(item.to_dict()),old['conflict_id']))
            return old['conflict_id']
        ident=str(uuid4())
        tx.execute('INSERT INTO apple_conflicts(conflict_id,token,field,base,source,apple) VALUES(?,?,?,?,?,?)',(ident,item.token,field,canonical_json(item.common_fields),canonical_json(item.to_dict()),payload))
        return ident


def _refresh():
    """Collect complete scopes before writing their journal snapshots."""
    sources=[]; unavailable=[]
    for scope in _scopes():
        if scope['status'] != 'active':
            continue
        try:
            collected = ADAPTERS[scope['domain']].collect(scope['week'])
        except SourceUnavailable:
            unavailable.append((scope['domain'],scope['week'])); continue
        sources.extend(collected)
    if len(sources)>MAX_ITEMS:
        raise BatchTooLarge('Too many source items for a complete batch')
    with db.write_transaction() as conn:
        for source in sources:
            store.refresh_source(source,conn=conn)
    return unavailable


def _eligible_items():
    scopes={(s['domain'],s['week']) for s in _scopes() if s['status']=='active'}
    return [i for i in _latest(store.list_items()) if (i.domain,i.week) in scopes]


def _block_retained(item):
    old=[i for i in store.list_items(domain=item.domain,week=item.week) if i.logical_id==item.logical_id and i.generation<item.generation and i.locator and i.state!='history']
    for retained in old:
        _conflict(retained,'retained_generation')
    return bool(old)


def _queue_new(unavailable=()):
    for item in _eligible_items():
        if (item.domain,item.week) in unavailable or item.state!='active' or item.locator or _block_retained(item):
            continue
        with db.connect() as conn:
            last=store._row(conn,item.token)['last_observation']
            last=json.loads(last) if last else {}
            if last.get('availability')=='unavailable' or (last.get('availability')=='missing' and not last.get('absence_confirmed')):
                continue
            conflict=conn.execute("SELECT 1 FROM apple_conflicts WHERE token=? AND status='open'",(item.token,)).fetchone()
        if not conflict:
            store.reserve_operation(item,'upsert',None)


def activate(domain: str, week: str, destination_id: str) -> SyncReport:
    with _LOCK:
        _owner(active=True); _recover()
        store.activate_scope(domain,week,destination_id)
        _prepare_activation(domain, week)
        unavailable=_refresh(); _queue_new(unavailable)
        return _report(unavailable=len(unavailable))


def _prepare_activation(domain, week):
    if domain == 'shopping':
        try:
            shopping.prepare_activation(week)
        except SourceUnavailable:
            # Keep the scope active and expose source availability through the
            # ordinary refresh/report path; polling never generates or migrates.
            pass


def update_scope(request):
    with _LOCK:
        _owner(active=True); _recover()
        result=store.update_scope(request)
        if request.state == 'active':
            _prepare_activation(request.domain, request.week)
        unavailable=_refresh(); _queue_new(unavailable)
        return {'scope':result,'report':_report(unavailable=len(unavailable)).to_dict()}


def _report(**changes):
    with db.connect() as conn:
        owner=conn.execute('SELECT * FROM apple_bridge WHERE id=1').fetchone()
        observations=conn.execute(
            "SELECT item.revision,item.last_observation FROM apple_items AS item "
            "JOIN apple_scopes AS scope ON scope.domain=item.domain AND scope.week=item.week "
            "WHERE scope.status='active' AND item.state='active' AND item.last_observation IS NOT NULL "
            "AND NOT EXISTS (SELECT 1 FROM apple_items AS newer WHERE newer.domain=item.domain "
            "AND newer.week=item.week AND newer.logical_id=item.logical_id "
            "AND newer.generation>item.generation)"
        )
        unavailable=0
        for row in observations:
            observed=json.loads(row['last_observation'])
            if observed.get('revision') != row['revision']:
                continue
            availability=observed.get('availability')
            if (availability=='unavailable' or (availability=='missing' and not observed.get('absence_confirmed'))
                    or observed.get('issue')):
                unavailable+=1
        values={'queued':conn.execute("SELECT COUNT(*) FROM apple_operations WHERE status='pending'").fetchone()[0]+conn.execute("SELECT COUNT(*) FROM apple_source_patches WHERE status='pending'").fetchone()[0]+conn.execute('SELECT COUNT(*) FROM pending_schedule_views').fetchone()[0]+conn.execute('SELECT COUNT(*) FROM apple_requests WHERE result IS NULL').fetchone()[0]+conn.execute("SELECT COUNT(*) FROM apple_resolutions WHERE status='pending'").fetchone()[0], 'conflicts':conn.execute("SELECT COUNT(*) FROM apple_conflicts WHERE status='open'").fetchone()[0], 'unavailable':unavailable, 'last_success':owner['last_success'] if owner else None}
    if 'unavailable' in changes:
        changes['unavailable']=max(values['unavailable'],changes['unavailable'])
    values.update(changes)
    return SyncReport(**values)


def status():
    with db.connect() as conn:
        owner=conn.execute('SELECT * FROM apple_bridge WHERE id=1').fetchone()
        conflicts=[dict(r) for r in conn.execute("SELECT conflict_id,token,field,revision FROM apple_conflicts WHERE status='open' ORDER BY created_at LIMIT 100")]
    return {'model_version':1,'configured':owner is not None,'connected':bool(owner and owner['connected']),'paused':bool(owner and owner['paused']),'settings_revision':owner['revision'] if owner else 0,'report':_report().to_dict(),'permissions':json.loads(owner['permissions']) if owner else {},'destinations':json.loads(owner['destinations']) if owner else {},'scopes':_scopes(),'conflicts':conflicts}


def _available_operations(unavailable, candidates=None):
    """Filter both fresh and cached responses through current pending work.

    A completed request may be replayed after a source disappears or an operation
    is superseded/acknowledged. Its cached response is evidence, not permission to
    return a now-unsafe write. No new operations are introduced into a replay.
    """
    blocked=set(unavailable)
    allowed={operation.operation_id:operation for operation in candidates} if candidates is not None else None
    items={item.token:item for item in store.list_items()}
    return [operation for operation in store.pending_operations()
            if (items[operation.token].domain,items[operation.token].week) not in blocked
            and (allowed is None or allowed.get(operation.operation_id)==operation)]


def work(context: BridgeContext) -> dict:
    with _LOCK:
        owner=_owner(context)
        if owner['paused']:
            return {'model_version':1,'context':context.to_dict(),'items':[],'operations':[],'scopes':_scopes(),'report':_report().to_dict(),'paused':True,'retry_requests':[],'retained_items':[]}
        _recover()
        unavailable=_refresh(); _queue_new(unavailable)
        with db.connect() as conn:
            retries=[{'request_id':r['request_id'],'observations':json.loads(r['payload'])} for r in conn.execute('SELECT * FROM apple_requests WHERE owner_id=? AND owner_generation=? AND result IS NULL',(context.owner_id,context.owner_generation))]
        items=[i for i in _eligible_items() if i.state not in {'history', 'suppressed'} and (i.state!='retired' or i.locator)]
        operations=store.pending_operations()
        latest_tokens={i.token for i in _latest(store.list_items())}
        active_scopes={(s['domain'],s['week']) for s in _scopes() if s['status']=='active'}
        cleanup_tokens={o.token for o in operations if o.action=='delete'}
        retained=[i for i in store.list_items() if i.token not in latest_tokens and i.locator and i.state!='history' and ((i.domain,i.week) in active_scopes or i.token in cleanup_tokens)]
        unavailable=set(unavailable)
        operations=_available_operations(unavailable,operations)
        if len(items)+len(retained)+len(operations)+sum(len(r['observations']) for r in retries)>MAX_ITEMS:
            raise BatchTooLarge('Too many items for a complete batch')
        result={'model_version':1,'context':context.to_dict(),'items':[i.to_dict() for i in items], 'operations':[] if retries else [o.to_dict() for o in operations],'scopes':_scopes(),'report':_report(unavailable=len(unavailable)).to_dict(),'paused':False,'retry_requests':retries,'retained_items':[i.to_dict() for i in retained]}
        if len(canonical_json(result).encode('utf-8'))>2*1024*1024:
            raise BatchTooLarge('Complete work payload exceeds 2 MiB')
        return result


def _observed_hash(observation):
    return canonical_hash({'title':observation.title,'fields':observation.fields})


def _record_observation(item, observation):
    with db.write_transaction() as conn:
        if store.get_item(item.token,conn=conn)!=item:
            raise RevisionConflict('Item changed during observation')
        store._current(conn,store._row(conn,item.token))
        moved = item.locator != observation.locator
        conn.execute('UPDATE apple_items SET locator=?,last_observation=?,revision=revision+? WHERE token=?',(canonical_json(observation.locator.to_dict()) if observation.locator else None,canonical_json(observation.to_dict()),int(moved),item.token))
        if moved:
            store._supersede(conn,item.token)
    return store.get_item(item.token)


def _recover_first_save(context, item, observation):
    """A current exact pending creation is proof for a lost save acknowledgement.

    Inspect before recording a discovered locator, which normally supersedes old
    work. The ordinary ack path retains owner/scope/generation/revision and hash
    checks; a marker alone or changed title/fields provides no such evidence.
    """
    if item.common_fields is not None or item.locator is not None:
        return item
    with db.connect() as conn:
        rows=conn.execute(
            "SELECT payload FROM apple_operations WHERE token=? AND generation=? "
            "AND revision=? AND action='upsert' AND status='pending' "
            "AND expected_apple_hash IS NULL",
            (item.token,item.generation,item.revision),
        ).fetchall()
    for row in rows:
        operation=AppleOperation.from_dict(json.loads(row['payload']))
        if (operation.locator is None and operation.title==observation.title
                and operation.fields==observation.fields
                and operation.destination_id==observation.locator.calendar_id):
            acknowledge(context,operation.operation_id,{
                'operation_id':operation.operation_id,'outcome':'saved',
                'locator':observation.locator.to_dict(),
                'observed_fields':observation.fields,
                'observed_hash':_observed_hash(observation),
            })
            return store.get_item(item.token)
    return item


def _resolved_export(item):
    """Find the still-pending correction chosen for this exact source snapshot.

    The operation and resolved conflict are durable intent, not a new common
    value. A fresh observation must still match the evidence the user chose.
    """
    with db.connect() as conn:
        operations = conn.execute(
            "SELECT payload FROM apple_operations WHERE token=? AND generation=? "
            "AND revision=? AND action='upsert' AND status='pending'",
            (item.token, item.generation, item.revision)).fetchall()
        conflicts = conn.execute(
            "SELECT field,source,apple FROM apple_conflicts WHERE token=? "
            "AND status='resolved' AND resolution='keep_kitchenos'",
            (item.token,)).fetchall()
    for row in operations:
        operation = AppleOperation.from_dict(json.loads(row['payload']))
        for conflict in conflicts:
            source = json.loads(conflict['source']) if conflict['source'] else {}
            evidence = json.loads(conflict['apple']) if conflict['apple'] else None
            if (source.get('source_revision') == item.source_revision and evidence
                    and operation.expected_apple_hash == _observed_hash(Observation.from_dict(evidence))):
                return operation, conflict['field']
    return None


def _apply_observation(observation, request_id, context):
    item=store.get_item(observation.token)
    if observation.availability=='unavailable' or (observation.availability=='missing' and not observation.absence_confirmed):
        if item.state=='retired' and item.locator is not None:
            # An uncertain read cannot prove this retired Apple object is gone.
            # Keep its marker/locator until the user explicitly detaches it.
            _conflict(item,'retired_unavailable',observation)
            return
        with db.write_transaction() as conn:
            conn.execute('UPDATE apple_items SET last_observation=? WHERE token=?',(canonical_json(observation.to_dict()),item.token))
            store._supersede(conn,item.token)
        return
    if observation.issue:
        _conflict(item,observation.issue,observation); return
    if item.state in {'history','conflict','suppressed'}:
        return
    if item.state=='retired':
        with db.connect() as conn:
            if conn.execute("SELECT 1 FROM apple_conflicts WHERE token=? AND field='retired_unavailable' "
                            "AND status='open'", (item.token,)).fetchone():
                # A later readable object is not permission to resume the
                # retirement delete while separation review is unresolved.
                return
    if observation.availability=='missing':
        if item.locator is None and item.common_fields is None:
            with db.write_transaction() as conn:
                conn.execute('UPDATE apple_items SET last_observation=? WHERE token=?',(canonical_json(observation.to_dict()),item.token))
            return # no existing object to delete; queue after the complete merge
        if item.state=='active':
            if item.domain=='cooking':
                cooking.apply(item,{'unscheduled':True},str(uuid5(NAMESPACE_URL,request_id+item.token)))
                with db.write_transaction() as conn:
                    conn.execute('UPDATE apple_items SET locator=NULL,common_payload=NULL,revision=revision+1 WHERE token=?',(item.token,))
                    store._supersede(conn,item.token)
            else:
                with db.write_transaction() as conn:
                    store.set_suppressed(item.token,True,expected_revision=item.revision,conn=conn)
                    conn.execute('UPDATE apple_items SET locator=NULL,common_payload=NULL WHERE token=?',(item.token,))
        return
    validate_fields(observation.fields,item.domain)
    item=_recover_first_save(context,item,observation)
    resolution = _resolved_export(item)
    item=_record_observation(item,observation)
    with db.connect() as conn:
        common_title=store._row(conn,item.token)['common_title']
    if item.state=='retired':
        if observation.fields.get('completed'):
            # A completion discovered after source retirement is permanent
            # history, even if Apple later reopens it. Preserve the verified
            # observation without claiming an import into the absent source.
            with db.write_transaction() as conn:
                if store.get_item(item.token,conn=conn) != item:
                    raise RevisionConflict('Item changed while preserving history')
                conn.execute("UPDATE apple_items SET state='history',revision=revision+1 WHERE token=?", (item.token,))
                store._supersede(conn,item.token)
                conn.execute("UPDATE apple_conflicts SET status='resolved',resolution='history',revision=revision+1 "
                             "WHERE token=? AND field='retirement' AND status='open'", (item.token,))
            return
        if (item.common_fields is None or observation.title != common_title
                or observation.fields != item.common_fields or observation.has_user_notes):
            _conflict(item,'retirement',observation); return
        store.reserve_operation(item,'delete',_observed_hash(observation)); return
    if resolution:
        operation, field = resolution
        if _observed_hash(observation) == operation.expected_apple_hash:
            # Recording a recovered locator may supersede the old reservation;
            # reserve again against the fresh locator and unchanged evidence.
            store.reserve_operation(item,'upsert',_observed_hash(observation))
            return
        if observation.title != operation.title or observation.fields != operation.fields:
            _conflict(item,field,observation); return
        # Exact desired state may be a saved update whose ack was lost. Normal
        # equality reconciliation can advance common without another write.
    with db.connect() as conn:
        if conn.execute("SELECT 1 FROM apple_conflicts WHERE token=? AND field='recovery' AND status='open'", (item.token,)).fetchone():
            # Keep the explicit choice pending, but replace stale Apple evidence
            # and bump its revision before a user can import an older snapshot.
            _conflict(item,'recovery',observation)
            return
    decision=merge_fields(item.common_fields,item.fields,observation.fields)
    if item.common_fields is not None and observation.title and observation.title!=common_title:
        item=store.set_title_override(item.token,observation.title,expected_revision=item.revision)
        with db.write_transaction() as conn:
            conn.execute('UPDATE apple_items SET common_title=? WHERE token=?',(observation.title,item.token))
    title_export = item.common_fields is not None and item.title != observation.title
    for field in decision.conflicts:
        _conflict(item,field,observation)
    if decision.source_patch:
        result=ADAPTERS[item.domain].apply(item,decision.source_patch,str(uuid5(NAMESPACE_URL,request_id+item.token)))
        item=store.refresh_source(result) if item.domain!='cooking' else store.get_item(item.token)
    # Only fields proven equal after a verified import become common. Conflicted
    # fields retain their old base, so the next poll cannot silently accept them.
    with db.write_transaction() as conn:
        current=store.get_item(item.token,conn=conn)
        if current!=item:
            raise RevisionConflict('Source changed during import')
        common=dict(item.common_fields or {})
        for field,value in item.fields.items():
            if field not in decision.conflicts and observation.fields.get(field,object())==value:
                common[field]=value
        if item.common_fields is not None and common!=item.common_fields:
            conn.execute('UPDATE apple_items SET common_payload=?,revision=revision+1 WHERE token=?',(canonical_json(common),item.token))
            store._supersede(conn,item.token)
    item=store.get_item(item.token)
    if (decision.apple_patch or title_export) and not decision.conflicts:
        store.reserve_operation(item,'upsert',_observed_hash(observation))


def observe(context: BridgeContext, observations: list[Observation], request_id: str) -> list[AppleOperation]:
    _uuid(request_id)
    observations=validate_observations(observations)
    if len(observations)>MAX_ITEMS:
        raise InvalidPayload('Too many observations')
    payload=canonical_json([o.to_dict() for o in observations])
    with _LOCK:
        _owner(context,active=True)
        with db.connect() as conn:
            old=conn.execute('SELECT * FROM apple_requests WHERE request_id=?',(request_id,)).fetchone()
            if conn.execute('SELECT 1 FROM apple_requests WHERE result IS NULL AND request_id!=?',(request_id,)).fetchone():
                raise RevisionConflict('Resume the pending observation request first')
        if old:
            if old['payload']!=payload or old['owner_id']!=context.owner_id or old['owner_generation']!=context.owner_generation:
                raise RevisionConflict('Request ID payload changed')
            if old['result'] is not None:
                _recover()
                unavailable=_refresh()
                cached=[AppleOperation.from_dict(v) for v in json.loads(old['result'])]
                return _available_operations(unavailable,cached)
        else:
            # Validate the whole incoming batch before recovery/import or any writes.
            with db.connect() as conn:
                for observation in observations:
                    row=store._row(conn,observation.token);store._current(conn,row)
                    item=store._item(row);store._scope(conn,item.domain,item.week)
                    if item.generation!=observation.generation or item.revision!=observation.revision:
                        raise RevisionConflict('Observation snapshot changed')
                    validate_fields(observation.fields,item.domain)
                    if observation.availability=='present' and observation.issue is None and (set(observation.fields)!=set(item.fields) or observation.title is None):
                        raise InvalidPayload('Present observation must include every domain field and title')
        _recover()
        unavailable=_refresh()
        if any((store.get_item(o.token).domain,store.get_item(o.token).week) in unavailable for o in observations):
            raise SourceUnavailable('Observed source is unavailable')
        with db.write_transaction() as conn:
            # Reserve under the same writer lock as the final owner check. Once
            # this row exists, quiescent disconnect cannot overtake the import.
            _owner(context,active=True,conn=conn)
            pending=conn.execute('SELECT request_id FROM apple_requests WHERE result IS NULL AND request_id!=?',(request_id,)).fetchone()
            if pending:
                raise RevisionConflict('Resume the pending observation request first')
            existing=conn.execute('SELECT * FROM apple_requests WHERE request_id=?',(request_id,)).fetchone()
            if existing:
                if existing['payload']!=payload or existing['owner_id']!=context.owner_id or existing['owner_generation']!=context.owner_generation:
                    raise RevisionConflict('Request ID payload changed')
            else:
                conn.execute('INSERT INTO apple_requests(request_id,owner_id,owner_generation,payload) VALUES(?,?,?,?)',(request_id,context.owner_id,context.owner_generation,payload))
        done=set(json.loads(old['progress'])) if old else set()
        for observation in observations:
            if observation.token in done:
                continue
            try:
                _apply_observation(observation,request_id,context)
            except RevisionConflict:
                # Semantic source drift is terminal for this observation; retain
                # visible evidence rather than leave an unreplayable request.
                _conflict(store.get_item(observation.token),'source_recovery',observation)
            done.add(observation.token)
            with db.write_transaction() as conn:
                conn.execute('UPDATE apple_requests SET progress=? WHERE request_id=?',(canonical_json(sorted(done)),request_id))
        _queue_new(unavailable)
        operations=_available_operations(unavailable)
        with db.write_transaction() as conn:
            conn.execute('UPDATE apple_requests SET result=? WHERE request_id=?',(canonical_json([o.to_dict() for o in operations]),request_id))
        return operations


def acknowledge(context: BridgeContext, operation_id: str, result: dict) -> SyncReport:
    ack=OperationAck.from_dict(result)
    if ack.operation_id!=operation_id:
        raise InvalidPayload('Operation path mismatch')
    with _LOCK:
        _owner(context,active=True)
        with db.connect() as conn:
            row=conn.execute('SELECT * FROM apple_operations WHERE operation_id=?',(operation_id,)).fetchone()
        if row is None:
            raise RevisionConflict('Unknown operation')
        if row['owner_id']!=context.owner_id or row['owner_generation']!=context.owner_generation:
            raise OwnershipConflict('Operation owner changed')
        op=AppleOperation.from_dict(json.loads(row['payload']))
        if ack.outcome in {'failed','changed'}:
            if row['status']!='pending':
                raise RevisionConflict('Operation is not pending')
            with db.write_transaction() as conn:
                conn.execute("UPDATE apple_operations SET status='failed' WHERE operation_id=?",(operation_id,))
            return _report(unavailable=1)
        if (ack.outcome=='saved')!=(op.action=='upsert'):
            raise InvalidPayload('Outcome does not match operation')
        expected=canonical_hash({'title':op.title,'fields':ack.observed_fields}) if ack.outcome=='saved' else None
        if ack.observed_hash!=expected:
            raise RevisionConflict('Observed hash differs from verified save')
        store.acknowledge(context,operation_id,ack.locator,ack.observed_fields)
        if row['status'] == 'acknowledged':
            return _report() # exact committed retry is not another delivery
        return _report(**({'deleted':1} if op.action=='delete' else {'created':1} if op.locator is None else {'updated':1}))



def complete_sync(context, scopes, request_ids):
    """Commit a successful complete scan, including a no-op, exactly once."""
    if (not isinstance(scopes, list) or not isinstance(request_ids, list) or not request_ids
            or len(request_ids) > MAX_ITEMS or any(not isinstance(v, str) for v in request_ids)
            or len(set(request_ids)) != len(request_ids)):
        raise InvalidPayload('Complete scope and observation proof required')
    for ident in request_ids:
        _uuid(ident)
    proof = canonical_hash({'context': context.to_dict(), 'scopes': scopes, 'request_ids': sorted(request_ids)})
    with _LOCK:
        _owner(context, active=True)
        _recover()
        unavailable = _refresh()
        if unavailable:
            raise SourceUnavailable('A source is unavailable')
        with db.write_transaction() as conn:
            _owner(context, active=True, conn=conn)
            current_scopes = [dict(r) for r in conn.execute('SELECT * FROM apple_scopes ORDER BY domain,week')]
            if scopes != current_scopes or not any(s['status'] == 'active' for s in current_scopes):
                raise RevisionConflict('Active scopes changed or none are active')
            report = _report()
            if report.queued or report.conflicts:
                raise RevisionConflict('Reconciliation still has pending work or conflicts')
            observed = {}
            for ident in request_ids:
                request = conn.execute('SELECT * FROM apple_requests WHERE request_id=?', (ident,)).fetchone()
                if (request is None or request['result'] is None or request['owner_id'] != context.owner_id
                        or request['owner_generation'] != context.owner_generation):
                    raise RevisionConflict('Observation request is incomplete or belongs to another owner')
                for value in json.loads(request['payload']):
                    observation = Observation.from_dict(value)
                    if observation.token in observed:
                        raise InvalidPayload('Repeated item in completion proof')
                    observed[observation.token] = observation
            active = {(s['domain'], s['week']) for s in current_scopes if s['status'] == 'active'}
            items = [i for i in _latest(store.list_items(conn=conn)) if (i.domain, i.week) in active
                     and i.state not in {'history', 'suppressed'} and (i.state != 'retired' or i.locator)]
            if set(observed) != {i.token for i in items}:
                raise RevisionConflict('Completion proof does not cover the current work')
            for item in items:
                observation = observed[item.token]
                if (observation.generation != item.generation or observation.revision != item.revision
                        or observation.availability != 'present' or observation.issue
                        or observation.locator != item.locator or observation.title != item.title
                        or observation.fields != item.fields or item.common_fields != item.fields):
                    raise RevisionConflict('Completion proof is not a current converged observation')
            receipt = conn.execute('SELECT completed_at FROM apple_sync_passes WHERE proof_hash=?', (proof,)).fetchone()
            timestamp = receipt['completed_at'] if receipt else datetime.now(timezone.utc).isoformat()
            conn.execute('INSERT OR IGNORE INTO apple_sync_passes(proof_hash,owner_id,owner_generation,completed_at) VALUES(?,?,?,?)',
                         (proof, context.owner_id, context.owner_generation, timestamp))
            conn.execute('UPDATE apple_bridge SET last_success=CASE WHEN last_success IS NULL OR last_success<? THEN ? ELSE last_success END WHERE id=1',
                         (timestamp, timestamp))
        return _report()


def recover_saved(context, operation_id, ack_data, observation):
    """Transfer verified superseded-save proof to a durable, explicit conflict."""
    ack = OperationAck.from_dict(ack_data)
    if ack.operation_id != operation_id or ack.outcome != 'saved':
        raise InvalidPayload('Recovery requires a saved acknowledgement for this operation')
    evidence = {'ack': ack.to_dict(), 'observation': observation.to_dict()}
    with _LOCK:
        _owner(context, active=True)
        _recover()
        _refresh()
        with db.write_transaction() as conn:
            _owner(context, active=True, conn=conn)
            record = conn.execute('SELECT * FROM apple_operations WHERE operation_id=?', (operation_id,)).fetchone()
            if record is None:
                raise RevisionConflict('Unknown save operation')
            if record['owner_id'] != context.owner_id or record['owner_generation'] != context.owner_generation:
                raise OwnershipConflict('Save belongs to another owner generation')
            previous = json.loads(record['result']) if record['result'] else {}
            if 'recovered_saved' in previous:
                if previous['recovered_saved'] != evidence:
                    raise RevisionConflict('Recovery retry proof changed')
                return _report()
            operation = AppleOperation.from_dict(json.loads(record['payload']))
            row = store._row(conn, operation.token)
            item = store._item(row)
            if (record['status'] != 'superseded' or operation.action != 'upsert'
                    or item.generation != operation.generation or observation.token != item.token
                    or observation.generation != operation.generation
                    or observation.revision not in {operation.revision, item.revision}
                    or observation.availability != 'present' or observation.issue or observation.locator is None
                    or ack.observed_fields != operation.fields
                    or ack.observed_hash != canonical_hash({'title': operation.title, 'fields': ack.observed_fields})
                    or ack.locator is None or ack.locator.calendar_id != operation.destination_id):
                raise RevisionConflict('Fresh owned-object proof does not match the superseded save')
            # The old save receipt is checked against its original operation.
            # The fresh uniquely owned observation may already have changed or
            # moved. Link only that observed object; never import old source data.
            conn.execute('UPDATE apple_items SET locator=?,last_observation=?,revision=revision+1 WHERE token=?',
                         (canonical_json(observation.locator.to_dict()), canonical_json(observation.to_dict()), item.token))
            current = store.get_item(item.token, conn=conn)
            latest = conn.execute('SELECT MAX(generation) FROM apple_items WHERE domain=? AND week=? AND logical_id=?',
                                  (item.domain, item.week, item.logical_id)).fetchone()[0]
            field = ('retained_generation' if current.state == 'history' or current.generation < latest
                     else 'retirement' if current.state == 'retired' else 'recovery')
            conflict_id = _conflict(current, field, observation, conn=conn)
            conn.execute('UPDATE apple_operations SET result=? WHERE operation_id=?',
                         (canonical_json({'recovered_saved': evidence, 'conflict_id': conflict_id}), operation_id))
        return _report()

def enqueue(domain, week):
    """Existing send entrypoints queue configured native scopes, even offline."""
    validate_scope(domain,week)
    if not configured():
        return None
    scopes=[s for s in _scopes() if s['domain']==domain and s['week']==week]
    if not scopes:
        raise RevisionConflict('Select a native destination for this week in the Mac app')
    if scopes[0]['status'] == 'archived':
        raise RevisionConflict('Reactivate this archived week in the Mac app before sending')
    state=status()
    if state['connected'] and not state['paused'] and scopes[0]['status']=='active':
        with _LOCK:
            _recover();unavailable=_refresh();_queue_new(unavailable)
    with db.connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM apple_operations o JOIN apple_items i ON i.token=o.token "
                             "WHERE i.domain=? AND i.week=? AND o.status='pending'", (domain, week)).fetchone()[0]
        count += conn.execute("SELECT COUNT(*) FROM apple_source_patches p JOIN apple_items i ON i.token=p.token "
                              "WHERE i.domain=? AND i.week=? AND p.status='pending'", (domain, week)).fetchone()[0]
        count += conn.execute("SELECT COUNT(*) FROM apple_resolutions r JOIN apple_conflicts c ON c.conflict_id=r.conflict_id "
                              "JOIN apple_items i ON i.token=c.token WHERE i.domain=? AND i.week=? AND r.status='pending'", (domain, week)).fetchone()[0]
        tokens = {row['token'] for row in conn.execute(
            'SELECT token FROM apple_items WHERE domain=? AND week=?', (domain, week))}
        # A journal request is one unit of pending recovery, even when it covers
        # several items in this scope. Empty requests have no scope attribution.
        count += sum(any(value['token'] in tokens for value in json.loads(row['payload']))
                     for row in conn.execute('SELECT payload FROM apple_requests WHERE result IS NULL'))
    return {'success':True,'queued':count,'delivered':0,'items_sent':0,'sent':0,'native':True}


def item_details(domain, week):
    from .models import validate_scope
    validate_scope(domain, week)
    with db.connect() as conn:
        count = conn.execute('SELECT COUNT(*) FROM apple_items WHERE domain=? AND week=?', (domain, week)).fetchone()[0]
        if count > MAX_ITEMS:
            raise BatchTooLarge('Too many items for a complete view')
        items = store.list_items(domain=domain, week=week, conn=conn)
        values = []
        for item in items:
            # Detail lists retained generations too. This read must not apply
            # the current-generation guard used by mutable due preferences.
            raw_due = store._row(conn, item.token)['due_override']
            values.append({**item.to_dict(), 'has_due_override': raw_due is not None,
                           'due_override': json.loads(raw_due) if raw_due is not None else None})
    return {'items': values}


def conflict_detail(conflict_id):
    _uuid(conflict_id)
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM apple_conflicts WHERE conflict_id=? AND status='open'", (conflict_id,)).fetchone()
        if row is None:
            raise RevisionConflict('Conflict no longer available')
        source = json.loads(row['source']) if row['source'] else None
        evidence = json.loads(row['apple']) if row['apple'] else None
        choices = ['keep_manual']
        shopping_demand = source.get('shopping_demand') if source else None
        if row['field'].startswith('shopping_'):
            # Old conflict records may predate the generated-demand evidence.
            # Never offer acceptance of a target this detail cannot disclose.
            choices = ['keep_kitchenos', 'keep_manual'] if shopping_demand else ['keep_manual']
        elif row['field'] not in {'retained_generation', 'retirement', 'retired_unavailable'}:
            item = store.get_item(row['token'], conn=conn)
            scope = conn.execute('SELECT status FROM apple_scopes WHERE domain=? AND week=?',
                                 (item.domain, item.week)).fetchone()
            active_scope = scope is not None and scope['status'] == 'active'
            if item.state == 'suppressed' and active_scope:
                choices += ['restore']
            # Source recovery means the source itself could not be applied or
            # recovered safely. A present Apple observation does not prove that
            # source is now readable, and source_recovery is not an importable
            # observation field. Keep this GET free of collect/recovery effects.
            if (row['field'] != 'source_recovery' and active_scope and item.state == 'active'
                    and source and source.get('source_revision') == item.source_revision and evidence
                    and evidence.get('availability') == 'present' and not evidence.get('issue')):
                choices = ['keep_kitchenos']
                # Mirror resolve_conflict's exact keep_apple patch selection:
                # recovery imports the whole dictionary; other fields must exist.
                if row['field'] == 'recovery' or row['field'] in evidence.get('fields', {}):
                    choices.append('keep_apple')
                choices.append('keep_manual')
        return {'conflict_id': row['conflict_id'], 'token': row['token'], 'field': row['field'],
                'revision': row['revision'], 'source': source, 'apple': evidence, 'choices': choices,
                'shopping_demand': shopping_demand}


def link(token):
    _uuid(token)
    item=store.get_item(token)
    return {'domain':item.domain,'week':item.week,'source_id':item.logical_id,'state':item.state}


def restore(token, expected_revision, *, _recover_first=True):
    """Only explicit restoration creates a new generation of a suppressed item."""
    _uuid(token)
    if type(expected_revision) is not int or expected_revision<1:
        raise InvalidPayload('Invalid item revision')
    with _LOCK:
        _owner(active=True)
        if _recover_first:
            _recover()
        item=store.get_item(token)
        source=next((s for s in ADAPTERS[item.domain].collect(item.week) if s.logical_id==item.logical_id),None)
        if source is None or source.state!='active':
            raise RevisionConflict('Source is not active for restoration')
        with db.write_transaction() as conn:
            row=store._row(conn,token);store._current(conn,row)
            if row['revision']!=expected_revision or row['state']!='suppressed' or store._item(row)!=item:
                raise RevisionConflict('Restore requires the current suppressed revision')
            store._scope(conn,row['domain'],row['week'])
            conn.execute("UPDATE apple_items SET state='retired',revision=revision+1 WHERE token=?",(token,))
            store._supersede(conn,token)
            result=store.refresh_source(source,conn=conn)
            # Explicit restore recreates the user's suppressed reminder as shown,
            # including its due choice. Ordinary reappearance still resets due.
            if item.domain in {'shopping','prep'}:
                conn.execute('UPDATE apple_items SET due_override=? WHERE token=?',(canonical_json(source.fields['due']),result.token))
        _queue_new()
        return result


def remove_owned(context, items, request_id):
    """Reserve only explicitly selected tokens with a fresh complete observation."""
    _uuid(request_id)
    if not isinstance(items,list) or not items or len(items)>MAX_ITEMS:
        raise InvalidPayload('Expected a bounded nonempty item list')
    values=[];seen=set()
    for data in items:
        if not isinstance(data,dict) or set(data)!={'token','expected_revision','observation'}:
            raise InvalidPayload('Invalid removal item')
        parsed=OwnedRemovalItem.from_dict(data)
        observation=parsed.observation
        _uuid(data['token'])
        if type(data['expected_revision']) is not int or data['expected_revision']<1:
            raise InvalidPayload('Invalid removal revision')
        if data['token'] in seen or data['token']!=observation.token or data['expected_revision']!=observation.revision:
            raise InvalidPayload('Duplicate or mismatched cleanup item')
        seen.add(data['token']);values.append((data,observation))
    with _LOCK, db.write_transaction() as conn:
        _owner(context,active=True,conn=conn)
        payload=canonical_json({'remove_owned':items})
        old=conn.execute('SELECT * FROM apple_requests WHERE request_id=?',(request_id,)).fetchone()
        if old:
            if old['payload']!=payload or old['owner_id']!=context.owner_id or old['owner_generation']!=context.owner_generation or old['result'] is None:
                raise RevisionConflict('Request ID payload changed')
            return [AppleOperation.from_dict(v) for v in json.loads(old['result'])]
        if conn.execute('SELECT 1 FROM apple_requests WHERE result IS NULL').fetchone():
            raise RevisionConflict('Resume the pending observation request first')
        operations=[]
        # Entire validation/reservation is one short DB transaction.
        for data,observation in values:
            item=store.get_item(data['token'],conn=conn)
            if (item.revision!=data['expected_revision'] or item.generation!=observation.generation or item.locator is None
                    or observation.availability!='present' or observation.issue is not None or observation.locator is None):
                raise RevisionConflict('Removal needs a fresh owned present observation')
            validate_fields(observation.fields,item.domain)
            conn.execute('UPDATE apple_items SET locator=?,last_observation=? WHERE token=?',(canonical_json(observation.locator.to_dict()),canonical_json(observation.to_dict()),item.token))
            item=store.get_item(item.token,conn=conn)
            operations.append(store.reserve_cleanup(item,_observed_hash(observation),conn=conn))
        conn.execute('INSERT INTO apple_requests(request_id,owner_id,owner_generation,payload,result) VALUES(?,?,?,?,?)',(request_id,context.owner_id,context.owner_generation,payload,canonical_json([o.to_dict() for o in operations])))
        return operations


def resolve_conflict(conflict_id: str, choice: str, expected_revision: int, *, _recover_first=True) -> SyncReport:
    _uuid(conflict_id)
    if type(expected_revision) is not int or expected_revision<1 or not isinstance(choice,str) or choice not in {'keep_kitchenos','keep_apple','keep_manual','restore'}:
        raise InvalidPayload('Invalid conflict resolution')
    with _LOCK:
        _owner(active=True)
        if _recover_first:
            _recover()
        with db.connect() as conn:
            conflict=conn.execute('SELECT * FROM apple_conflicts WHERE conflict_id=?',(conflict_id,)).fetchone()
        if conflict and conflict['status']=='resolved' and conflict['resolution']==choice and conflict['revision']==expected_revision:
            return _report()
        if conflict is None or conflict['status']!='open' or conflict['revision']!=expected_revision:
            raise RevisionConflict('Conflict revision changed')
        item=store.get_item(conflict['token'])
        if not conflict['field'].startswith('shopping_') and choice in {'keep_kitchenos', 'keep_apple'}:
            with db.connect() as conn:
                scope = conn.execute('SELECT status FROM apple_scopes WHERE domain=? AND week=?',
                                     (item.domain, item.week)).fetchone()
            if scope is None or scope['status'] != 'active' or item.state != 'active':
                raise RevisionConflict('An active item and scope are required to accept this value')
        # Conflict source evidence is a SyncItem from service or SourceItem from
        # the shopping adapter. Compare the authoritative source revision either way.
        source=json.loads(conflict['source']) if conflict['source'] else {}
        if conflict['field'] not in {'source_recovery','retained_generation'} and source.get('source_revision')!=item.source_revision:
            raise RevisionConflict('Source changed since conflict was presented')
        if conflict['field'] in {'retirement', 'retired_unavailable'} and (
                item.state!='retired' or item.locator is None
                or source.get('token')!=item.token
                or source.get('generation')!=item.generation
                or source.get('revision')!=item.revision
                or source.get('locator')!=item.locator.to_dict()):
            raise RevisionConflict('Retired Apple link changed since review')
        evidence=json.loads(conflict['apple']) if conflict['apple'] else None
        observation=Observation.from_dict(evidence) if evidence else None
        operation_id=str(uuid5(NAMESPACE_URL,conflict_id+':'+str(expected_revision)+':'+choice))
        field=conflict['field']
        with db.write_transaction() as conn:
            pending=conn.execute('SELECT * FROM apple_resolutions WHERE conflict_id=?',(conflict_id,)).fetchone()
            if pending and pending['status']=='conflict':
                conn.execute('DELETE FROM apple_resolutions WHERE conflict_id=?',(conflict_id,))
                pending=None
            if pending and (pending['choice']!=choice or pending['expected_revision']!=expected_revision):
                raise RevisionConflict('Resolution retry choice changed')
            conn.execute("INSERT OR IGNORE INTO apple_resolutions(conflict_id,choice,expected_revision,status) VALUES(?,?,?,'pending')",(conflict_id,choice,expected_revision))
        if field.startswith('shopping_'):
            result=shopping.resolve(item,choice,operation_id)
            if result is not None:
                store.refresh_source(result)
            else:
                with db.write_transaction() as conn:
                    conn.execute("UPDATE apple_items SET locator=NULL,common_payload=NULL,state='history',revision=revision+1 WHERE token=?",(item.token,))
                    store._supersede(conn,item.token)
        elif choice=='keep_manual':
            with db.write_transaction() as conn:
                if store.get_item(item.token,conn=conn)!=item:
                    raise RevisionConflict('Item changed during resolution')
                conn.execute("UPDATE apple_items SET locator=NULL,common_payload=NULL,suppressed=1,state=CASE WHEN state IN ('retired','history') THEN 'history' ELSE 'suppressed' END,revision=revision+1 WHERE token=?",(item.token,))
                store._supersede(conn,item.token)
                if field in {'retirement', 'retired_unavailable'}:
                    # Either review detaches the same retired link. Its other
                    # review is now obsolete and must not block completion.
                    other = 'retirement' if field == 'retired_unavailable' else 'retired_unavailable'
                    conn.execute("UPDATE apple_conflicts SET status='resolved',resolution='keep_manual',revision=revision+1 "
                                 "WHERE token=? AND field=? AND status='open'", (item.token, other))
                    updated=conn.execute("UPDATE apple_conflicts SET status='resolved',resolution='keep_manual' "
                                         "WHERE conflict_id=? AND status='open' AND revision=?",
                                         (conflict_id, expected_revision)).rowcount
                    if updated!=1:
                        raise RevisionConflict('Conflict changed during resolution')
                    conn.execute("UPDATE apple_resolutions SET status='applied' WHERE conflict_id=?", (conflict_id,))
            if field in {'retirement', 'retired_unavailable'}:
                return _report()
        elif field in {'retained_generation', 'retirement', 'retired_unavailable'}:
            raise RevisionConflict('Retired objects require keep_manual or explicit remove-owned')
        elif choice=='restore':
            restore(item.token,item.revision,_recover_first=False)
        elif observation is None or observation.availability!='present' or observation.issue:
            raise RevisionConflict('This conflict requires keep_manual or restore')
        else:
            current_source=next((s for s in ADAPTERS[item.domain].collect(item.week) if s.logical_id==item.logical_id),None)
            if current_source is None or current_source.source_revision!=item.source_revision:
                raise RevisionConflict('Source changed before resolution')
            if choice=='keep_apple':
                if field=='recovery':
                    patch=observation.fields
                elif field in observation.fields:
                    patch={field:observation.fields[field]}
                else:
                    raise RevisionConflict('No valid Apple value to keep')
                result=ADAPTERS[item.domain].apply(item,patch,operation_id)
                item=store.get_item(item.token) if item.domain=='cooking' else store.refresh_source(result)
                with db.write_transaction() as conn:
                    common=dict(item.common_fields or {})
                    common.update(patch)
                    conn.execute('UPDATE apple_items SET common_payload=?,revision=revision+1 WHERE token=?',(canonical_json(common),item.token))
                    store._supersede(conn,item.token)
            else:
                store.reserve_operation(item,'upsert',_observed_hash(observation))
        with db.write_transaction() as conn:
            updated=conn.execute("UPDATE apple_conflicts SET status='resolved',resolution=? WHERE conflict_id=? AND status='open' AND revision=?",(choice,conflict_id,expected_revision)).rowcount
            if updated!=1:
                raise RevisionConflict('Conflict changed during resolution')
            conn.execute("UPDATE apple_resolutions SET status='applied' WHERE conflict_id=?",(conflict_id,))
        return _report()
