"""Synthetic browser fixture: no live server, vault, DB, Apple store or LLM."""
from pathlib import Path
from urllib.parse import urlsplit
import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e

SCRIPT = Path(__file__).resolve().parents[2] / 'static' / 'planning-calendar.js'

@pytest.mark.parametrize('focus,expected', [('42','linked'), ('999','missing'), ('42%2F..','ignored'), ('-1','ignored')])
def test_native_cook_focus_is_read_only_and_exact(page, focus, expected):
    requests=[]
    errors=[]
    page.on('pageerror', lambda error: errors.append(str(error)))
    def respond(route):
        request=route.request
        requests.append((request.method, urlsplit(request.url).path))
        path=urlsplit(request.url).path
        if path=='/':
            route.fulfill(content_type='text/html',body='<main id="calendar"></main>')
        elif path.startswith('/api/planning-calendar/'):
            route.fulfill(json=dict(fresh=False,timezone='America/Chicago',duration_minutes=90,
                events=[],schedules=[],choices={},days={f'2026-10-{d:02}':dict(covered=False,windows=[]) for d in range(5,12)}))
        elif path=='/api/week-board/2026-W41':
            route.fulfill(json={'cooks':[dict(id=42,recipe='Linked dinner',date=None,bundle_id=None,cooked_at=None)]})
        elif path=='/api/recipes/Linked%20dinner' or path=='/api/recipes/Linked dinner':
            route.fulfill(json={'cooking_duration':{'minutes':90,'source':'estimate'}})
        else:
            route.fulfill(status=404,json={'error':'Unexpected request'})
    page.route('**/*',respond)
    page.goto('http://kitchenos.test/?focusCookID='+focus)
    page.add_script_tag(content=SCRIPT.read_text())
    page.evaluate("window.mounted=KitchenPlanningCalendar.mount({root:document.querySelector('#calendar'),week:'2026-W41'})")
    if expected=='linked':
        expect(page.get_by_label('Cooking date',exact=True)).to_be_visible()
        expect(page.locator('.pc-editor h3')).to_have_text('Linked dinner')
        expect(page.get_by_role('button',name='Schedule meal',exact=True)).to_be_visible()
    elif expected=='missing':
        expect(page.locator('.pc-status')).to_contain_text('no longer available')
        expect(page.locator('.pc-editor')).to_be_hidden()
    else:
        expect(page.locator('.pc-status')).to_have_text('Calendar needs refresh')
        expect(page.locator('.pc-editor')).to_be_hidden()
    assert not errors
    assert all(method=='GET' for method,path in requests), requests
    assert not any(path.endswith('/schedule') for method,path in requests)
    page.evaluate('window.mounted.destroy()')
