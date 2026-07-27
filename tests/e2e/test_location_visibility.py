"""End-to-end browser coverage for storage-location visibility on `/review`.

The unit suite only asserts the markup strings ship in the response body, which
a page with a dead handler would also pass. What can actually break here only
breaks in a browser: a group header counting rows it doesn't label, a moved row
staying pinned in its old block, a "?" rendering on a confirmed row, a
last-used stamp that reads "NaNd ago".

Isolation: `live_server` serves copies of the vault and DB. The server is
session-scoped and therefore shared, so every test seeds uniquely named items
and asserts only about its own.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
import requests

pytestmark = pytest.mark.e2e


def _item(name: str, **kw) -> dict:
    return {
        "name": name,
        "quantity": 1,
        "unit": "each",
        "category": "produce",
        "location": "fridge",
        "purchased": date.today().isoformat(),
        "expires": (date.today() + timedelta(days=5)).isoformat(),
        **kw,
    }


def _seed(server, items: list[dict]) -> None:
    resp = requests.post(
        server.url("/api/inventory/add"),
        json={"items": items, "match_plan": False},
        timeout=30,
    )
    assert resp.status_code in (200, 201), resp.text


def _open_review(page, server, sort: str = "expiry") -> None:
    page.goto(server.url("/review"), wait_until="domcontentloaded")
    page.wait_for_selector("#list li", timeout=15_000)
    if sort != "expiry":
        page.select_option("#sortby", sort)
        page.wait_for_timeout(400)


def _row(page, name: str):
    return page.locator("#list li").filter(
        has=page.locator(".name", has_text=name)
    ).first


def test_an_explicit_location_is_not_marked_unsure(live_server, page, page_errors):
    """A location supplied in the request is the caller's choice, so `manual` —
    it must render bare, with no "?"."""
    _seed(live_server, [_item("E2E Loc Explicit", location="counter")])
    _open_review(page, live_server)

    sub = _row(page, "E2E Loc Explicit").locator(".sub").inner_text()
    assert "counter" in sub
    assert "counter?" not in sub, "a stated location was presented as a guess"
    assert page_errors == []


def test_an_unresolvable_item_is_marked_unsure(live_server, page, page_errors):
    """Nothing in by_item or a real by_category matches, so the location is a
    shrug and says so."""
    _seed(live_server, [
        _item("E2E Loc Mystery Zzz", category="other", location=None),
    ])
    _open_review(page, live_server)

    sub = _row(page, "E2E Loc Mystery Zzz").locator(".sub").inner_text()
    assert "?" in sub, f"expected an unsure marker, got {sub!r}"
    assert page_errors == []


def test_location_sort_blocks_rows_under_headers_that_count_them(
    live_server, page, page_errors
):
    """The header's count must match the rows it actually labels."""
    _seed(live_server, [
        _item("E2E Grp Fridge A", location="fridge"),
        _item("E2E Grp Freezer B", location="freezer"),
    ])
    _open_review(page, live_server, sort="location")

    headers = page.locator("#list li.group")
    assert headers.count() >= 2, "no location group headers rendered"

    # Lowercased: the header CSS sets text-transform: capitalize, and
    # inner_text() returns rendered text, so this reads "Fridge" in the browser.
    texts = [headers.nth(i).inner_text().lower() for i in range(headers.count())]
    assert any("fridge" in t for t in texts)
    assert any("freezer" in t for t in texts)

    counted = 0
    for t in texts:
        # "❄️ fridge — 12 · 3 unsure"  ->  12
        after_dash = t.split("—", 1)[1] if "—" in t else "0"
        counted += int(after_dash.split("·")[0].strip())
    non_header_rows = page.locator("#list li:not(.group)").count()
    assert counted == non_header_rows, (
        f"headers claim {counted} rows, list shows {non_header_rows}"
    )
    assert page_errors == []


