"""Tests for the injected Claude launch bar."""
import pytest
from api_server import app, _inject_after_body, _claude_bar_html


@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as c:
        yield c


# --- unit: injection helper ---

def test_inject_after_body_tag():
    out = _inject_after_body('<html><body class="x">HI</body></html>', 'SNIP')
    assert out == '<html><body class="x">SNIPHI</body></html>'

def test_inject_no_body_prepends():
    out = _inject_after_body('<div>no body here</div>', 'SNIP')
    assert out == 'SNIP<div>no body here</div>'

def test_inject_is_case_insensitive():
    out = _inject_after_body('<BODY>HI</BODY>', 'SNIP')
    assert out.startswith('<BODY>SNIP')

def test_bar_html_has_ssh_and_endpoint():
    bar = _claude_bar_html()
    assert 'id="ko-claude-bar"' in bar
    assert 'ssh://' in bar
    assert '/api/claude-notes' in bar

def test_bar_html_uses_env_target(monkeypatch):
    monkeypatch.setenv('KITCHENOS_SSH_TARGET', 'tester@example.ts.net')
    assert 'ssh://tester@example.ts.net' in _claude_bar_html()


# --- route level: every simple page carries the bar ---

@pytest.mark.parametrize('path', ['/review', '/system-health', '/nutrition-review',
                                  '/meal-planner', '/receipt-paste'])
def test_page_has_claude_bar(client, path):
    r = client.get(path)
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert 'id="ko-claude-bar"' in body
    assert 'ssh://' in body
    assert '/api/claude-notes' in body
