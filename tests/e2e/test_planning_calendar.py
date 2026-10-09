import json
import sqlite3
from datetime import datetime, timezone
from playwright.sync_api import expect


def seed(live_server):
    conn=sqlite3.connect(live_server.db)
    conn.execute("DELETE FROM cooks WHERE week='2026-W39'")
    cursor=conn.execute("INSERT INTO cooks(recipe,week,scale,servings_produced) VALUES ('The Sexy Skillet Lasagna','2026-W39',1,8)")
    identity=cursor.lastrowid
    conn.commit();conn.close()
    return identity


def test_manual_schedule_keyboard_and_reload(page,live_server):
    identity=seed(live_server)
    page.request.post(live_server.url('/api/planning-calendar/snapshot'),data={'version':1,'clear':True})
    page.set_viewport_size({'width':390,'height':844})
    page.goto(live_server.url('/meal-planner?week=2026-W39&view=calendar'))
    expect(page.get_by_role('button',name='Calendar',exact=True)).to_have_attribute('aria-pressed','true')
    expect(page.get_by_text('Calendar needs refresh',exact=True)).to_be_visible()
    page.get_by_role('button',name='Choose cooking time',exact=True).focus()
    page.keyboard.press('Enter')
    expect(page.get_by_text('90 min · planning estimate',exact=True)).to_be_visible()
    page.get_by_label('Cooking date',exact=True).fill('2026-09-22')
    page.get_by_label('Start time',exact=True).fill('19:00')
    page.get_by_label('Timezone',exact=True).fill('America/Chicago')
    page.get_by_role('button',name='Schedule meal',exact=True).click()
    expect(page.get_by_text('Meal scheduled.',exact=True)).to_be_visible()
    page.reload()
    expect(page.locator('.pc-cook-block')).to_have_count(1)
    conn=sqlite3.connect(live_server.db)
    assert conn.execute('SELECT SUM(count) FROM placements WHERE cook_id=?',(identity,)).fetchone()[0]==1
    conn.close()
    assert page.locator('#planning-calendar').evaluate('(el)=>el.scrollWidth<=el.clientWidth+1')
    page.get_by_role('button',name='Next day',exact=True).click()
    page.screenshot(path='/tmp/kitchen-planning-mobile.png',full_page=True)


def test_real_all_day_choice_and_hostile_title(page,live_server):
    seed(live_server)
    snapshot=dict(version=1,selection_id='a'*64,generated_at=datetime.now(timezone.utc).isoformat(),timezone='America/Chicago',coverage_start='2026-09-19',coverage_end='2026-10-24',events=[
        dict(id='b'*64,title='Validator',start='2026-09-21T00:00:00-05:00',end='2026-09-28T00:00:00-05:00',all_day=True,role='firm'),
        dict(id='c'*64,title='<img src=x onerror=alert(1)>',start='2026-09-22T17:00:00-05:00',end='2026-09-22T19:00:00-05:00',all_day=False,role='flexible')])
    assert page.request.post(live_server.url('/api/planning-calendar/snapshot'),data=snapshot).ok
    page.set_viewport_size({'width':1280,'height':900})
    page.goto(live_server.url('/meal-planner?week=2026-W39&view=calendar'))
    expect(page.get_by_text('<img src=x onerror=alert(1)>',exact=True)).to_be_visible()
    expect(page.locator('#planning-calendar img')).to_have_count(0)
    page.get_by_role('button',name='Background information',exact=True).first.click()
    expect(page.get_by_role('button',name='Background information',exact=True).first).to_have_attribute('aria-pressed','true')
    page.get_by_role('button',name='Choose cooking time',exact=True).click()
    page.get_by_label('Cooking date',exact=True).fill('2026-09-22')
    page.get_by_label('Cooking date',exact=True).dispatch_event('change')
    expect(page.locator('.pc-opening').first).to_be_visible()
    page.locator('.pc-opening').first.click()
    expect(page.get_by_role('button',name='Schedule meal',exact=True)).to_be_visible()
    page.screenshot(path='/tmp/kitchen-planning-desktop.png',full_page=True)


def test_recipe_timing_and_failed_refresh_clears_calendar_details(page,live_server):
    seed(live_server)
    page.route('**/api/recipes/The%20Sexy%20Skillet%20Lasagna',lambda route:route.fulfill(json={'cooking_duration':{'minutes':75,'source':'recipe'}}))
    page.goto(live_server.url('/meal-planner?week=2026-W39&view=calendar'))
    page.get_by_role('button',name='Choose cooking time',exact=True).click()
    expect(page.get_by_label('Duration (minutes)',exact=True)).to_have_value('75')
    page.route('**/api/planning-calendar/2026-W39*',lambda route:route.fulfill(status=503,json={'error':'Unavailable'}))
    page.get_by_role('button',name='Refresh calendar',exact=True).click()
    expect(page.locator('.pc-all-day-item')).to_have_count(0)
    expect(page.get_by_text('Calendar availability is unknown.',exact=False)).to_be_visible()


def test_native_fetch_bridge_scopes_credentials_and_preserves_requests(page,live_server):
    from pathlib import Path
    script=(Path(__file__).resolve().parents[2]/'KitchenOSKit/Sources/KitchenOSKit/Resources/planning-auth.js').read_text()
    page.goto(live_server.url('/health'))
    seen=[]
    page.route('**/api/bridge-test',lambda route:(seen.append(dict(route.request.headers)),route.fulfill(json={'ok':True})))
    page.route('https://example.invalid/api/bridge-test',lambda route:(seen.append(dict(route.request.headers)),route.fulfill(headers={'Access-Control-Allow-Origin':'*'},json={'ok':True})))
    page.evaluate('(() => {'+script+f'\ninstallPlanningAuthorization({json.dumps(live_server.base_url)}, "test-token");'+'})()')
    page.evaluate("fetch(new Request('/api/bridge-test',{headers:{'X-Kitchen-Test':'kept'}}),{method:'POST',body:'body'})")
    assert seen[-1]['authorization']=='Bearer test-token'
    assert seen[-1]['x-kitchen-test']=='kept'
    page.evaluate("fetch('https://example.invalid/api/bridge-test')")
    assert 'authorization' not in seen[-1]


def test_switching_meals_reloads_openings_for_their_duration(page,live_server):
    seed(live_server)
    conn=sqlite3.connect(live_server.db)
    conn.execute("INSERT INTO cooks(recipe,week,scale,servings_produced) VALUES ('Second meal','2026-W39',1,4)")
    conn.commit();conn.close()
    page.route('**/api/recipes/*',lambda route:route.fulfill(json={'cooking_duration':{'minutes':90,'source':'estimate'}}))
    page.goto(live_server.url('/meal-planner?week=2026-W39&view=calendar'))
    page.get_by_role('button',name='Choose cooking time',exact=True).first.click()
    page.get_by_label('Duration (minutes)',exact=True).fill('180')
    with page.expect_response('**/api/planning-calendar/*duration_minutes=180*'):
        page.get_by_label('Duration (minutes)',exact=True).dispatch_event('change')
    with page.expect_response('**/api/planning-calendar/*duration_minutes=90*'):
        page.get_by_role('button',name='Choose cooking time',exact=True).nth(1).click()
