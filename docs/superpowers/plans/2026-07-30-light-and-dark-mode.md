# Light and Dark Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every KitchenOS web page renders in Ink (dark) or Dawn (light) following the OS setting, by moving all sixteen HTML surfaces onto the shared `static/tokens.css` design language.

**Architecture:** Ten light-only templates and six inline `api_server.py` pages each carry a private palette. Each is converted by deleting its colour `:root`, linking `/static/tokens.css`, and rewriting its literals through a fixed mapping table. A shrinking allowlist in `tests/theme_allowlist.py` drives the work: a static guard test and an e2e dark-mode test both read it, every conversion task removes one entry, and the job is done when the set is empty.

**Tech Stack:** Flask (no Jinja — templates are `open().read()` plus string replacement), vanilla CSS custom properties, `color-mix()`, pytest, Playwright.

**Spec:** [`docs/superpowers/specs/2026-07-30-light-and-dark-mode-design.md`](../specs/2026-07-30-light-and-dark-mode-design.md)

## Global Constraints

- **Mode follows the OS only.** `prefers-color-scheme`. No toggle, no persisted state, no new UI. Nothing sets `data-theme`.
- **`static/tokens.css` is a copy, not a fork.** Never edit its values locally. Changes go upstream to `~/Dev/design-system/tokens.css` and are re-vendored per `static/README.md` (`cp`, `shasum -a 256`, update the version row).
- **Keep layout custom properties.** The rule is "no raw hex", never "no `:root`". `meal_planner.html`'s `--sidebar-width`, `--shelf-h`, `--shelf-collapsed-h` must survive — `initShelf()` writes `--shelf-h` onto `:root` at runtime.
- **Colour and material only.** Do not change layout, spacing, type scale, or markup structure. A page keeps its shape.
- **Restart rule.** Template and `static/*.css` edits are live. Any `api_server.py` edit needs `launchctl unload/load ~/Library/LaunchAgents/com.kitchenos.api.plist` or the server serves stale code.
- **Run Python as `.venv/bin/python`.** Python 3.11.
- **Commit trailer:** every commit ends with `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.

### The mapping table (used by every conversion task)

| Bucket | Found as | Becomes |
|---|---|---|
| page ground | `#f5f5f7` `#f0f0f2` `#f4f4f2` `Canvas` | `var(--bg)` |
| card surface | `#fff` `#ffffff` `#fafafa` `#f9f9fb` `#fafafc` `#f6f6f8` | `var(--surface)` |
| raised surface | `#ebebed` `#f0f0f0` | `var(--raised)` |
| borders | `#e5e5e7` `#e9e9eb` `#e8e8ed` `#d8d8dc` `#ccc` `#ddd` | `var(--line)` |
| text | `#1d1d1f` `#1a1a1a` `CanvasText` | `var(--ink)` |
| muted text | `#86868b` `#6e6e73` `#666` `#555` `#444` `#888` `GrayText` | `var(--muted)` |
| accent | `#0071e3` `#0077ed` `#4a90d9` `#2563eb` `#1d4ed8` | `var(--app-kitchenos)` |
| success | `#34c759` `#3f9e4d` `#1a6b34` `#1a7a37` `#0a0` `#060` | `var(--done)` |
| danger | `#ff3b30` `#c0392b` `#d33` `#b8291f` `#8b1a1a` `#a11` `#c00` | `var(--alert)` |
| warning | `#b7791f` `#ff9f0a` `#ff9500` `#c58a00` `#8a6d00` `#8a5000` `#b8860b` `#e69500` `#c2680a` `#b8650a` `#a15c00` `#f0c274` | `var(--warning)` |
| text on a filled accent/semantic | `#fff` **when it sits on a coloured fill** | `var(--text-on-accent)` |
| tint fill | `#fde8e8` `#fee` → alert · `#d4f5de` `#f1f8f2` `#efe` → done · `#fff3e0` `#fff8e1` `#fff8ec` `#fff7ec` `#ffeed4` `#fff0d6` `#ffe082` → warning · `#e3f2ff` `#f2f7ff` `#eef` → accent | `var(--tint-*)` |
| tint border | the 1px border beside a tint fill | `var(--edge-*)` |
| scrim / neutral alpha | `#0006` `#0003` `#8886` `#8884` `#8883` `#8882` `#fff5` `#fff3` `#222d` | explicit `rgba()`, unchanged colour |

**`#fff` is ambiguous by design** — it is `var(--surface)` when it is a card background and `var(--text-on-accent)` when it is label text on a coloured button. Read each site.

### The head block (added verbatim to every template)

```html
    <meta name="theme-color" content="#f4ede3" media="(prefers-color-scheme: light)">
    <meta name="theme-color" content="#0f1116" media="(prefers-color-scheme: dark)">
    <link rel="stylesheet" href="/static/tokens.css">
    <link rel="stylesheet" href="/static/kitchenos.css">
```

Order matters: `tokens.css` first, `kitchenos.css` second (it derives from the tokens).

---

## File Structure

| File | Responsibility |
|---|---|
| `~/Dev/design-system/tokens.css` | **Modify** — add the `@media print` Dawn block (Task 0) |
| `static/tokens.css` | **Modify** — re-vendored copy, byte-identical to upstream |
| `static/README.md` | **Modify** — refresh the sha256 row |
| `static/kitchenos.css` | **Create** — the eight derived tint/edge variables. Nothing else. |
| `tests/theme_allowlist.py` | **Create** — the single shrinking `UNCONVERTED` set plus `TEMPLATE_ROUTES` |
| `tests/test_theme_tokens.py` | **Create** — static guard, runs in the normal suite |
| `tests/e2e/test_dark_mode.py` | **Create** — Playwright, marked `e2e` |
| `api_server.py` | **Modify** — `_html_page()` helper, six inline pages, `_CLAUDE_BAR_TEMPLATE` |
| `templates/*.html` | **Modify** — ten conversions |

---

## Task 0: Paper always prints Dawn (upstream + re-vendor)

**Files:**
- Modify: `~/Dev/design-system/tokens.css` (append a block)
- Modify: `static/tokens.css` (re-vendored copy)
- Modify: `static/README.md:24` (the `tokens.css` sha256 row)

**Interfaces:**
- Consumes: nothing
- Produces: a `@media print` block guaranteeing Dawn values on paper regardless of OS theme. Every later task depends on this for the two print pages.

- [ ] **Step 1: Append the print block to the upstream file**

Append to the **very end** of `~/Dev/design-system/tokens.css`, after the `.dl-surface` helper. It must be last in the file: media queries add no specificity, so against the equal-specificity `@media (prefers-color-scheme: dark) { :root { … } }` block, source order is what decides.

```css

/* ---- Paper is always Dawn ----
   Print pages set `print-color-adjust: exact`, so an Ink ground would print a
   black page. The selector list matters: a media query adds no specificity, so
   a bare `:root` here would lose to `:root[data-theme="dark"]`. This block must
   stay LAST in the file — against the equal-specificity prefers-color-scheme
   block, source order decides. */
@media print {
  :root, :root[data-theme="dark"], .theme-dark {
    --bg:#f4ede3; --surface:#fffdf9; --raised:#fbf5ec;
    --ink:#2c2733; --muted:#8a7f8e; --line:#ece1d3; --line-soft:#f1e8dc;
    --try:#0d8ea3; --done:#3f8f2f; --warning:#b7791f;
    --alert:#c0392b; --info:#2f7fd1; --insight:#9a4fb5; --next:#b26a2e;
    --app-kitchenos:#d1663b; --app-selene:#8a63d6; --app-lumen:#c0842a;
    --app-journal:#0f9d8c; --app-personal:#d24d78;
    --text-on-accent:#fffdf9;
    /* Material paper supplies or cannot render */
    --dots:none; --grain:none; --shadow:none;
  }
}
```

- [ ] **Step 2: Commit upstream**

```bash
cd ~/Dev/design-system
git add tokens.css
git commit -m "feat: paper always prints Dawn

Print pages set print-color-adjust: exact, so an Ink ground prints a black
page. Pins the light values under @media print for every consumer.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 3: Re-vendor into KitchenOS and capture the new hash**

```bash
cd ~/Dev/KitchenOS
cp ~/Dev/design-system/tokens.css static/tokens.css
shasum -a 256 static/tokens.css
```

Expected: a hash **different** from the `78107b36844d64f4fa5fe3a0c71cfec4fb1a1eddca8effb2acda5880c544d05b` currently in `static/README.md`.

- [ ] **Step 4: Update the vendoring table**

In `static/README.md:24`, replace the old sha256 with the value from Step 3, and change the version cell from ``v1 (`~/Dev/design-system` @ `82d7ad4`)`` to `v1.1` followed by the new upstream short SHA from Step 2.

- [ ] **Step 5: Verify the copy is byte-identical**

```bash
diff ~/Dev/design-system/tokens.css static/tokens.css && echo IDENTICAL
```

Expected: `IDENTICAL`

- [ ] **Step 6: Commit**

```bash
git add static/tokens.css static/README.md
git commit -m "chore: re-vendor tokens.css with the print-Dawn block

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 1: Derived tints and the static guard

