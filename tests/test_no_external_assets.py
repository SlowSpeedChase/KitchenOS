"""No template may depend on the public internet to render.

KitchenOS is local-first and its pages are opened over a private tailnet from
phones that may have no usable route off-net. `templates/meal_planner.html` once
loaded Sortable from jsDelivr, and because `setupEventListeners()` calls
`Sortable.create()` before `init()` reaches its first fetch, a failed CDN load
killed the whole page before it rendered or requested anything — the server saw
`GET /meal-planner 200` and then nothing.

Vendor assets into `static/` instead (see `static/README.md`). These tests are the
guard that stops a CDN reference coming back.
"""

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
TEMPLATES = REPO / "templates"
STATIC = REPO / "static"

# src="..." / href="..." pointing at an absolute http(s) URL.
_EXTERNAL_REF = re.compile(r'(?:src|href)\s*=\s*"(https?://[^"]+)"', re.IGNORECASE)

# Not every absolute URL is a render dependency: a human-facing hyperlink is fine.
# Only <script src> and <link rel=stylesheet href> block or break rendering.
_BLOCKING_REF = re.compile(
    r'<script[^>]*\bsrc\s*=\s*"(https?://[^"]+)"'
    r'|<link[^>]*\bhref\s*=\s*"(https?://[^"]+)"[^>]*>',
    re.IGNORECASE | re.DOTALL,
)


def _templates():
    return sorted(TEMPLATES.glob("*.html"))


def test_there_are_templates_to_check():
    """Guard the guard: a glob that matches nothing would pass everything below."""
    assert _templates(), f"no templates found under {TEMPLATES}"


@pytest.mark.parametrize("template", _templates(), ids=lambda p: p.name)
def test_template_has_no_external_render_dependency(template):
    html = template.read_text(encoding="utf-8")
    offenders = [
        (m.group(1) or m.group(2))
        for m in _BLOCKING_REF.finditer(html)
    ]
    assert not offenders, (
        f"{template.name} loads a render-blocking asset from the public internet: "
        f"{offenders}. Vendor it into static/ and reference it as /static/<name> — "
        f"see static/README.md. A page that needs a CDN fails on the tailnet."
    )


def test_meal_planner_loads_sortable_locally():
    """The specific regression: this page must reference the vendored copy."""
    html = (TEMPLATES / "meal_planner.html").read_text(encoding="utf-8")
    assert "/static/sortable.min.js" in html
    assert "cdn.jsdelivr.net" not in html


def test_vendored_sortable_exists_and_is_the_real_library():
    """A missing or truncated vendored file breaks the page just as hard as a CDN."""
    js = STATIC / "sortable.min.js"
    assert js.exists(), "static/sortable.min.js is missing — the page cannot render"
    src = js.read_text(encoding="utf-8")
    # UMD wrapper's global assignment; the page relies on the `Sortable` global.
    assert "Sortable=e()" in src, "vendored file is not the Sortable UMD bundle"
    assert len(src) > 20_000, f"vendored file looks truncated ({len(src)} chars)"
