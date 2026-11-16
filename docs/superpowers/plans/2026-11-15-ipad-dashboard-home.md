# iPad Dashboard Home Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the `/` home page with one iPad-landscape screen showing the meal calendar, the grocery list and the inventory side by side, with nothing to open or close.

**Architecture:** `/` stays a server-rendered shell (`templates/home.html`) that fills three columns client-side from endpoints that already exist. All behaviour lives in one new script, `static/dashboard.js`; all styling in one new stylesheet, `static/dashboard.css`, written only through `static/tokens.css` variables. No new API routes, no new Python modules.

**Tech Stack:** Flask (existing `api_server.py`), vanilla JS (no build step, no libraries), CSS custom properties, pytest, Playwright (`tests/e2e`).

**Spec:** `docs/superpowers/specs/2026-11-15-ipad-dashboard-chat-trmnl-design.md`, Piece 1 only. Pieces 2 (chat) and 3 (TRMNL) get their own plans.

> **Status: executed, then superseded in part.** Tasks 1–6 were built from this plan. The layout
> was then changed to a full-page calendar at Chase's request (commit "feat(home): full-page
> interactive calendar"); see the revision note in the spec. The code in the repository, not
> the code blocks below, is current.

## Low-cost execution rules

This plan is written to be executed mechanically by a smaller model in one session.

- **Every code block is final. Copy it; do not redesign, rename or "improve" it.**
- **Do not explore the repository.** Everything needed is in this file. Open another file only when a step names it.
- **Do not re-read a file you just wrote**, and do not print file contents back.
- Run only the commands a step lists, and append `2>&1 | tail -15` to every pytest command.
- Do Tasks 1–6 in order in a single session. **Skip Task 7** — the reviewer does it.
- When a test fails: read the last 15 lines, make one targeted fix, re-run. After two failed
  fixes on the same test, stop and report the test name, the output and what you tried.
- Final report: at most 10 lines — commits made, pass/fail counts per task, anything skipped.

## Global Constraints

- Work in the worktree `.worktrees/ipad-dashboard` on a new branch `feat/ipad-dashboard-home` cut from `spec/ipad-dashboard`. Never edit the main checkout.
- Python 3.11, always via `.venv/bin/python` / `.venv/bin/pytest`. The worktree has no `.venv`; use the main checkout's: `../../.venv/bin/pytest`.
- Unit suite: `../../.venv/bin/pytest -q`. E2E: `../../.venv/bin/pytest tests/e2e -m e2e --trace off -q <file>`.
- No external assets: every script and stylesheet is served from `/static/`. `tests/test_no_external_assets.py` must pass.
- No colour literals. Style only through `tokens.css` variables. Do not edit `static/tokens.css`.
- `templates/home.html` must link `/static/tokens.css` and `/static/kitchenos.css`, must contain the text `window.kitchenosContext`, and must not contain `href="/"`.
- The dashboard must never call `PUT /api/meal-plan/<week>`. Moves go through `POST /api/cooks/<id>/move` or `POST /api/bundles/<id>/move` only.
- A week id (`YYYY-Www`) appears only in URLs and values, never in visible text. Visible text is a date range.
- Shopping "match" lines are never rendered as checkboxes. Only rows from `GET /api/shopping-list/saved/<week>` (which are purchase checkboxes) get a checkbox.
- UI copy: sentence case, no exclamation marks, no "please", no "successfully".
- Touch targets at least 44px tall.
- Commit messages end with `Co-Authored-By: Claude Fable 5.2 <noreply@anthropic.com>`.

## Deviations from the spec, decided while planning

These were forced by what the existing data can support. Each is called out so the reviewer can reject it.

1. **Grocery list is not grouped by aisle.** The saved list is a flat alphabetical checklist; no aisle data exists. The column shows unchecked items first, then checked items muted.
2. **"Inventory matches — verify" lines are not shown in the column.** They are not in the saved-list payload. A "Full list" link opens the page that shows them.
3. **Moving a meal uses a native `<select>` inside the expanded meal, not drag.** It reaches the same ledger endpoints with far less code and no drag library on this page. Drag stays on `/meal-planner`.
4. **The expanded meal shows open recipe, move, and edit in planner.** "Ingredients on hand vs missing" is left to the recipe page.
5. **Week and month have previous/next controls**, which the spec did not mention; planning next week is impossible without them.
6. **Any change refreshes all three columns**, not only the affected one. All three are fast local reads.

## File Structure

| File | Responsibility |
|---|---|
| `templates/home.html` (rewrite) | The shell: header, verdict slot, three empty columns, the all-pages popover |
| `static/dashboard.css` (new) | All dashboard layout and styling |
| `static/dashboard.js` (new) | Fetch, render and interact for the three columns |
| `api_server.py` `home_page()` (modify) | Fill the shell's placeholders |
| `tests/test_home_dashboard.py` (new) | Unit tests for the served shell |
| `tests/e2e/test_dashboard.py` (new) | Browser tests for the three columns |
| `tests/e2e/test_prep_page.py` (modify) | Drop the retired home-page prep-card assertion |
| `docs/ROADMAP.md` (modify) | Shipped entry |

`dashboard.js` duplicates five small date helpers from `templates/meal_calendar.html`. That is deliberate: no shared JS module exists and creating one is outside this plan.

---

### Task 1: The dashboard shell

**Files:**
- Rewrite: `templates/home.html`
- Create: `static/dashboard.css`
- Create: `static/dashboard.js` (stub)
- Modify: `api_server.py` (`home_page`, near line 4525)
- Create: `tests/test_home_dashboard.py`
- Modify: `tests/e2e/test_prep_page.py` (`TestHomePage`)

**Interfaces:**
- Produces: DOM ids `meals-body`, `meals-label`, `meals-prev`, `meals-next`, `buy-body`, `buy-label`, `hand-body`, `view-week`, `view-month`, `all-pages`. Template placeholders `<!--TODAY_HEADING-->`, `<!--VERDICT-->`, `<!--SECTIONS-->`. Later tasks render into those ids.

- [ ] **Step 1: Create the branch**

```bash
cd /Users/chaseeasterling/Dev/KitchenOS/.worktrees/ipad-dashboard
git switch -c feat/ipad-dashboard-home
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_home_dashboard.py`:

```python
"""The `/` shell: three columns, the registry behind a popover, no retired cards."""
import re
from datetime import date
from pathlib import Path

import pytest

from api_server import app

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def body():
    app.config['TESTING'] = True
    with app.test_client() as client:
        response = client.get('/')
        assert response.status_code == 200
        return response.get_data(as_text=True)


@pytest.mark.parametrize("element_id", [
    "meals-body", "meals-label", "meals-prev", "meals-next",
    "buy-body", "buy-label", "hand-body", "view-week", "view-month",
])
def test_shell_carries_every_mount_point(body, element_id):
    assert f'id="{element_id}"' in body


def test_registry_lives_in_a_native_popover(body):
    assert re.search(r'<nav id="all-pages" popover\b', body)
    assert 'popovertarget="all-pages"' in body


def test_heading_is_todays_date_not_a_week_id(body):
    assert date.today().strftime('%A, %b %-d') in body
    assert not re.search(r'>\s*\d{4}-W\d{2}\s*<', body)


def test_no_placeholder_survives(body):
    for placeholder in ("<!--TODAY_HEADING-->", "<!--VERDICT-->", "<!--SECTIONS-->"):
        assert placeholder not in body


def test_kitchen_today_cards_are_retired(body):
    assert 'today-card' not in body


def test_dashboard_assets_are_local(body):
    assert '<link rel="stylesheet" href="/static/dashboard.css">' in body
    assert '<script src="/static/dashboard.js" defer></script>' in body


def test_dashboard_css_uses_tokens_only():
    css = (REPO / "static" / "dashboard.css").read_text()
    assert not re.search(r'#[0-9a-fA-F]{3,8}\b', css), "colour literal in dashboard.css"
    assert not re.search(r'\brgba?\(', css), "colour literal in dashboard.css"
```

