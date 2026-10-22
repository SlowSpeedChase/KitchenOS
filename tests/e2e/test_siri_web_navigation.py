"""Real remote authentication, exact-day content, and zero navigation writes."""
import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e
TOKEN = {'Authorization': 'Bearer siri-fixture-token'}


def open_destination(page, server, destination):
    if not any(c['name']=='kitchenos_view' for c in page.context.cookies()):
        assert page.request.get(server.url('/api/recipes')).status == 401
    response = page.request.post(server.url('/api/browser-handoffs'), headers=TOKEN, data=destination)
    assert response.ok, response.text()
    path = response.json()['handoff_path']
    secret_at_exchange=[]
    def observe_exchange(request):
        if request.url.endswith('/api/browser-handoffs/exchange'):
            secret_at_exchange.append('#' in page.url)
    page.on('request',observe_exchange)
    page.goto(server.url(path))
    page.wait_for_url(lambda url: '/browser/open' not in str(url))
    expect(page.get_by_text('Viewing from Siri', exact=False)).to_be_visible()
    assert 'code=' not in page.url
    assert secret_at_exchange == [False]
    page.remove_listener('request',observe_exchange)


def visible_in_viewport(locator):
    expect(locator).to_be_visible()
    expect(locator).to_be_in_viewport(ratio=1)


@pytest.mark.parametrize('size', [{'width':390,'height':844}, {'width':1440,'height':1000}])
def test_exact_recipe_read_only_and_local_scaling(page, siri_server, size):
    page.set_viewport_size(size)
    open_destination(page, siri_server, {'kind':'recipe','name':'Rice & Beans 100%'})
    writes=[]
    page.on('request', lambda request: writes.append(request.url) if request.method not in ('GET','HEAD') else None)
    expect(page.get_by_text('Simmer the fixture rice until tender.', exact=False).first).to_be_visible()
    if size['width']==390:page.screenshot(path='/tmp/kitchenos-siri-recipe.png')
    expect(page.locator('#add-week-btn')).to_be_disabled()
    page.locator('#scale-select').select_option('2')
    expect(page.locator('#scale-select')).to_have_value('2')
    page.reload()
    expect(page.get_by_text('Simmer the fixture rice until tender.', exact=False).first).to_be_visible()
    assert writes == []


@pytest.mark.parametrize('size', [{'width':390,'height':844}, {'width':1440,'height':1000}])
def test_exact_day_content_survives_reload_refresh_and_view_switch(page, siri_server, size):
    page.set_viewport_size(size)
    open_destination(page, siri_server, {'kind':'meal_plan','date':'2026-10-16'})
    writes=[]
    page.on('request', lambda request: writes.append(request.url) if request.method not in ('GET','HEAD') else None)
    heading = page.locator('.pc-meals-heading[data-date="2026-10-16"]')
    expect(heading).to_be_focused()
    expect(page.locator('#loading')).to_have_css('opacity','0')
    visible_in_viewport(heading)
    assert heading.evaluate('(el)=>el.getBoundingClientRect().top')<160
    meal = page.locator('.pc-selected-day .pc-day-meals').get_by_text('Rice & Beans 100% · dinner', exact=True)
    visible_in_viewport(meal)
    expect(page.locator('#loading')).to_have_css('opacity','0')
    if size['width']==390:page.screenshot(path='/tmp/kitchenos-siri-friday.png')
    page.get_by_role('button',name='Refresh calendar',exact=True).click()
    expect(page.locator('.pc-selected-day')).to_have_attribute('data-date','2026-10-16')
    expect(page.get_by_role('button',name='Refresh calendar',exact=True)).to_be_focused()
    page.get_by_role('button',name='Grid',exact=True).click()
    expect(page.locator('.day-header.selected-date')).to_be_focused()
    visible_in_viewport(page.locator('.grid-cell.selected-date[data-meal="dinner"] .cook-card'))
    expect(page.locator('.cook-card .remove-btn')).to_be_disabled()
    assert page.locator('.grid-cell').first.evaluate('(el)=>!Sortable.get(el)')
    page.locator('.grid-cell.selected-date[data-meal="breakfast"]').click()
    page.get_by_role('button',name='Calendar',exact=True).click()
    expect(heading).to_be_focused()
    page.reload()
    expect(heading).to_be_focused()
    page.get_by_role('button',name='Next day',exact=True).click()
    expect(page.locator('.pc-selected-day')).to_have_attribute('data-date','2026-10-17')
    expect(page.locator('.pc-meals-heading[data-date="2026-10-17"]')).to_be_focused()
    visible_in_viewport(page.locator('.pc-selected-day').get_by_text('No meals planned for this day.',exact=True))
    assert 'date=2026-10-17' in page.url
    page.get_by_role('button',name='Next week',exact=True).click()
    expect(page.locator('.pc-selected-day')).to_have_attribute('data-date','2026-10-24')
    assert 'week=2026-W43' in page.url and 'date=2026-10-24' in page.url
    assert writes == []


