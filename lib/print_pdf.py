"""Render a KitchenOS print page to a PDF with headless Chromium.

Why a server-side PDF: iOS Safari's ``window.print()`` is unreliable and the
old iOS branch of ``static/print-action.js`` shared the page *URL* — nothing a
phone could print. A PDF opens in every device's viewer, which has Print in its
share sheet. Rendering the existing print page (rather than building a second
layout in a PDF library) keeps one stylesheet as the authority for both the
on-screen preview and the paper.

The page is always fetched over loopback by the caller, so the URL here is
trusted; this module never sees request input directly.
"""
from __future__ import annotations

import threading

# Each render launches a Chromium (~150 MB). Two at once covers "iPad and
# phone tapped Print together" without letting a burst exhaust the Mac mini.
_SLOTS = threading.BoundedSemaphore(2)
NAV_TIMEOUT_S = 90  # a recipe card may spend its whole LLM web budget first
_PAPER_CSS = "html, body { background: #fff !important; }"


class PdfError(RuntimeError):
    """Chromium is missing, crashed, or timed out."""


class PdfSourceError(PdfError):
    """The print page itself answered with an error status."""

    def __init__(self, status: int):
        super().__init__(f"print page returned HTTP {status}")
        self.status = status


def render_pdf(url: str, *, timeout_s: float = NAV_TIMEOUT_S) -> bytes:
    try:
        from playwright.sync_api import Error as PlaywrightError, sync_playwright
    except ImportError as exc:  # pragma: no cover - dependency missing
        raise PdfError("playwright is not installed") from exc

    if not _SLOTS.acquire(timeout=timeout_s):
        raise PdfError("PDF renderer busy")
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                # Light scheme: paper is white even if the Mac is in dark mode.
                page = browser.new_page(color_scheme="light")
                page.emulate_media(media="print")
                response = page.goto(url, wait_until="networkidle",
                                     timeout=timeout_s * 1000)
                if response is not None and not response.ok:
                    raise PdfSourceError(response.status)
                # Paper is white. The page's cream --bg is a screen theme; a
                # browser's own Print drops it by default, so match that while
                # keeping print_background for table tints and warning boxes.
                page.add_style_tag(content=_PAPER_CSS)
                return page.pdf(format="Letter", print_background=True,
                                prefer_css_page_size=True)
            finally:
                browser.close()
    except PdfError:
        raise
    except PlaywrightError as exc:
        raise PdfError(str(exc).splitlines()[0]) from exc
    finally:
        _SLOTS.release()
