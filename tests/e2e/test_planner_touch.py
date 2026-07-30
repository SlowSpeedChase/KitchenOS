"""The planner as a touchscreen surface: tap targets, the shelf, tap-to-assign.

These are failures only a real viewport can show. No unit test can see that a
control renders 17x20 px, that 28 grid slots overflow the space the shelf leaves
them, or that tapping a recipe arms nothing — here the CSS and the geometry *are*
the behaviour.

Touch mode is forced with `?touch=1` (see the page's head script) rather than a
touch-capable browser context, so these run in the same browser as the rest of
the e2e suite.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.e2e

IPAD_PORTRAIT = {"width": 820, "height": 1180}
IPAD_LANDSCAPE = {"width": 1180, "height": 820}

# Apple HIG's floor, and the threshold below which measured tap error rates climb
# past 25%. It is a minimum, not a target.
TAP_FLOOR = 44

# One documented exception. Today's Prep is scheduled to leave this screen
# entirely (it is a *today* object on a *week* screen — see
# docs/plans/2026-07-30-planner-shelf-and-tap-to-assign.md, "out of scope"), and
# a native checkbox cannot be grown to 44 px without either an absurd glyph or an
# appearance:none rebuild of a component with a filed removal plan. Named here
# rather than silently skipped: if Today's Prep is still on this screen when
# someone next reads this, the exception has outlived its reason.
KNOWN_SMALL = ".prep-task input[type=checkbox]"

# Anything that takes a tap. `pointer-events: none` elements are excluded because
# they genuinely cannot be tapped — under touch the recipe title is one, since the
# card around it owns the tap and the title would otherwise be 252 duplicate
# sub-44 "targets" that do exactly what the card does.
MEASURE_JS = """
(known) => {
  const sel = 'button, a, select, input, [role=button], .sidebar-tab, .chip, .scale-btn';
  const excluded = new Set(document.querySelectorAll(known));
  const live = [...document.querySelectorAll(sel)].filter(el => {
    if (excluded.has(el)) return false;
    if (!el.checkVisibility({checkVisibilityCSS: true})) return false;
    if (getComputedStyle(el).pointerEvents === 'none') return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  });
  const small = live.filter(el => {
    const r = el.getBoundingClientRect();
    return Math.min(r.width, r.height) < %d;
  }).map(el => ({
    what: (el.className || '').toString().split(' ')[0] || el.id || el.tagName.toLowerCase(),
    w: Math.round(el.getBoundingClientRect().width),
    h: Math.round(el.getBoundingClientRect().height),
    label: (el.getAttribute('aria-label') || el.textContent || '').trim().slice(0, 30),
  }));
  return {measured: live.length, small};
}
""" % TAP_FLOOR


def _open(page, live_server, viewport):
    page.set_viewport_size(viewport)
    page.goto(live_server.url("/meal-planner?touch=1"), wait_until="domcontentloaded")
    page.wait_for_selector(".recipe-card")
    page.wait_for_selector(".grid-cell")


class TestTapTargets:
    """Before this suite: 526 of 607 visible controls were under 44 pt, 477 under 30."""

    @pytest.mark.parametrize("viewport,name", [
        (IPAD_PORTRAIT, "portrait"), (IPAD_LANDSCAPE, "landscape")])
    def test_no_control_is_below_the_floor(self, live_server, page, page_errors,
                                           viewport, name):
        _open(page, live_server, viewport)
        result = page.evaluate(MEASURE_JS, KNOWN_SMALL)

        # Guard the guard: a typo'd selector or a page that never rendered would
        # otherwise report "0 too small" and pass while measuring nothing.
        assert result["measured"] > 200, (
            f"only {result['measured']} controls measured in {name} — the sweep "
            f"is not seeing the page, so a clean result proves nothing")

        offenders = "\n".join(
            f"  {o['w']}x{o['h']}  {o['what']}  {o['label']}" for o in result["small"])
        assert not result["small"], (
            f"{len(result['small'])} controls under {TAP_FLOOR}pt in {name}:\n{offenders}")
        assert page_errors == []

    def test_the_preview_button_is_tappable(self, live_server, page):
        """20x20 before — the single most repeated undersized control, 252 of them."""
        _open(page, live_server, IPAD_PORTRAIT)
        box = page.locator(".recipe-card .recipe-info-link").first.bounding_box()
        assert box["width"] >= TAP_FLOOR and box["height"] >= TAP_FLOOR

    def test_the_redundant_card_menu_is_gone_under_touch(self, live_server, page):
        """17x20, and the whole card already opens the same sheet under touch."""
        _open(page, live_server, IPAD_PORTRAIT)
        menus = page.locator(".grid-card .card-menu-btn")
        for i in range(menus.count()):
            assert not menus.nth(i).is_visible()


class TestShelf:
    def test_the_library_is_on_screen_without_a_tap(self, live_server, page, page_errors):
        """It used to sit off-canvas behind a FAB while ~700px of screen was empty."""
        _open(page, live_server, IPAD_PORTRAIT)
        state = page.evaluate("""() => {
          const sb = document.getElementById('sidebar').getBoundingClientRect();
          return {
            top: Math.round(sb.top), height: Math.round(sb.height),
            left: Math.round(sb.left),
            fab: getComputedStyle(document.getElementById('sidebar-toggle')).display,
            cards: document.querySelectorAll('#recipe-list .recipe-card').length,
          };
        }""")
        assert state["left"] == 0, "the shelf spans the width in portrait"
        assert state["top"] < IPAD_PORTRAIT["height"], "the shelf is on screen"
        assert state["height"] > 200, f"the shelf has usable height, got {state['height']}"
        assert state["fab"] == "none", "the drawer FAB has nothing left to open"
        assert state["cards"] > 0, "and it actually has recipes in it"
        assert page_errors == []

    @pytest.mark.parametrize("viewport", [
        IPAD_PORTRAIT,                    # iPad Air / Pro 11"
        {"width": 834, "height": 1194},   # iPad Pro 11" (older)
    ])
    def test_the_whole_week_fits_above_the_shelf(self, live_server, page, viewport):
        """The shelf only delivers an overview if the week still fits beside it.

        Not asserted at 768x1024 (iPad mini / classic portrait): once any slot
        holds a photo card the grid is taller than that viewport at *any* shelf
        height, so it scrolls there by design rather than by regression. The
        shelf is sized in dvh so it shrinks with the screen instead of breaking.

        Pinned to an empty far-future week on purpose. The claim under test is
        that the *compressed empty grid* fits; a slot holding a photo card is
        content that has earned its height, and the session-scoped server means
        any earlier test that placed a cook would otherwise silently change the
        answer depending on run order.
        """
        page.set_viewport_size(viewport)
        page.goto(live_server.url("/meal-planner?touch=1&week=2030-W20"),
                  wait_until="domcontentloaded")
        page.wait_for_selector(".recipe-card")
        page.wait_for_selector(".grid-cell")
        state = page.evaluate("""() => {
          const gc = document.querySelector('.grid-container');
          const cells = [...document.querySelectorAll('.grid-cell')];
          return {
            cells: cells.length,
            onscreen: cells.filter(c => {
              const r = c.getBoundingClientRect();
              return r.top >= 0 && r.bottom <= window.innerHeight;
            }).length,
            overflow: gc.scrollHeight - gc.clientHeight,
            shelf: Math.round(document.getElementById('sidebar').getBoundingClientRect().height),
            cards: document.querySelectorAll('.grid-card').length,
          };
        }""")
        assert state["cells"] == 28, "7 days x 4 meals"
        assert state["overflow"] <= 2, (
            f"the grid overflows by {state['overflow']}px at "
            f"{viewport['width']}x{viewport['height']} (shelf {state['shelf']}px, "
            f"{state['cards']} cards placed) — the week no longer fits above the shelf")
        assert state["onscreen"] == 28, (
            f"only {state['onscreen']}/28 slots visible — the big picture is cut off")

    def test_landscape_keeps_its_docked_rail(self, live_server, page):
        """Landscape measured fine before this work; the change must not touch it."""
        _open(page, live_server, IPAD_LANDSCAPE)
        state = page.evaluate("""() => {
          const sb = document.getElementById('sidebar').getBoundingClientRect();
          const mn = document.querySelector('.main').getBoundingClientRect();
          return {sbLeft: Math.round(sb.left), sbHeight: Math.round(sb.height),
                  mainLeft: Math.round(mn.left), vh: window.innerHeight};
        }""")
        assert state["sbLeft"] == 0 and state["mainLeft"] >= 200, "rail on the left"
        assert state["sbHeight"] >= state["vh"] - 2, "rail is full height, not a shelf"

    def test_shelf_height_survives_a_reload(self, live_server, page):
        _open(page, live_server, IPAD_PORTRAIT)
        page.evaluate("""() => {
          localStorage.setItem('planner.shelfHeight', '300');
          localStorage.setItem('planner.shelfCollapsed', '0');
        }""")
        page.reload(wait_until="domcontentloaded")
        page.wait_for_selector(".recipe-card")
        height = page.evaluate(
            "() => Math.round(document.getElementById('sidebar').getBoundingClientRect().height)")
        assert abs(height - 300) <= 2, f"expected the saved 300px shelf, got {height}"

    def test_collapsing_leaves_the_handle_reachable(self, live_server, page):
        """A collapsed shelf that can't be re-opened is a hidden library again."""
        _open(page, live_server, IPAD_PORTRAIT)
        page.evaluate("() => setShelfCollapsed(true)")
        box = page.locator("#shelf-handle").bounding_box()
        assert box["height"] >= TAP_FLOOR
        assert box["y"] + box["height"] <= IPAD_PORTRAIT["height"] + 1
        page.evaluate("() => setShelfCollapsed(false)")
        assert page.evaluate(
            "() => document.getElementById('sidebar').getBoundingClientRect().height") > 200