def test_date_overrides_week_and_invalid_date_explained(page,siri_server):
    open_destination(page,siri_server,{'kind':'meal_plan','date':'2026-10-16'})
    page.goto(siri_server.url('/meal-planner?week=2026-W01&date=2027-01-03&view=calendar'))
    assert 'week=2026-W53' in page.url
    expect(page.locator('.pc-selected-day')).to_have_attribute('data-date','2027-01-03')
    page.goto(siri_server.url('/meal-planner?date=2026-02-29&view=calendar'))
    expect(page.get_by_role('alert')).to_contain_text('Choose a valid date')


def test_bootstrap_missing_code_is_clear_and_does_not_fetch(page,siri_server):
    posts=[]
    page.on('request', lambda request: posts.append(request.url) if request.method=='POST' else None)
    page.goto(siri_server.url('/browser/open'))
    expect(page.get_by_role('alert')).to_contain_text('Ask Siri to open')
    assert posts == []


@pytest.mark.parametrize('destination', [
    {'kind':'recipe','name':'Rice & Beans 100%'},
    {'kind':'meal_plan','date':'2026-10-16'},
])
def test_expiry_stops_refresh_and_reload_stays_restricted(page,siri_server,destination):
    import time
    clock = siri_server.db.parent / 'clock.txt'
    started=time.time()
    clock.write_text(str(started))
    from datetime import datetime, timezone
    page.clock.install(time=datetime.fromtimestamp(started,timezone.utc))
    open_destination(page,siri_server,destination)
    if destination['kind']=='meal_plan':
        expect(page.locator('.pc-selected-day')).to_have_attribute('data-date','2026-10-16')
    page.clock.fast_forward(901_000)
    expect(page.locator('.browser-view-banner')).to_contain_text('has expired')
    requests=[]
    page.on('request',lambda req: requests.append((req.method,req.url)))
    page.clock.fast_forward(180_000)
    assert requests == []
    clock.write_text(str(started+901))
    cookies=page.context.cookies()
    assert any(c['name']=='kitchenos_view' for c in cookies)
    page.reload()
    expect(page.locator('.browser-view-banner')).to_contain_text('has expired')
    assert not [url for _,url in requests if '/api/' in url]
    response=page.request.get(siri_server.url('/api/recipes/Rice%20%26%20Beans%20100%25'))
    assert response.status==401
    response=page.request.get(siri_server.url('/refresh?file=Rice%20%26%20Beans%20100%25'))
    assert response.status in (401,403)
    clock.write_text(str(time.time()))


def test_late_old_calendar_response_cannot_restore_previous_week(page,siri_server):
    from datetime import date,timedelta
    open_destination(page,siri_server,{'kind':'meal_plan','date':'2026-10-16'})
    expect(page.locator('.pc-selected-day')).to_have_attribute('data-date','2026-10-16')
    page.get_by_role('button',name='Grid',exact=True).click()
    pending=[]
    page.route('**/api/planning-calendar/2026-W42*',lambda route:pending.append(route))
    with page.expect_request('**/api/planning-calendar/2026-W42*'):
        page.get_by_role('button',name='Calendar',exact=True).click()
    page.get_by_role('button',name='Next week',exact=True).click()
    expect(page.locator('.pc-selected-day')).to_have_attribute('data-date','2026-10-23')
    assert pending
    days={(date(2026,10,12)+timedelta(days=i)).isoformat():{'covered':False,'windows':[]} for i in range(7)}
    pending[0].fulfill(json={'timezone':'America/Chicago','days':days,'events':[],'schedules':[],'choices':{},'fresh':False})
    expect(page.locator('.pc-selected-day')).to_have_attribute('data-date','2026-10-23')
    expect(page.locator('.pc-meals-heading[data-date="2026-10-23"]')).to_be_focused()
    assert 'date=2026-10-23' in page.url