- [ ] **Step 3: Run them to verify they fail**

Run: `../../.venv/bin/pytest tests/test_home_dashboard.py -q`
Expected: FAIL — `id="meals-body"` not in body, and `FileNotFoundError` for `static/dashboard.css`.

- [ ] **Step 4: Rewrite `templates/home.html`**

Replace the whole file with:

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
    <meta name="apple-mobile-web-app-title" content="KitchenOS">
    <meta name="theme-color" content="#f4ede3" media="(prefers-color-scheme: light)">
    <meta name="theme-color" content="#0f1116" media="(prefers-color-scheme: dark)">
    <!-- Deliberately NOT apple-mobile-web-app-capable: standalone mode strips
         Safari's chrome, and every link here leads to a page that needs Back. -->
    <title>KitchenOS</title>
    <link rel="stylesheet" href="/static/tokens.css">
    <link rel="stylesheet" href="/static/kitchenos.css">
    <link rel="stylesheet" href="/static/dashboard.css">
</head>
<body>
    <header class="dash-head">
        <div>
            <div class="kicker">KitchenOS</div>
            <h1><!--TODAY_HEADING--></h1>
        </div>
        <div class="dash-tools">
            <div class="seg" role="group" aria-label="Calendar range">
                <button type="button" id="view-week" aria-pressed="true">Week</button>
                <button type="button" id="view-month" aria-pressed="false">Month</button>
            </div>
            <button type="button" class="menu-btn" popovertarget="all-pages">All pages</button>
        </div>
    </header>

    <!--VERDICT-->

    <main class="dash">
        <section class="col" aria-labelledby="meals-label">
            <div class="col-head">
                <button type="button" class="nav-btn" id="meals-prev" aria-label="Earlier">&lsaquo;</button>
                <h2 class="col-label" id="meals-label">Meals</h2>
                <button type="button" class="nav-btn" id="meals-next" aria-label="Later">&rsaquo;</button>
            </div>
            <div class="col-body" id="meals-body"></div>
        </section>
        <section class="col" aria-labelledby="buy-label">
            <div class="col-head"><h2 class="col-label" id="buy-label">To buy</h2></div>
            <div class="col-body" id="buy-body"></div>
        </section>
        <section class="col" aria-labelledby="hand-label">
            <div class="col-head"><h2 class="col-label" id="hand-label">On hand</h2></div>
            <div class="col-body" id="hand-body"></div>
        </section>
    </main>

    <nav id="all-pages" popover aria-label="All pages">
        <!--SECTIONS-->
    </nav>

    <script src="/static/dashboard.js" defer></script>
    <script>
        // One PATCH, no navigation. Mirrors /prep's handler; both exist because
        // the ask has to be wherever you already are.
        document.querySelectorAll('.verdict-ask .verdict-btn').forEach(btn => {
            btn.addEventListener('click', async () => {
                const ask = btn.closest('.verdict-ask');
                const makeAgain = btn.dataset.verdict === '1';
                ask.querySelectorAll('.verdict-btn').forEach(b => b.disabled = true);
                try {
                    const resp = await fetch(`/api/cooks/${ask.dataset.cookId}`, {
                        method: 'PATCH',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ make_again: makeAgain }),
                    });
                    if (!resp.ok) throw new Error('save failed');
                    ask.classList.add('answered');
                    ask.querySelector('.verdict-q').textContent =
                        makeAgain ? 'Noted — you’d make it again.' : 'Noted — not again.';
                } catch (err) {
                    ask.querySelectorAll('.verdict-btn').forEach(b => b.disabled = false);
                    ask.querySelector('.verdict-q').textContent = 'Couldn’t save that. Try again.';
                }
            });
        });
    </script>
    <script>
        // Commands are interpreted against the week on screen, not the calendar week.
        window.kitchenosContext = () =>
            window.koDash ? {screen: 'home', week: window.koDash.week} : {screen: 'home'};
    </script>
</body>
</html>
```

- [ ] **Step 5: Create `static/dashboard.css`**

```css
/* The `/` dashboard. Styled only through tokens.css variables — no literals. */
* { margin: 0; padding: 0; box-sizing: border-box; }

body {
    font-family: var(--font-body);
    background: var(--bg);
    background-image: var(--dots);
    background-size: var(--dot-size) var(--dot-size);
    color: var(--ink);
    border-top: 3px solid var(--app-kitchenos);
    -webkit-text-size-adjust: 100%;
    min-height: 100dvh;
    display: flex;
    flex-direction: column;
    padding-block: 16px calc(16px + env(safe-area-inset-bottom));
    padding-inline: max(20px, env(safe-area-inset-left)) max(20px, env(safe-area-inset-right));
}

/* ---- Header ---- */
.dash-head {
    display: flex; align-items: flex-end; justify-content: space-between;
    gap: 16px; flex-wrap: wrap; margin-block-end: 20px;
}
.kicker {
    font-family: var(--font-mono); font-size: 11px; text-transform: uppercase;
    letter-spacing: .12em; color: var(--app-kitchenos); margin-block-end: 4px;
}
h1 { font-family: var(--font-display); font-size: 28px; font-weight: 600; letter-spacing: -.01em; }
.dash-tools { display: flex; align-items: center; gap: 12px; }

.seg { display: flex; border: 1px solid var(--line); border-radius: var(--radius-box); overflow: hidden; }
.seg button, .menu-btn, .nav-btn, .act {
    font: inherit; color: var(--ink); background: var(--surface);
    min-height: 44px; padding-inline: 16px; cursor: pointer;
}
.seg button { border: 0; }
.seg button[aria-pressed="true"] { background: var(--app-kitchenos); color: var(--text-on-accent); }
.menu-btn, .act { border: 1px solid var(--line); border-radius: var(--radius-box); }
.nav-btn { border: 0; background: transparent; min-width: 44px; padding-inline: 0; font-size: 22px; color: var(--muted); }

/* ---- Columns: grouped by space, not rules ---- */
.dash { display: grid; grid-template-columns: minmax(0, 1fr); gap: 32px; flex: 1; min-height: 0; }
.col { display: flex; flex-direction: column; min-width: 0; min-height: 0; }
.col-head { display: flex; align-items: center; gap: 4px; min-height: 44px; margin-block-end: 8px; }
.col-label {
    font-family: var(--font-mono); font-size: 11px; font-weight: 600;
    text-transform: uppercase; letter-spacing: .1em; color: var(--muted); flex: 1;
}
.col-body { display: flex; flex-direction: column; gap: 6px; min-height: 0; }

/* Three columns hold as long as each keeps ~260px; below that they stack.
   The 64px end padding keeps the floating command button off the last rows. */
@media (min-width: 880px) {
    body { height: 100dvh; overflow: hidden; }
    .dash { grid-template-columns: repeat(3, minmax(0, 1fr)); padding-block-end: 64px; }
    .col-body { overflow-y: auto; -webkit-overflow-scrolling: touch; padding-block-end: 24px; }
}

