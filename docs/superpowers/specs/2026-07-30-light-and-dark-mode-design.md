# Light and dark mode on every KitchenOS page

**Status:** Done
**Created:** 2026-07-30
**Updated:** 2026-07-31

---

## Problem

Ten of KitchenOS's fourteen web pages are light-only, and each one carries its own
private copy of a palette.

The four newest pages — `home.html`, `prep.html`, `recent.html`, `note_view.html` — were
built against `static/tokens.css`, the personal design language (Ink dark / Dawn light,
KitchenOS accent coral). They follow the OS theme correctly. Every page older than that
declares a `:root` block of hardcoded hex and ignores `prefers-color-scheme` entirely.

The result on a phone at night: `/` renders in Ink, and tapping the first card throws a
full-brightness white `/meal-planner` at you. This is the kitchen's most common evening
use.

The second cost is drift. Across the ten unconverted templates there are **~65 distinct
hex literals**, but they are ten near-copies of one palette — `#f5f5f7` and `#f4f4f2` are
both "page ground", `#e5e5e7` / `#ebebed` / `#e9e9eb` / `#e8e8ed` / `#d8d8dc` are all
"border". Nothing keeps them in step, so they have already diverged. One has already
rotted outright: `review.html:29` sets `border-color: #d3355`, a five-digit literal that
is not valid CSS, so the declaration is dropped and `.rm` silently falls back to
`currentColor`.

This work is **Phase 1 (web) of `~/Dev/design-system/plans/design-language-rollout.md`**,
which was started and left half-finished.

### Current state

| Template | Lines | Raw hexes | State |
|---|---:|---:|---|
| `home.html` | 154 | 2 | ✅ tokens, both modes |
| `prep.html` | 191 | 3 | ✅ tokens, both modes |
| `note_view.html` | 203 | 2 | ✅ tokens, both modes |
| `recent.html` | 89 | 2 | ✅ tokens, both modes |
| `meal_planner.html` | 4805 | 74 | light-only |
| `review.html` | 590 | 24 | light-only |
| `nutrition_review.html` | 568 | 28 | light-only |
| `recipe_detail.html` | 549 | 19 | light-only |
| `system_health.html` | 308 | 23 | light-only |
| `receipt_paste.html` | 230 | 18 | light-only |
| `recipe_card.html` | 75 | 11 | light-only |
| `print_week.html` | 56 | 5 | system colours, not the design language |
| `plan_week.html` | 54 | 4 | light-only |
| `cook_now.html` | 171 | 0 | `color-scheme: light dark`, not the design language |

(The 2–3 hexes on the converted pages are the `theme-color` metas, which cannot hold a
`var()`.)

Plus six HTML pages built inline as f-strings in `api_server.py`: `error_page`,
`success_page`, the `/refresh-nutrition` success page, "Add to Meal Plan",
`_success_page_for_wikilink`, and "Schedule Meal".

## Solution

Convert all ten templates and all six inline pages onto `static/tokens.css`, so dark mode
arrives as a consequence of the pages finally sharing one palette rather than as a
tenth private palette bolted beside nine others.

**Mode follows the OS.** `prefers-color-scheme` only — no toggle, no persisted state, no
new UI. `tokens.css` ships `[data-theme]` overrides; nothing in KitchenOS sets them and
nothing here starts.

## Design

### How a page becomes themed

Four mechanical steps per template:

1. Add to `<head>`, exactly as `home.html:7-13` has it:
   ```html
   <meta name="theme-color" content="#f4ede3" media="(prefers-color-scheme: light)">
   <meta name="theme-color" content="#0f1116" media="(prefers-color-scheme: dark)">
   <link rel="stylesheet" href="/static/tokens.css">
   ```
2. Delete the **colour** half of the page's `:root`. Keep the layout half —
   `meal_planner.html` stores `--sidebar-width`, `--shelf-h` and `--shelf-collapsed-h`
   there, and `initShelf()` writes `--shelf-h` onto `:root` at runtime from localStorage
   so `.panel-dock` can read the live value. The guard rule is therefore **"no raw
   hex"**, never "no `:root`".
3. Rewrite every colour through the mapping table below.
4. Apply the material: `background-image: var(--dots)` with
   `background-size: var(--dot-size) var(--dot-size)` on `body`, and `var(--grain)` on
   cards. Both are `none` in Ink. This is the step that makes a converted page *look*
   like `home.html` instead of merely tolerating dark mode.

There is no Jinja in this codebase — `_serve_page_with_claude_bar` does
`open(f'templates/{name}').read()` plus string replacement — so "shared head" cannot mean
template inheritance. The `<link>` stays written out per file: it matches the four
already-converted pages, the guard test can require the literal tag, and a template is
then self-describing.

