"""Tests for global page chrome."""
import pytest
from api_server import app, _inject_after_body


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

# --- route level: simple pages do not expose the disabled bridge ---

PAGES = ['/', '/review', '/system-health', '/nutrition-review',
         '/meal-planner', '/receipt-paste']


@pytest.mark.parametrize('path', PAGES)
def test_page_has_no_claude_bridge(client, path):
    response = client.get(path)
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'id="ko-claude-bar"' not in body
    assert '/api/claude-send' not in body
    assert '/api/claude-notes' not in body


@pytest.mark.parametrize("method,path", [
    ("get", "/api/claude-notes"),
    ("post", "/api/claude-notes"),
    ("post", "/api/claude-send"),
])
def test_claude_bridge_routes_are_absent(client, method, path):
    response = getattr(client, method)(path, json={"notes": "x", "text": "x"})
    assert response.status_code == 404


def test_the_stale_banner_never_escapes_the_page():
    """`escape()` returns Markup, and `str + Markup` escapes the LEFT operand.

    The first cut concatenated raw `escape(...)` into the banner, so the banner
    escaped itself and then, via `_inject_after_body`, the whole document — the
    planner served 260KB of visible `&lt;!DOCTYPE html&gt;` and no grid rendered. A
    page that cannot render is a worse outcome than the staleness this banner
    reports, so the type is pinned here.
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
                              banner)
    assert "&lt;!DOCTYPE" not in page and "<body>" in page
    assert "GRID" in page