.note { color: var(--muted); font-size: 14px; }
.note.bad { color: var(--alert); }
.foot { margin-block-start: 10px; font-size: 14px; }
.foot a, .meal-body a { color: var(--app-kitchenos); }

/* ---- Meals: week ---- */
.day { padding: 8px 10px; border-radius: var(--radius-box); }
.day.today { background: var(--surface); background-image: var(--grain); border: 1px solid var(--app-kitchenos); }
.day-name { font-family: var(--font-mono); font-size: 11px; text-transform: uppercase; letter-spacing: .08em; color: var(--muted); }
.day.today .day-name { color: var(--app-kitchenos); }
.open { color: var(--muted); font-size: 15px; min-height: 28px; display: flex; align-items: center; }

details.meal > summary {
    list-style: none; cursor: pointer; min-height: 44px;
    display: flex; align-items: center; gap: 8px; font-size: 16px; overflow-wrap: anywhere;
}
details.meal > summary::-webkit-details-marker { display: none; }
.tag { font-family: var(--font-mono); font-size: 11px; color: var(--muted); flex: none; }
.meal-body { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; padding-block: 4px 12px; font-size: 14px; }
.meal-body a { display: inline-flex; align-items: center; min-height: 44px; }
.meal-body select { font: inherit; min-height: 44px; color: var(--ink); background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius-box); padding-inline: 10px; }

/* ---- Meals: month ---- */
.month { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: 4px; }
.month .dow { font-family: var(--font-mono); font-size: 11px; color: var(--muted); text-align: center; padding-block-end: 4px; }
.month button.cell {
    font: inherit; color: var(--ink); text-align: start; cursor: pointer;
    background: var(--surface); border: 1px solid var(--line-soft); border-radius: 8px;
    min-height: 64px; padding: 4px 6px; display: flex; flex-direction: column; gap: 2px; min-width: 0;
}
.month button.cell.out { background: transparent; color: var(--muted); }
.month button.cell.today { border-color: var(--app-kitchenos); }
.month .num { font-family: var(--font-mono); font-size: 11px; color: var(--muted); }
.month .dish { font-size: 12px; line-height: 1.25; overflow: hidden; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }

/* ---- To buy ---- */
.buy-row { display: flex; align-items: center; gap: 12px; min-height: 44px; font-size: 16px; overflow-wrap: anywhere; }
.buy-row input { width: 22px; height: 22px; flex: none; accent-color: var(--app-kitchenos); }
.buy-row.done { color: var(--muted); text-decoration: line-through; }

/* ---- On hand ---- */
.grp { font-family: var(--font-mono); font-size: 11px; text-transform: uppercase; letter-spacing: .08em; color: var(--muted); margin-block: 14px 2px; }
.grp:first-child { margin-block-start: 0; }
.grp.soon { color: var(--warning); }
.item { display: flex; justify-content: space-between; gap: 12px; font-size: 15px; min-height: 28px; align-items: center; overflow-wrap: anywhere; }
.item .qty { color: var(--muted); font-size: 13px; flex: none; }
.item .qty.expired { color: var(--alert); }
details.staples > summary { cursor: pointer; min-height: 44px; display: flex; align-items: center; color: var(--muted); font-size: 14px; }

/* ---- Verdict ask (markup shared with /prep) ---- */
.verdict-ask {
    display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap;
    margin-block-end: 18px; padding: 10px 16px; border: 1px solid var(--line); border-radius: var(--radius-box);
}
.verdict-btns { display: flex; gap: 12px; }
.verdict-btn { font-size: 20px; line-height: 1; min-width: 52px; min-height: 44px; border: 1px solid var(--line); border-radius: 8px; background: transparent; cursor: pointer; }
.verdict-ask.answered { color: var(--muted); }

/* ---- All pages popover ---- */
#all-pages {
    inset: auto; inset-block-start: 72px; inset-inline-end: 20px;
    width: min(420px, calc(100vw - 40px)); max-height: 76dvh; overflow-y: auto;
    padding: 6px 16px 16px; color: var(--ink);
    background: var(--surface); background-image: var(--grain);
    border: 1px solid var(--line); border-radius: var(--radius); box-shadow: var(--shadow);
}
#all-pages h2 { font-family: var(--font-mono); font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: .1em; color: var(--muted); margin-block: 16px 6px; }
#all-pages .card { display: flex; align-items: center; gap: 12px; min-height: 52px; padding-block: 6px; text-decoration: none; color: inherit; }
#all-pages .card .emoji { font-size: 20px; flex: none; }
#all-pages .card .text { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
#all-pages .card .title { font-size: 15px; font-weight: 600; }
#all-pages .card .desc { font-size: 13px; color: var(--muted); overflow-wrap: anywhere; }
```

- [ ] **Step 6: Create the `static/dashboard.js` stub**

```js
/* KitchenOS dashboard: fills the three columns of `/`. See templates/home.html. */
(function () {
    'use strict';
})();
```

- [ ] **Step 7: Update `home_page()` in `api_server.py`**

Replace the body of `home_page` (keep the decorator) with:

```python
def home_page():
    """The web home page: meals, groceries and inventory on one screen.

    The shell renders with no data in it — each column fetches its own — so this
    route never waits on anything slower than the verdict lookup. The full page
    registry stays reachable from the header's popover, so nothing is orphaned.
    """
    from lib import kitchen_today, web_dashboard

    today = date.today()
    return _serve_page('home.html', [
        ('<!--TODAY_HEADING-->', today.strftime('%A, %b %-d')),
        ('<!--VERDICT-->',
         kitchen_today.render_verdict_html(kitchen_today.verdict_prompt(today))),
        ('<!--SECTIONS-->', web_dashboard.render_html()),
    ])
```

- [ ] **Step 8: Retire the home-page prep-card e2e assertion**

In `tests/e2e/test_prep_page.py`, delete the method `test_the_home_page_carries_a_prep_card` from `class TestHomePage`. Keep `test_the_home_page_stays_fast` unchanged.

- [ ] **Step 9: Run the unit suite**

Run: `../../.venv/bin/pytest -q`
Expected: PASS, including `tests/test_home_dashboard.py`, `tests/test_page_chrome.py`, `tests/test_api_endpoints.py::test_home_page_lists_every_registered_page`, `tests/test_theme_tokens.py` and `tests/test_no_external_assets.py`. If `tests/test_kitchen_today.py` or `tests/test_verdict_prompt.py` assert on home-page HTML that no longer exists, fix the assertion to target the function under test (`kitchen_today.gather`, `render_html`, `verdict_prompt`) rather than `/`; do not re-add cards to the page.

- [ ] **Step 10: Commit**

```bash
git add templates/home.html static/dashboard.css static/dashboard.js api_server.py tests/test_home_dashboard.py tests/e2e/test_prep_page.py
git commit -m "feat(home): three-column dashboard shell at /

Co-Authored-By: Claude Fable 5.2 <noreply@anthropic.com>"
```

---

### Task 2: Meals column, week view

**Files:**
- Modify: `static/dashboard.js`
- Create: `tests/e2e/test_dashboard.py`

**Interfaces:**
- Consumes: ids from Task 1. `GET /api/week-board/<week>` → `{planned_meals: [{date, meal, recipe, cook_id, bundle_id, bundle_name, anchor, count}], ...}`. `POST /api/cooks/<id>/move` and `POST /api/bundles/<id>/move`, body `{date, meal}`, error body `{error}`.
- Produces: `window.koDash = {week}`; inside the IIFE: `state = {view, week, month}`, `el(tag, cls, text)`, `getJSON(url)`, `postJSON(url, body)`, `failed(body, message, retry)`, `loadMeals()`, `refreshAll()`, date helpers `pad`, `iso`, `weekOf`, `mondayOf`, `addDays`. The page opens on `?week=YYYY-Www` when given, else the current week.

- [ ] **Step 1: Write the failing e2e tests**

Create `tests/e2e/test_dashboard.py`:

```python
"""The `/` dashboard, driven in a real browser against a throwaway vault and DB."""
from datetime import date, timedelta

