from datetime import datetime, timedelta, timezone
import pytest


def client():
    from api_server import app
    return app.test_client()


def test_missing_calendar_is_unknown():
    response = client().get('/api/cooking-availability/2026-W36')
    assert response.status_code == 200
    assert set(response.json['days'].values()) == {'unknown'}


def test_snapshot_roundtrip_and_clear():
    c = client()
    payload = {'days': {'2026-09-04': 'possible', '2026-09-05': 'busy', '2026-09-06': 'good'}}
    assert c.post('/api/cooking-availability', json=payload).status_code == 200
    days = c.get('/api/cooking-availability/2026-W36').json['days']
    assert [days[d] for d in payload['days']] == ['possible', 'busy', 'good']
    assert days['2026-09-03'] == 'unknown'
    assert c.post('/api/cooking-availability', json={'days': {}}).status_code == 200
    assert set(c.get('/api/cooking-availability/2026-W36').json['days'].values()) == {'unknown'}


@pytest.mark.parametrize('payload', [None, [], {'days': {'bad': 'good'}}, {'days': {'2026-09-04': 'free'}}, {'days': {}, 'title': 'private'}, {'days': []}])
def test_invalid_snapshot_rejected(payload):
    assert client().post('/api/cooking-availability', json=payload).status_code == 400


def test_stale_data_is_unknown():
    from lib import cooking_availability as ca
    now = datetime.now(timezone.utc)
    ca.save_snapshot({'days': {'2026-09-04': 'good'}}, now=now-timedelta(hours=7))
    assert set(ca.week_status('2026-W36', now=now)['days'].values()) == {'unknown'}


def test_invalid_week():
    assert client().get('/api/cooking-availability/2026-W99').status_code == 400


def test_remote_write_requires_token(monkeypatch):
    monkeypatch.setenv('KITCHENOS_API_TOKEN', 'calendar-test-token')
    assert client().post('/api/cooking-availability', json={'days': {}}, environ_base={'REMOTE_ADDR': '203.0.113.5'}).status_code == 401


def test_bad_upload_does_not_replace_existing_snapshot():
    c = client()
    c.post('/api/cooking-availability', json={'days': {'2026-09-04': 'busy'}})
    assert c.post('/api/cooking-availability', json={'days': {'2026-09-04': []}}).status_code == 400
    assert c.get('/api/cooking-availability/2026-W36').json['days']['2026-09-04'] == 'busy'


def test_expiry_boundary_and_future_timestamp():
    from lib import cooking_availability as ca
    now = datetime.now(timezone.utc)
    for synced_at in [now-timedelta(hours=6), now+timedelta(minutes=1)]:
        ca.save_snapshot({'days': {'2026-09-04': 'good'}}, now=synced_at)
        assert ca.week_status('2026-W36', now=now)['days']['2026-09-04'] == 'unknown'
