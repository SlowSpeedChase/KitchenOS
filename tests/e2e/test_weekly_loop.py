"""End-to-end walk of the weekly loop: plan → cook → place servings → shop.

Scope note: these assert on *observable outcomes* (a ledger row exists, a vault
file was written, the UI renders the name), never on HTTP 200 alone. A 200 that
renders an empty week is the exact failure mode this file exists to catch.

Every test is self-contained. That matters more here than in the unit suite:
`POST /api/cooks` calls `_regen_weeks()`, which **rewrites the week's Markdown
from the ledger**, so one test's fixture data becomes another test's input if
they share a week. Tests that must not see each other's writes use their own
week via `unique_week()`.
"""
from __future__ import annotations

import sqlite3
from datetime import date

import pytest
import requests

pytestmark = pytest.mark.e2e

SURFACES = ["/", "/meal-planner", "/nutrition-review", "/system-health", "/review"]


def current_week() -> str:
    iso = date.today().isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def unique_week(offset: int) -> tuple[str, str]:
    """A far-future week no real plan occupies, so a test owns its own state.

    Returns `(week, date_inside_it)`. Derive the date rather than hardcoding
    one: a cook whose `date` falls outside its `week` is filed correctly but
    never rendered on that week's board, which reads as an app bug and is not.
    """
    week_no = offset + 1
    return f"2099-W{week_no:02d}", date.fromisocalendar(2099, week_no, 3).isoformat()