import pytest
import requests
from playwright.sync_api import expect

from tests.e2e._weeks import unique_week

pytestmark = pytest.mark.e2e

IPAD = {"width": 1180, "height": 820}
RECIPE = "The Sexy Skillet Lasagna"


def _cook(server, week, when, recipe=RECIPE):
    resp = requests.post(server.url("/api/cooks"), json={
        "recipe": recipe, "week": week, "scale": 1.0, "servings_produced": 8,
        "date": when, "meal": "dinner", "initial_placement_count": 1,
    }, timeout=30)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _open(page, server, week=None):
    """Open the dashboard on a week the test owns, or on the real current week."""
    page.set_viewport_size(IPAD)
    page.goto(server.url(f"/?week={week}" if week else "/"), wait_until="networkidle")


def test_week_lists_seven_days_with_the_planned_dinner(live_server, page, page_errors):
    week, wednesday = unique_week(20)
    _cook(live_server, week, wednesday)
    _open(page, live_server, week)
    expect(page.locator("#meals-body .day")).to_have_count(7)
    day = page.locator(f'#meals-body .day[data-date="{wednesday}"]')
    expect(day.locator("details.meal summary")).to_contain_text(RECIPE)
    expect(page.locator("#meals-body .open")).to_have_count(6)
    expect(page.locator("#meals-label")).not_to_contain_text("W")
    assert page_errors == []


def test_moving_a_meal_keeps_its_scale_and_never_uses_the_legacy_put(live_server, page, page_errors):
    week, wednesday = unique_week(21)
    cook = _cook(live_server, week, wednesday)
    friday = (date.fromisoformat(wednesday) + timedelta(days=2)).isoformat()
    puts = []
    page.on("request", lambda r: r.method == "PUT" and puts.append(r.url))
    _open(page, live_server, week)
    page.locator(f'.day[data-date="{wednesday}"] details.meal summary').click()
    page.locator(f'.day[data-date="{wednesday}"] select').select_option(friday)
    expect(page.locator(f'.day[data-date="{friday}"] details.meal')).to_have_count(1)
    expect(page.locator(f'.day[data-date="{wednesday}"] details.meal')).to_have_count(0)
    moved = requests.get(live_server.url(f"/api/cooks/{cook['id']}"), timeout=30).json()
    assert moved["date"] == friday
    assert moved["scale"] == cook["scale"]
    assert puts == []
    assert page_errors == []


def test_a_failed_meals_fetch_leaves_the_other_columns_alone(live_server, page):
    week, _ = unique_week(22)
    page.route("**/api/week-board/**", lambda route: route.fulfill(status=500, body="{}"))
    _open(page, live_server, week)
    expect(page.locator("#meals-body .note.bad")).to_be_visible()
    expect(page.locator("#meals-body button.act")).to_have_text("Try again")
```

- [ ] **Step 2: Run them to verify they fail**

Run: `../../.venv/bin/pytest tests/e2e/test_dashboard.py -m e2e --trace off -q`
Expected: 3 FAIL — `#meals-body .day` has count 0.

- [ ] **Step 3: Implement the week view**

Replace `static/dashboard.js` with:

```js
/* KitchenOS dashboard: fills the three columns of `/`. See templates/home.html. */
(function () {
    'use strict';

    const MEALS = ['breakfast', 'lunch', 'snack', 'dinner'];

    // ---- dates (same arithmetic as templates/meal_calendar.html) ----
    function pad(n) { return String(n).padStart(2, '0'); }
    function iso(d) { return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`; }
    function addDays(d, n) { return new Date(d.getFullYear(), d.getMonth(), d.getDate() + n); }
    function weekOf(d) {
        const date = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
        const dayNum = date.getUTCDay() || 7;
        date.setUTCDate(date.getUTCDate() + 4 - dayNum);
        const yearStart = new Date(Date.UTC(date.getUTCFullYear(), 0, 1));
        return `${date.getUTCFullYear()}-W${pad(Math.ceil((((date - yearStart) / 86400000) + 1) / 7))}`;
    }
    function mondayOf(week) {
        const [y, w] = week.split('-W').map(Number);
        const jan4Dow = new Date(y, 0, 4).getDay() || 7;
        return new Date(y, 0, 4 - (jan4Dow - 1) + (w - 1) * 7);
    }

    const now = new Date();
    const todayISO = iso(now);
    const thisWeek = weekOf(now);
    const asked = new URLSearchParams(location.search).get('week') || '';
    const state = {
        view: 'week',
        week: /^\d{4}-W\d{2}$/.test(asked) ? asked : thisWeek,
        month: new Date(now.getFullYear(), now.getMonth(), 1),
    };
    window.koDash = { week: state.week };

    // ---- dom + http ----
    const $ = id => document.getElementById(id);
    function el(tag, cls, text) {
        const e = document.createElement(tag);
        if (cls) e.className = cls;
        if (text != null) e.textContent = text;
        return e;
    }
    async function request(url, options) {
        const resp = await fetch(url, options);
        let data = null;
        try { data = await resp.json(); } catch (err) { /* empty or non-JSON body */ }
        if (!resp.ok) {
            const error = new Error((data && data.error) || `HTTP ${resp.status}`);
            error.status = resp.status;
            throw error;
        }
        return data;
    }
    const getJSON = url => request(url);
    const postJSON = (url, body) => request(url, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
    function failed(body, message, retry) {
        body.replaceChildren(el('p', 'note bad', message));
        const again = el('button', 'act', 'Try again');
        again.type = 'button';
        again.addEventListener('click', retry);
        body.appendChild(again);
    }

    // ---- labels ----
    const shortDay = new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' });
    const longDay = new Intl.DateTimeFormat(undefined, { weekday: 'short', month: 'short', day: 'numeric' });
    function weekLabel(week) {
        const monday = mondayOf(week);
        const range = `${shortDay.format(monday)} – ${shortDay.format(addDays(monday, 6))}`;
        if (week === thisWeek) return `This week · ${range}`;
        if (week === weekOf(addDays(now, 7))) return `Next week · ${range}`;
        if (week === weekOf(addDays(now, -7))) return `Last week · ${range}`;
        return range;
    }

    // ---- meals: week ----
    // A plate (bundle) is several cooks sharing bundle_id; show it once, by name.
    function mealsOn(planned, date) {
        const seen = new Set();
        const out = [];
        planned.filter(p => p.date === date)
            .sort((a, b) => MEALS.indexOf(a.meal) - MEALS.indexOf(b.meal))
            .forEach(p => {
                const key = (p.bundle_id ? `b:${p.bundle_id}` : `c:${p.cook_id}`) + `|${p.meal}`;
                if (seen.has(key)) return;
                seen.add(key);
                out.push(p);
            });
        return out;
    }

    async function move(p, date, body) {
        const url = p.bundle_id ? `/api/bundles/${encodeURIComponent(p.bundle_id)}/move`
                                : `/api/cooks/${p.cook_id}/move`;
        try {
            await postJSON(url, { date, meal: p.meal });
            refreshAll();
        } catch (err) {
            body.appendChild(el('p', 'note bad', `Couldn’t move it. ${err.message}`));
        }
    }

    function mealRow(p, monday) {
        const row = el('details', 'meal');
        const summary = el('summary', null, p.bundle_name || p.recipe);
        const tags = [];
        if (p.meal !== 'dinner') tags.push(p.meal);
        if (!p.anchor) tags.push('leftover');
        if (tags.length) summary.appendChild(el('span', 'tag', tags.join(' · ')));
        row.appendChild(summary);

        const body = el('div', 'meal-body');
        if (!p.bundle_id) {
            const open = el('a', null, 'Open recipe');
            open.href = `/recipe/${encodeURIComponent(p.recipe)}`;
            body.appendChild(open);
        }
        if (p.anchor) {  // only the cook itself moves; a leftover follows its placement
            const pick = el('select');
            pick.setAttribute('aria-label', 'Move to another day');
            for (let i = 0; i < 7; i++) {
                const d = addDays(monday, i);
                const option = el('option', null, longDay.format(d));
                option.value = iso(d);
                option.selected = iso(d) === p.date;
                pick.appendChild(option);
            }
            pick.addEventListener('change', () => move(p, pick.value, body));
            body.appendChild(pick);
        }
        const edit = el('a', null, 'Edit in planner');
        edit.href = `/meal-planner?week=${state.week}`;
        body.appendChild(edit);
        row.appendChild(body);
        return row;
    }

    function renderWeek(board) {
        const body = $('meals-body');
        const monday = mondayOf(state.week);
        const dayName = new Intl.DateTimeFormat(undefined, { weekday: 'short', day: 'numeric' });
        const days = [];
        for (let i = 0; i < 7; i++) {
            const d = addDays(monday, i);
            const date = iso(d);
            const day = el('article', 'day');
            day.dataset.date = date;
            if (date === todayISO) day.classList.add('today');
            day.appendChild(el('div', 'day-name', date === todayISO ? 'Today' : dayName.format(d)));
            const meals = mealsOn(board.planned_meals || [], date);
            if (!meals.length) day.appendChild(el('div', 'open', 'Open'));
            meals.forEach(p => day.appendChild(mealRow(p, monday)));
            days.push(day);
        }
        body.replaceChildren(...days);
    }

    async function loadMeals() {
        $('meals-label').textContent = weekLabel(state.week);
        try {
            renderWeek(await getJSON(`/api/week-board/${state.week}`));
        } catch (err) {
            failed($('meals-body'), 'Couldn’t load meals.', loadMeals);
        }
    }

    function shift(direction) {
        state.week = weekOf(addDays(mondayOf(state.week), 7 * direction));
        window.koDash.week = state.week;
        refreshAll();
    }
    $('meals-prev').addEventListener('click', () => shift(-1));
    $('meals-next').addEventListener('click', () => shift(1));

    function refreshAll() {
        loadMeals();
    }

    refreshAll();
})();
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `../../.venv/bin/pytest tests/e2e/test_dashboard.py -m e2e --trace off -q`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add static/dashboard.js tests/e2e/test_dashboard.py
git commit -m "feat(home): meals column with in-place move