@pytest.mark.parametrize('zone,day,week', [
    ('Pacific/Kiritimati','2026-10-16','2026-W42'),
    ('America/New_York','2026-11-01','2026-W44'),
    ('Pacific/Kiritimati','2027-01-03','2026-W53'),
    ('America/Chicago','2027-01-04','2027-W01'),
])
def test_civil_date_keeps_requested_day_across_timezone_and_iso_year(browser,siri_server,zone,day,week):
    context=browser.new_context(timezone_id=zone,viewport={'width':390,'height':844})
    page=context.new_page()
    try:
        open_destination(page,siri_server,{'kind':'meal_plan','date':day})
        heading=page.locator(f'.pc-meals-heading[data-date="{day}"]')
        expect(heading).to_be_focused()
        visible_in_viewport(heading)
        assert f'week={week}' in page.url and f'date={day}' in page.url
        page.get_by_role('button',name='Grid',exact=True).click()
        expect(page.locator('.day-header.selected-date')).to_have_attribute('data-date',day)
        page.reload()
        expect(page.locator('.day-header.selected-date')).to_have_attribute('data-date',day)
    finally:
        context.close()


def test_legacy_markdown_meal_is_visible_without_import_or_write(page,siri_server):
    import sqlite3
    plan=siri_server.vault/'Meal Plans'/'2026-W43.md'
    side=siri_server.vault/'Recipes'/'Legacy side.md'
    side.write_text((siri_server.vault/'Recipes'/'Rice & Beans 100%.md').read_text().replace('Rice & Beans 100%','Legacy side'))
    plan.write_text('## Friday (Oct 23)\n### Dinner\n[[Rice & Beans 100%]] x1\n[[Legacy side]] x0.5\n')
    before=plan.read_bytes()
    writes=[]
    try:
        open_destination(page,siri_server,{'kind':'meal_plan','date':'2026-10-23'})
        page.on('request',lambda req:writes.append(req.url) if req.method not in ('GET','HEAD') else None)
        meal=page.locator('.pc-selected-day .pc-day-meals').get_by_text('Rice & Beans 100% · dinner',exact=True)
        expect(page.locator('#loading')).to_have_css('opacity','0')
        visible_in_viewport(meal)
        visible_in_viewport(page.locator('.pc-selected-day .pc-day-meals').get_by_text('Legacy side · dinner',exact=True))
        expect(page.locator('.pc-selected-day .pc-planned-meal')).to_have_count(2)
        expect(page.locator('.pc-selected-day').get_by_text('No meals planned for this day.',exact=True)).to_have_count(0)
        page.reload()
        visible_in_viewport(meal)
        with sqlite3.connect(siri_server.db) as conn:
            assert conn.execute("SELECT COUNT(*) FROM cooks WHERE week='2026-W43'").fetchone()[0]==0
        assert plan.read_bytes()==before and writes==[]
    finally:
        plan.unlink(missing_ok=True)
        side.unlink(missing_ok=True)


@pytest.fixture
def projected_meals(siri_server):
    import sqlite3
    with sqlite3.connect(siri_server.db) as conn:
        cursor=conn.execute("INSERT INTO cooks(recipe,week,date,meal,scale,servings_produced) VALUES ('Rice & Beans 100%','2026-W45','2026-11-06','dinner',1,8)")
        identity=cursor.lastrowid
        for day,meal in [('2026-11-06','dinner'),('2026-11-07','lunch'),('2026-11-13','lunch')]:
            conn.execute("INSERT INTO placements(cook_id,destination,date,meal,count) VALUES (?,'slot',?,?,1)",(identity,day,meal))
    # Generated Markdown can repeat the same ledger identity; it must not double the meal.
    plan=siri_server.vault/'Meal Plans'/'2026-W45.md'
    plan.write_text('## Friday (Nov 6)\n### Dinner\n[[Rice & Beans 100%]] x1\n')
    yield identity
    plan.unlink(missing_ok=True)
    with sqlite3.connect(siri_server.db) as conn:
        conn.execute('DELETE FROM placements WHERE cook_id=?',(identity,))
        conn.execute('DELETE FROM cooks WHERE id=?',(identity,))


def test_anchor_and_leftover_placements_show_once_in_each_requested_day(page,siri_server,projected_meals):
    for day,slot in [('2026-11-06','dinner'),('2026-11-07','lunch'),('2026-11-13','lunch')]:
        open_destination(page,siri_server,{'kind':'meal_plan','date':day})
        row=page.locator('.pc-selected-day .pc-day-meals').get_by_text(f'Rice & Beans 100% · {slot}',exact=True)
        expect(row).to_have_count(1)
        visible_in_viewport(row)
        expect(page.locator('.pc-selected-day').get_by_text('No meals planned for this day.',exact=True)).to_have_count(0)