def _log_cook(server, *, week, recipe, produced, meal="dinner", when=None, initial=1):
    resp = requests.post(
        server.url("/api/cooks"),
        json={"recipe": recipe, "week": week, "scale": 1.0,
              "servings_produced": produced,
              "date": when or date.today().isoformat(), "meal": meal,
              "initial_placement_count": initial},
        timeout=30,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# --------------------------------------------------------------------------
# Do the screens actually work?
# --------------------------------------------------------------------------

@pytest.mark.parametrize("route", SURFACES)
def test_surface_renders_without_js_errors(live_server, page, page_errors, route):
    """Each screen loads and its JS runs clean.

    Catches what a curl check cannot: the page arrives, then a handler throws
    and the screen is quietly inert.
    """
    page.goto(live_server.url(route), wait_until="domcontentloaded")
    page.wait_for_timeout(2000)  # let deferred fetches settle and any handler throw
    assert page_errors == [], f"{route} raised: {page_errors}"


def test_meal_planner_lists_recipes(live_server, page, page_errors):
    """The planner is useless if the recipe rail is empty — assert it populated."""
    page.goto(live_server.url("/meal-planner"), wait_until="domcontentloaded")
    page.wait_for_selector("#recipe-list", timeout=15_000)
    cards = page.locator("#recipe-list li, #recipe-list .recipe-card")
    assert cards.count() > 0, "recipe rail rendered no recipes"
    assert page_errors == [], f"planner raised: {page_errors}"


# --------------------------------------------------------------------------
# The loop itself
# --------------------------------------------------------------------------

def test_logging_a_cook_records_yield_and_placements(live_server):
    """A cook yielding 4 servings — eaten once, frozen 3x — is recorded.

    This is the "how many meals does this actually cover vs. get frozen"
    question the health-goals plan depends on: if this breaks, the ledger can
    never accumulate the ground truth that later automation needs.
    """
    week, when = unique_week(1)
    cook = _log_cook(live_server, week=week, recipe="E2E Yield Cook",
                     produced=4, when=when)

    frozen = requests.post(
        live_server.url("/api/placements"),
        json={"cook_id": cook["id"], "destination": "freezer", "count": 3},
        timeout=30,
    )
    assert frozen.status_code == 201, frozen.text

    # Verify against SQLite, which serving_ledger's docstring names authoritative.
    conn = sqlite3.connect(live_server.db)
    produced = conn.execute(
        "SELECT servings_produced FROM cooks WHERE id = ?", (cook["id"],)
    ).fetchone()[0]
    placed = conn.execute(
        "SELECT destination, count FROM placements WHERE cook_id = ? ORDER BY destination",
        (cook["id"],),
    ).fetchall()
    conn.close()

    assert produced == 4
    assert dict(placed) == {"freezer": 3.0, "slot": 1.0}, (
        f"expected 1 eaten + 3 frozen, got {placed}"
    )


def test_logged_cook_appears_on_the_week_board(live_server, page, page_errors):
    """The ledger row must surface in the UI, not just the DB."""
    week, when = unique_week(2)
    _log_cook(live_server, week=week, recipe="E2E Visible Cook",
              produced=2, when=when)

    page.goto(live_server.url(f"/meal-planner?week={week}"), wait_until="domcontentloaded")
    page.wait_for_selector("#grid", timeout=15_000)
    assert page.get_by_text("E2E Visible Cook").count() > 0, (
        "cook was written to the ledger but never rendered on the week board"
    )
    assert page_errors == [], f"planner raised: {page_errors}"


def test_verdict_can_be_recorded_from_the_planner(live_server, page, page_errors):
    """One tap on the cook card records "make again" — the whole point.

    Driven through the UI rather than the API because the friction being tested
    is human: if the verdict takes more than a tap while tired, it never gets
    recorded and the ledger never learns what was liked.
    """
    week, when = unique_week(4)
    cook = _log_cook(live_server, week=week, recipe="E2E Verdict Cook",
                     produced=2, when=when)

    page.goto(live_server.url(f"/meal-planner?week={week}"), wait_until="domcontentloaded")
    page.wait_for_selector(".cook-card", timeout=15_000)
    # Open via the ⋮ button: the tap-to-open handler is gated on IS_TOUCH, so
    # on a desktop browser this is the only route into the sheet.
    page.locator(".cook-card .card-menu-btn").first.click()
    page.get_by_role("button", name="Make again 👍").click()

    # The toast is cosmetic; the ledger is the assertion.
    page.wait_for_timeout(1500)
    conn = sqlite3.connect(live_server.db)
    verdict = conn.execute(
        "SELECT make_again FROM cooks WHERE id = ?", (cook["id"],)
    ).fetchone()[0]
    conn.close()

    assert verdict == 1, "tapping 'Make again' did not reach the ledger"
    assert page_errors == [], f"planner raised: {page_errors}"


def test_cook_verdict_reaches_the_recipe_note(live_server):
    """Cooking must backfill the recipe's yield without anyone being asked.

    This is the mechanism that closes the 46%-missing-`servings` gap through
    use rather than through a chore.
    """
    week, when = unique_week(5)
    recipe = "Creamy Garlic Tofu"  # a real note in the vault copy
    _log_cook(live_server, week=week, recipe=recipe, produced=5, when=when)

    note = live_server.vault / "Recipes" / f"{recipe}.md"
    assert note.exists(), "fixture recipe missing from the vault copy"
    body = note.read_text(encoding="utf-8")
    assert "observed_servings: 5" in body, (
        f"cook did not write observed yield back to the note:\n{body[:400]}"
    )
    assert "cook_count: 1" in body


def test_shopping_list_generation_writes_a_vault_file(live_server):
    """Generating a shopping list must leave a real note behind.

    Seeds its own cook first: a shopping list derives from a plan, and an empty
    plan is the current real-world state (see test_live_state.py).
    """
    week, when = unique_week(3)
    _log_cook(live_server, week=week, recipe="Creamy Garlic Tofu",
              produced=2, when=when)

    resp = requests.post(
        live_server.url("/generate-shopping-list"),
        json={"week": week}, timeout=180, allow_redirects=False,
    )
    assert resp.status_code in (200, 302), resp.text[:500]

    written = live_server.vault / "Shopping Lists" / f"{week}.md"
    listed = sorted(p.name for p in (live_server.vault / "Shopping Lists").glob("*.md"))
    assert written.exists(), f"no shopping list written for {week}; present: {listed}"
    assert written.read_text(encoding="utf-8").strip(), "shopping list written but empty"


@pytest.mark.xfail(
    reason="Timing-sensitive, so non-strict. /api/tasks/<week> rebuilds its "
           "sidecar through Ollama on a cold week; measured at 9.7s when the "
           "model had to load and well under 1s once mistral:7b is resident. "
           "The cost is therefore Ollama's first-inference warm-up rather than "
           "a per-load penalty — but it lands on whoever opens the planner "
           "first after a reboot, and a 10s wait on a phone is a habit-killer.",
    strict=False,
)
def test_cold_planner_load_is_quick_enough_to_keep_a_habit(live_server, page):
    """A fresh week must become interactive fast enough to stay usable.

    Budget is deliberately generous — this is not a micro-benchmark, it is the
    difference between opening the planner and giving up on it.
    """
    import time
    week = current_week()
    start = time.monotonic()
    page.goto(live_server.url(f"/meal-planner?week={week}"),
              wait_until="domcontentloaded")
    page.wait_for_selector("#grid", timeout=30_000)
    page.wait_for_function("() => !document.getElementById('loading') "
                           "|| document.getElementById('loading').offsetParent === null",
                           timeout=30_000)
    elapsed = time.monotonic() - start
    assert elapsed < 4.0, f"planner took {elapsed:.1f}s to become usable"


def test_marking_a_plan_card_cooked_creates_a_ledger_row(live_server, page, page_errors):
    """The workflow actually in use: meals typed into the plan markdown.

    Those render as *legacy* cards with no cook row behind them, so before this
    the one action a person really takes — "I cooked this" — decremented
    inventory and told the ledger nothing. No yield learned, no verdict
    possible, invisible to On Track. Reported from an iPad as "I don't see the
    make again button", and the button was right to be absent: there was no
    cook to attach it to.
    """
    # Author the legacy week rather than borrowing the current one: once a real
    # week is marked cooked it converts to ledger cooks, so a test keyed on
    # "today" silently skips itself the moment the feature it covers is used.
    week = "2099-W07"
    plan = live_server.vault / "Meal Plans" / f"{week}.md"
    plan.write_text(
        "# Meal Plan - Week 7 (Feb 9 - Feb 15, 2099)\n\n"
        "## Monday (Feb 9)\n"
        "### Breakfast\n\n### Lunch\n\n### Snack\n\n"
        # A recipe no other test cooks: two tests cooking the same one shift its
        # median observed yield and break the other's assertion.
        "### Dinner\n[[Okroshka]]\n\n### Notes\n\n",
        encoding="utf-8",
    )

    page.goto(live_server.url(f"/meal-planner?week={week}"),
              wait_until="domcontentloaded")
    page.wait_for_selector("#grid", timeout=15_000)

    legacy = page.locator(".grid-card:not(.cook-card)")
    assert legacy.count() > 0, "authored plan rendered no legacy cards"

    page.once("dialog", lambda d: d.accept())          # the "subtract ingredients?" confirm
    legacy.first.locator(".cooked-btn").click(force=True)
    page.wait_for_timeout(4000)

    conn = sqlite3.connect(live_server.db)
    cooks = conn.execute("SELECT COUNT(*) FROM cooks WHERE week = ?", (week,)).fetchone()[0]
    conn.close()
    assert cooks > 0, "marking a plan card cooked left no ledger row"