Co-Authored-By: Claude Fable 5.2 <noreply@anthropic.com>"
```

---

### Task 3: Meals column, month view

**Files:**
- Modify: `static/dashboard.js`
- Modify: `tests/e2e/test_dashboard.py`

**Interfaces:**
- Consumes: `state`, `el`, `getJSON`, `failed`, `mealsOn`, `weekOf`, `mondayOf`, `addDays`, `iso`, `loadMeals`, `refreshAll`, `shift` from Task 2.
- Produces: `loadMonth()`, `setView(view)`. `loadMeals()` now dispatches on `state.view`. The To buy column (Task 4) reads `state.week`, which month view leaves untouched until a day is tapped.

- [ ] **Step 1: Write the failing tests**

Append to `tests/e2e/test_dashboard.py`. Both tests open the real current week, because they assert on today's cell; they check structure only, so real meal data cannot break them:

```python
def test_month_toggle_swaps_only_the_meals_column(live_server, page, page_errors):
    _open(page, live_server)
    page.locator("#view-month").click()
    expect(page.locator("#view-month")).to_have_attribute("aria-pressed", "true")
    expect(page.locator("#view-week")).to_have_attribute("aria-pressed", "false")
    cells = page.locator("#meals-body .month button.cell")
    assert cells.count() in (28, 35, 42)
    expect(page.locator("#meals-body .month button.cell.today")).to_have_count(1)
    expect(page.locator("#buy-body")).to_be_visible()
    expect(page.locator("#hand-body")).to_be_visible()
    assert page_errors == []


def test_tapping_a_month_day_opens_that_week(live_server, page, page_errors):
    _open(page, live_server)
    page.locator("#view-month").click()
    page.locator("#meals-body .month button.cell.today").click()
    expect(page.locator("#view-week")).to_have_attribute("aria-pressed", "true")
    expect(page.locator("#meals-body .day.today")).to_have_count(1)
    expect(page.locator("#meals-label")).to_contain_text("This week")
    assert page_errors == []
```

- [ ] **Step 2: Run them to verify they fail**

Run: `../../.venv/bin/pytest tests/e2e/test_dashboard.py -m e2e --trace off -q -k month`
Expected: 2 FAIL — `aria-pressed` stays `"false"` on `#view-month`.

- [ ] **Step 3: Implement the month view**

In `static/dashboard.js`, replace the whole `loadMeals` function and the `shift` function with the block below (everything between `async function loadMeals()` and the `$('meals-prev')` listener line):

```js
    // ---- meals: month ----
    async function loadMonth() {
        const first = state.month;
        const label = new Intl.DateTimeFormat(undefined, { month: 'long', year: 'numeric' });
        $('meals-label').textContent = label.format(first);
        const start = mondayOf(weekOf(first));
        const last = new Date(first.getFullYear(), first.getMonth() + 1, 0);
        const weeks = [];
        for (let d = start; d <= last; d = addDays(d, 7)) weeks.push(weekOf(d));

        // One failed week must not blank the month: its days simply show no dish.
        const boards = await Promise.allSettled(weeks.map(w => getJSON(`/api/week-board/${w}`)));
        if (boards.every(b => b.status === 'rejected')) {
            failed($('meals-body'), 'Couldn’t load meals.', loadMeals);
            return;
        }
        const planned = boards.flatMap(b => b.status === 'fulfilled' ? (b.value.planned_meals || []) : []);

        const grid = el('div', 'month');
        ['M', 'T', 'W', 'T', 'F', 'S', 'S'].forEach(d => grid.appendChild(el('div', 'dow', d)));
        const spoken = new Intl.DateTimeFormat(undefined, { weekday: 'long', month: 'long', day: 'numeric' });
        for (let i = 0; i < weeks.length * 7; i++) {
            const d = addDays(start, i);
            const date = iso(d);
            const cell = el('button', 'cell');
            cell.type = 'button';
            if (d.getMonth() !== first.getMonth()) cell.classList.add('out');
            if (date === todayISO) cell.classList.add('today');
            cell.appendChild(el('span', 'num', String(d.getDate())));
            const dinners = mealsOn(planned, date).filter(p => p.meal === 'dinner');
            dinners.forEach(p => cell.appendChild(el('span', 'dish', p.bundle_name || p.recipe)));
            cell.setAttribute('aria-label',
                `${spoken.format(d)}: ${dinners.map(p => p.bundle_name || p.recipe).join(', ') || 'open'}`);
            cell.addEventListener('click', () => {
                state.week = weekOf(d);
                window.koDash.week = state.week;
                setView('week');
            });
            grid.appendChild(cell);
        }
        $('meals-body').replaceChildren(grid);
    }

    async function loadMeals() {
        if (state.view === 'month') return loadMonth();
        $('meals-label').textContent = weekLabel(state.week);
        try {
            renderWeek(await getJSON(`/api/week-board/${state.week}`));
        } catch (err) {
            failed($('meals-body'), 'Couldn’t load meals.', loadMeals);
        }
    }

    function setView(view) {
        state.view = view;
        $('view-week').setAttribute('aria-pressed', String(view === 'week'));
        $('view-month').setAttribute('aria-pressed', String(view === 'month'));
        if (view === 'month') {
            const monday = mondayOf(state.week);
            state.month = new Date(monday.getFullYear(), monday.getMonth(), 1);
            loadMeals();  // grocery and inventory do not move
        } else {
            refreshAll();
        }
    }
    $('view-week').addEventListener('click', () => setView('week'));
    $('view-month').addEventListener('click', () => setView('month'));

    function shift(direction) {
        if (state.view === 'month') {
            state.month = new Date(state.month.getFullYear(), state.month.getMonth() + direction, 1);
            loadMeals();
            return;
        }
        state.week = weekOf(addDays(mondayOf(state.week), 7 * direction));
        window.koDash.week = state.week;
        refreshAll();
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `../../.venv/bin/pytest tests/e2e/test_dashboard.py -m e2e --trace off -q`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add static/dashboard.js tests/e2e/test_dashboard.py
git commit -m "feat(home): month view for the meals column

Co-Authored-By: Claude Fable 5.2 <noreply@anthropic.com>"
```