def test_read_only_touch_card_opens_web_recipe_without_mutations(browser,siri_server):
    context=browser.new_context(viewport={'width':390,'height':844},is_mobile=True,has_touch=True)
    page=context.new_page()
    try:
        open_destination(page,siri_server,{'kind':'meal_plan','date':'2026-10-16'})
        page.get_by_role('button',name='Grid',exact=True).tap()
        assert page.evaluate('window.IS_TOUCH') is True
        writes=[]
        page.on('request',lambda req:writes.append(req.url) if req.method not in ('GET','HEAD') else None)
        page.locator('.cook-card').tap()
        expect(page.locator('#card-sheet-backdrop')).to_have_class('sheet-backdrop visible')
        expect(page.locator('#card-sheet-actions button')).to_have_count(1)
        page.get_by_role('button',name='Open recipe',exact=True).tap()
        expect(page.locator('#instructions-list')).to_contain_text('Simmer the fixture rice until tender.')
        assert '/recipe/Rice%20%26%20Beans%20100%25' in page.url
        assert writes==[]
    finally:
        context.close()


@pytest.mark.parametrize('ledger',[False,True])
def test_plate_keeps_its_name_and_canonical_members_in_calendar_and_touch_sheet(browser,siri_server,ledger):
    import sqlite3
    recipes=siri_server.vault/'Recipes'
    side=recipes/'Side 50%.md'
    side.write_text((recipes/'Rice & Beans 100%.md').read_text().replace('Rice & Beans 100%','Side 50%'))
    definition=siri_server.vault/'Meals'/'Fixture plate.meal.md'
    definition.write_text('---\ntype: meal\nname: Fixture plate\nslot: dinner\nsub_recipes:\n  - recipe: "Rice & Beans 100%"\n    servings: 0.5\n  - recipe: "Side 50%"\n    servings: 0.5\n---\n')
    plan=siri_server.vault/'Meal Plans'/'2026-W45.md'
    plan.write_text('## Friday (Nov 6)\n### Dinner\n[[Meal: Fixture plate]] x1\n')
    identities=[]
    if ledger:
        with sqlite3.connect(siri_server.db) as conn:
            for recipe in ['Rice & Beans 100%','Side 50%']:
                cursor=conn.execute("INSERT INTO cooks(recipe,week,date,meal,scale,servings_produced,bundle_id,bundle_name) VALUES (?,'2026-W45','2026-11-06','dinner',0.5,4,'fixture-bundle','Fixture plate')",(recipe,))
                identities.append(cursor.lastrowid)
                for day,slot in [('2026-11-06','dinner'),('2026-11-07','lunch')]:
                    conn.execute("INSERT INTO placements(cook_id,destination,date,meal,count) VALUES (?,'slot',?,?,0.5)",(cursor.lastrowid,day,slot))
    context=browser.new_context(viewport={'width':390,'height':844},is_mobile=True,has_touch=True)
    page=context.new_page()
    try:
        open_destination(page,siri_server,{'kind':'meal_plan','date':'2026-11-06'})
        expect(page.locator('.pc-selected-day .pc-planned-meal')).to_have_count(1)
        expect(page.locator('.pc-selected-day').get_by_text('Fixture plate · dinner',exact=True)).to_be_visible()
        links=page.locator('.pc-selected-day .pc-planned-meal a')
        expect(links).to_have_count(2)
        assert links.nth(0).get_attribute('href')=='/recipe/Rice%20%26%20Beans%20100%25'
        assert links.nth(1).get_attribute('href')=='/recipe/Side%2050%25'
        writes=[]
        page.on('request',lambda req:writes.append(req.url) if req.method not in ('GET','HEAD') else None)
        page.get_by_role('button',name='Grid',exact=True).tap()
        page.locator('.grid-card.is-meal .meal-header').tap()
        expect(page.locator('#card-sheet-actions button')).to_have_count(2)
        page.get_by_role('button',name='Open Rice & Beans 100%',exact=True).tap()
        expect(page.locator('#instructions-list')).to_contain_text('Simmer the fixture rice until tender.')
        if ledger:
            page.goto(siri_server.url('/meal-planner?date=2026-11-07&view=calendar'))
            expect(page.locator('.pc-selected-day .pc-planned-meal')).to_have_count(1)
            expect(page.locator('.pc-selected-day').get_by_text('Fixture plate · lunch',exact=True)).to_be_visible()
            expect(page.locator('.pc-selected-day .pc-planned-meal a')).to_have_count(2)
        assert writes==[]
    finally:
        context.close()
        for path in [side,definition,plan]:path.unlink(missing_ok=True)
        with sqlite3.connect(siri_server.db) as conn:
            for identity in identities:
                conn.execute('DELETE FROM placements WHERE cook_id=?',(identity,))
                conn.execute('DELETE FROM cooks WHERE id=?',(identity,))
