"""Tests for global page chrome."""
from pathlib import Path

import pytest
from api_server import app, _html_page, _inject_after_body, _serve_page


REPO = Path(__file__).resolve().parents[1]
TEMPLATES = sorted(path.name for path in (REPO / "templates").glob("*.html"))


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


@pytest.mark.parametrize("template", TEMPLATES)
def test_every_template_page_has_one_home_link_except_home_itself(template):
    """A new template cannot ship without a route back to KitchenOS Home."""
    html = _serve_page(template)
    expected = 0 if template == "home.html" else 1
    assert html.count('href="/"') == expected


def test_inline_pages_have_accessible_home_navigation():
    """Success, error, and form pages built in Python inherit Home navigation."""
    html = _html_page("Result", "<main>Done</main>")
    assert '<nav class="ko-home-nav" aria-label="Primary">' in html
    assert '<a class="ko-home-link" href="/">' in html
    assert "KitchenOS Home" in html

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


from api_server import COMMAND_BAR_SKIP

BAR = '<script src="/static/command-bar.js" defer></script>'


@pytest.mark.parametrize("template", TEMPLATES)
def test_every_page_gets_the_command_bar_except_print_and_handoff(template):
    html = _serve_page(template)
    expected = 0 if template in COMMAND_BAR_SKIP else 1
    assert html.count(BAR) == expected


def test_skip_list_names_real_templates():
    assert COMMAND_BAR_SKIP <= set(TEMPLATES)
    assert {"print_week.html", "print_cooking_packet.html", "recipe_card.html",
            "browser_open.html"} == COMMAND_BAR_SKIP


def test_read_only_browser_session_gets_no_bar(monkeypatch):
    import api_server
    monkeypatch.setattr(api_server, "_browser_view_config",
                        lambda: {"state": "active", "readOnly": True, "expires_at": None})
    with app.test_request_context("/"):
        assert BAR not in _serve_page("home.html")


#: Templates that deliberately send {screen: "other"}: the engine has no screen
#: for them, so stating none is the decision. A new template must either set
#: window.kitchenosContext or be listed here with a reason.
CONTEXT_OTHER = {
    "meal_calendar.html": "read-only agenda list; commands here act on no particular week",
    "nutrition_review.html": "fixes food matches; no command acts on it",
    "plan_week.html": "the weekly front door; planner commands run from the planner",
    "prep.html": "today's tasks; no command acts on prep steps",
    "receipt_paste.html": "a paste form",
    "recent.html": "a list of new recipes",
    "review.html": "recipe review queue",
    "system_health.html": "operator page",
    "cooking_packet.html": "a printable week view",
}


@pytest.mark.parametrize("template", sorted(set(TEMPLATES) - COMMAND_BAR_SKIP))
def test_every_bar_page_states_its_context_or_says_why_not(template):
    source = (REPO / "templates" / template).read_text()
    assert ("window.kitchenosContext" in source) != (template in CONTEXT_OTHER), (
        f"{template}: set window.kitchenosContext in the template, or add it to "
        "CONTEXT_OTHER with a reason — not both."
    )


def test_shopping_note_states_its_week(monkeypatch):
    import api_server
    with app.test_request_context("/current/shopping-list"):
        html = api_server._render_note_page("Shopping Lists", "2026-W47", "Shopping list",
                                            "<p>none</p>", screen="shopping")
    assert '{"screen": "shopping", "week": "2026-W47"}' in html