---

### Task 4: To buy column

**Files:**
- Modify: `static/dashboard.js`
- Modify: `tests/e2e/test_dashboard.py`

**Interfaces:**
- Consumes: `state.week`, `el`, `getJSON`, `postJSON`, `failed`, `weekLabel`, `refreshAll`. `GET /api/shopping-list/saved/<week>` → `{week, content_hash, rows: [{id, text, completed, issue}]}` or 404. `POST /api/shopping-list/saved/<week>/completion` with exactly `{row_id, completed, expected_hash, operation_id}` → the same payload shape; 409 when the note changed underneath. `POST /generate-shopping-list` with `{week}`.
- Produces: `loadBuy()`, called from `refreshAll()`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/e2e/test_dashboard.py`:

```python
def test_empty_week_offers_to_build_the_list(live_server, page, page_errors):
    week, wednesday = unique_week(25)
    _cook(live_server, week, wednesday)
    _open(page, live_server, week)
    build = page.locator("#buy-body button.act")
    expect(build).to_have_text("Build this week’s list")
    build.click()
    expect(page.locator("#buy-body .buy-row").first).to_be_visible()
    assert page_errors == []


def test_ticking_an_item_persists_across_reload(live_server, page, page_errors):
    week, wednesday = unique_week(26)
    _cook(live_server, week, wednesday)
    made = requests.post(live_server.url("/generate-shopping-list"), json={"week": week}, timeout=60)
    assert made.status_code == 200, made.text
    _open(page, live_server, week)
    first = page.locator("#buy-body .buy-row").first
    name = first.inner_text().strip()
    first.locator("input").check()
    expect(page.locator("#buy-body .buy-row.done")).to_have_count(1)
    page.reload(wait_until="networkidle")
    done = page.locator("#buy-body .buy-row.done")
    expect(done).to_have_count(1)
    expect(done).to_contain_text(name)
    expect(page.locator("#buy-body .buy-row").last).to_have_class("buy-row done")
    assert page_errors == []
```

- [ ] **Step 2: Run them to verify they fail**

Run: `../../.venv/bin/pytest tests/e2e/test_dashboard.py -m e2e --trace off -q -k "list or ticking"`
Expected: 2 FAIL — `#buy-body button.act` not found.

- [ ] **Step 3: Implement the column**

In `static/dashboard.js`, insert this block immediately above `function refreshAll()`:

```js
    // ---- to buy ----
    // crypto.randomUUID needs a secure context; a plain-HTTP tailnet host is not one.
    function uuid() {
        if (crypto.randomUUID) return crypto.randomUUID();
        const b = crypto.getRandomValues(new Uint8Array(16));
        b[6] = (b[6] & 0x0f) | 0x40;
        b[8] = (b[8] & 0x3f) | 0x80;
        const h = [...b].map(x => x.toString(16).padStart(2, '0')).join('');
        return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
    }

    function renderBuy(list) {
        const body = $('buy-body');
        const left = list.rows.filter(r => !r.completed).length;
        $('buy-label').textContent = `To buy · ${left}`;
        // Unticked first; a ticked item sinks rather than vanishing, so a mis-tap is visible.
        const rows = [...list.rows].sort((a, b) => Number(a.completed) - Number(b.completed));
        const nodes = rows.map(r => {
            const row = el('label', 'buy-row');
            if (r.completed) row.classList.add('done');
            if (r.id) {  // a row without an id predates row identity and cannot be ticked from here
                const box = el('input');
                box.type = 'checkbox';
                box.checked = r.completed;
                box.addEventListener('change', () => tick(list, r, box.checked));
                row.appendChild(box);
            }
            row.appendChild(el('span', null, r.text));
            return row;
        });
        if (!nodes.length) nodes.push(el('p', 'note', 'Nothing to buy this week.'));
        const foot = el('p', 'foot');
        const full = el('a', null, 'Full list');
        full.href = `/current/shopping-list?week=${list.week}`;
        foot.appendChild(full);
        body.replaceChildren(...nodes, foot);
    }

    async function tick(list, row, completed) {
        try {
            renderBuy(await postJSON(`/api/shopping-list/saved/${list.week}/completion`, {
                row_id: row.id, completed, expected_hash: list.content_hash, operation_id: uuid(),
            }));
        } catch (err) {
            await loadBuy();  // the list changed elsewhere, or the write failed: show the truth
            $('buy-body').prepend(el('p', 'note bad',
                err.status === 409 ? 'The list changed somewhere else. Tick it again.'
                                   : 'Couldn’t save that tick. Try again.'));
        }
    }

    async function buildList(week) {
        $('buy-body').replaceChildren(el('p', 'note', 'Building the list…'));
        try {
            await postJSON('/generate-shopping-list', { week });
            await loadBuy();
        } catch (err) {
            failed($('buy-body'), 'Couldn’t build the list.', () => buildList(week));
        }
    }

    async function loadBuy() {
        const week = state.week;
        try {
            renderBuy(await getJSON(`/api/shopping-list/saved/${week}`));
        } catch (err) {
            if (err.status !== 404) {
                failed($('buy-body'), 'Couldn’t load the list.', loadBuy);
                return;
            }
            $('buy-label').textContent = 'To buy';
            const build = el('button', 'act', 'Build this week’s list');
            build.type = 'button';
            build.addEventListener('click', () => buildList(week));
            $('buy-body').replaceChildren(el('p', 'note', 'No list for this week yet.'), build);
        }
    }

```

Then replace `refreshAll` with:

```js
    function refreshAll() {
        loadMeals();
        loadBuy();
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `../../.venv/bin/pytest tests/e2e/test_dashboard.py -m e2e --trace off -q`
Expected: 7 passed. If `test_empty_week_offers_to_build_the_list` fails because `/generate-shopping-list` returns a non-2xx status for a week whose only recipe yields no purchase rows, read the response body in the server log (`live_server.log`) and change the test's recipe to one with purchasable ingredients; do not weaken the assertion.

- [ ] **Step 5: Commit**

```bash
git add static/dashboard.js tests/e2e/test_dashboard.py
git commit -m "feat(home): to-buy column with working checkboxes

Co-Authored-By: Claude Fable 5.2 <noreply@anthropic.com>"
```

---

### Task 5: On hand column

**Files:**
- Modify: `static/dashboard.js`
- Modify: `tests/e2e/test_dashboard.py`

**Interfaces:**
- Consumes: `el`, `getJSON`, `failed`, `todayISO`. `GET /api/inventory` → `[{name, quantity, unit, category, location, source, expires, expiry_status}]` where `expiry_status` is `"expired"`, `"soon"`, `"ok"` or `null`, `location` is one of `fridge`, `freezer`, `pantry`, `counter`, `other`, and a pantry staple has `source == "staple"`.
- Produces: `loadHand()`, called from `refreshAll()`.

- [ ] **Step 1: Write the failing test**

Append to `tests/e2e/test_dashboard.py`. The inventory is stubbed so the test does not depend on what is really in the kitchen:

```python
def _inventory_fixture():
    soon = (date.today() + timedelta(days=2)).isoformat()
    gone = (date.today() - timedelta(days=1)).isoformat()

    def item(name, location, **extra):
        return {"name": name, "quantity": 1.0, "unit": "ct", "category": "other",
                "location": location, "source": "manual", "expires": None,
                "expiry_status": None, **extra}

    return [
        item("spinach", "fridge", expires=soon, expiry_status="soon"),
        item("yogurt", "fridge", expires=gone, expiry_status="expired"),
        item("eggs", "fridge", quantity=12.0),
        item("adobo", "freezer", quantity=2.0, unit="servings"),
        item("rice", "pantry"),
        item("kosher salt", "pantry", source="staple"),
    ]


def test_on_hand_leads_with_what_expires_and_folds_staples(live_server, page, page_errors):
    week, _ = unique_week(27)
    page.route("**/api/inventory", lambda route: route.fulfill(json=_inventory_fixture()))
    _open(page, live_server, week)
    groups = page.locator("#hand-body .grp").all_inner_texts()
    assert [g.lower() for g in groups] == ["use soon", "fridge", "freezer", "pantry"]
    soon = page.locator("#hand-body .grp.soon ~ .item").all_inner_texts()
    assert soon[0].lower().startswith("yogurt") and "expired" in soon[0].lower()
    assert soon[1].lower().startswith("spinach") and "2 days" in soon[1].lower()
    assert page.locator("#hand-body .item", has_text="spinach").count() == 1
    staples = page.locator("#hand-body details.staples")
    expect(staples.locator("summary")).to_have_text("Staples · 1")
    expect(staples.locator(".item")).to_be_hidden()
    expect(page.locator("#hand-body .item", has_text="eggs")).to_contain_text("12")
    assert page_errors == []
```

- [ ] **Step 2: Run it to verify it fails**

Run: `../../.venv/bin/pytest tests/e2e/test_dashboard.py -m e2e --trace off -q -k on_hand`
Expected: FAIL — `groups` is `[]`.

- [ ] **Step 3: Implement the column**

In `static/dashboard.js`, insert this block immediately above `function refreshAll()`:

```js
    // ---- on hand ----
    const PLACES = ['fridge', 'freezer', 'counter', 'pantry', 'other'];

    function amount(item) {
        // A row is a container, not a count: "1 ct" says nothing, so it is not shown.
        if (item.quantity === 1 && ['ct', 'ea', ''].includes(item.unit || '')) return '';
        const n = Number.isInteger(item.quantity) ? String(item.quantity) : item.quantity.toFixed(1);
        return `${n} ${item.unit || ''}`.trim();
    }
    function expiryWord(item) {
        if (item.expiry_status === 'expired') return 'expired';
        const days = Math.round((new Date(`${item.expires}T00:00`) - new Date(`${todayISO}T00:00`)) / 86400000);
        return days <= 0 ? 'today' : days === 1 ? '1 day' : `${days} days`;
    }
    function itemRow(item, note, cls) {
        const row = el('div', 'item');
        row.appendChild(el('span', null, item.name));
        if (note) row.appendChild(el('span', `qty ${cls || ''}`.trim(), note));
        return row;
    }
    const byName = (a, b) => a.name.localeCompare(b.name);

    function renderHand(items) {
        const nodes = [];
        const soon = items.filter(i => i.expiry_status === 'expired' || i.expiry_status === 'soon')
            .sort((a, b) => a.expires.localeCompare(b.expires));
        if (soon.length) {
            nodes.push(el('div', 'grp soon', 'Use soon'));
            soon.forEach(i => nodes.push(itemRow(i, expiryWord(i), i.expiry_status === 'expired' ? 'expired' : '')));
        }
        const rest = items.filter(i => !soon.includes(i));
        const stock = rest.filter(i => i.source !== 'staple');
        PLACES.forEach(place => {
            const here = stock.filter(i => i.location === place).sort(byName);
            if (!here.length) return;
            nodes.push(el('div', 'grp', place));
            here.forEach(i => nodes.push(itemRow(i, amount(i))));
        });
        const staples = rest.filter(i => i.source === 'staple').sort(byName);
        if (staples.length) {
            const fold = el('details', 'staples');
            fold.appendChild(el('summary', null, `Staples · ${staples.length}`));
            staples.forEach(i => fold.appendChild(itemRow(i, amount(i))));
            nodes.push(fold);
        }
        if (!nodes.length) nodes.push(el('p', 'note', 'Nothing in the inventory yet.'));
        const foot = el('p', 'foot');
        const review = el('a', null, 'Review inventory');
        review.href = '/review';
        foot.appendChild(review);
        $('hand-body').replaceChildren(...nodes, foot);
    }

    async function loadHand() {
        try {
            renderHand(await getJSON('/api/inventory'));
        } catch (err) {
            failed($('hand-body'), 'Couldn’t load the inventory.', loadHand);
        }
    }