def test_a_moved_row_lands_in_its_new_block(live_server, page, page_errors):
    """Location is part of the row key, so a move changes the row's identity.
    Patching in place left the rows Map under the stale key and the row pinned
    in its old block.

    The destination is chosen from what the menu actually offers rather than
    hardcoded: a single row's menu hides the row's *own* location, and the
    live_server is session-scoped, so an earlier test's teaching can change
    where this row lands. Any destination exercises the re-home path.
    """
    name = "E2E Move Block Ccc"
    _seed(live_server, [_item(name, location="fridge")])
    _open_review(page, live_server, sort="location")

    row = _row(page, name)
    row.scroll_into_view_if_needed()
    before = row.locator(".sub").inner_text().lower()

    row.locator(".kebab").click()
    page.wait_for_selector("#menu.show", timeout=5_000)
    chips = page.locator("#menu .chips").first.locator("button")
    # Exclude the "✓ <loc>" confirm chip, which is offered on an unsure row and
    # is not a destination — it re-asserts the row's current shelf.
    offered = [t for t in (chips.nth(i).inner_text().strip().lower()
                           for i in range(chips.count()))
               if "✓" not in t]
    assert offered, "the row menu offered no location chips"
    dest = offered[0]
    assert dest not in before, (
        f"menu offered the row's current location; offered={offered} sub={before!r}"
    )
    page.locator("#menu .chips").first.get_by_role(
        "button", name=dest, exact=True
    ).click()
    page.wait_for_timeout(2000)

    sub = _row(page, name).locator(".sub").inner_text().lower()
    assert dest in sub, f"row did not re-home to {dest}; subline reads {sub!r}"
    # And a move is a confirmation, so the guess marker is gone.
    assert f"{dest}?" not in sub
    assert page_errors == []


def test_a_used_row_shows_when_it_was_last_used(live_server, page, page_errors):
    """consume-on-cook writes last_used; this is the only view that reads it."""
    name = "E2E Used Stamp Ddd"
    _seed(live_server, [_item(name)])
    # Stamp it directly — driving a real cook would couple this to the vault's
    # recipe corpus, and what's under test is the rendering.
    resp = requests.post(
        live_server.url("/api/inventory/bulk"),
        json={"action": "extend",
              "refs": [{"name": name, "unit": "each", "location": "fridge"}],
              "days": 1},
        timeout=30,
    )
    assert resp.status_code == 200, resp.text

    stamped = datetime.now().replace(microsecond=0).isoformat()
    page.goto(live_server.url("/review"), wait_until="domcontentloaded")
    page.wait_for_selector("#list li", timeout=15_000)
    # Render the label directly against a known stamp: the seeded row has never
    # been cooked, so there is no real last_used to assert against.
    text = page.evaluate(
        "ts => usedLabel({last_used: ts, use_count: 3})", stamped
    )
    assert "used today" in text
    assert 'title="used 3 times"' in text
    assert "NaN" not in text
    assert page_errors == []


def test_a_never_used_row_shows_no_stamp(live_server, page, page_errors):
    page.goto(live_server.url("/review"), wait_until="domcontentloaded")
    page.wait_for_selector("#list li", timeout=15_000)
    assert page.evaluate("() => usedLabel({last_used: null, use_count: 0})") == ""
    assert page.evaluate("() => usedLabel({})") == ""
    assert page_errors == []


def test_an_unsure_row_can_confirm_its_current_shelf(live_server, page, page_errors):
    """Without this there is no way to clear the "?" on a row that is already in
    the right place: the menu skips the row's own location, so the only escape is
    moving it away and back — which teaches a wrong override on the first tap.
    """
    name = "E2E Confirm Shelf Eee"
    _seed(live_server, [_item(name, category="other", location=None)])
    _open_review(page, live_server)

    row = _row(page, name)
    row.scroll_into_view_if_needed()
    assert "?" in row.locator(".sub").inner_text(), "row was not unsure to begin with"

    row.locator(".kebab").click()
    page.wait_for_selector("#menu.show", timeout=5_000)
    # The current shelf is offered, marked as a confirmation rather than a move.
    confirm = page.locator("#menu .chips").first.locator("button", has_text="✓")
    assert confirm.count() == 1, "no confirm-current-shelf chip offered"
    confirm.first.click()
    page.wait_for_timeout(2000)

    sub = _row(page, name).locator(".sub").inner_text()
    assert "?" not in sub, f"still marked unsure after confirming: {sub!r}"
    assert "pantry" in sub.lower()
    assert page_errors == []


def test_a_confirmed_row_offers_no_confirm_chip(live_server, page, page_errors):
    """Only an unsure row needs the affordance; a settled row's own location
    stays skipped so the menu doesn't fill with no-ops."""
    name = "E2E Confirm Settled Fff"
    _seed(live_server, [_item(name, location="counter")])  # explicit -> manual
    _open_review(page, live_server)

    row = _row(page, name)
    row.scroll_into_view_if_needed()
    assert "?" not in row.locator(".sub").inner_text()
    row.locator(".kebab").click()
    page.wait_for_selector("#menu.show", timeout=5_000)
    chips = page.locator("#menu .chips").first
    assert chips.locator("button", has_text="✓").count() == 0
    labels = [chips.locator("button").nth(i).inner_text().strip().lower()
              for i in range(chips.locator("button").count())]
    assert "counter" not in labels, "a settled row offered its own location"
    assert page_errors == []
