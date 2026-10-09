"""Version-one HTTP contract. Local writer checks are independent of token policy."""
from functools import wraps
from flask import jsonify, request
from werkzeug.exceptions import BadRequest, UnsupportedMediaType, RequestEntityTooLarge
from . import service
from .models import BridgeContext, BatchTooLarge, InvalidPayload, OwnershipConflict, RevisionConflict, ScopeRequest, SourceUnavailable, validate_observations

MAX_BYTES=2*1024*1024

def register_routes(app, require_token):
    def endpoint(path, methods, *, local=False):
        def decorate(fn):
            @wraps(fn)
            def handle(**kwargs):
                if local and request.remote_addr not in {'127.0.0.1','::1'}:
                    return jsonify(error='Designated bridge requires localhost'),403
                request.max_content_length=MAX_BYTES
                try:
                    if request.content_length and request.content_length>MAX_BYTES:
                        raise RequestEntityTooLarge()
                    response=jsonify(fn(**kwargs))
                    if len(response.get_data())>MAX_BYTES:
                        raise RequestEntityTooLarge()
                    return response
                except (RequestEntityTooLarge,BatchTooLarge):
                    return jsonify(error='Complete batch exceeds request limit'),413
                except (InvalidPayload,BadRequest,UnsupportedMediaType) as exc:
                    return jsonify(error=str(exc)),400
                except OwnershipConflict as exc:
                    return jsonify(error=str(exc)),403
                except RevisionConflict as exc:
                    return jsonify(error=str(exc)),409
                except (SourceUnavailable,OSError):
                    return jsonify(error='Source recovery unavailable; retry',retryable=True,report=service._report(unavailable=1).to_dict()),503
            app.add_url_rule('/api/apple-integration'+path,'apple_'+fn.__name__,require_token(handle),methods=methods)
            return fn
        return decorate

    def body(required, optional=()):
        data=request.get_json()
        if not isinstance(data,dict) or data.keys()-set(required)-set(optional) or set(required)-data.keys():
            raise InvalidPayload('Unexpected or missing request keys')
        return data

    @endpoint('/owner',['POST'],local=True)
    def owner():
        data=body(['owner_id'],['permissions','destinations'])
        context=service.register_owner(**data)
        return {'model_version':1,'context':context.to_dict(),'status':service.status()}

    @endpoint('/owner',['DELETE'],local=True)
    def disconnect():
        data=body(['context'])
        return service.disconnect(BridgeContext.from_dict(data['context']))

    @endpoint('/settings',['PUT'])
    def settings():
        return service.settings(**body(['paused','expected_revision']))

    @endpoint('/scopes/<domain>/<week>',['PUT'])
    def scope(domain,week):
        data=body(['domain','week','destination_id','state','expected_revision'])
        if data['domain']!=domain or data['week']!=week:
            raise InvalidPayload('Scope path differs from payload')
        return service.update_scope(ScopeRequest.from_dict(data))

    @endpoint('/status',['GET'])
    def status():
        return service.status()

    @endpoint('/work',['GET'],local=True)
    def work():
        if set(request.args)!={'owner_id','owner_generation'}:
            raise InvalidPayload('Owner context required')
        try:
            generation=int(request.args['owner_generation'])
        except ValueError as exc:
            raise InvalidPayload('Invalid owner generation') from exc
        return service.work(BridgeContext(request.args['owner_id'],generation))

    @endpoint('/observations',['POST'],local=True)
    def observations():
        data=body(['context','request_id','complete','observations'])
        if data['complete'] is not True:
            raise InvalidPayload('Only complete batches are accepted')
        if isinstance(data['observations'],list) and len(data['observations'])>service.MAX_ITEMS:
            raise RequestEntityTooLarge()
        values=validate_observations(data['observations'])
        result=service.observe(BridgeContext.from_dict(data['context']),values,data['request_id'])
        return {'operations':[op.to_dict() for op in result],'report':service._report(unavailable=sum(o.availability=='unavailable' or (o.availability=='missing' and not o.absence_confirmed) for o in values)).to_dict()}

    @endpoint('/operations/<operation_id>/ack',['POST'],local=True)
    def acknowledge(operation_id):
        data=body(['context','operation_id','outcome','locator','observed_fields','observed_hash'])
        context=BridgeContext.from_dict(data.pop('context'))
        return {'report':service.acknowledge(context,operation_id,data).to_dict()}

    @endpoint('/conflicts/<conflict_id>/resolve',['POST'])
    def resolve(conflict_id):
        data=body(['choice','expected_revision'])
        return {'report':service.resolve_conflict(conflict_id,**data).to_dict()}

    @endpoint('/items/<token>/restore',['POST'])
    def restore(token):
        data=body(['expected_revision'])
        return {'item':service.restore(token,**data).to_dict(),'report':service._report().to_dict()}

    @endpoint('/items/remove-owned',['POST'],local=True)
    def remove_owned():
        data=body(['context','request_id','items'])
        if isinstance(data['items'],list) and len(data['items'])>service.MAX_ITEMS:
            raise RequestEntityTooLarge()
        return {'operations':[o.to_dict() for o in service.remove_owned(BridgeContext.from_dict(data['context']),data['items'],data['request_id'])]}

    @endpoint('/items',['GET'])
    def item_details():
        if set(request.args) != {'domain', 'week'}:
            raise InvalidPayload('domain and week required')
        return service.item_details(request.args['domain'], request.args['week'])

    @endpoint('/conflicts/<conflict_id>',['GET'])
    def conflict_detail(conflict_id):
        return service.conflict_detail(conflict_id)

    @endpoint('/links/<token>',['GET'])
    def link(token):
        return service.link(token)