**Files:**
- Create: `static/kitchenos.css`
- Create: `tests/theme_allowlist.py`
- Create: `tests/test_theme_tokens.py`

**Interfaces:**
- Consumes: `static/tokens.css` from Task 0
- Produces:
  - CSS variables `--tint-alert`, `--tint-done`, `--tint-warning`, `--tint-accent`, `--edge-alert`, `--edge-done`, `--edge-warning`, `--edge-accent`
  - `tests/theme_allowlist.py` exporting `UNCONVERTED: set[str]` (template filenames), `TEMPLATE_ROUTES: dict[str, str | None]`, and `HEX: re.Pattern`
  - `tests/test_theme_tokens.py` — every later task removes exactly one entry from `UNCONVERTED` and makes this test pass again

- [ ] **Step 1: Create the derived-tint stylesheet**

Create `static/kitchenos.css`:

```css
/* ============================================================
   KitchenOS-local derivations from the design language.
   NOT a component library — these eight variables and nothing else.

   Why here and not in tokens.css: static/README.md declares tokens.css
   "a copy, not a fork", pinned by sha256. Editing it locally is how
   KitchenOS drifts away from Selene and the Obsidian theme.

   --tint-*: the fill of a callout, banner, pill or highlighted cell.
   --edge-*: the 1px border of that same element, a step stronger.

   color-mix resolves against the live --surface/--line, so a tint is a
   pale wash on Dawn and a dark wash on Ink with no second declaration.
   ============================================================ */
:root {
  --tint-alert:   color-mix(in srgb, var(--alert)          14%, var(--surface));
  --tint-done:    color-mix(in srgb, var(--done)           14%, var(--surface));
  --tint-warning: color-mix(in srgb, var(--warning)        16%, var(--surface));
  --tint-accent:  color-mix(in srgb, var(--app-kitchenos)  12%, var(--surface));

  --edge-alert:   color-mix(in srgb, var(--alert)          38%, var(--line));
  --edge-done:    color-mix(in srgb, var(--done)           38%, var(--line));
  --edge-warning: color-mix(in srgb, var(--warning)        38%, var(--line));
  --edge-accent:  color-mix(in srgb, var(--app-kitchenos)  38%, var(--line));
}
```

- [ ] **Step 2: Create the shared allowlist module**

Create `tests/theme_allowlist.py`:

```python
"""The one shrinking list that drives the light/dark conversion.

Two tests read this module: ``tests/test_theme_tokens.py`` (static) and
``tests/e2e/test_dark_mode.py`` (browser). A template in ``UNCONVERTED``
is exempt from both. Every conversion commit removes exactly one entry,
and the work is finished when the set is empty — at which point the
``test_allowlist_is_temporary`` guard below stops being skipped.

Do not add an entry to buy time. The set only ever shrinks.
"""
from __future__ import annotations

import re

# A hex colour literal, and NOT a CSS id selector.
#
# A naive `#[0-9a-fA-F]{3,8}` matches `#add-week-status` (recipe_detail.html)
# and `#add-sub-recipe` (meal_planner.html) as the colour `#add`. A trailing
# \b does not help, because `-` is itself a word boundary — hence the explicit
# "no identifier character follows" lookahead.
#
# The length alternation matters on its own: an unanchored {3,8} accepts 5- and
# 7-digit runs, which is how review.html's invalid `#d3355` reads as a colour.
HEX = re.compile(
    r'#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})(?![0-9a-zA-Z_-])'
)

# `<meta name="theme-color">` cannot hold a var(), so these two literals are
# permanently legal — but only on a theme-color line.
THEME_COLOR_LITERALS = {"#f4ede3", "#0f1116"}

# Surfaces not yet converted. SHRINKS TO EMPTY.
#
# api_server.py is in here for the same reason the templates are: it holds the
# Claude bar and six inline pages, and its two assertions below would otherwise
# sit red from the moment this file lands until Task 4 finishes. One mechanism,
# one finish line.
UNCONVERTED: set[str] = {
    "api_server.py",
    "cook_now.html",
    "plan_week.html",
    "print_week.html",
    "recipe_card.html",
    "review.html",
    "receipt_paste.html",
    "system_health.html",
    "nutrition_review.html",
    "recipe_detail.html",
    "meal_planner.html",
}

# One representative route per template, for the browser test. None means the
# template is not reachable as a standalone page.
#
# The two path-param entries carry a `{recipe}` placeholder that
# tests/e2e/test_dark_mode.py fills from the fixture vault.
TEMPLATE_ROUTES: dict[str, str | None] = {
    "home.html": "/",
    "prep.html": "/prep",
    "recent.html": "/recent",
    "note_view.html": "/current/meal-plan",
    "cook_now.html": "/cook-now",
    "plan_week.html": "/plan-week",
    "print_week.html": "/print/week",
    "recipe_card.html": "/recipe-card/{recipe}",
    "receipt_paste.html": "/receipt-paste",
    "system_health.html": "/system-health",
    "nutrition_review.html": "/nutrition-review",
    "review.html": "/review",
    "recipe_detail.html": "/recipe/{recipe}",
    "meal_planner.html": "/meal-planner",
}
```

- [ ] **Step 3: Write the guard test**

Create `tests/test_theme_tokens.py`:

```python
"""Every page styles through the design language, not through hex literals.

Ten templates each carried a private copy of one palette; they had already
drifted (review.html shipped an invalid five-digit `#d3355` that CSS silently
dropped). This test is what stops that recurring: a page either links
tokens.css and styles through the variables, or the suite says so.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.theme_allowlist import HEX, THEME_COLOR_LITERALS, UNCONVERTED

REPO = Path(__file__).resolve().parents[1]
TEMPLATES = sorted(p for p in (REPO / "templates").glob("*.html"))
TOKENS_LINK = '<link rel="stylesheet" href="/static/tokens.css">'
KITCHENOS_LINK = '<link rel="stylesheet" href="/static/kitchenos.css">'

assert TEMPLATES, "no templates found — check REPO resolution"


def _offending_hexes(text: str) -> list[str]:
    """Hex literals that are neither a theme-color meta value nor an rgba()."""
    bad = []
    for line in text.splitlines():
        if "theme-color" in line:
            # Only the two known Dawn/Ink ground values are legal here.
            for found in HEX.findall(line):
                if found not in THEME_COLOR_LITERALS:
                    bad.append(f"{found} (theme-color line)")
            continue
        bad.extend(HEX.findall(line))
    return bad


@pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: p.name)
def test_template_links_the_design_language(path: Path):
    if path.name in UNCONVERTED:
        pytest.skip(f"{path.name} not yet converted")
    text = path.read_text()
    assert TOKENS_LINK in text, f"{path.name} does not link tokens.css"
    assert KITCHENOS_LINK in text, f"{path.name} does not link kitchenos.css"


@pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: p.name)
def test_template_has_no_raw_hex(path: Path):
    if path.name in UNCONVERTED:
        pytest.skip(f"{path.name} not yet converted")
    offenders = _offending_hexes(path.read_text())
    assert not offenders, (
        f"{path.name} still hardcodes {len(offenders)} colour(s): "
        f"{sorted(set(offenders))}. Style through the tokens — see "
        f"docs/superpowers/specs/2026-07-30-light-and-dark-mode-design.md"
    )


def test_api_server_has_no_raw_hex():
    """api_server.py builds six pages plus the Claude bar as f-strings.

    Scanning the whole file is exact rather than approximate: a Flask server
    has no legitimate non-markup reason to name a colour.
    """
    if "api_server.py" in UNCONVERTED:
        pytest.skip("api_server.py not yet converted")
    offenders = _offending_hexes((REPO / "api_server.py").read_text())
    assert not offenders, (
        f"api_server.py still hardcodes {len(offenders)} colour(s): "
        f"{sorted(set(offenders))}"
    )


def test_every_inline_page_goes_through_the_shared_head():
    """One <!DOCTYPE in api_server.py — the one inside _html_page().

    Six pages were hand-rolled with six different <head> blocks, which is how
    they ended up light-only while the templates moved on.
    """
    if "api_server.py" in UNCONVERTED:
        pytest.skip("api_server.py not yet converted")
    text = (REPO / "api_server.py").read_text()
    assert text.count("<!DOCTYPE") == 1, (
        f"expected exactly 1 <!DOCTYPE in api_server.py, found "
        f"{text.count('<!DOCTYPE')} — build the page through _html_page()"
    )


def test_allowlist_is_temporary():
    """Fails once UNCONVERTED empties, as a prompt to delete the machinery."""
    if UNCONVERTED:
        pytest.skip(f"{len(UNCONVERTED)} template(s) still to convert")
    pytest.fail(
        "UNCONVERTED is empty — the conversion is done. Delete the skip "
        "branches in this file and in tests/e2e/test_dark_mode.py, then "
        "delete UNCONVERTED from tests/theme_allowlist.py."
    )
```

- [ ] **Step 4: Run the guard and confirm it is green with everything allowlisted**

```bash
.venv/bin/python -m pytest tests/test_theme_tokens.py -v
.venv/bin/python -m pytest -q 2>&1 | tail -3
```

Expected: the four already-converted templates PASS both parametrized tests; the ten in `UNCONVERTED` SKIP; both `api_server.py` tests SKIP; `test_allowlist_is_temporary` SKIPs. **The full suite stays green** — every surface is either converted or allowlisted, so this file never lands red.

- [ ] **Step 5: Commit**

```bash
git add static/kitchenos.css tests/theme_allowlist.py tests/test_theme_tokens.py
git commit -m "test: guard that every page styles through the design language

Adds the derived tint/edge variables and the shrinking allowlist that
drives the conversion. Every surface starts allowlisted, so the guard
lands green and goes strict one entry at a time.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: The browser dark-mode test

**Files:**
- Create: `tests/e2e/test_dark_mode.py`

**Interfaces:**
- Consumes: `UNCONVERTED` and `TEMPLATE_ROUTES` from Task 1; the `live_server`, `page` and `page_errors` fixtures from `tests/e2e/conftest.py`
- Produces: proof that a page linking the tokens actually *obeys* them — the failure the static guard structurally cannot see

- [ ] **Step 1: Write the test**

Create `tests/e2e/test_dark_mode.py`:

```python
"""Every page actually renders Ink in dark mode and Dawn in light.

