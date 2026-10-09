from datetime import datetime, timedelta, timezone
import pytest
from lib import planning_calendar as pc

NOW = datetime(2026, 9, 19, 23, 45, tzinfo=timezone.utc)

def snapshot():
    return dict(version=1, selection_id='a'*64, generated_at=NOW.isoformat(),
                timezone='America/Chicago', coverage_start='2026-09-19', coverage_end='2026-10-24',
                events=[dict(id='b'*64, title='Validator', start='2026-09-21T00:00:00-05:00',
                             end='2026-09-28T00:00:00-05:00', all_day=True, role='firm')])

def test_choice_survives_refresh_and_clear_removes_details():
    pc.save_snapshot(snapshot(), now=NOW)
    view = pc.read_week('2026-W39', now=NOW)
    pc.set_occurrence_choice('b'*64, 'background', view['revision'], now=NOW)
    pc.save_snapshot(snapshot(), now=NOW)
    assert pc.read_week('2026-W39', now=NOW)['choices'] == {'b'*64: 'background'}
    pc.clear_snapshot()
    assert pc.read_week('2026-W39', now=NOW)['events'] == []

def test_expiry_hides_titles_and_choices():
    pc.save_snapshot(snapshot(), now=NOW)
    view = pc.read_week('2026-W39', now=NOW + timedelta(hours=6))
    assert not view['fresh'] and not view['events'] and not view['choices']
    with pytest.raises(pc.StaleSnapshot):
        pc.set_occurrence_choice('b'*64, 'background', view['revision'], now=NOW+timedelta(hours=6))

def test_exclusive_end_and_outside_coverage():
    pc.save_snapshot(snapshot(), now=NOW)
    assert pc.read_week('2026-W40', now=NOW)['events'] == []
    assert not any(d['covered'] for d in pc.read_week('2026-W48', now=NOW)['days'].values())

@pytest.mark.parametrize('change', [
    {'version': True}, {'extra':'secret'}, {'timezone':'not/a/zone'}, {'generated_at':'2026-09-19'},
    {'coverage_end':'2026-12-01'}, {'selection_id':'raw-calendar'}, {'events':[{}]},
])
def test_rejects_invalid_without_replacing(change):
    pc.save_snapshot(snapshot(), now=NOW)
    bad = snapshot(); bad.update(change)
    with pytest.raises(ValueError): pc.save_snapshot(bad, now=NOW)
    assert pc.read_week('2026-W39', now=NOW)['events'][0]['title'] == 'Validator'

@pytest.mark.parametrize('change', [{'title':'x'*301}, {'all_day':1}, {'start':'2026-09-21'}, {'role':'other'}, {'description':'secret'}])
def test_bad_event(change):
    bad = snapshot(); bad['events'][0].update(change)
    with pytest.raises(ValueError): pc.save_snapshot(bad, now=NOW)

def test_duplicate_and_excess_events():
    for count in [2,5001]:
        bad=snapshot(); bad['events'] *= count
        with pytest.raises(ValueError): pc.save_snapshot(bad, now=NOW)

def test_selection_change_and_old_upload():
    pc.save_snapshot(snapshot(), now=NOW)
    rev = pc.read_week('2026-W39', now=NOW)['revision']
    pc.set_occurrence_choice('b'*64, 'blocking', rev, now=NOW)
    newer=snapshot(); newer.update(selection_id='c'*64, generated_at=(NOW+timedelta(seconds=1)).isoformat())
    pc.save_snapshot(newer, now=NOW+timedelta(seconds=1))
    assert not pc.read_week('2026-W39', now=NOW+timedelta(seconds=1))['choices']
    with pytest.raises(pc.StaleSnapshot): pc.save_snapshot(snapshot(), now=NOW+timedelta(seconds=2))
    with pytest.raises(pc.StaleSnapshot): pc.set_occurrence_choice('b'*64,'background',rev,now=NOW+timedelta(seconds=2))

def test_http_bounds_token_and_legacy_independence(monkeypatch):
    from api_server import app
    client=app.test_client()
    assert client.post('/api/planning-calendar/snapshot',data='x'*(2*1024*1024+1), content_type='application/json').status_code == 413
    monkeypatch.setenv('KITCHENOS_API_TOKEN','test-secret')
    assert client.get('/api/planning-calendar/2026-W39',environ_base={'REMOTE_ADDR':'203.0.113.5'}).status_code == 401
    pc.save_snapshot(snapshot(),now=NOW)
    client.post('/api/cooking-availability',json={'days':{}})
    assert pc.read_week('2026-W39',now=NOW)['synced_at'] == NOW.isoformat()
    assert client.get('/api/planning-calendar/bad').status_code == 400
    assert client.post('/api/planning-calendar/snapshot',json={'version':1,'clear':True}).status_code == 200


def test_clear_keeps_a_timestamp_barrier_against_delayed_uploads():
    pc.save_snapshot(snapshot(),now=NOW)
    pc.clear_snapshot(now=NOW+timedelta(milliseconds=500))
    with pytest.raises(pc.StaleSnapshot): pc.save_snapshot(snapshot(),now=NOW+timedelta(seconds=1))
    assert pc.read_week('2026-W39',now=NOW+timedelta(seconds=1))['events']==[]


def test_same_time_different_selection_is_not_an_idempotent_upload():
    pc.save_snapshot(snapshot(),now=NOW)
    changed=snapshot();changed['selection_id']='c'*64
    with pytest.raises(pc.StaleSnapshot):pc.save_snapshot(changed,now=NOW)
