"""End-to-end browser coverage for bulk select + edit on `/review`.

The bulk path is ~200 lines of page JS that no unit test executes: the unit
suite only asserts the markup strings ship in the response body, which a
page with a dead handler would also pass. What can actually break here only
breaks in a browser — a selection surviving a re-render, two rows merging away
under a move, undo replaying five removed rows from a toast.

These cover the manual phone script from the implementation plan, so the
scenarios stay verified after the branch merges instead of being checked once
by hand and never again.

Isolation: `live_server` serves copies of the vault and DB, so these click the
real destructive buttons without touching real inventory. The server is
session-scoped and therefore shared, so every test seeds **uniquely named**
items and asserts only about its own.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest
import requests

pytestmark = pytest.mark.e2e


def _item(name: str, **kw) -> dict:
    """A minimal well-formed inventory row, overridable per field."""
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
    """Put rows in inventory.

    `match_plan=False` because the default tags added items with the meal-plan
    recipe they were bought for, which would make these tests depend on the
    copied vault's current week.
    """
    resp = requests.post(
        server.url("/api/inventory/add"),
        json={"items": items, "match_plan": False},
        timeout=30,
    )
    assert resp.status_code in (200, 201), resp.text


def _inventory(server) -> list[dict]:
    resp = requests.get(server.url("/api/inventory"), timeout=30)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _rows_named(server, name: str) -> list[dict]:
    return [i for i in _inventory(server) if i["name"].lower() == name.lower()]


def _open_review(page, server) -> None:
    page.goto(server.url("/review"), wait_until="domcontentloaded")
    page.wait_for_selector("#list li", timeout=15_000)


def _row(page, name: str):
    """The `<li>` element(s) whose name cell is exactly `name`."""
    return page.locator("#list li").filter(
        has=page.locator(".name", has_text=name)
    )


def _select(page, name: str) -> int:
    """Tick every row named `name`. Returns how many were ticked."""
    picks = _row(page, name).locator(".pick")
    count = picks.count()
    assert count, f"no row rendered for {name!r}"
    for i in range(count):
        picks.nth(i).check()
    return count


def test_bulk_extend_advances_every_selected_row(live_server, page, page_errors):
    """Plan step 1: select three, tap +7d, all three land on the same date."""
    names = ["E2E Ext Kale", "E2E Ext Leek", "E2E Ext Lime"]
    _seed(live_server, [
        _item(n, expires=(date.today() + timedelta(days=2)).isoformat())
        for n in names
    ])

    _open_review(page, live_server)
    for n in names:
        _select(page, n)
    assert page.locator("#bulkcount").inner_text() == "3 selected"

    page.locator("#bulkbar button[data-bd='7']").click()
    page.wait_for_timeout(1500)

    # _apply_extend sets today+days, it does not add to the existing expiry.
    want = (date.today() + timedelta(days=7)).isoformat()
    for n in names:
        rows = _rows_named(live_server, n)
        assert len(rows) == 1, f"{n}: {rows}"
        assert rows[0]["expires"] == want, f"{n}: {rows[0]['expires']}"
    assert page_errors == [], page_errors


def test_bulk_move_merges_rows_that_collide_at_the_destination(
    live_server, page, page_errors
):
    """Plan step 2: two locations, one unit, one destination — one row out.

    This is the case that motivated the whole branch: `(name, unit, location)`
    is the real uniqueness key, so moving both rows to `freezer` has to sum
    them rather than leave a duplicate or silently drop one.
    """
    name = "E2E Merge Chard"
    _seed(live_server, [
        _item(name, quantity=2, unit="bunch", location="fridge"),
        _item(name, quantity=3, unit="bunch", location="counter"),
    ])
    assert len(_rows_named(live_server, name)) == 2, "seed did not make two rows"

    _open_review(page, live_server)
    assert _select(page, name) == 2

    page.locator("#bulkkebab").click()
    page.wait_for_selector("#menu.show", timeout=5_000)
    page.locator("#menu .chips").first.get_by_role(
        "button", name="freezer", exact=True
    ).click()
    page.wait_for_timeout(2000)

    rows = _rows_named(live_server, name)
    assert len(rows) == 1, f"expected one merged row, got {rows}"
    assert rows[0]["location"] == "freezer"
    assert rows[0]["quantity"] == 5, f"quantities did not sum: {rows[0]}"
    assert page_errors == [], page_errors


def test_bulk_remove_then_undo_restores_every_row(live_server, page, page_errors):
    """Plan step 3: remove five, tap Undo, all five come back intact."""
    seeds = [
        _item("E2E Undo Apple", quantity=2, unit="each", category="produce",
              location="counter"),
        _item("E2E Undo Butter", quantity=1, unit="lb", category="dairy",
              location="fridge"),
        _item("E2E Undo Cod", quantity=3, unit="fillet", category="seafood",
              location="freezer"),
        _item("E2E Undo Dill", quantity=1, unit="bunch", category="produce",
              location="fridge",
              expires=(date.today() + timedelta(days=30)).isoformat()),
        _item("E2E Undo Elbows", quantity=2, unit="box", category="pantry",
              location="pantry"),
    ]
    _seed(live_server, seeds)
    before = len(_inventory(live_server))

    _open_review(page, live_server)
    for s in seeds:
        _select(page, s["name"])
    assert page.locator("#bulkcount").inner_text() == "5 selected"

    page.locator("#bulkrm").click()
    page.wait_for_timeout(2000)
    assert len(_inventory(live_server)) == before - 5
    for s in seeds:
        assert not _rows_named(live_server, s["name"]), f"{s['name']} survived"

    page.locator("#undo").click()
    page.wait_for_timeout(2500)

    assert len(_inventory(live_server)) == before, "undo did not restore the count"
    for s in seeds:
        rows = _rows_named(live_server, s["name"])
        assert len(rows) == 1, f"{s['name']}: {rows}"
        got = rows[0]
        for field in ("quantity", "unit", "category", "location", "expires"):
            assert got[field] == s[field], (
                f"{s['name']}.{field}: {got[field]!r} != {s[field]!r}"
            )
    assert page_errors == [], page_errors


@pytest.mark.xfail(
    reason="Undo replays the removed rows through POST /api/inventory/add, and "
           "add_items auto-fills a shelf-life expiry whenever expires is None. "
           "So a deliberately-cleared expiry ('🚫 Remove expiration') comes back "
           "dated — here a year out. The bulk endpoint is not at fault: its "
           "`removed` payload carries the null faithfully. Pre-existing on main "
           "via the single-row remove path, which replays the same way; bulk "
           "only widens it to a whole selection. Fixing it needs a way to add a "
           "row with an explicitly null expiry, which is a schema/contract "
           "decision outside this branch's scope.",
    strict=True,
)
def test_undo_restores_a_deliberately_cleared_expiry(live_server, page, page_errors):
    """Removing an expiry-less item and undoing should not invent an expiry."""
    name = "E2E Null Expiry Salt"
    _seed(live_server, [_item(name, unit="box", category="pantry",
                              location="pantry")])
    resp = requests.post(
        live_server.url("/api/inventory/set-expiry"),
        json={"name": name, "location": "pantry", "expires": None},
        timeout=30,
    )
    assert resp.status_code == 200, resp.text
    assert _rows_named(live_server, name)[0]["expires"] is None

    _open_review(page, live_server)
    _select(page, name)
    page.locator("#bulkrm").click()
    page.wait_for_timeout(2000)
    assert not _rows_named(live_server, name)

    page.locator("#undo").click()
    page.wait_for_timeout(2500)

    rows = _rows_named(live_server, name)
    assert len(rows) == 1, f"undo did not restore the row: {rows}"
    assert rows[0]["expires"] is None, (
        f"undo invented an expiry: {rows[0]['expires']!r}"
    )


def test_heterogeneous_selection_offers_every_category(
    live_server, page, page_errors
):
    """Plan step 4: a mixed selection has no current value, so nothing is skipped.

    A single row's menu hides its own category and location. A selection
    spanning two categories must hide neither, or the chip you want is the one
    missing.
    """
    _seed(live_server, [
        _item("E2E Mixed Spinach", category="produce", location="fridge"),
        _item("E2E Mixed Yogurt", category="dairy", location="counter"),
    ])

    _open_review(page, live_server)
    _select(page, "E2E Mixed Spinach")
    _select(page, "E2E Mixed Yogurt")

    page.locator("#bulkkebab").click()
    page.wait_for_selector("#menu.show", timeout=5_000)

    chips = page.locator("#menu .chips")
    assert chips.first.locator("button").count() == 5, "a location chip was skipped"
    assert chips.nth(1).locator("button").count() == 10, "a category chip was skipped"
    assert page_errors == [], page_errors


def test_select_all_then_unchecking_one_row_goes_indeterminate(
    live_server, page, page_errors
):
    """Plan step 5: the header box selects everything and tracks partial state."""
    names = ["E2E All Onion", "E2E All Pear", "E2E All Quinoa"]
    _seed(live_server, [_item(n) for n in names])

    _open_review(page, live_server)
    total = page.locator("#list li").count()
    assert total >= len(names)

    selall = page.locator("#selall")
    selall.check()
    assert page.locator("#bulkcount").inner_text() == f"{total} selected"
    assert page.locator("#list li .pick:checked").count() == total
    assert selall.evaluate("el => el.indeterminate") is False

    _row(page, names[0]).locator(".pick").first.uncheck()
    assert page.locator("#bulkcount").inner_text() == f"{total - 1} selected"
    assert selall.evaluate("el => el.indeterminate") is True
    assert selall.is_checked() is False
    assert page_errors == [], page_errors