### The mapping table

| Bucket | Found as | Becomes |
|---|---|---|
| page ground | `#f5f5f7` `#f0f0f2` `#f4f4f2` | `--bg` |
| card surface | `#fff` `#ffffff` `#fafafa` `#f9f9fb` `#fafafc` `#f6f6f8` | `--surface` |
| raised surface | `#ebebed` | `--raised` |
| borders | `#e5e5e7` `#e9e9eb` `#e8e8ed` `#d8d8dc` `#ccc` | `--line` / `--line-soft` |
| text | `#1d1d1f` `#1a1a1a` | `--ink` |
| muted text | `#86868b` `#6e6e73` `#666` `#555` `#444` | `--muted` |
| accent | `#0071e3` `#0077ed` `#4a90d9` | `--app-kitchenos` |
| success | `#34c759` `#3f9e4d` `#1a6b34` `#1a7a37` | `--done` |
| danger | `#ff3b30` `#c0392b` `#d33` `#b8291f` `#8b1a1a` `#a11` | `--alert` |
| warning | `#b7791f` `#ff9f0a` `#ff9500` `#c58a00` `#8a6d00` `#8a5000` `#b8860b` `#e69500` `#c2680a` `#b8650a` `#a15c00` `#f0c274` | `--warning` |

Two literals are deliberately absent from the table because they are not solid colours:
`#4a90d955` (an accent at 33% alpha, in a `review.html` keyframe) and `#f1f8f2` (a success
wash on `recipe_card.html`'s finish cell). Both become tints — see below.

### `static/kitchenos.css` (new)

The mapping table leaves two residues.

**Tinted fills.** `#fde8e8` behind an error, `#d4f5de` / `#f1f8f2` behind a success,
`#fff3e0` / `#fff8e1` / `#ffe082` / `#fff0d6` behind a warning, `#e3f2ff` / `#f2f7ff` /
`#4a90d955` behind an accent note — a pale wash of a semantic colour. In Ink these must
invert to *dark* washes, and `tokens.css` has no token for them. Deriving them solves both
modes at once:

```css
/* static/kitchenos.css — KitchenOS-local derivations. Not a component library.
   --tint-*: the fill of a callout, banner, pill or highlighted cell.
   --edge-*: the 1px border of that same element, a step stronger than the fill. */
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

The one alpha-over-*transparent* case, `review.html`'s "just moved" keyframe, mixes
against `transparent` at its use site rather than earning a ninth variable:
`color-mix(in srgb, var(--app-kitchenos) 33%, transparent)`.

`color-mix` is already a baseline assumption here — `print_week.html:29` uses it today.

This is a **separate file, not an addition to `tokens.css`**, because `static/README.md`
declares tokens.css "a copy, not a fork", pins it by sha256, and states that editing the
values locally is how KitchenOS drifts away from Selene and the Obsidian theme. Pages
load both stylesheets, tokens first.

**Scrims and overlays.** `#0006` `#8886` `#8884` `#8883` `#8882` `#fff5` `#fff3` `#222d`
are deliberately theme-neutral alphas used for modal backdrops, toast bodies and
hairlines. A black 40% scrim is correct in *both* modes; rewriting it to `var(--ink)`
would turn the Ink backdrop white, and `review.html:49`'s near-black toast is legible on
either ground. These are rewritten to explicit `rgba()` — same colour, non-hex spelling —
which both documents the intent and keeps them out of the guard's way.

### Paper always prints Dawn

`print_week.html` sets `-webkit-print-color-adjust: exact`, so an Ink background there
would print a black page.

Forcing light on paper needs a `@media print` block that re-pins the light values.
Writing that into the two print templates would re-duplicate the palette this work
exists to delete, so it goes **upstream** into `~/Dev/design-system/tokens.css`, then
comes back via the copy procedure `static/README.md` already documents (`cp`, re-`shasum`,
update the row):

```css
/* Paper is always Dawn. Last block in the file — see note below. */
@media print {
  :root, :root[data-theme="dark"], .theme-dark {
    /* byte-for-byte the declarations already in the :root[data-theme="light"]
       block above — neutrals, semantics, app accents, --text-on-accent — */
    --bg:#f4ede3; --surface:#fffdf9; --raised:#fbf5ec;
    --ink:#2c2733; --muted:#8a7f8e; --line:#ece1d3; --line-soft:#f1e8dc;
    --try:#0d8ea3; --done:#3f8f2f; --warning:#b7791f;
    --alert:#c0392b; --info:#2f7fd1; --insight:#9a4fb5; --next:#b26a2e;
    --app-kitchenos:#d1663b; --app-selene:#8a63d6; --app-lumen:#c0842a;
    --app-journal:#0f9d8c; --app-personal:#d24d78;
    --text-on-accent:#fffdf9;
    /* — except the material, which paper supplies or cannot render */
    --dots:none; --grain:none; --shadow:none;
  }
}
```

Two details that are easy to get wrong: media queries add no specificity, so a bare
`:root` here would lose to `:root[data-theme="dark"]` — hence the selector list. And
against the equal-specificity `@media (prefers-color-scheme: dark) { :root {…} }` block,
source order decides, so this must be **last in the file**.

"Paper is Dawn" is a design-language rule rather than a KitchenOS one, which is why
upstream is the right home: Selene gets it for free.

### The planner stops being blue

`meal_planner.html` is themed on Apple system colours — `--accent: #0071e3`,
`--success: #34c759`, `--danger: #ff3b30`. Converting it makes the accent **coral**,
success the design language's olive `--done`, danger its softer `--alert`.

This is the rollout plan's "one accent per app = identity" rule applied, and it is the
single most visible change in this work. Called out here so it is not discovered in
review.

### Out of scope

- **Any manual theme toggle.** OS-follow only.
- **Layout, spacing, type-scale and component redesign.** Colour, material and the
  `<head>` block only. A page keeps its structure.
- **`static/kitchenos.css` growing into a component library.** It holds the eight derived
  tints and nothing else. Shared page chrome is a separate piece of work.
- **The Obsidian vault theme and the SwiftUI app.** The vault half of the rollout plan's
  Phase 1, and its Phase 4.
- **Markdown note templates** (`recipe_template.py`, `meal_plan_template.py`,
  `my_macros_template.py`, `shopping_list_template.py`). Those render through Obsidian's
  theme, not through `tokens.css`.

## Implementation Notes

### Sequencing

**Upstream first.** One commit in `~/Dev/design-system` adding the `@media print` block,
then `cp ~/Dev/design-system/tokens.css static/tokens.css`, re-`shasum -a 256`, and
update the version row in `static/README.md`.

**PR 1 — everything except the planner.** `static/kitchenos.css`; an `_html_page(title,
body)` helper that owns `<!DOCTYPE>` and `<head>`, plus the six inline `api_server.py`
pages rewritten to call it; **nine** templates — `cook_now`, `plan_week`, `print_week`,
`recipe_card`, `receipt_paste`, `system_health`, `nutrition_review`, `review`,
`recipe_detail`; both test files, with `meal_planner.html` on the guard's allowlist.
`review.html:29`'s invalid `border-color: #d3355` is fixed in passing — it maps to
`--edge-alert`, which is what it was reaching for.

**PR 2 — `meal_planner.html` alone.** 4805 lines, 74 hexes, and the page in daily use.
Reviewed and revertable by itself. Its final commit deletes the allowlist entry, so the
guard goes fully live exactly when the last page lands.

### Testing

| Test | Purpose |
|---|---|
| `tests/test_theme_tokens.py` | **new** — static guard, runs in the normal suite |
| `tests/e2e/test_dark_mode.py` | **new** — marked `e2e`, deselected by default |

**`test_theme_tokens.py`** — for every `templates/*.html` and every inline page in
`api_server.py`: the `<link rel="stylesheet" href="/static/tokens.css">` tag is present,
and no raw hex appears. Three allowances, each named in the test: the two `theme-color`
meta values, `rgba()` scrims (which are not hex and so pass structurally), and an
`ALLOWLIST` set that starts holding `meal_planner.html` and ends empty.

**The hex pattern must not match CSS ID selectors**, or the guard is unshippable from day
one: `recipe_detail.html:181` declares `#add-week-status`, `meal_planner.html:1735`
declares `#add-sub-recipe`, and a naive `#[0-9a-fA-F]{3,8}` reads both as the colour
`#add`. A trailing `\b` does not help, because `-` is itself a word boundary. The rule is
a valid hex length followed by no identifier character:

```python
HEX = re.compile(r'#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})(?![0-9a-zA-Z_-])')
```

The alternation also matters on its own: an unanchored `{3,8}` accepts five- and
seven-digit runs, which is how `review.html`'s invalid `#d3355` reads as legitimate.

For `api_server.py` the guard runs the same pattern over **the whole file**, which is
exact rather than approximate: a Flask server has no legitimate non-markup reason to name
a colour. It additionally asserts the file contains exactly one `<!DOCTYPE` — the one
inside `_html_page` — so a seventh hand-rolled page cannot appear without going through
the shared head.

Its 54 hex literals are **not** all in the six pages, as an earlier draft of this document
claimed. Roughly 18 belong to `_CLAUDE_BAR_TEMPLATE`, the Claude launch bar that
`_serve_page_with_claude_bar` injects after the opening `<body>` of *every* page. That
makes it a seventeenth surface and the most consequential one: it was hardcoded dark, so
without converting it each newly-Dawn page would carry a dark strip across its top. Its
purple maps to `--insight` — a *meaning* colour — rather than to `--app-kitchenos`,
because the accent's job is identity and a second coral element in shared chrome blurs it.

**`test_dark_mode.py`** — walks `SECTIONS` + `HOME` from `lib/web_dashboard.py`, the same
registry that feeds the home page and the Safari bookmark sync, so a new page joins this
test for free. Path-param pages absent from the registry (`/recipe/<name>`,
`/recipe-card/<name>`) are listed explicitly. Per route:

- `color_scheme="dark"` → `body` computed background is `rgb(15, 17, 22)`
- `color_scheme="light"` → `rgb(244, 237, 227)`
- `page_errors == []` — a CSS rewrite should not touch JS, but `meal_planner.html` is
  4805 lines of both

Plus, for `/print/week` and `/recipe-card/<name>`,
`page.emulate_media(media="print", color_scheme="dark")` must still report Dawn cream —
testing the paper rule directly rather than by inspection.

### Restart caveat

Templates are read per-request, so template edits are live. `static/*.css` is served by
Flask's static route and is likewise live (hard-refresh to defeat the browser cache).
Changes to `api_server.py` — the `_html_page` helper and the six inline pages — **do**
require the LaunchAgent reload from `CLAUDE.md`, or the server keeps serving stale code.

## Ready for Implementation Checklist

- [x] **Acceptance criteria defined** — below
- [x] **ADHD check passed** — below
- [x] **Scope check** — sixteen surfaces, one mapping table, two new test files, no new
      runtime behaviour; two PRs, well under a week
- [x] **No blockers** — the upstream `~/Dev/design-system` print commit landed and was
      copied back; `static/tokens.css` is confirmed byte-identical (see below)

### Acceptance Criteria

- [x] All fourteen templates and all six inline `api_server.py` pages link
      `/static/tokens.css` and declare no raw hex outside the three named allowances
- [x] Every route in `SECTIONS` + `HOME` renders Ink under `prefers-color-scheme: dark`
      and Dawn under light, verified by `tests/e2e/test_dark_mode.py`
- [ ] `/print/week` and `/recipe-card/<name>` render Dawn under print emulation **while
      the OS is in dark mode**, and a real print preview of `/print/week` from a dark-mode
      Mac is ink-on-white — the emulated half is green in `tests/e2e/test_dark_mode.py`
      (`test_paper_is_always_dawn`); the real Safari ⌘P preview from a dark-mode Mac is
      pending the user's manual check
- [x] `static/kitchenos.css` contains the derived tints and nothing else
- [x] `api_server.py` builds every page through `_html_page`, and contains exactly one
      hand-rolled `<!DOCTYPE html>`/`<html>` page
- [x] `review.html`'s `.rm` has a real border colour again
- [x] `static/tokens.css` is byte-identical to `~/Dev/design-system/tokens.css`, and the
      sha256 row in `static/README.md` matches
- [x] `tests/test_theme_tokens.py`'s allowlist is empty when PR 2 lands — `UNCONVERTED`
      was deleted outright, along with the skip branches and the guard that watched for it
- [x] Full unit suite green; `tests/e2e -m e2e` green; `ruff` no worse than main
- [ ] Both modes checked on the phone over the tailnet, on `/meal-planner` and `/review`
      at minimum — pending the user's manual walkthrough in both appearances

### ADHD Design Check

- [x] **Reduces friction?** Removes the white-flash jolt when moving between pages at
      night, which is the moment the kitchen is actually in use.
- [x] **Visible?** Nothing new to notice; the pages simply stop disagreeing with each
      other and with the phone.
- [x] **Externalizes cognition?** The guard test holds the rule, so "which pages are
      themed" stops being something to remember.
- [x] **Additive, never a chore?** No maintenance surface. The registry-driven e2e test
      and the lint mean a new page is themed or the suite says so.

---

## Links

- **Rollout plan:** `~/Dev/design-system/plans/design-language-rollout.md` — Phase 1 (web)
- **Design language:** `~/Dev/design-system/DESIGN-LANGUAGE.md`, `tokens.css`
- **Vendoring rules:** [`static/README.md`](../../../static/README.md)
- **Branch:** `light-and-dark-mode` (PR 1), `planner-dark-mode` (PR 2, this branch)
- **PR:** _(both intentionally not yet opened — held pending the user's manual
  verification of PR 1)_
