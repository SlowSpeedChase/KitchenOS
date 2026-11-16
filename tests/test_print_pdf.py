"""Print buttons open a server-built PDF, so printing works the same on iPad,
iPhone and Mac.

iOS Safari's `window.print()` prints only the visible tab, and the old iOS
branch shared the page *URL*, not a document, so there was nothing to print
from a phone. The PDF is rendered from the same print page by headless
Chromium, so it shares one stylesheet with the on-screen preview.
"""
from __future__ import annotations

import pytest

import api_server
from lib import print_pdf


@pytest.fixture
def client():
    api_server.app.config['TESTING'] = True
    with api_server.app.test_client() as c:
        yield c


@pytest.fixture
def captured(monkeypatch):
    calls = []

    def fake_render(url, **kwargs):
        calls.append(url)
        return b"%PDF-1.7 fake"

    monkeypatch.setattr(print_pdf, "render_pdf", fake_render)
    return calls


def _week_plan(tmp_vault):
    (tmp_vault / "Recipes").mkdir(parents=True, exist_ok=True)
    plans = tmp_vault / "Meal Plans"
    plans.mkdir(parents=True, exist_ok=True)
    (plans / "2026-W31.md").write_text("## Monday (Jul 27)\n\n### dinner\n\n")


def test_week_pdf_renders_the_print_page_over_loopback(client, tmp_vault, captured):
    _week_plan(tmp_vault)
    resp = client.get("/print/week.pdf?week=2026-W31&recipes=1")
    assert resp.status_code == 200
    assert resp.mimetype == "application/pdf"
    assert resp.data.startswith(b"%PDF")
    # inline, so iOS opens its viewer (Share → Print) instead of downloading
    disp = resp.headers["Content-Disposition"]
    assert disp.startswith("inline")
    assert "Jul 27" in disp  # human week range, never the bare week id
    [url] = captured
    assert url.startswith("http://127.0.0.1:")
    assert "/print/week?" in url and "week=2026-W31" in url and "recipes=1" in url


def test_week_pdf_drops_unknown_params(client, tmp_vault, captured):
    """Only the page's own options pass through to the loopback fetch."""
    _week_plan(tmp_vault)
    client.get("/print/week.pdf?week=2026-W31&evil=http://x")
    assert "evil" not in captured[0]


def test_week_pdf_invalid_week_400_without_rendering(client, captured):
    assert client.get("/print/week.pdf?week=nope").status_code == 400
    assert captured == []


def test_week_pdf_missing_plan_404_without_rendering(client, tmp_vault, captured):
    (tmp_vault / "Recipes").mkdir(parents=True, exist_ok=True)
    assert client.get("/print/week.pdf?week=2099-W01").status_code == 404
    assert captured == []


def test_recipe_card_pdf(client, tmp_vault, captured):
    recipes = tmp_vault / "Recipes"
    recipes.mkdir()
    (recipes / "Beef Bowl.md").write_text('---\ntitle: "Beef Bowl"\n---\n# Beef Bowl\n')
    resp = client.get("/recipe-card/Beef%20Bowl.pdf")
    assert resp.status_code == 200 and resp.mimetype == "application/pdf"
    assert "/recipe-card/Beef%20Bowl" in captured[0]
    assert "Beef Bowl" in resp.headers["Content-Disposition"]


def test_recipe_card_pdf_missing_recipe_404(client, tmp_vault, captured):
    (tmp_vault / "Recipes").mkdir()
    assert client.get("/recipe-card/Nope.pdf").status_code == 404
    assert captured == []


def test_cooking_packet_pdf_requires_saved_packet(client, monkeypatch, captured):
    from lib import cooking_packet_store as store
    monkeypatch.setattr(store, "get_packet", lambda week: None)
    assert client.get("/print/cooking-packet.pdf?week=2026-W31").status_code == 404
    assert captured == []
    monkeypatch.setattr(store, "get_packet", lambda week: {"week": week})
    resp = client.get("/print/cooking-packet.pdf?week=2026-W31")
    assert resp.status_code == 200
    assert "/print/cooking-packet?week=2026-W31" in captured[0]


def test_render_failure_is_a_friendly_page_not_a_500(client, tmp_vault, monkeypatch):
    _week_plan(tmp_vault)

    def boom(url, **kwargs):
        raise print_pdf.PdfError("chromium missing")

    monkeypatch.setattr(print_pdf, "render_pdf", boom)
    resp = client.get("/print/week.pdf?week=2026-W31")
    assert resp.status_code == 503
    assert "text/html" in resp.content_type
    assert "PDF" in resp.get_data(as_text=True)


@pytest.mark.parametrize("template", [
    "print_week.html", "print_cooking_packet.html", "recipe_card.html"])
def test_print_buttons_open_the_pdf(template):
    from pathlib import Path
    html = (Path(api_server.__file__).parent / "templates" / template).read_text()
    assert "data-print-action" in html
    js = (Path(api_server.__file__).parent / "static" / "print-action.js").read_text()
    assert ".pdf" in js
    # the old iOS branch shared the page URL — nothing printable on a phone
    assert "navigator.share" not in js


def test_render_pdf_really_produces_a_pdf(tmp_path):
    """End-to-end through real headless Chromium (skipped where absent)."""
    pytest.importorskip("playwright.sync_api")
    page = tmp_path / "p.html"
    page.write_text("<html><body><h1>Hello print</h1></body></html>")
    try:
        data = print_pdf.render_pdf(page.as_uri())
    except print_pdf.PdfError as exc:
        pytest.skip(f"no headless chromium here: {exc}")
    assert data.startswith(b"%PDF")