class TestTapToAssign:
    """WCAG 2.2 SC 2.5.7: dragging needs a single-pointer alternative."""

    def test_tap_a_recipe_then_a_slot_assigns_it(self, live_server, page, page_errors):
        _open(page, live_server, IPAD_PORTRAIT)
        card = page.locator("#recipe-list .recipe-card").first
        name = card.get_attribute("data-name")

        cell = page.locator('.grid-cell[data-day="Thursday"][data-meal="dinner"]')
        assert cell.locator(".grid-card").count() == 0, "starting from an empty slot"

        card.click()
        page.wait_for_selector("#assign-bar:not([hidden])")
        assert name in page.inner_text("#assign-bar")

        cell.click()
        page.wait_for_selector(
            '.grid-cell[data-day="Thursday"][data-meal="dinner"] .grid-card',
            timeout=10000)
        assert name in cell.inner_text()
        assert page.locator("#assign-bar").is_hidden(), "the bar clears after placing"
        assert page_errors == []

    def test_the_armed_state_says_where_it_can_go(self, live_server, page):
        _open(page, live_server, IPAD_PORTRAIT)
        assert page.locator(".grid-cell .empty-label").first.inner_text().strip() == "+"
        page.locator("#recipe-list .recipe-card").first.click()
        page.wait_for_selector("#assign-bar:not([hidden])")
        assert page.locator(".grid-cell .empty-label").first.inner_text().strip() == "+ here"
        assert page.locator(".app.placing").count() == 1

    def test_tapping_the_armed_card_again_cancels(self, live_server, page):
        _open(page, live_server, IPAD_PORTRAIT)
        card = page.locator("#recipe-list .recipe-card").first
        card.click()
        page.wait_for_selector("#assign-bar:not([hidden])")
        card.click()
        page.wait_for_selector("#assign-bar", state="hidden")
        assert page.locator(".recipe-card.armed").count() == 0

    def test_escape_and_cancel_both_disarm(self, live_server, page):
        _open(page, live_server, IPAD_PORTRAIT)
        card = page.locator("#recipe-list .recipe-card").first

        card.click()
        page.wait_for_selector("#assign-bar:not([hidden])")
        page.keyboard.press("Escape")
        page.wait_for_selector("#assign-bar", state="hidden")

        card.click()
        page.wait_for_selector("#assign-bar:not([hidden])")
        page.click("#assign-bar-cancel")
        page.wait_for_selector("#assign-bar", state="hidden")
        assert page.locator(".grid-cell .empty-label").first.inner_text().strip() == "+"

    def test_the_preview_button_does_not_arm(self, live_server, page):
        """The ⓘ owns its tap — otherwise previewing would arm behind the modal."""
        _open(page, live_server, IPAD_PORTRAIT)
        page.locator("#recipe-list .recipe-card .recipe-info-link").first.click()
        page.wait_for_timeout(500)
        assert page.locator("#assign-bar").is_hidden()
        assert page.locator(".recipe-card.armed").count() == 0

    def test_an_empty_slot_still_suggests_when_nothing_is_armed(self, live_server, page):
        """Tap-to-assign must not eat the existing tap-an-empty-slot behaviour.

        Asserts the *routing*, by standing in for suggestMeal, rather than a live
        suggestion: suggestMeal legitimately no-ops on a board-backed week
        (`weekBoard.cooks.length > 0`), so a week that any earlier test placed a
        cook into would make an outcome-based assertion vacuous.
        """
        _open(page, live_server, IPAD_PORTRAIT)
        page.evaluate("""() => {
            window.__suggestedFor = null;
            window.suggestMeal = (cell) =>
                window.__suggestedFor = `${cell.dataset.day}-${cell.dataset.meal}`;
        }""")

        page.locator('.grid-cell[data-day="Friday"][data-meal="lunch"]').click()
        assert page.evaluate("() => window.__suggestedFor") == "Friday-lunch"

        # ...and an armed recipe claims the tap instead of the suggester.
        page.evaluate("() => { window.__suggestedFor = null; }")
        page.locator("#recipe-list .recipe-card").first.click()
        page.wait_for_selector("#assign-bar:not([hidden])")
        page.locator('.grid-cell[data-day="Saturday"][data-meal="lunch"]').click()
        assert page.evaluate("() => window.__suggestedFor") is None