```

Then replace `refreshAll` with:

```js
    function refreshAll() {
        loadMeals();
        loadBuy();
        loadHand();
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `../../.venv/bin/pytest tests/e2e/test_dashboard.py -m e2e --trace off -q`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add static/dashboard.js tests/e2e/test_dashboard.py
git commit -m "feat(home): on-hand column, expiring first

Co-Authored-By: Claude Fable 5.2 <noreply@anthropic.com>"
```

---

### Task 6: Live refresh, layout guarantees, both themes

**Files:**
- Modify: `static/dashboard.js`
- Modify: `tests/e2e/test_dashboard.py`

**Interfaces:**
- Consumes: `refreshAll()`. `static/command-bar.js` dispatches a cancelable `kitchenos:changed` `CustomEvent` on `document` after a command changes data, and reloads the page unless a listener calls `preventDefault()`.
- Produces: the dashboard refreshes in place after a command and when the tab becomes visible again.

- [ ] **Step 1: Write the failing tests**

Append to `tests/e2e/test_dashboard.py`:

```python
def test_a_command_refreshes_in_place_without_a_reload(live_server, page, page_errors):
    week, wednesday = unique_week(28)
    _open(page, live_server, week)
    page.evaluate("window.__stayed = true")
    _cook(live_server, week, wednesday)
    cancelled = page.evaluate(
        "() => !document.dispatchEvent(new CustomEvent('kitchenos:changed', {cancelable: true}))")
    assert cancelled, "the dashboard must preventDefault so the command bar does not reload the page"
    expect(page.locator(f'.day[data-date="{wednesday}"] details.meal')).to_have_count(1)
    assert page.evaluate("window.__stayed") is True
    assert page_errors == []


def test_landscape_ipad_shows_three_columns_without_page_scroll(live_server, page):
    week, _ = unique_week(29)
    _open(page, live_server, week)
    tops = page.evaluate("() => [...document.querySelectorAll('.col')].map(c => c.getBoundingClientRect().top)")
    assert len(set(round(t) for t in tops)) == 1, "columns are not side by side"
    assert page.evaluate("() => document.documentElement.scrollHeight <= window.innerHeight + 1")
    assert page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth + 1")


@pytest.mark.parametrize("viewport", [{"width": 820, "height": 1180}, {"width": 390, "height": 844}])
def test_narrow_screens_stack_in_reading_order(live_server, page, viewport):
    page.set_viewport_size(viewport)
    page.goto(live_server.url("/"), wait_until="networkidle")
    tops = page.evaluate("() => [...document.querySelectorAll('.col')].map(c => c.getBoundingClientRect().top)")
    assert tops == sorted(tops) and len(set(round(t) for t in tops)) == 3
    assert page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth + 1")


def test_controls_are_thumb_sized(live_server, page):
    week, _ = unique_week(30)
    _open(page, live_server, week)
    heights = page.evaluate(
        "() => [...document.querySelectorAll('.seg button, .menu-btn, .nav-btn')]"
        ".map(b => b.getBoundingClientRect().height)")
    assert heights and min(heights) >= 44


def test_all_pages_popover_opens_and_light_dismisses(live_server, page, page_errors):
    week, _ = unique_week(31)
    _open(page, live_server, week)
    page.locator(".menu-btn").click()
    expect(page.locator("#all-pages")).to_be_visible()
    expect(page.locator('#all-pages a[href="/meal-planner"]')).to_be_visible()
    page.mouse.click(10, 400)
    expect(page.locator("#all-pages")).to_be_hidden()
    assert page_errors == []
```

- [ ] **Step 2: Run them to see which fail**

Run: `../../.venv/bin/pytest tests/e2e/test_dashboard.py -m e2e --trace off -q -k "command or landscape or narrow or thumb or popover"`
Expected: `test_a_command_refreshes_in_place_without_a_reload` FAILS (`cancelled` is false). The other four should already pass from Task 1's CSS; if any fails, fix `static/dashboard.css` (not the test) until it passes, keeping to token variables.

- [ ] **Step 3: Implement live refresh**

In `static/dashboard.js`, replace the final `refreshAll();` call (the last statement before `})();`) with:

```js
    // A command changed something: redraw in place instead of letting the bar reload the page.
    document.addEventListener('kitchenos:changed', event => {
        event.preventDefault();
        refreshAll();
    });

    // Picking the iPad back up should show the truth without a tap. Throttled so
    // flicking between apps does not hammer the server.
    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible' && Date.now() - lastRefresh > 30000) refreshAll();
    });

    refreshAll();
```

Then replace `refreshAll` (written in Task 5) with the version below, which records when it last ran:

```js
    let lastRefresh = 0;
    function refreshAll() {
        lastRefresh = Date.now();
        loadMeals();
        loadBuy();
        loadHand();
    }
```

- [ ] **Step 4: Run the whole dashboard file, the theme test and the surface smoke test**

Run: `../../.venv/bin/pytest tests/e2e/test_dashboard.py tests/e2e/test_dark_mode.py tests/e2e/test_weekly_loop.py tests/e2e/test_command_bar.py tests/e2e/test_prep_page.py -m e2e --trace off -q`
Expected: all pass. `test_dark_mode.py` exercises `/` in both themes through `tests/theme_allowlist.py`; a failure there means a colour is not coming from a token.

- [ ] **Step 5: Run the unit suite**

Run: `../../.venv/bin/pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add static/dashboard.js static/dashboard.css tests/e2e/test_dashboard.py
git commit -m "feat(home): refresh in place after a command and on return

Co-Authored-By: Claude Fable 5.2 <noreply@anthropic.com>"
```

---

### Task 7: Design review pass and ship notes

**Files:**
- Modify: `static/dashboard.css`, `templates/home.html` (only as findings require)
- Modify: `docs/ROADMAP.md`
- Modify: `static/README.md`

**Interfaces:**
- Consumes: the finished page from Tasks 1–6.
- Produces: a reviewed page, screenshots for the PR, and documentation.

- [ ] **Step 1: Capture the page in both themes at three sizes**

Start the server against the main checkout's data on a spare port, from the worktree:

```bash
cd /Users/chaseeasterling/Dev/KitchenOS/.worktrees/ipad-dashboard
KITCHENOS_NO_LLM=1 PORT=5055 ../../.venv/bin/python api_server.py &
```

Then, with Playwright, save six screenshots of `http://127.0.0.1:5055/` to `tmp/dashboard-{ipad,portrait,phone}-{light,dark}.png` at 1180×820, 820×1180 and 390×844, using `color_scheme="light"` and `"dark"` and `device_scale_factor=2`. Stop the server afterwards with `kill %1`.

- [ ] **Step 2: Review against the design skills**

Invoke, in this order, the skills `better-layout`, `better-typography`, `better-colors`, `better-accessibility` and `better-ui` on `templates/home.html`, `static/dashboard.css` and the six screenshots. For each finding of severity HIGH or MEDIUM, fix it in `static/dashboard.css` or `templates/home.html`, staying inside the Global Constraints (tokens only, 44px targets, sentence case). Record LOW findings you decline in the PR description with a one-line reason.

- [ ] **Step 3: Re-run every test touched by this plan**

Run: `../../.venv/bin/pytest -q && ../../.venv/bin/pytest tests/e2e/test_dashboard.py tests/e2e/test_dark_mode.py tests/e2e/test_weekly_loop.py tests/e2e/test_command_bar.py tests/e2e/test_prep_page.py -m e2e --trace off -q`
Expected: all pass.

- [ ] **Step 4: Document it**

In `docs/ROADMAP.md`, add as the first entry under `## Done / Shipped`:

```markdown
**2026-11 — iPad dashboard home.** `/` is now one screen: meals (week or month), the week's
grocery list with working checkboxes, and inventory with what expires first. Everything else
is behind the header's "All pages" popover. The Kitchen Today cards left the home page; their
data is the three columns. **Still open:** the chat bar (Piece 2) and meals on TRMNL (Piece 3)
— see `docs/superpowers/specs/2026-11-15-ipad-dashboard-chat-trmnl-design.md`.
```

In `static/README.md`, add two rows to the Contents table:

```markdown
| `dashboard.css` | — | written here | — |
| `dashboard.js` | — | written here | — |
```

- [ ] **Step 5: Commit**

```bash
git add static/dashboard.css templates/home.html docs/ROADMAP.md static/README.md
git commit -m "docs(home): dashboard ship notes and design-review fixes

Co-Authored-By: Claude Fable 5.2 <noreply@anthropic.com>"
```

- [ ] **Step 6: Stop before deploying**

Do not push, open a PR, or run `scripts/deploy_api.py`. Report the branch name, the test results and the six screenshots to Chase, and wait for a go-ahead. Shipping to the live API follows `docs/OPERATIONS.md` "Reviewed API releases" and needs his approval.
