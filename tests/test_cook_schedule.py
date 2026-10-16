from concurrent.futures import ThreadPoolExecutor
import pytest
from lib import serving_ledger as sl


def cook():
    return sl.create_cook(recipe='The Sexy Skillet Lasagna',week='2026-W39',servings_produced=8)

def args(**changes):
    return dict(dict(date='2026-09-22',meal='dinner',start='2026-09-22T19:00:00-05:00',timezone='America/Chicago',duration_minutes=90,servings_to_eat=1),**changes)

def test_retry_and_concurrency_only_place_once():
    c=cook()
    with ThreadPoolExecutor(2) as pool:
        list(pool.map(lambda _:sl.schedule_cook(c['id'],**args()),range(2)))
    saved=sl.get_cook(c['id'])
    assert saved['date']=='2026-09-22'
    assert sum(p['count'] for p in saved['placements'])==1
    assert saved['unassigned']==7 and saved['cooked_at'] is None and saved['scale']==1
    assert len(sl.schedules_for_week('2026-W39'))==1

def test_capacity_rollback_and_fractional_first_placement():
    c=cook()
    with pytest.raises(sl.OverplacementError): sl.schedule_cook(c['id'],**args(servings_to_eat=9))
    assert sl.get_cook(c['id'])['date'] is None
    assert not sl.schedules_for_week('2026-W39')
    sl.schedule_cook(c['id'],**args(servings_to_eat=1.5))
    assert sl.get_cook(c['id'])['unassigned']==6.5

def test_existing_servings_and_leftovers_preserved_then_cleanup():
    c=cook()
    sl.schedule_cook(c['id'],**args(servings_to_eat=2))
    sl.add_placement(c['id'],'slot',1,date='2026-09-25',meal='lunch')
    sl.schedule_cook(c['id'],**args(date='2026-09-23',start='2026-09-23T19:00:00-05:00',servings_to_eat=3))
    assert {(p['date'],p['count']) for p in sl.get_cook(c['id'])['placements']}=={('2026-09-23',2),('2026-09-25',1)}
    sl.move_cook(c['id'],'2026-09-24','dinner')
    assert not sl.schedules_for_week('2026-W39')
    sl.schedule_cook(c['id'],**args())
    sl.update_cook(c['id'],notes='unchanged anchor')
    assert sl.schedules_for_week('2026-W39')
    sl.update_cook(c['id'],meal='lunch')
    assert not sl.schedules_for_week('2026-W39')
    sl.schedule_cook(c['id'],**args())
    sl.delete_cook(c['id'])
    assert not sl.schedules_for_week('2026-W39')

@pytest.mark.parametrize('changes',[
    {'date':'2026-09-29','start':'2026-09-29T19:00:00-05:00'},
    {'start':'2026-09-22T19:00:00Z'}, {'start':'2026-09-22T19:01:00-05:00'},
    {'start':'2026-09-23T19:00:00-05:00'}, {'start':'2026-09-22T23:00:00-05:00'},
    {'timezone':'bad'}, {'duration_minutes':True}, {'servings_to_eat':float('nan')},
    {'servings_to_eat':0},{'servings_to_eat':True}])
def test_invalid_schedule_is_atomic(changes):
    c=cook()
    with pytest.raises(ValueError): sl.schedule_cook(c['id'],**args(**changes))
    assert sl.get_cook(c['id'])['date'] is None

def test_cooked_and_missing_rejected():
    with pytest.raises(ValueError):sl.schedule_cook(999,**args())
    c=cook();sl.update_cook(c['id'],cooked_at='2026-09-21')
    with pytest.raises(ValueError):sl.schedule_cook(c['id'],**args())

def test_api_schedule_and_read():
    from api_server import app
    c=cook();client=app.test_client()
    response=client.post(f"/api/cooks/{c['id']}/schedule",json=args())
    assert response.status_code==200
    assert response.json['cook']['date']=='2026-09-22'
    assert client.get('/api/planning-calendar/2026-W39').json['schedules'][0]['cook_id']==c['id']


def test_selected_cook_does_not_block_its_own_opening():
    from lib import planning_calendar as pc
    from datetime import datetime,timezone
    now=datetime.now(timezone.utc)
    pc.save_snapshot(dict(version=1,selection_id='a'*64,generated_at=now.isoformat(),timezone='America/Chicago',coverage_start='2026-09-19',coverage_end='2026-10-24',events=[]))
    c=cook();sl.schedule_cook(c['id'],**args(duration_minutes=180))
    result=pc.read_week('2026-W39',duration_minutes=180,exclude_cook_id=c['id'])
    assert any(w['start']=='2026-09-22T19:00:00-05:00' for w in result['days']['2026-09-22']['windows'])
