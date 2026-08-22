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

def test_inject_ignores_body_spelled_out_inside_the_head():
    """A template that *writes about* <body> must not be spliced at that word.

    meal_planner.html documents the chrome bar in a CSS comment naming the
    literal tag; a plain find('<body') matched the comment and dropped the bar
    into the stylesheet, where the browser discards it — leaving a page that
    contains the markup and shows no bar.
    """
    html = ('<html><head><style>/* sticky at the top of <body>, so .app '
            'shifts down */</style></head><body class="x">HI</body></html>')
    out = _inject_after_body(html, 'SNIP')
    assert '<body class="x">SNIP' in out
    assert out.index('SNIP') > out.index('</style>')

def test_bar_html_has_ssh_and_endpoint():
    bar = _claude_bar_html()
    assert 'id="ko-claude-bar"' in bar
    assert 'ssh://' in bar
    assert '/api/claude-notes' in bar

def test_bar_html_uses_env_target(monkeypatch):
    monkeypatch.setenv('KITCHENOS_SSH_TARGET', 'tester@example.ts.net')
    assert 'ssh://tester@example.ts.net' in _claude_bar_html()

def test_bar_html_has_home_link():
    bar = _claude_bar_html()
    assert 'id="ko-home-link"' in bar
    assert 'href="/"' in bar


# --- route level: every simple page carries the bar ---

# Every HTML page served through _serve_page_with_claude_bar.
PAGES = ['/', '/review', '/system-health', '/nutrition-review',
         '/meal-planner', '/receipt-paste']


@pytest.mark.parametrize('path', PAGES)
def test_page_has_claude_bar(client, path):
    r = client.get(path)
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert 'id="ko-claude-bar"' in body
    assert 'ssh://' in body
    assert '/api/claude-notes' in body


@pytest.mark.parametrize('path', PAGES)
def test_every_page_links_home(client, path):
    body = client.get(path).get_data(as_text=True)
    assert 'id="ko-home-link"' in body


@pytest.mark.parametrize('path', PAGES)
def test_bar_is_not_buried_in_the_stylesheet(client, path):
    """Presence of the markup is not the same as a rendered bar.

    The string assertions above passed for months while /meal-planner showed no
    bar at all, because the snippet had been spliced inside <style>. Assert the
    injection point is real markup: no <style> is still open where it landed.
    """
    body = client.get(path).get_data(as_text=True)
    bar = body.index('id="ko-claude-bar"')
    assert body.rfind('<style', 0, bar) <= body.rfind('</style>', 0, bar), \
        f'{path}: bar was injected inside an open <style> block'


def test_the_stale_banner_never_escapes_the_page():
    """`escape()` returns Markup, and `str + Markup` escapes the LEFT operand.

    The first cut concatenated raw `escape(...)` into the banner, so the banner
    escaped itself, then the Claude bar, then via `_inject_after_body` the whole
    document — the planner served 260KB of visible `&lt;!DOCTYPE html&gt;` and no
    grid rendered. A page that cannot render is a worse outcome than the
    staleness this banner reports, so the type is pinned here.
    """
    import api_server

    api_server._stale_cache.update(checked_at=0.0, html="")
    monkey = {"status": "failing", "detail": '<script>"x" & y</script>',
              "consequence": "c", "fix": "f", "id": "server_freshness",
              "label": "l"}
    from lib import health_assertions
    real = health_assertions.check_server_freshness
    health_assertions.check_server_freshness = lambda *a, **k: monkey
    try:
        banner = api_server._stale_banner_html()
    finally:
        health_assertions.check_server_freshness = real
        api_server._stale_cache.update(checked_at=0.0, html="")

    assert type(banner) is str, f"banner is {type(banner)}, which escapes on concat"
    assert banner.startswith("<div"), "banner escaped its own markup"
    assert "<script>" not in banner, "the detail text was not escaped"
    page = _inject_after_body("<html><head></head><body>GRID</body></html>",
                              banner + _claude_bar_html())
    assert "&lt;!DOCTYPE" not in page and "<body>" in page
    assert "GRID" in page