The static guard proves a template links tokens.css and names no hex. It
cannot prove the page obeys them — a body that never sets `background` at
all passes the lint and still renders browser-white. This does the looking.
"""
from __future__ import annotations

import pytest

from tests.theme_allowlist import TEMPLATE_ROUTES, UNCONVERTED

pytestmark = pytest.mark.e2e

# The Dawn and Ink grounds, as the browser reports them.
DAWN = "rgb(244, 237, 227)"
INK = "rgb(15, 17, 22)"

ROUTABLE = [(name, route) for name, route in TEMPLATE_ROUTES.items() if route]


def _a_recipe_name(live_server) -> str:
    """First recipe in the fixture vault — deterministic, no API dependency."""
    names = sorted(p.stem for p in (live_server.vault / "Recipes").glob("*.md"))
    assert names, "fixture vault has no recipes"
    return names[0]


def _resolve(route: str, live_server) -> str:
    return route.replace("{recipe}", _a_recipe_name(live_server))


def _body_background(page) -> str:
    return page.evaluate(
        "getComputedStyle(document.body).backgroundColor"
    )


@pytest.mark.parametrize("name,route", ROUTABLE, ids=[n for n, _ in ROUTABLE])
def test_page_follows_the_os_theme(name, route, live_server, page, page_errors):
    if name in UNCONVERTED:
        pytest.skip(f"{name} not yet converted")
    url = live_server.url(_resolve(route, live_server))

    page.emulate_media(color_scheme="dark")
    page.goto(url, wait_until="domcontentloaded")
    assert _body_background(page) == INK, f"{name} is not Ink in dark mode"

    page.emulate_media(color_scheme="light")
    page.goto(url, wait_until="domcontentloaded")
    assert _body_background(page) == DAWN, f"{name} is not Dawn in light mode"

    assert page_errors == [], f"{name} raised: {page_errors}"


@pytest.mark.parametrize(
    "name,route",
    [("print_week.html", "/print/week"),
     ("recipe_card.html", "/recipe-card/{recipe}")],
)
def test_paper_is_always_dawn(name, route, live_server, page):
    """A dark-mode Mac must still print ink on white.

    print_week.html sets `print-color-adjust: exact`, so an Ink ground here
    does not degrade politely — it prints a black page.
    """
    if name in UNCONVERTED:
        pytest.skip(f"{name} not yet converted")
    page.emulate_media(media="print", color_scheme="dark")
    page.goto(live_server.url(_resolve(route, live_server)),
              wait_until="domcontentloaded")
    assert _body_background(page) == DAWN, (
        f"{name} would print an Ink ground from a dark-mode machine"
    )
```

- [ ] **Step 2: Confirm it is green (four converted pages only)**

```bash
.venv/bin/pytest tests/e2e/test_dark_mode.py -m e2e -v
```

Expected: `/`, `/prep`, `/recent`, `/current/meal-plan` PASS; the other ten SKIP; both paper tests SKIP.

If the four already-converted pages fail here, stop — the expectation constants or the fixture vault are wrong, and every later task would inherit the error.

- [ ] **Step 3: Confirm the default suite is unaffected**

```bash
.venv/bin/pytest -q 2>&1 | tail -5
```

Expected: fully green. The e2e tests are deselected by `addopts = -m "not e2e"`.

- [ ] **Step 4: Commit**

```bash
git add tests/e2e/test_dark_mode.py
git commit -m "test: assert each page renders Ink in dark and Dawn in light

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: The Claude bar

**Files:**
- Modify: `api_server.py:95-112` (`_CLAUDE_BAR_TEMPLATE`)
- Test: `tests/test_claude_bar.py` (existing — must stay green; it asserts injection, not colour)

**Interfaces:**
- Consumes: the tokens from Task 0
- Produces: a theme-following bar. It is injected into **every** page by `_serve_page_with_claude_bar`, so this lands before the page conversions — otherwise each converted page gets a hardcoded dark strip across the top of a Dawn page.

**Why the mapping is what it is:** the bar's `#7c5cff` purple is a *meaning* colour in the design language's semantic lane (`--insight`), not the app accent — using `--app-kitchenos` would put a second coral element in the chrome and blur the accent's identity job.

- [ ] **Step 1: Replace the bar's inline colours**

In `api_server.py`, rewrite `_CLAUDE_BAR_TEMPLATE`'s opening markup. Apply exactly these substitutions inside the `style="..."` attributes, leaving all layout declarations untouched:

| Element | Was | Becomes |
|---|---|---|
| `#ko-claude-bar` | `background:#1a1a2e;color:#e8e8f0` | `background:var(--raised);color:var(--ink);border-bottom:1px solid var(--line)` |
| `#ko-claude-bar` shadow | `box-shadow:0 2px 8px rgba(0,0,0,0.3)` | `box-shadow:var(--shadow)` |
| `#ko-home-link` | `color:#e8e8f0;border:1px solid #44445a` | `color:var(--ink);border:1px solid var(--line)` |
| `#ko-claude-launch` | `background:#7c5cff;color:#fff` | `background:var(--insight);color:var(--text-on-accent)` |
| `#ko-claude-toggle` | `color:#b8b8d0;border:1px solid #44445a` | `color:var(--muted);border:1px solid var(--line)` |
| `#ko-claude-status` | `color:#8a8aa5` | `color:var(--muted)` |
| `#ko-claude-notes` | `background:#0f0f1e;color:#e8e8f0;border:1px solid #44445a` | `background:var(--surface);color:var(--ink);border:1px solid var(--line)` |
| `#ko-claude-save` | `background:#2ecc71;color:#08210f` | `background:var(--done);color:var(--text-on-accent)` |
| `#ko-claude-save-status` | `color:#8a8aa5` | `color:var(--muted)` |

- [ ] **Step 2: Verify no hex survives in the bar**

```bash
.venv/bin/python -c "
import re, pathlib
from tests.theme_allowlist import HEX
src = pathlib.Path('api_server.py').read_text()
start = src.index('_CLAUDE_BAR_TEMPLATE')
end = src.index('def success_page', start) if 'def success_page' in src[start:] else len(src)
print(sorted(set(HEX.findall(src[start:start+4000]))))
"
```

Expected: `[]`

- [ ] **Step 3: Restart the API and confirm the bar still works**

```bash
launchctl unload ~/Library/LaunchAgents/com.kitchenos.api.plist
launchctl load ~/Library/LaunchAgents/com.kitchenos.api.plist
sleep 3 && curl -s http://localhost:5001/health
```

Expected: a healthy JSON response.

- [ ] **Step 4: Run the bar's existing tests**

```bash
.venv/bin/python -m pytest tests/test_claude_bar.py -v
```

Expected: all PASS (this test asserts injection and route coverage, never colour).

- [ ] **Step 5: Commit**

```bash
git add api_server.py
git commit -m "feat: the Claude bar follows the theme

It is injected into every page, so a hardcoded dark bar would sit across
the top of every Dawn page. Purple maps to --insight (a meaning colour),
not to the app accent, which stays coral's alone.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: `_html_page()` and the six inline pages

**Files:**
- Modify: `api_server.py` — `error_page` (~78), `success_page` (~172), the `/refresh-nutrition` success page (~952), `_render_add_to_meal_plan_form` (~1640), `_success_page_for_wikilink` (~1720), `_render_schedule_prompt` (~1754)
- Test: `tests/test_theme_tokens.py` (from Task 1 — two failing assertions go green here)

**Interfaces:**
- Consumes: tokens + `kitchenos.css` from Tasks 0–1
- Produces: `_html_page(title: str, body: str, extra_css: str = "") -> str` — the only place in `api_server.py` that writes `<!DOCTYPE>` or `<head>`

- [ ] **Step 1: Go strict on `api_server.py`, and watch it fail**

Delete `"api_server.py",` from `UNCONVERTED` in `tests/theme_allowlist.py`, then:

```bash
.venv/bin/python -m pytest tests/test_theme_tokens.py -v -k "api_server or shared_head"
```

Expected: both FAIL — `test_api_server_has_no_raw_hex` listing the six pages' literals, and `test_every_inline_page_goes_through_the_shared_head` reporting 6 `<!DOCTYPE` where 1 is required.

The Claude bar's colours (Task 3) are already gone, so anything the first assertion still reports belongs to the six pages.

- [ ] **Step 2: Add the shared page helper**

Insert immediately above `def error_page` in `api_server.py`:

```python
def _html_page(title: str, body: str, extra_css: str = "") -> str:
    """The one <head> for every page api_server builds in Python.

    Six pages used to hand-roll their own, which is how they stayed
    light-only while the templates moved onto the design language. The
    guard in tests/test_theme_tokens.py asserts this is the only
    <!DOCTYPE in the file.
    """
    style = f"<style>{extra_css}</style>" if extra_css else ""
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#f4ede3" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#0f1116" media="(prefers-color-scheme: dark)">
<title>{title}</title>
<link rel="stylesheet" href="/static/tokens.css">
<link rel="stylesheet" href="/static/kitchenos.css">
<style>
  body {{ font-family: var(--font-body); background: var(--bg);
         background-image: var(--dots);
         background-size: var(--dot-size) var(--dot-size);
         color: var(--ink); padding: 2rem 1.5rem; max-width: 600px;
         margin: 0 auto; -webkit-text-size-adjust: 100%; }}
  .card {{ background: var(--surface); background-image: var(--grain);
          border: 1px solid var(--line); border-radius: var(--radius-box);
          padding: 1rem; }}
  .card.ok {{ background: var(--tint-done); border-color: var(--edge-done); }}
  .card.bad {{ background: var(--tint-alert); border-color: var(--edge-alert); }}
  .card.info {{ background: var(--tint-accent); border-color: var(--edge-accent); }}
  .card.warn {{ background: var(--tint-warning); border-color: var(--edge-warning); }}
  .card.ok strong {{ color: var(--done); }}
  .card.bad strong {{ color: var(--alert); }}
  a {{ color: var(--app-kitchenos); }}
  .btn {{ display: inline-block; padding: 12px 20px; border: 1px solid var(--line);
         border-radius: var(--radius-box); text-decoration: none; color: var(--ink); }}
</style>
{style}
</head>
<body>
{body}
</body>
</html>'''
```

- [ ] **Step 3: Rewrite `error_page`**

Replace the whole body of `error_page` (keeping its docstring) with:

```python
    return _html_page("KitchenOS", f'''
<div class="card bad"><strong>Error</strong><br>{escape(message)}</div>
<p><a class="btn" href="obsidian://open?vault={VAULT_NAME}">Return to Obsidian</a></p>
''')
```

- [ ] **Step 4: Rewrite `success_page`**

```python
    return _html_page("KitchenOS", f'''
<div class="card ok"><strong>Success</strong><br>{message}</div>
<p><a class="btn" href="obsidian://open?vault={VAULT_NAME}&file=Recipes/{encoded_filename}">Return to {filename}</a></p>
''')
```

- [ ] **Step 5: Rewrite the `/refresh-nutrition` success page**

Replace the `warnings_html` construction and the returned f-string with:

```python
        warnings_html = ""
        if warnings:
            warnings_list = "".join(f"<li>{w}</li>" for w in warnings)
            warnings_html = (
                f'<div class="card warn" style="margin-top:1rem;">'
                f'<strong>Warnings:</strong><ul>{warnings_list}</ul></div>'
            )

        return _html_page("KitchenOS", f'''
<div class="card ok"><strong>Success</strong><br>Dashboard updated for {week}</div>
{warnings_html}
<p><a href="obsidian://open?vault={VAULT_NAME}&file=Nutrition%20Dashboard">View Dashboard</a></p>
''')
```

- [ ] **Step 6: Rewrite `_success_page_for_wikilink`**

```python
    return _html_page("KitchenOS", f'''
<div class="card ok"><strong>Added!</strong><br>
[[{wikilink_target}]] &rarr; {day} {meal} ({week})</div>
<p><a href="obsidian://open?vault={VAULT_NAME}&file={encoded_file}">View Meal Plan</a></p>
<p><a href="obsidian://open?vault={VAULT_NAME}">Back to Obsidian</a></p>
''')
```

- [ ] **Step 7: Rewrite the "Add to Meal Plan" form page**

Pass its form-specific rules as `extra_css` and drop its `<head>`. **The form markup does not change at all** — keep every `<input>`, `<label>`, `<select>`, `onchange` handler and interpolated value exactly as it is today. Only the wrapper and the style block change: delete everything from `<!DOCTYPE html>` through `</head>` and from `</body></html>` at the end, and hand what remains to `_html_page` as the `body` argument.

```python
    return _html_page("Add to Meal Plan", f'''
<h2>Add to Meal Plan</h2>
<div class="recipe-name">{recipe_display}</div>
{error_html}
<form method="POST" action="/add-to-meal-plan">
    <input type="hidden" name="recipe" value="{recipe_display}">
    ... the existing form markup, verbatim, through its closing </form> ...
''', extra_css='''
    body { max-width: 480px; padding: 1.5rem; }
    h2 { margin-top: 0; }
    .recipe-name { background: var(--raised); padding: 0.75rem;
                   border-radius: var(--radius-box); margin-bottom: 1.5rem;
                   font-weight: 600; }
    .error { background: var(--tint-alert); border: 1px solid var(--edge-alert);
             color: var(--alert); padding: 0.75rem;
             border-radius: var(--radius-box); margin-bottom: 1rem; }
    .branch { display: block; padding: 0.75rem; margin-bottom: 0.5rem;
              border: 1px solid var(--line); border-radius: var(--radius-box);
              cursor: pointer; background: var(--surface); }
    .branch input[type="radio"] { margin-right: 0.5rem; }
    .branch.disabled { opacity: 0.5; cursor: not-allowed; }
    .fields { display: none; margin-top: 1rem; }
    .fields.active { display: block; }
    label { display: block; font-weight: 600; margin-bottom: 0.25rem;
            margin-top: 1rem; }
    select, input[type="text"] { width: 100%; padding: 0.75rem; font-size: 16px;
             border: 1px solid var(--line); border-radius: var(--radius-box);
             background: var(--surface); color: var(--ink);
             -webkit-appearance: none; box-sizing: border-box; }
    button { width: 100%; padding: 1rem; font-size: 18px; font-weight: 600;
             background: var(--app-kitchenos); color: var(--text-on-accent);
             border: none; border-radius: var(--radius-box);
             margin-top: 1.5rem; cursor: pointer; }
    button:active { opacity: 0.85; }
''')
```

The braces in `extra_css` are **not** doubled, because it is a plain string argument rather than part of the f-string. The braces inside the `body` f-string still are.

- [ ] **Step 8: Rewrite the "Schedule Meal" page**

Same shape as Step 6 — the form markup carries over verbatim, only the wrapper and styles change:

```python
    return _html_page("Schedule Meal", f'''
<div class="card ok"><strong>&#10003;</strong> {banner}</div>
{info_html}
<h3>Schedule it now? <span style="font-weight:400;color:var(--muted);">(optional)</span></h3>
<form method="POST" action="/add-to-meal-plan">
    <input type="hidden" name="recipe" value="{recipe}">
    <input type="hidden" name="mode" value="schedule_meal">
    ... the existing form markup, verbatim, through its closing </form> ...
''', extra_css='''
    body { max-width: 480px; padding: 1.5rem; }
    .info { background: var(--tint-accent); border: 1px solid var(--edge-accent);
            color: var(--app-kitchenos); padding: 0.5rem 0.75rem;
            border-radius: var(--radius-box); margin-bottom: 1rem;
            font-size: 14px; }
    h3 { margin-top: 0.5rem; }
    label { display: block; font-weight: 600; margin-bottom: 0.25rem;
            margin-top: 1rem; }
    select { width: 100%; padding: 0.75rem; font-size: 16px;
             border: 1px solid var(--line); border-radius: var(--radius-box);
             background: var(--surface); color: var(--ink);
             -webkit-appearance: none; }
    button { width: 100%; padding: 1rem; font-size: 18px; font-weight: 600;
             background: var(--app-kitchenos); color: var(--text-on-accent);
             border: none; border-radius: var(--radius-box);
             margin-top: 1.5rem; cursor: pointer; }
    .skip { display: block; text-align: center; margin-top: 1rem;
            color: var(--muted); }
''')
```

The `.ok` class now comes from `_html_page`, so the page-local `.ok` rule is deleted rather than rewritten.

- [ ] **Step 9: Run the guard — the two red assertions go green**

```bash
.venv/bin/python -m pytest tests/test_theme_tokens.py -v
```

Expected: `test_api_server_has_no_raw_hex` PASS and `test_every_inline_page_goes_through_the_shared_head` PASS — both red since Step 1.

- [ ] **Step 10: Restart and smoke-test each rewritten page**

```bash
launchctl unload ~/Library/LaunchAgents/com.kitchenos.api.plist
launchctl load ~/Library/LaunchAgents/com.kitchenos.api.plist
sleep 3
curl -s "http://localhost:5001/refresh-nutrition" | head -3
curl -s "http://localhost:5001/add-to-meal-plan?recipe=Butter%20Biscuits" | head -3
```

Expected: both return the new `<!DOCTYPE html>` / `<html lang="en">` head, not the old bare one.

- [ ] **Step 11: Run the full unit suite**

```bash
.venv/bin/python -m pytest -q 2>&1 | tail -5
```

Expected: all green. `tests/test_api_endpoints.py` and `tests/test_api_server.py` exercise several of these pages — if one asserts on old markup, update the assertion to the new class-based structure, not the other way round.

- [ ] **Step 12: Commit**

```bash
git add api_server.py tests/theme_allowlist.py
git commit -m "feat: build every inline page through one themed head

Six hand-rolled <head> blocks were how these pages stayed light-only
while the templates moved on. _html_page() is now the only <!DOCTYPE
in the file, and the guard asserts it.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: `cook_now.html` and `plan_week.html`

**Files:**
- Modify: `templates/cook_now.html:1-33`
- Modify: `templates/plan_week.html:1-54`
- Modify: `tests/theme_allowlist.py` (remove two entries)

**Interfaces:**
- Consumes: the head block and mapping table from Global Constraints
- Produces: nothing later tasks depend on

These are the two cheapest conversions. `cook_now.html` has **zero** hex literals — it already runs on `color-scheme: light dark` and inherited colours, so it needs only the head block and the material. `plan_week.html` has four.

- [ ] **Step 1: Remove both from the allowlist (the failing test)**

In `tests/theme_allowlist.py`, delete the `"cook_now.html",` and `"plan_week.html",` lines from `UNCONVERTED`.

- [ ] **Step 2: Run the guard and watch it fail**

```bash
.venv/bin/python -m pytest tests/test_theme_tokens.py -v -k "cook_now or plan_week"
```

Expected: FAIL — `cook_now.html does not link tokens.css`, and `plan_week.html still hardcodes 4 colour(s): ['#3f9e4d', '#c58a00', '#fff']`.

- [ ] **Step 3: Convert `cook_now.html`**

Replace lines 6–8 (`<title>` through the `:root` line) with:

```html
<title>Cook Now — KitchenOS</title>
<meta name="theme-color" content="#f4ede3" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#0f1116" media="(prefers-color-scheme: dark)">
<link rel="stylesheet" href="/static/tokens.css">
<link rel="stylesheet" href="/static/kitchenos.css">
<style>
```

Then replace the `body` rule and the three colour-bearing rules:

```css
  body { font-family: var(--font-body); background: var(--bg);
         background-image: var(--dots);
         background-size: var(--dot-size) var(--dot-size);
         color: var(--ink);
         margin: 0; padding: 1rem; max-width: 900px; margin-inline: auto; }
  .chip { border: 1px solid var(--line); border-radius: 999px;
          padding: .35rem .8rem; font-size: .9rem; cursor: pointer;
          background: var(--surface); color: var(--muted); }
  .chip[aria-pressed="true"] { color: var(--app-kitchenos);
          border-color: var(--app-kitchenos); font-weight: 600; }
  .recipe { display: block; padding: .7rem 0; min-height: 44px;
            border-bottom: 1px solid var(--line);
            color: inherit; text-decoration: none; }
```

Leave `#cook-now-chips`, `#hidden-note`, `.recipe-head`, `.name`, `.cov`, `.chev`, `.missing`, `.group-tag`, `.recipe:active` and the `@media (hover: hover)` rule untouched — they carry no colour.

Note the chip change: the original signalled "off" with `opacity: .45` on `currentColor`. Chips now signal off as muted and on as accent, which reads correctly on both grounds where a blanket opacity did not.

- [ ] **Step 4: Convert `plan_week.html`**

Replace line 8's `:root` and the body rule:

```css
        :root { --accent: var(--app-kitchenos); }
        * { box-sizing: border-box; }
        body {
            font-family: var(--font-body);
            margin: 0; padding: 20px;
            background: var(--bg);
            background-image: var(--dots);
            background-size: var(--dot-size) var(--dot-size);
            color: var(--ink);
        }
```

Then the three remaining sites:

- line 20 `.targets { color: GrayText; … }` → `color: var(--muted);`
- lines 27 and 31, `color: #c58a00` → `color: var(--warning);`
- line 44, `color: #fff` (a label on a filled accent chip) → `color: var(--text-on-accent);`

Add the head block after the `<title>` on line 6.

- [ ] **Step 5: Run the guard and the browser test**

```bash
.venv/bin/python -m pytest tests/test_theme_tokens.py -v -k "cook_now or plan_week"
.venv/bin/pytest tests/e2e/test_dark_mode.py -m e2e -v -k "cook_now or plan_week"
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add templates/cook_now.html templates/plan_week.html tests/theme_allowlist.py
git commit -m "feat: cook-now and plan-week follow the theme

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: The paper pair — `print_week.html` and `recipe_card.html`

**Files:**
- Modify: `templates/print_week.html`
- Modify: `templates/recipe_card.html`
- Modify: `tests/theme_allowlist.py` (remove two entries)

**Interfaces:**
- Consumes: the `@media print` block from Task 0 — without it these two pages print a black page from a dark-mode Mac
- Produces: the first exercise of `test_paper_is_always_dawn`

- [ ] **Step 1: Remove both from the allowlist**

Delete `"print_week.html",` and `"recipe_card.html",` from `UNCONVERTED`.

- [ ] **Step 2: Watch both fail**

```bash
.venv/bin/python -m pytest tests/test_theme_tokens.py -v -k "print_week or recipe_card"
```

Expected: FAIL, listing `#3f9e4d` `#b8860b` `#8a6d00` `#ffe082` for `print_week.html` and `#3f9e4d` `#1a1a1a` `#f4f4f2` `#fff` `#555` `#8a6d00` `#fff8e1` `#ffe082` `#f1f8f2` for `recipe_card.html`.

- [ ] **Step 3: Convert `print_week.html`**

Add the head block after line 6's `<title>`, then:

```css
        :root { --rule: var(--done); }
        * { box-sizing: border-box; }
        body {
            font-family: var(--font-body);
            margin: 0; padding: 20px;
            background: var(--bg); color: var(--ink);
            -webkit-print-color-adjust: exact; print-color-adjust: exact;
        }
```

**The rename is not optional.** `--line` is a token name, so this page's local `--line: #3f9e4d` was *overriding* the design language's border colour for everything on the page. Rename it to `--rule` and update all six use sites — `.toolbar button` (border and color, line 19), `h2` (line 22), `table.week-grid th, td` (line 27), `.week-grid a` (line 32), and the `color-mix` on line 29.

Then:

- line 23 `.targets { color: GrayText; }` → `var(--muted)`
- lines 33–34 `.mult` / `.empty { color: GrayText; }` → `var(--muted)`
- line 35 `.warn { color: #b8860b; }` → `var(--warning)`
- lines 36–37 `.warnings` → `color: var(--warning); background: var(--tint-warning); border: 1px solid var(--edge-warning);`
- line 29 `background: color-mix(in srgb, var(--line) 14%, Canvas)` → `color-mix(in srgb, var(--rule) 14%, var(--surface))`
- line 40 `.checklist .meta { color: GrayText; }` → `var(--muted)`

Leave the whole `@media print` block's layout rules alone — Task 0 handles the colours.

- [ ] **Step 4: Convert `recipe_card.html`**

Add the head block after line 6's `<title>`. The local `--ink: #1a1a1a` **must go** — `--ink` is a token name and the local declaration was overriding the design language's text colour:

```css
        :root { --grid-line: var(--done); }
        * { box-sizing: border-box; }
        body {
            font-family: var(--font-body);
            color: var(--ink);
            background: var(--bg);
            background-image: var(--dots);
            background-size: var(--dot-size) var(--dot-size);
            margin: 0;
            padding: 24px;
        }
```

Then:

- line 20 `.card { background: #fff; }` → `background: var(--surface); background-image: var(--grain);`
- line 27 `.card-meta { color: #555; }` → `var(--muted)`
- lines 29–33 `.review-note` → `color: var(--warning); background: var(--tint-warning); border: 1px solid var(--edge-warning);`
- line 43 `td.action.finish { background: #f1f8f2; }` → `var(--tint-done)`
- line 53 `.toolbar button { background: #fff; }` → `var(--surface)`
- line 57 `@media print { body { background: #fff; } }` → `background: var(--surface);`

- [ ] **Step 5: Verify both the screen and the paper behaviour**

```bash
.venv/bin/python -m pytest tests/test_theme_tokens.py -v -k "print_week or recipe_card"
.venv/bin/pytest tests/e2e/test_dark_mode.py -m e2e -v
```

Expected: all PASS, including both `test_paper_is_always_dawn` cases, which run for the first time here.

- [ ] **Step 6: Look at an actual print preview**

Set macOS to dark mode, open `http://localhost:5001/print/week` in Safari, and press ⌘P.

Expected: the preview is dark-grey text on white paper. If it is white-on-black, Task 0's block is not last in `static/tokens.css`.

- [ ] **Step 7: Commit**

```bash
git add templates/print_week.html templates/recipe_card.html tests/theme_allowlist.py
git commit -m "feat: the print pages follow the theme on screen, Dawn on paper

Both declared local --line / --ink, which are token names — the locals
were silently overriding the design language for the whole page.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: `review.html`

**Files:**
- Modify: `templates/review.html`
- Modify: `tests/theme_allowlist.py` (remove one entry)

**Interfaces:**
- Consumes: the scrim rule and tint variables
- Produces: nothing later tasks depend on

This page is mostly neutral alphas (`#8886` family) rather than named colours, so it is the one conversion where most literals **keep their colour** and only change spelling. It also carries the invalid-CSS bug.

- [ ] **Step 1: Remove from the allowlist and watch it fail**

Delete `"review.html",` from `UNCONVERTED`, then:

```bash
.venv/bin/python -m pytest tests/test_theme_tokens.py -v -k review
```

Expected: FAIL listing 24 literals including the invalid `#d3355`.

- [ ] **Step 2: Add the head block and convert the ground**

After line 6's `<title>`, add the head block. Then:

```css
  :root { }
  * { box-sizing: border-box; }
  body { margin: 0; font: 16px/1.4 var(--font-body);
         background: var(--bg);
         background-image: var(--dots);
         background-size: var(--dot-size) var(--dot-size);
         color: var(--ink); padding: env(safe-area-inset-top) 0 4rem; }
  header { position: sticky; top: 0; background: var(--surface); padding: 12px 16px;
           display: flex; align-items: center; gap: 12px;
           border-bottom: 1px solid var(--line); }
```

Delete the now-empty `:root { }` line entirely — this page has no layout variables to keep.

- [ ] **Step 3: Convert the borders and neutral fills**

| Line | Was | Becomes |
|---|---|---|
| 15 | `border: 1px solid #8886` | `border: 1px solid var(--line)` |
| 16 | `background: #8882` | `background: var(--raised)` |
| 17 | `button:active { background: #8884 }` | `background: var(--line)` |
| 21 | `border-bottom: 1px solid #8883` | `border-bottom: 1px solid var(--line-soft)` |
| 32 | `background: Canvas; color: CanvasText; border: 1px solid #8886` | `background: var(--surface); color: var(--ink); border: 1px solid var(--line)` |
| 38 | `#menu .mi:active/:hover { background: #8882 }` | `background: var(--raised)` |
| 40 | `#menu hr { border-top: 1px solid #8883 }` | `border-top: 1px solid var(--line-soft)` |
| 46 | `border: 1px solid #8886; background: Canvas` | `border: 1px solid var(--line); background: var(--surface)` |
| 59 | `background: Canvas; border-top: 1px solid #8886` | `background: var(--surface); border-top: 1px solid var(--line)` |

- [ ] **Step 4: Convert the semantic colours, fixing the invalid literal**

| Line | Was | Becomes |
|---|---|---|
| 26 | `.badge-expired { color: #d33 }` | `color: var(--alert)` |
| 26 | `.badge-soon { color: #e69500 }` | `color: var(--warning)` |
| 29 | `.rm { color: #d33; border-color: #d3355; }` | `color: var(--alert); border-color: var(--edge-alert);` |
| 39 | `#menu .mi.danger { color: #d33 }` | `color: var(--alert)` |
| 47 | `.err { color: #d33 }` | `color: var(--alert)` |
| 55 | `accent-color: #4a90d9` | `accent-color: var(--app-kitchenos)` |
| 65 | `@keyframes moved { from { background: #4a90d955 } }` | `from { background: color-mix(in srgb, var(--app-kitchenos) 33%, transparent); }` |

`#d3355` is five hex digits — not valid CSS, so the declaration was dropped and `.rm` fell back to `currentColor`. `var(--edge-alert)` is what it was reaching for.

- [ ] **Step 5: Convert the scrims — same colour, non-hex spelling**

These are deliberately theme-neutral. A black 40% scrim is correct on both grounds; `var(--ink)` would make the Ink backdrop white.

| Line | Was | Becomes |
|---|---|---|
| 33 | `box-shadow: 0 8px 24px #0006` | `box-shadow: 0 8px 24px rgba(0,0,0,.4)` |
| 60 | `box-shadow: 0 -4px 16px #0003` | `box-shadow: 0 -4px 16px rgba(0,0,0,.2)` |
| 49 | `#toast { background: #222d; color: #fff; }` | `background: rgba(34,34,34,.87); color: rgba(255,255,255,1);` |
| 52 | `#toast button { background: #fff3; color: #fff; border-color: #fff5; }` | `background: rgba(255,255,255,.2); color: rgba(255,255,255,1); border-color: rgba(255,255,255,.33);` |

The toast stays a near-black slab in both themes on purpose — it is a transient overlay, legible on either ground, and flipping it to `--surface` would make it vanish into a Dawn page.

- [ ] **Step 6: Verify**

```bash
.venv/bin/python -m pytest tests/test_theme_tokens.py -v -k review
.venv/bin/pytest tests/e2e/test_dark_mode.py -m e2e -v -k review
.venv/bin/pytest tests/e2e/test_location_visibility.py tests/e2e/test_bulk_inventory.py -m e2e -q
```

Expected: all PASS. The last command matters — two existing e2e suites drive this page's menus and toasts.

- [ ] **Step 7: Commit**

```bash
git add templates/review.html tests/theme_allowlist.py
git commit -m "feat: inventory review follows the theme

Also fixes border-color: #d3355 — five hex digits, invalid CSS, silently
dropped, so .rm had been falling back to currentColor.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: The four shared-palette pages

**Files:**
- Modify: `templates/receipt_paste.html`, `templates/system_health.html`, `templates/nutrition_review.html`, `templates/recipe_detail.html`
- Modify: `tests/theme_allowlist.py` (remove four entries, one per commit)

**Interfaces:**
- Consumes: the tint variables from Task 1
- Produces: the alias-block pattern that Task 10 reuses for `meal_planner.html`

All four open with a **byte-identical** nine-variable `:root`. Convert it once and reuse. Each file gets its own commit so a single page can be reverted.

**The alias block** — replaces that `:root` in all four:

```css
        :root {
            /* Local names aliased onto the design language. --bg and --warning
               are token names already, so they are simply not redeclared —
               redeclaring them here would override the tokens for the page. */
            --card-bg:    var(--surface);
            --border:     var(--line);
            --text:       var(--ink);
            --text-muted: var(--muted);
            --accent:     var(--app-kitchenos);
            --success:    var(--done);
            --danger:     var(--alert);
        }
```

Every `var(--bg)` and `var(--warning)` use site in these files then resolves to the token with no edit at all. Aliasing rather than renaming keeps the diff to the top of each file.

- [ ] **Step 1: `receipt_paste.html`**

Remove `"receipt_paste.html",` from `UNCONVERTED`. Confirm the failure:

```bash
.venv/bin/python -m pytest tests/test_theme_tokens.py -v -k receipt_paste
```

Add the head block after the `<title>`, swap in the alias block, then the nine remaining sites:

| Line | Was | Becomes |
|---|---|---|
| 22 | `body { background: var(--bg); … }` | add `background-image: var(--dots); background-size: var(--dot-size) var(--dot-size);` |
| 44 | `background: var(--accent); color: #fff` | `color: var(--text-on-accent)` |
| 46 | `button.secondary { background: #e8e8ed }` | `background: var(--raised)` |
| 53 | `background: #fafafa` | `background: var(--surface)` |
| 57 | `background: #fafafa` | `background: var(--surface)` |
| 67 | `.banner.ok { background: rgba(52,199,89,.12); color: #1a7a37 }` | `background: var(--tint-done); color: var(--done)` |
| 68 | `.banner.warn { background: rgba(255,159,10,.14); color: #a15c00 }` | `background: var(--tint-warning); color: var(--warning)` |
| 69 | `.banner.dup { background: rgba(255,59,48,.10); color: #a11 }` | `background: var(--tint-alert); color: var(--alert)` |
| 73 | `background: #1d1d1f; color: #fff` | `background: rgba(29,29,31,.92); color: rgba(255,255,255,1)` — a transient toast, same reasoning as `review.html` |

The three `rgba()` banner fills were hardcoded against the *light* semantic hexes, which is why they must become `--tint-*` rather than being left alone as scrims.

Verify and commit:

```bash
.venv/bin/python -m pytest tests/test_theme_tokens.py -v -k receipt_paste
.venv/bin/pytest tests/e2e/test_dark_mode.py -m e2e -v -k receipt_paste
.venv/bin/python -m pytest tests/test_api_receipt_paste.py -q
git add templates/receipt_paste.html tests/theme_allowlist.py
git commit -m "feat: receipt paste follows the theme

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 2: `system_health.html`**

Remove from `UNCONVERTED`, add the head block, swap in the alias block, then:

| Line | Was | Becomes |
|---|---|---|
| 92 | `.chip.green { background: #d4f5de; color: #1a6b34 }` | `background: var(--tint-done); color: var(--done)` |
| 94 | `.chip.red { background: #fde8e8; color: #8b1a1a }` | `background: var(--tint-alert); color: var(--alert)` |
| 96 | `.chip.neutral { background: #ebebed; color: #444 }` | `background: var(--raised); color: var(--muted)` |
| 129–130 | `background: #ebebed; color: #555` | `background: var(--raised); color: var(--muted)` |
| 133 | `.badge.red { background: #fde8e8; color: #c0392b }` | `background: var(--tint-alert); color: var(--alert)` |
| 134 | `.badge.green { background: #d4f5de; color: #1a6b34 }` | `background: var(--tint-done); color: var(--done)` |
| 135 | `.badge.orange { background: #fff0d6; color: #8a5000 }` | `background: var(--tint-warning); color: var(--warning)` |

Add the dot grid to `body` as in Step 1. Verify and commit:

```bash
.venv/bin/python -m pytest tests/test_theme_tokens.py -v -k system_health
.venv/bin/pytest tests/e2e/test_dark_mode.py -m e2e -v -k system_health
git add templates/system_health.html tests/theme_allowlist.py
git commit -m "feat: system health follows the theme

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 3: `nutrition_review.html`**

Remove from `UNCONVERTED`, add the head block and alias block, then:

| Line | Was | Becomes |
|---|---|---|
| 75, 212 | `color: #fff` (on a filled accent button) | `var(--text-on-accent)` |
| 78 | `button.primary:hover { color: #fff }` | `var(--text-on-accent)` |
| 109 | `tr.recipe-row:hover { background: #f9f9fb }` | `var(--raised)` |
| 110 | `tr.recipe-row.expanded { background: #f2f7ff }` | `var(--tint-accent)` |
| 118, 143 | `background: #ebebed` | `var(--raised)` |
| 144 | `color: #555` | `var(--muted)` |
| 147 | `.badge.red { background: #fde8e8; color: #c0392b }` | `background: var(--tint-alert); color: var(--alert)` |
| 148 | `.badge.green { background: #d4f5de; color: #1a6b34 }` | `background: var(--tint-done); color: var(--done)` |
| 149 | `.badge.orange { background: #fff0d6; color: #8a5000 }` | `background: var(--tint-warning); color: var(--warning)` |
| 153 | `background: #fafafc` | `var(--surface)` |
| 177–178 | `background: #fff0d6; color: #8a5000` | `background: var(--tint-warning); color: var(--warning)` |
| 184 | `td.weak-row { background: #fff8ec }` | `var(--tint-warning)` |
| 192 | `background: #fff` | `var(--surface)` |

Verify and commit:

```bash
.venv/bin/python -m pytest tests/test_theme_tokens.py -v -k nutrition_review
.venv/bin/pytest tests/e2e/test_dark_mode.py -m e2e -v -k nutrition_review
git add templates/nutrition_review.html tests/theme_allowlist.py
git commit -m "feat: nutrition review follows the theme

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 4: `recipe_detail.html`**

Remove from `UNCONVERTED`, add the head block and alias block, then:

| Line | Was | Becomes |
|---|---|---|
| 75, 78 | `color: #fff` (on a filled accent button) | `var(--text-on-accent)` |
| 150 | `.basis { color: #666 }` | `var(--muted)` |
| 151–152 | `.basis-warn` / `.warn-line { color: #b7791f }` | `var(--warning)` |
| 160 | `border: 1px solid #ccc` | `1px solid var(--line)` |
| 164 | `background: #0071e3; color: #fff` | `background: var(--app-kitchenos); color: var(--text-on-accent)` |
| 167 | `.servings-form .bad { color: #c0392b }` | `var(--alert)` |
| 174 | `background: #fff3e0` | `var(--tint-warning)` |

Watch for the `#add-week-status` selector on line 181 — it is an id, not a colour, and must not be touched.

Verify and commit:

```bash
.venv/bin/python -m pytest tests/test_theme_tokens.py -v -k recipe_detail
.venv/bin/pytest tests/e2e/test_dark_mode.py -m e2e -v -k recipe_detail
git add templates/recipe_detail.html tests/theme_allowlist.py
git commit -m "feat: recipe detail follows the theme

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: Ship PR 1

**Files:**
- Modify: `docs/superpowers/specs/2026-07-30-light-and-dark-mode-design.md` (status + the corrected `api_server.py` claim)

- [ ] **Step 1: Correct the spec's inaccurate claim**

The spec says all 54 of `api_server.py`'s hex literals sit inside the six page f-strings. About 18 of them were in `_CLAUDE_BAR_TEMPLATE`, which is injected into every page rather than being a page. Reword that sentence to name the bar, and add the bar to the spec's surface count (sixteen surfaces plus the shared bar).

- [ ] **Step 2: Run everything**

```bash
.venv/bin/python -m pytest -q 2>&1 | tail -5
.venv/bin/pytest tests/e2e -m e2e -q 2>&1 | tail -5
.venv/bin/ruff check . 2>&1 | tail -3
```

Expected: unit suite fully green; e2e green with `meal_planner.html` the only skip; ruff no worse than `main`.

- [ ] **Step 3: Check both modes on the phone over the tailnet**

```bash
tailscale ip -4
```

Open `http://<that-ip>:5001/` on the phone, walk `/cook-now`, `/review`, `/system-health`, `/receipt-paste`, `/nutrition-review`, and flip iOS between light and dark appearance.

Expected: no white flash between pages, the Claude bar matches its page, no unreadable text.

- [ ] **Step 4: Commit and open the PR**

```bash
git add docs/superpowers/specs/2026-07-30-light-and-dark-mode-design.md
git commit -m "docs: correct the api_server hex accounting

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
git push -u origin HEAD
gh pr create --title "Light and dark mode on every page except the planner" --body "$(cat <<'EOF'
Converts nine templates, the six inline `api_server.py` pages and the shared
Claude bar onto `static/tokens.css`, so every page follows the OS theme.

`meal_planner.html` is deliberately excluded and stays on the guard's
allowlist — it is 4805 lines and the page in daily use, so it gets its own
reviewable, revertable PR.

## What changed
- `static/kitchenos.css` — eight derived tint/edge variables via `color-mix`
- `_html_page()` — one `<head>` replacing six hand-rolled ones
- The Claude bar follows the theme instead of being hardcoded dark
- Paper always prints Dawn (upstream `@media print` block, re-vendored)

## Fixed in passing
`review.html` shipped `border-color: #d3355` — five hex digits, invalid CSS,
silently dropped, so `.rm` had been falling back to `currentColor`.

## Verification
- `tests/test_theme_tokens.py` — links + no raw hex, allowlist-driven
- `tests/e2e/test_dark_mode.py` — every registry route in both schemes, plus
  print emulation from a dark-mode machine
- Checked on the phone over the tailnet in both appearances

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01Pd5JGPEqppDFTvwBo1yb2Y
EOF
)"
```

---

## Task 10: `meal_planner.html` (PR 2)

**Files:**
- Modify: `templates/meal_planner.html`
- Modify: `tests/theme_allowlist.py` (remove the last entry)

**Interfaces:**
- Consumes: the alias-block pattern from Task 8
- Produces: an empty `UNCONVERTED`, which flips `test_allowlist_is_temporary` from skip to fail — that failure is the prompt for Task 11

Branch this off `main` **after PR 1 merges**, so the guard and the tint variables are already there.

- [ ] **Step 1: Branch and remove the last allowlist entry**

```bash
git checkout main && git pull
git checkout -b feat/planner-dark-mode
```

Delete `"meal_planner.html",` from `UNCONVERTED` — leaving the set empty.

- [ ] **Step 2: Watch it fail with the full inventory**

```bash
.venv/bin/python -m pytest tests/test_theme_tokens.py -v -k meal_planner
```

Expected: FAIL listing 74 literals. Copy that list — it is the task's checklist.

- [ ] **Step 3: Add the head block and convert the `:root`**

Add the head block after the `<title>`. Then replace lines 22–46's colour declarations with the alias block, **keeping every layout variable and its comment**:

```css
        :root {
            /* Local names aliased onto the design language. --bg is a token
               name already and is deliberately not redeclared. */
            --card-bg:      var(--surface);
            --border:       var(--line);
            --text:         var(--ink);
            --text-muted:   var(--muted);
            --accent:       var(--app-kitchenos);
            --accent-hover: color-mix(in srgb, var(--app-kitchenos) 82%, var(--ink));
            --success:      var(--done);
            --danger:       var(--alert);
            --drop-zone:    var(--raised);

            /* Height of the bottom library shelf below 1080px. Overwritten on
               :root by initShelf() from localStorage, so CSS that has to clear
               the shelf (.panel-dock) can read the live value.
               44dvh is the largest default that still leaves the compressed
               28-slot week fitting above it without scrolling on iPad Air/Pro
               portrait (820x1180 and 834x1194) — measured across sizes, not
               guessed, and pinned by test_planner_touch.py. 48dvh overflows
               820x1180 by 7px. A 768x1024 iPad mini/classic overflows at any
               shelf height once a slot holds a photo card, so it scrolls; the
               shelf is proportional so it degrades rather than breaking. */
            --shelf-h: 44dvh;
            --shelf-collapsed-h: 52px;
        }
```

Deleting `--shelf-h` or `--shelf-collapsed-h` breaks `initShelf()` and `.panel-dock` silently — the shelf renders at the wrong height with no error.

- [ ] **Step 4: Add the material to `body`**

```css
        body {
            font-family: var(--font-body);
            background: var(--bg);
            background-image: var(--dots);
            background-size: var(--dot-size) var(--dot-size);
            /* …every other existing declaration unchanged… */
        }
```

- [ ] **Step 5: Sweep the remaining literals**

Work down the Step 2 list applying the Global Constraints mapping table. Watch for three page-specific traps:

- `#add-sub-recipe` on line 1735 is an **id selector**, not the colour `#add`. Do not touch it.
- `#fff` appears both as a card background (`var(--surface)`) and as label text on filled accent buttons and drag chips (`var(--text-on-accent)`). Read each site.
- Drag/drop states (`--drop-zone`, hover highlights) were tuned against a near-white ground. After conversion, drag a recipe onto a slot in both themes and confirm the target is still obviously distinguishable — this is the one behaviour a computed-style assertion cannot check.

Re-run the guard after each pass; it prints exactly what is left.

- [ ] **Step 6: Verify**

```bash
.venv/bin/python -m pytest tests/test_theme_tokens.py -v -k meal_planner
.venv/bin/pytest tests/e2e/test_dark_mode.py -m e2e -v -k meal_planner
.venv/bin/pytest tests/e2e/test_planner_touch.py tests/e2e/test_planner_library.py -m e2e -q
.venv/bin/python -m pytest -q 2>&1 | tail -5
```

Expected: the first three PASS. The last reports `test_allowlist_is_temporary` FAILING — that is the intended signal, cleared in Task 11.

- [ ] **Step 7: Drive the page in both themes**

Open `/meal-planner` on the iPad and the phone in each appearance. Drag a recipe into a slot, open the library shelf, collapse it, and read the macro totals row.

- [ ] **Step 8: Commit**

```bash
git add templates/meal_planner.html tests/theme_allowlist.py
git commit -m "feat: the meal planner follows the theme

The planner was themed on Apple system colours; it now takes the app
accent, so coral replaces blue. Layout custom properties (--shelf-h and
friends) stay in :root — initShelf() writes to them at runtime.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 11: Retire the allowlist

**Files:**
- Modify: `tests/theme_allowlist.py` — delete `UNCONVERTED`
- Modify: `tests/test_theme_tokens.py` — delete the skip branches and `test_allowlist_is_temporary`
- Modify: `tests/e2e/test_dark_mode.py` — delete the skip branches
- Modify: `docs/superpowers/specs/2026-07-30-light-and-dark-mode-design.md` — status to Done, tick the acceptance criteria

**Interfaces:**
- Consumes: an empty `UNCONVERTED` from Task 10
- Produces: a guard with no exemptions

- [ ] **Step 1: Delete the machinery**

Remove `UNCONVERTED` from `tests/theme_allowlist.py`; remove its import and the four `if … in UNCONVERTED: pytest.skip(...)` branches from the two test files; delete `test_allowlist_is_temporary`. Keep `HEX`, `THEME_COLOR_LITERALS` and `TEMPLATE_ROUTES` — all three are still consumed.

- [ ] **Step 2: Confirm the guard covers everything with no exemptions**

```bash
.venv/bin/python -m pytest tests/test_theme_tokens.py -v
```

Expected: 14 templates × 2 parametrized tests, all PASS, **zero skips**.

- [ ] **Step 3: Full verification**

```bash
.venv/bin/python -m pytest -q 2>&1 | tail -5
.venv/bin/pytest tests/e2e -m e2e -q 2>&1 | tail -5
.venv/bin/ruff check . 2>&1 | tail -3
```

Expected: green, green, no new findings.

- [ ] **Step 4: Close out the spec**

Set `**Status:** Done`, tick every acceptance criterion, and fill the Branch and PR links.

- [ ] **Step 5: Commit and open PR 2**

```bash
git add tests/ docs/superpowers/specs/2026-07-30-light-and-dark-mode-design.md
git commit -m "chore: retire the theme allowlist

Every page is converted, so the exemption mechanism goes with it.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
git push -u origin HEAD
gh pr create --title "The meal planner follows the theme" --body "$(cat <<'EOF'
The last page. Converts `meal_planner.html` (4805 lines, 74 hex literals) onto
`static/tokens.css` and retires the allowlist that drove the conversion, so the
guard now covers all fourteen templates with no exemptions.

**The planner stops being blue.** It was themed on Apple system colours; it now
takes the KitchenOS accent, so coral replaces `#0071e3`, `--done` replaces
`#34c759`, and `--alert` replaces `#ff3b30`. That is the design language's
"one accent per app" rule, and it is the most visible change here.

Layout custom properties (`--shelf-h`, `--shelf-collapsed-h`,
`--sidebar-width`) stay in `:root` — `initShelf()` writes `--shelf-h` at
runtime and `.panel-dock` reads it.

## Verification
- `tests/test_theme_tokens.py` — 14 templates, zero skips
- `tests/e2e/test_dark_mode.py`, `test_planner_touch.py`, `test_planner_library.py`
- Drag-and-drop driven on iPad and phone in both appearances

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01Pd5JGPEqppDFTvwBo1yb2Y
EOF
)"
```

---

## Verification Summary

| Check | Command |
|---|---|
| Static guard | `.venv/bin/python -m pytest tests/test_theme_tokens.py -v` |
| Browser, both schemes | `.venv/bin/pytest tests/e2e/test_dark_mode.py -m e2e -v` |
| Paper from a dark machine | included above, plus one real ⌘P preview |
| Planner interactions | `.venv/bin/pytest tests/e2e/test_planner_touch.py tests/e2e/test_planner_library.py -m e2e` |
| Review interactions | `.venv/bin/pytest tests/e2e/test_location_visibility.py tests/e2e/test_bulk_inventory.py -m e2e` |
| Vendoring intact | `diff ~/Dev/design-system/tokens.css static/tokens.css` |
| Full suite | `.venv/bin/python -m pytest -q` |
