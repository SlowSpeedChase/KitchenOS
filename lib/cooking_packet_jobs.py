"""Bounded, process-local packet operations; saved packets remain durable.

Replay is scoped to kind/week/request ID while an operation is retained. Once
lost or pruned, callers may retry; the repository deduplicates committed request
IDs. Workers publish only validated revision numbers, never exception text.
"""
from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
import re
import threading
from typing import Callable
from uuid import uuid4

from lib.safe_paths import parse_iso_week

MAX_TERMINAL_OPERATIONS = 100
MAX_ACTIVE_OPERATIONS = 16
_lock = threading.RLock()
_operations: dict[str, dict] = {}
_requests: dict[tuple[str, str, str], str] = {}
_active: dict[tuple[str, str], str] = {}
_terminal: OrderedDict[str, None] = OrderedDict()
_FAILURE = 'Refresh failed. The previous saved packet is still available. Please retry.'


class OperationConflict(ValueError):
    """A different request is already running for this kind and week."""


class OperationCapacity(ValueError):
    """All background worker slots are occupied."""


def _identifier(value, *, limit=128):
    if not isinstance(value, str) or not 1 <= len(value) <= limit or not re.fullmatch(r'[A-Za-z0-9_-]+', value):
        raise ValueError('invalid operation identifier')


def _scope(kind, week):
    _identifier(kind, limit=32)
    parse_iso_week(week)


def _launch(target):
    threading.Thread(target=target, name='cooking-packet-refresh', daemon=True).start()


def clear_operations():
    """Forget volatile status (also used to isolate tests); cannot cancel work."""
    with _lock:
        _operations.clear()
        _requests.clear()
        _active.clear()
        _terminal.clear()


def _finish(operation_id, result):
    with _lock:
        operation = _operations.get(operation_id)
        if operation is None:  # A reset must not resurrect a forgotten worker.
            return
        operation.update(result)
        _active.pop((operation['kind'], operation['week']), None)
        _terminal[operation_id] = None
        while len(_terminal) > MAX_TERMINAL_OPERATIONS:
            oldest, _ = _terminal.popitem(last=False)
            expired = _operations.pop(oldest)
            _requests.pop((expired['kind'], expired['week'], expired['request_id']), None)


def start_operation(kind: str, week: str, request_id: str, worker: Callable[[], dict]) -> dict:
    """Atomically reserve one worker; duplicate requests reuse its status."""
    _scope(kind, week)
    _identifier(request_id)
    if not callable(worker):
        raise ValueError('worker must be callable')
    with _lock:
        key = (kind, week, request_id)
        if key in _requests:
            return deepcopy(_operations[_requests[key]])
        if (kind, week) in _active:
            raise OperationConflict('A refresh for this week is already running.')
        if len(_active) >= MAX_ACTIVE_OPERATIONS:
            raise OperationCapacity('Refresh workers are busy. Please retry shortly.')
        operation_id = uuid4().hex
        operation = {'id': operation_id, 'kind': kind, 'week': week,
                     'request_id': request_id, 'status': 'pending'}
        _operations[operation_id] = operation
        _requests[key] = operation_id
        _active[(kind, week)] = operation_id

    def run():
        try:
            output = worker()
            if not isinstance(output, dict):
                raise ValueError('invalid worker result')
            result = {'status': 'complete'}
            if 'revision' in output:
                if type(output['revision']) is not int or output['revision'] < 1:
                    raise ValueError('invalid committed revision')
                result['revision'] = output['revision']
        except Exception:
            result = {'status': 'failed', 'error': _FAILURE}
        _finish(operation_id, result)

    try:
        _launch(run)
    except Exception:
        _finish(operation_id, {'status': 'failed', 'error': _FAILURE})
    with _lock:
        return deepcopy(_operations.get(operation_id, operation))


def get_operation(kind: str, week: str, operation_id: str) -> dict | None:
    """Return a detached status only within the requested kind/week scope."""
    _scope(kind, week)
    _identifier(operation_id)
    with _lock:
        operation = _operations.get(operation_id)
        if operation and (operation['kind'], operation['week']) == (kind, week):
            return deepcopy(operation)
    return None
