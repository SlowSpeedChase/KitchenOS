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

from tests.e2e._weeks import unique_week  # noqa: F401  (re-exported: grep `unique_week(`)

pytestmark = pytest.mark.e2e

SURFACES = ["/", "/meal-planner", "/nutrition-review", "/system-health", "/review"]


def current_week() -> str:
    iso = date.today().isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


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
    # Wait for a *card*, not the rail. `#recipe-list` ships in the static HTML, so
    # waiting on it returns instantly and the count below then races the fetch that
    # fills it — the test passed or failed on how warm the caches were. A timeout
    # here still means "the rail never populated", which is the bug being guarded.
    cards = page.locator("#recipe-list li, #recipe-list .recipe-card")
    cards.first.wait_for(timeout=15_000)
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


def _mark_cooked(server, cook_id):
    """The 🍳 tap: the NULL -> set `cooked_at` transition on a ledger row."""
    resp = requests.patch(
        server.url(f"/api/cooks/{cook_id}"),
        json={"cooked_at": f"{date.today().isoformat()}T18:30:00"},
        timeout=30,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_cook_verdict_reaches_the_recipe_note(live_server):
    """Cooking must backfill the recipe's yield without anyone being asked.

    This is the mechanism that closes the 46%-missing-`servings` gap through
    use rather than through a chore.

    A `cooks` row is *intent* until `cooked_at` is set (or a verdict lands):
    dropping a recipe on the board is planning, and a batch that was never made
    has no yield to observe — see `cook_history._is_cooked`. So the test has to
    actually cook, not just plan; before that correction, planning alone wrote
    `observed_servings`, which is the bug it fixed. `test_shopping_list_…` also
    plans this recipe, but never cooks it, so it cannot move this median.
    """
    week, when = unique_week(5)
    recipe = "Creamy Garlic Tofu"  # a real note in the vault copy
    cook = _log_cook(live_server, week=week, recipe=recipe, produced=5, when=when)
    _mark_cooked(live_server, cook["id"])

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
    # `.hidden` is what hideLoading() sets. Not `offsetParent === null`: the
    # overlay is position:fixed, for which offsetParent is *always* null, so
    # that wait returned before the page was usable and timed nothing.
    page.wait_for_selector("#loading.hidden", state="attached", timeout=30_000)
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
    #
    # Claimed through unique_week() even though the body hardcodes the dates, so
    # that `grep unique_week(` lists every week this file owns. As a bare string
    # it was invisible to that check and a later test picked offset 6 — the same
    # week — which flipped this one into board mode and deleted the legacy cards
    # it asserts on. Offset 6 is 2099-W07, so the Feb 9 dates below still hold.
    week, _ = unique_week(6)
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

    # Wait for a *card*, not for #grid: the grid ships in the static HTML and the
    # cards land only after /api/meal-plan answers, so counting right after #grid
    # appears reads 0 on a busy machine. A timeout here still means "no legacy
    # card rendered", which is the thing being guarded.
    legacy = page.locator(".grid-card:not(.cook-card)")
    legacy.first.wait_for(timeout=15_000)
    assert legacy.count() > 0, "authored plan rendered no legacy cards"

    page.once("dialog", lambda d: d.accept())          # the "subtract ingredients?" confirm
    # A plain click, never `force=True`: on a cold server the full-screen
    # #loading overlay is still up when #grid appears, and a forced click lands
    # on the overlay — no confirm, no request, no row — while a warm server
    # (any earlier test in the session) clears it in time. That is exactly the
    # order-dependence this test used to have. Playwright's actionability wait
    # is the same wait a person makes: the button has to be the thing under
    # the pointer.
    legacy.first.locator(".cooked-btn").click()
    page.wait_for_timeout(4000)

    conn = sqlite3.connect(live_server.db)
    cooks = conn.execute("SELECT COUNT(*) FROM cooks WHERE week = ?", (week,)).fetchone()[0]
    conn.close()
    assert cooks > 0, "marking a plan card cooked left no ledger row"


def test_a_cook_can_be_moved_to_another_slot_by_tapping(live_server, page, page_errors):
    """The single-pointer alternative to the card drag (WCAG 2.2 SC 2.5.7).

    Driven through the UI because the ledger call is the easy half; the part
    that breaks is the armed state routing a cook card into a *move* rather
    than into createCook(), which would schedule the same meal twice.
    """
    from datetime import date as _date
    week, when = unique_week(8)
    target = _date.fromisocalendar(2099, 9, 5).isoformat()   # Friday, same week
    cook = _log_cook(live_server, week=week, recipe="E2E Move Cook",
                     produced=2, when=when, meal="dinner")

    page.goto(live_server.url(f"/meal-planner?week={week}"),
              wait_until="domcontentloaded")
    page.wait_for_selector(".cook-card", timeout=15_000)

    # ⋮ is the only route into the sheet on a desktop browser (tap-to-open is
    # gated on IS_TOUCH).
    page.locator(".cook-card .card-menu-btn").first.click()
    page.get_by_role("button", name="Move to another slot").click()

    page.wait_for_selector("#assign-bar:not([hidden])")
    assert "Moving" in page.inner_text("#assign-bar"), \
        "a move announced as 'Placing' reads as duplicating the meal"

    page.locator('.grid-cell[data-day="Friday"][data-meal="lunch"]').click()
    page.wait_for_timeout(2000)

    conn = sqlite3.connect(live_server.db)
    row = conn.execute("SELECT date, meal FROM cooks WHERE id = ?",
                       (cook["id"],)).fetchone()
    placements = conn.execute(
        "SELECT date, meal, count FROM placements WHERE cook_id = ?"
        " AND destination = 'slot'", (cook["id"],)).fetchall()
    conn.close()

    assert row == (target, "lunch"), "the tap route did not re-anchor the cook"
    assert placements == [(target, "lunch", 1.0)], \
        "the home serving must travel with the card"
    assert page_errors == [], f"planner raised: {page_errors}"


def test_a_cook_can_be_dragged_to_another_slot(live_server, page, page_errors):
    """The drag itself. SortableJS runs with forceFallback, so it listens to raw
    pointer events and Playwright's drag_to() is a no-op here — the gesture has
    to be synthesised past the 100ms delay and the 5px touchStartThreshold.
    """
    from datetime import date as _date
    week, when = unique_week(7)
    target = _date.fromisocalendar(2099, 8, 5).isoformat()   # Friday, same week
    cook = _log_cook(live_server, week=week, recipe="E2E Drag Cook",
                     produced=2, when=when, meal="dinner")

    page.goto(live_server.url(f"/meal-planner?week={week}"),
              wait_until="domcontentloaded")
    page.wait_for_selector(".cook-card", timeout=15_000)

    card = page.locator(".cook-card").first.bounding_box()
    dest = page.locator(
        '.grid-cell[data-day="Friday"][data-meal="lunch"]').bounding_box()

    # Grab the card's lower edge, clear of the name link and the button row.
    page.mouse.move(card["x"] + card["width"] / 2, card["y"] + card["height"] - 4)
    page.mouse.down()
    page.wait_for_timeout(300)          # clear the 100ms hold-to-drag delay
    for i in range(1, 11):              # stepped, so Sortable hit-tests en route
        page.mouse.move(
            card["x"] + (dest["x"] + dest["width"] / 2 - card["x"]) * i / 10,
            card["y"] + (dest["y"] + dest["height"] / 2 - card["y"]) * i / 10,
        )
        page.wait_for_timeout(30)
    page.mouse.up()
    page.wait_for_timeout(2500)

    conn = sqlite3.connect(live_server.db)
    row = conn.execute("SELECT date, meal FROM cooks WHERE id = ?",
                       (cook["id"],)).fetchone()
    conn.close()

    assert row == (target, "lunch"), "the drag did not reach the ledger"

    # The CLAUDE.md invariant, pinned: a card drag must never fall through to
    # debounceSave()/saveMealPlan(), which PUTs scale-less legacy meal-plan data
    # over ledger-authored Markdown. Scoped to this test's own week, since the
    # log is shared across the session and legacy weeks legitimately PUT.
    assert f"PUT /api/meal-plan/{week}" not in live_server.log.read_text(errors="replace"), \
        "the drag reached the legacy save path"

    assert page_errors == [], f"planner raised: {page_errors}"


# --------------------------------------------------------------------------
# Composite plates
# --------------------------------------------------------------------------

def _place_plate(server, *, meal_name, week, when, meal="dinner"):
    resp = requests.post(
        server.url("/api/bundles"),
        json={"meal_name": meal_name, "week": week, "date": when,
              "meal": meal, "scale": 1.0},
        timeout=30,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _plate_kcal(server, meal_name) -> int:
    resp = requests.get(server.url(f"/api/meals/{meal_name}"), timeout=30)
    assert resp.status_code == 200, resp.text
    return round(resp.json()["nutrition"]["calories"])


PLATE = "Osso Buco Plate"


def test_a_plate_lands_in_the_day_totals_row(live_server, page, page_errors):
    """A composite plate contributes its macros to the day-totals row.

    The first assertion in this suite on `.totals-cell` *content*, and the whole
    reason the branch exists. The board could render three cook cards and still
    show "—" here — that was exactly the old behaviour — so assert the number,
    not the cards.
    """
    week, when = unique_week(9)
    expected = _plate_kcal(live_server, PLATE)
    # Otherwise a plate whose macros all got excluded would make this pass with
    # 0 == 0, which is the exact failure the test exists to catch.
    assert expected > 0, f"{PLATE} reports no calories; the test proves nothing"
    _place_plate(live_server, meal_name=PLATE, week=week, when=when)

    page.goto(live_server.url(f"/meal-planner?week={week}"),
              wait_until="domcontentloaded")
    page.wait_for_selector(".bundle-card", timeout=15_000)

    # unique_week() puts the date on the Wednesday of its week.
    cell = page.locator('.totals-cell[data-day="Wednesday"] .totals-kcal')
    cell.wait_for(timeout=15_000)
    text = cell.inner_text()
    actual = int("".join(ch for ch in text.split("kcal")[0] if ch.isdigit()))
    assert abs(actual - expected) <= 1, (
        f"plate reports {expected} kcal on its card but the day row says {text!r}"
    )
    assert page_errors == [], f"planner raised: {page_errors}"


def test_a_plate_draws_as_one_card_naming_its_members(live_server, page, page_errors):
    week, when = unique_week(10)
    bundle = _place_plate(live_server, meal_name=PLATE, week=week, when=when)

    page.goto(live_server.url(f"/meal-planner?week={week}"),
              wait_until="domcontentloaded")
    page.wait_for_selector(".bundle-card", timeout=15_000)

    assert page.locator(".bundle-card").count() == 1, "a plate drew as several cards"
    card = page.locator(".bundle-card").first
    assert PLATE in card.inner_text()
    # Every sub-recipe is named on the card, so the plate can be read at a glance.
    assert card.locator(".bundle-member").count() == len(bundle["cooks"])
    assert page_errors == [], f"planner raised: {page_errors}"


def test_dragging_a_plate_moves_every_member(live_server, page, page_errors):
    """A silent no-op here is what a missing bundle branch in moveCookCard looks
    like — the card snaps back and nothing happens."""
    week, when = unique_week(11)
    bundle = _place_plate(live_server, meal_name=PLATE, week=week, when=when)
    target = date.fromisoformat(when).replace(day=date.fromisoformat(when).day + 1)

    page.goto(live_server.url(f"/meal-planner?week={week}"),
              wait_until="domcontentloaded")
    page.wait_for_selector(".bundle-card", timeout=15_000)
    page.locator(".bundle-card .card-menu-btn").first.click()
    page.get_by_role("button", name="Move to another slot").click()
    page.locator('.grid-cell[data-day="Thursday"][data-meal="dinner"]').first.click()
    page.wait_for_timeout(1500)

    resp = requests.get(live_server.url(f"/api/week-board/{week}"), timeout=30)
    cooks = [c for c in resp.json()["cooks"] if c["bundle_id"] == bundle["bundle_id"]]
    assert cooks, "the plate vanished from the board"
    assert all(c["date"] == target.isoformat() and c["meal"] == "dinner"
               for c in cooks), (
        f"only some members moved: {[(c['recipe'], c['date']) for c in cooks]}"
    )
    assert page_errors == [], f"planner raised: {page_errors}"
