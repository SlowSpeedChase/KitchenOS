"""Operation deduplication, bounded lifecycle, and sanitized failures."""
from concurrent.futures import ThreadPoolExecutor
import importlib
import threading

import pytest


@pytest.fixture
def jobs(monkeypatch):
    module = importlib.import_module('lib.cooking_packet_jobs')
    module.clear_operations()
    yield module
    module.clear_operations()


@pytest.fixture
def queued(jobs, monkeypatch):
    pending = []
    monkeypatch.setattr(jobs, '_launch', pending.append)
    return pending


def test_replay_pending_and_complete_runs_worker_once(jobs, queued):
    calls = []
    def work():
        calls.append(1)
        return {'revision': 2}
    first = jobs.start_operation('packet', '2026-W40', 'abc', work)
    replay = jobs.start_operation('packet', '2026-W40', 'abc', work)
    assert first['id'] == replay['id'] and first['status'] == 'pending'
    assert len(queued) == 1
    queued.pop()()
    terminal = jobs.get_operation('packet', '2026-W40', first['id'])
    assert terminal['status'] == 'complete' and terminal['revision'] == 2
    assert jobs.start_operation('packet', '2026-W40', 'abc', work) == terminal
    assert calls == [1]
    terminal['status'] = 'corrupted'
    assert jobs.get_operation('packet', '2026-W40', first['id'])['status'] == 'complete'


def test_active_conflict_and_independent_scopes(jobs, queued):
    jobs.start_operation('packet', '2026-W40', 'a', lambda: {})
    with pytest.raises(jobs.OperationConflict):
        jobs.start_operation('packet', '2026-W40', 'b', lambda: {})
    jobs.start_operation('packet', '2026-W41', 'b', lambda: {})
    jobs.start_operation('stores', '2026-W40', 'b', lambda: {})
    assert len(queued) == 3


def test_concurrent_replay_only_launches_one_worker(jobs, queued):
    barrier = threading.Barrier(8)
    def start(_):
        barrier.wait()
        return jobs.start_operation('packet', '2026-W40', 'same', lambda: {'revision': 1})
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(start, range(8)))
    assert len({r['id'] for r in results}) == 1 and len(queued) == 1


def test_terminal_pruning_keeps_active_and_newest(jobs, queued):
    active = jobs.start_operation('packet', '2026-W41', 'active', lambda: {})
    oldest = None
    for i in range(101):
        operation = jobs.start_operation('packet', '2026-W40', str(i), lambda: {'revision': 1})
        oldest = oldest or operation
        queued.pop()()
    assert jobs.get_operation('packet', '2026-W40', oldest['id']) is None
    assert jobs.get_operation('packet', '2026-W40', operation['id'])['status'] == 'complete'
    assert jobs.get_operation('packet', '2026-W41', active['id'])['status'] == 'pending'
    assert sum(jobs.get_operation('packet', '2026-W40', jobs.start_operation('packet', '2026-W40', str(i), lambda: {})['id']) is not None for i in range(1, 101)) == 100


def test_failure_is_sanitized_and_new_request_can_retry(jobs, queued):
    def fail():
        raise RuntimeError('secret-token <script>bad</script>')
    operation = jobs.start_operation('packet', '2026-W40', 'fail', fail)
    queued.pop()()
    failed = jobs.get_operation('packet', '2026-W40', operation['id'])
    assert failed['status'] == 'failed' and 'secret-token' not in str(failed)
    assert 'script' not in str(failed)
    assert jobs.start_operation('packet', '2026-W40', 'retry', lambda: {})['status'] == 'pending'


@pytest.mark.parametrize('kind,week,request_id', [
    ('', '2026-W40', 'a'), ('x'*33, '2026-W40', 'a'), ('<script>', '2026-W40', 'a'),
    ('packet', '2021-W53', 'a'), ('packet', '2026-W4', 'a'), ('packet', '2026-W40\n', 'a'),
    ('packet', '2026-W40', ''), ('packet', '2026-W40', 'x'*129),
    ('packet', '2026-W40', '<script>'), ('packet', '2026-W40', None),
])
def test_invalid_scope_or_request_rejected(jobs, queued, kind, week, request_id):
    with pytest.raises(ValueError):
        jobs.start_operation(kind, week, request_id, lambda: {})
    assert not queued


def test_unknown_wrong_scope_and_invalid_operation_id(jobs, queued):
    operation = jobs.start_operation('packet', '2026-W40', 'a', lambda: {})
    assert jobs.get_operation('packet', '2026-W41', operation['id']) is None
    assert jobs.get_operation('stores', '2026-W40', operation['id']) is None
    assert jobs.get_operation('packet', '2026-W40', 'unknown') is None
    for invalid in ('', 'a'*129, '<script>'):
        with pytest.raises(ValueError):
            jobs.get_operation('packet', '2026-W40', invalid)


def test_reset_does_not_allow_old_worker_to_publish(jobs, queued):
    before = jobs.start_operation('packet', '2026-W40', 'a', lambda: {'revision': 1})
    jobs.clear_operations()
    after = jobs.start_operation('packet', '2026-W40', 'a', lambda: {'revision': 2})
    queued.pop(0)()
    assert jobs.get_operation('packet', '2026-W40', before['id']) is None
    assert jobs.get_operation('packet', '2026-W40', after['id'])['status'] == 'pending'


def test_default_worker_runs_in_daemon_thread(jobs):
    completed = threading.Event()
    observed = []
    def worker():
        observed.append(threading.current_thread().daemon)
        completed.set()
        return {'revision': 1}
    jobs.start_operation('packet', '2026-W40', 'real-thread', worker)
    assert completed.wait(2)
    assert observed == [True]


def test_active_capacity_is_bounded_and_replay_still_available(jobs, queued):
    for week in range(1, 17):
        jobs.start_operation('packet', f'2026-W{week:02d}', 'a', lambda: {'revision': 1})
    with pytest.raises(jobs.OperationCapacity):
        jobs.start_operation('packet', '2026-W17', 'a', lambda: {})
    assert jobs.start_operation('packet', '2026-W01', 'a', lambda: {})['status'] == 'pending'
    queued.pop(0)()
    assert jobs.start_operation('packet', '2026-W17', 'a', lambda: {})['status'] == 'pending'


def test_launch_failure_is_terminal_and_releases_scope(jobs, monkeypatch):
    def fail(target):
        raise RuntimeError('secret launch failure')
    monkeypatch.setattr(jobs, '_launch', fail)
    failed = jobs.start_operation('packet', '2026-W40', 'a', lambda: {})
    assert failed['status'] == 'failed' and 'secret' not in str(failed)
    assert jobs.start_operation('packet', '2026-W40', 'b', lambda: {})['status'] == 'failed'


@pytest.mark.parametrize('result', [None, {'revision': True}, {'revision': 0}, {'revision': 'secret'}])
def test_invalid_worker_result_never_publishes_complete(jobs, queued, result):
    operation = jobs.start_operation('packet', '2026-W40', 'a', lambda: result)
    queued.pop()()
    finished = jobs.get_operation('packet', '2026-W40', operation['id'])
    assert finished['status'] == 'failed' and 'secret' not in str(finished)
