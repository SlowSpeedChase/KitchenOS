"""The `/` shell: three columns, the registry behind a popover, no retired cards."""
import re
from datetime import date
from pathlib import Path

import pytest

from api_server import app

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def body():
    app.config['TESTING'] = True
    with app.test_client() as client:
        response = client.get('/')
        assert response.status_code == 200
        return response.get_data(as_text=True)


@pytest.mark.parametrize("element_id", [
    "meals-body", "meals-label", "meals-prev", "meals-next",
    "buy-body", "buy-label", "hand-body", "hand-label", "cook-body", "cook-day",
    "cook-open", "view-week", "view-month",
])
def test_shell_carries_every_mount_point(body, element_id):
    assert f'id="{element_id}"' in body


def test_registry_lives_in_a_native_popover(body):
    assert re.search(r'<nav id="all-pages" class="sheet" popover\b', body)
    assert 'popovertarget="all-pages"' in body


def test_heading_is_todays_date_not_a_week_id(body):
    assert date.today().strftime('%A, %b %-d') in body
    assert not re.search(r'>\s*\d{4}-W\d{2}\s*<', body)


def test_no_placeholder_survives(body):
    for placeholder in ("<!--TODAY_HEADING-->", "<!--VERDICT-->", "<!--SECTIONS-->"):
        assert placeholder not in body


def test_kitchen_today_cards_are_retired(body):
    assert 'today-card' not in body


def test_dashboard_assets_are_local(body):
    assert '<link rel="stylesheet" href="/static/dashboard.css">' in body
    assert '<script src="/static/dashboard.js" defer></script>' in body


def test_dashboard_css_uses_tokens_only():
    css = (REPO / "static" / "dashboard.css").read_text()
    assert not re.search(r'#[0-9a-fA-F]{3,8}\b', css), "colour literal in dashboard.css"
    assert not re.search(r'\brgba?\(', css), "colour literal in dashboard.css"
