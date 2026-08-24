# KitchenOS Roadmap

**ROADMAP = what's next.** Shipped design history lives in `docs/superpowers/specs`
(per-feature design docs) and `docs/plans/archive` (frozen pre-superpowers plans).
Build/deploy history (the Siri/App-Intents build log, origin-story rationale) lives
in `docs/history`. This file tracks only: what shipped since the last update (for
context) and what's genuinely still open.

Audited 2026-07-01 against `main` (post-convergence). Original 2026-06-24 audit
covered the salvaged-branch Python backlog below; this pass adds the native/Siri
tier that shipped since and corrects two stale statuses.

---

## Done / Shipped

**2026-08-23 — iOS print/share fallback.** Printable week packets and recipe
cards now use the system share sheet on iPhone and iPad, where people can choose
**Print**, Save to Files, or AirDrop. Desktop browsers retain their normal print
dialog. The shared action is deliberately attached to both printable surfaces so
one cannot silently regress back to a no-op on iOS.

**2026-07-08 — Web dashboard tailnet launcher** (PR #32). `lib/web_dashboard.py`
+ `scripts/generate_web_dashboard.py` regenerate `Dashboards/KitchenOS Web.md` — a
tap-anywhere generated note whose links point at `KITCHENOS_API_BASE` (Tailscale
MagicDNS host by default), so the web app (Meal Planner, current plan/shopping
list, Nutrition Review, System Health) opens from any device on the tailnet, not
just localhost on the server. Follows the generated-read-only-view pattern
(`Inventory.md` / `Use It Up.md`); runbook entry in `docs/OPERATIONS.md`.

The native tier — entirely undocumented here until now — is built and merged to
`main` (both forked app branches, `siri-app-intents` and `ingredient-cleaning`,
converged via `docs/superpowers/plans/2026-06-24-convergence-plan.md`; both
branches are gone, both surfaces coexist in one app):

- **`KitchenOSSiri`** — single XcodeGen target building **iOS 26 + macOS 26**
  (bundle `com.kitchenos.siri`), multiplatform: macOS gets the `AppShell` sidebar
  (Cook / Plan / Stock / System sections), iOS/iPadOS gets the tab-based
  Assistant/Plan/Cook/Search/Settings surface. Both platforms share
  `KitchenOSKit`.
- **`KitchenOSKit`** — shared Swift package: async `KitchenOSClient`, Codable
  models, Keychain-backed credential store, `WeekDate` helpers.
- **App Intents + `AppShortcutsProvider`** — 9 intents: `FindRecipesByIngredient`,
  `GetMealPlan`, `SuggestForMealPlan`, `AddRecipeToMealPlan` (gated behind
  `requestConfirmation`), `GetRecipeNutrition`, `SummarizeRecipe`, `OpenRecipe`,
  `SmartFindRecipes`, `AskKitchenOS`. All Swift-side relay/format only — recipe,
  AI, and nutrition logic stays server-side in Python.
- **On-device Apple Foundation Models** (Subsystem C, phases C1/C2):
  `RecipeAI` (single Foundation Models gateway; `@Generable RecipeQuery` filter;
  backs `SummarizeRecipeIntent`) and `MealPlanAssistant` + three `Tool`
  conformances (`FindRecipesTool`, `MealPlanTool`, `SuggestMealTool`) powering the
  in-app chat assistant.
- **CoreSpotlight / `IndexedEntity` semantic search** (Subsystem C, phase C3):
  `RecipeEntity: IndexedEntity` with a `CSSearchableItemAttributeSet`
  (title/cuisine/protein), `RecipeIndexer.reindexAll`, indexed on launch + a
  manual "Reindex for search" Settings button. Spotlight/Siri can match recipes
  by meaning, not just exact name. (`AssistantSchemas`/`@AssistantEntity` were
  evaluated and correctly skipped — no matching Apple domain exists for
  food/recipe/meal.)
- **Backend Phase 0** (`docs/superpowers/plans/2026-06-21-siri-backend-phase0.md`):
  `GET /api/recipes?ingredient=<term>` server-side filter, and optional
  `KITCHENOS_API_TOKEN` bearer-token auth (no-op when unset, localhost always
  exempt) gating the Siri-facing endpoints for the iPad-over-Tailscale case.
  `/api/recipes/by-ingredients` also shipped as part of the merged backend work.
- **Inventory cleanup screen** (`docs/superpowers/plans/2026-06-26-inventory-cleanup-screen.md`):
  `GET /api/inventory` now returns a computed `expiry_status`
  (`expired`/`soon`/`ok`/`null`, from `lib/expiry.py` — same thresholds as
  `Inventory.md`). The native `InventoryView` shows an "Added … · Exp … 🔴/🟡"
  secondary line, sorts each category worst-first by expiry, and stepping
  quantity to 0 removes the item.
- **Convergence merge**: `siri-app-intents` and `ingredient-cleaning` are merged
  to `main` and deleted; the app is one multiplatform target, not two forks.

---

## Native / Siri — pending polish

Genuinely open items surfaced by the superpowers specs/plans, not yet built:

- **CoreSpotlight ingredient-keyword enrichment + reindex cadence** (C3
  follow-up). C3 v1 indexes title/cuisine/protein only — ingredient keywords
  need a backend "all recipes with ingredients" endpoint that doesn't exist yet.
  Reindexing today is launch-time + a manual Settings button; no background/
  periodic cadence.
- **`AppShell` `ComingSoonView` fallback** (`KitchenOSSiri/Sources/Shell/AppShell.swift`):
  a placeholder view still exists for any `SidebarSection` the `detail(for:)`
  switch doesn't explicitly handle. As of this audit every current section
  (Search, Recipes, Meals, Nutrition, Meal Plan, Planner Board, Shopping List,
  Tasks, Inventory, Pantry, Receipts, Extraction (macOS), System Health,
  Settings) routes to a real screen — so this is currently dead code / a safety
  net, not an active gap. Worth removing or re-purposing next time a new section
  is added rather than leaving it as a silent fallback.

## Native inventory: zone + shelf layout (next concrete step)

**Status:** the flat-category cleanup screen (dates + expiry badges, worst-first
sort) shipped — see Done/Shipped above. `main` still routes every item to one of
five flat locations (`fridge/freezer/pantry/counter/other` in `lib/inventory.py`);
the richer zone → shelf → group hierarchy from the salvaged
`claude/kitchen-inventory-system-EdBZI` branch (below) was never built.

The concrete next step is **not** a new screen from scratch — it's reconciling
the shipped flat `storage_location`/`for_recipe` router
(`lib/storage_locations.py:resolve_location`) with the branch's richer
`Location/Shelf/Group` model into **one** item → `(zone, shelf, location)`
router, then surfacing shelf grouping in both `Inventory.md` and the native
`InventoryView`. See the salvaged-branch entry below for the original design
(`config/storage_locations.json` schema, `route_item()`).

---

## Usage feedback — 2026-07-31

Eleven items from a session of actually using the system, ordered by priority.
**The two P1 bugs and two P2 items are fixed** (see the struck-through entries below, kept for the
diagnosis); the remaining nine were traced far enough to name the code involved,
or are waiting on a screenshot or a design decision. Two screenshots referenced in
the original feedback were on the user's Desktop and not available to the session
that triaged this — they are called out below.

### ~~P1 — Shopping list doesn't compare against inventory (from the phone)~~ FIXED

**Fixed 2026-07-31.** `POST /generate-shopping-list` — the button on
`/current/shopping-list`, the only trigger reachable from the phone you shop with
— passed no pantry, so `generate_shopping_list(week, pantry=None)` compared
against nothing and told you to buy the garlic salt, eggs and brown sugar already
in the kitchen. The MCP `generate_shopping_list` tool inherited it, since
`lib/mcp_tools.py` POSTs to that same endpoint (an earlier draft of this entry
listed it as a second independent caller — it isn't; fixing the endpoint fixed
both surfaces).

Resolved as **annotate, never decrement**: the endpoint now reads the pantry to
keep owned items off the buy list, and records what it credited under an
"Already have" section. Those notes are plain bullets, deliberately *not*
checkboxes — `parse_shopping_list_file` collects every `- [ ]` line in the file
regardless of section, so a checkbox there would be sent to Reminders as
something to buy and would return as a phantom "manual item" on the next
regeneration. `POST /api/shopping-list/preview` → `/confirm` remains the only path
that actually spends stock. `use_pantry: false` restores raw-demand behaviour.

### ~~P1 — Grouped ingredient sections are silently dropped~~ FIXED

**Fixed 2026-07-31.** Both ingredient-section parsers truncated, in different
ways, and an earlier draft of this entry wrongly said the shopping list was
unaffected — it wasn't:

- `parse_recipe_body` matched one *contiguous* run of table rows, so it stopped at
  the first blank line. A recipe grouped as "…thighs / `### For the spice rub` /
  …paprika" kept the thighs and lost every spice — the reported bug. A table not
  preceded by exactly one blank line yielded **zero** ingredients.
- `shopping_list_generator.extract_ingredient_table` stopped at `\n##`, which
  matches the first two hashes of `\n###` — so a sub-heading truncated the section
  there too.

Folded onto one extractor, `recipe_parser.extract_ingredients_section`, whose
`(?=\n#{1,2}\s|\Z)` ends the section only at an h1/h2 (the trailing `\s` can't
match an h3's third `#`). `parse_ingredient_table` already skips non-table lines,
separators and repeated headers, so grouped tables parse as one list.

### ~~P2 — Week numbers everywhere instead of date ranges~~ FIXED

**Fixed 2026-08-01 (#64).** Eight surfaces, not the three this entry originally
named: the `/plan-week` nav (three raw ids in one line, on the page that defaults
to *next* week), the planner header, `week_view`'s plan title (which had no dates
at all), the printed week packet's h1 (`2026-W31  (2026-07-27 → 2026-08-02)`), the
plan and shopping-list note titles, the meal-plans index table, the note-view
subtitle, and the week dropdowns (which appended the id beside the range, putting
the unreadable form back in front of the user when it was already the option's
value).

All now render `format_week_range`, or `format_week_heading` — "This week · Jul 27
- Aug 2, 2026". The relative prefix is the orientation the week number was really
standing in for. Display-layer only: week ids are untouched as keys in every href,
filename, API path and wikilink.

### ~~P2 — Recipe page should colour ingredients you don't have~~ FIXED

**Fixed 2026-08-01.** `/api/recipes/<name>` annotates each ingredient with
`in_stock` + `have` via `pantry.stock_for_ingredients`, which delegates to
`find_match` — the same matcher the shopping list uses, so the page and the list
can't disagree about what you own. `/recipe/<name>` colours the row, marks it
`✓`/`•` (colour is never the only signal), and shows a summary line.

Two deliberate limits. It reports **presence, not sufficiency**: the page scales
1x-4x, so a server-side "do you have enough" would be wrong the moment the reader
scales up, and computing it client-side would mean a second copy of the
unit-conversion rules `unit_compatibility` owns. And `in_stock` is **tri-state** —
`null` when there's no inventory to check against, rendered unmarked, because
painting every ingredient red on an empty pantry is a claim about the kitchen
rather than about the data.

### ~~P2 — Servings / freezer flow is not discoverable~~ FIXED

**Fixed 2026-08-01.** Nothing was broken — it was unexplained. The board turns on
and chips, a scale stepper, a freezer tab and a bin all appear at once with no
statement of what any of them are.

- A one-line legend under the grid header, shown **only in board mode** (a legend
  for chips that don't exist is noise on a legacy week), naming all three
  destinations a chip can go to.
- Every serving chip carries a `title` saying what it is and where it can go.
- The freezer's empty state said "Freezer is empty" — true, useless, and a dead
  end. It now says how food gets in, because dragging a chip onto a tray is not a
  guessable gesture.
- The Unscheduled tray says what "unscheduled" means.

Deliberately copy and affordances only: no behaviour changed, so nothing here can
break a working board. A walkthrough on `/plan-week` was considered and skipped —
explaining the model where the controls actually are beats a tour of them
elsewhere.

### ~~P2 — Nutrition review page: unclear what to do about a flagged item~~ FIXED

**Fixed 2026-08-01.** The actions already existed (pick a USDA match → **Use**, or
mark **Negligible**) but only inside an expanded row, and nothing said the rows
expanded, what the buttons meant, or what being flagged costs you.

- A lead paragraph stating the job *and the stakes*: a flagged recipe is skipped
  when suggestions are ranked against your targets, and its day shows a ⚠.
- "click a row to fix it" in the column header — the affordance was a bare
  `cursor: pointer`.
- Each expanded recipe opens with how many ingredients are the problem and what
  the two answers mean, plus the fact that an answer is **remembered for every
  recipe using that ingredient** — the thing that makes the work worth doing.
- Tooltips on Use / Negligible. "Negligible" is jargon for "count this as zero
  calories, permanently".

### ~~P3 — the Obsidian button block leaking to the top~~ FIXED

**Fixed 2026-07-31.** All 252 recipe bodies open with a `[!tools]` callout of
```button blocks, *above* the `# Title`. `renderBodyMarkdown` in
`templates/recipe_detail.html` escapes whatever it doesn't understand and had no
concept of a fence, so that callout arrived at the top of the Full Recipe panel
as literal `> ```button / > name Re-extract / > type link / > action http://…`.

Resolved by **stripping, not reviving**: `stripObsidianChrome()` drops `button`
fences, the `[!tools]` callout, HTML-comment authoring prompts, and blockquote
markers, then hands the rest to the existing renderer. Unlike the `kitchenos://`
buttons `lib/note_view.py` revives, these three actions (re-extract, refresh, add
to plan) are already plain HTTP links *and* already buttons in this page's own
header, so rendering them would only duplicate the header. Only `button` fences
are dropped — a fence of any other kind is content, and `[!abstract]` (48
recipes) is content, so only `[!tools]` is matched by name.

Covered by `tests/e2e/test_recipe_body_chrome.py`, including a guard that the
strip doesn't eat real sections.

### P3 — Recipe view layout

Still open, and the screenshot now makes the complaint concrete: the **Full
Recipe panel repeats the whole page**. Ingredients, Instructions and Equipment
are already rendered as structured cards above it, then appear again as raw
markdown — including the ingredients table as literal `| Amount | Unit |` pipes
and `---` as three dashes, because the minimal renderer handles only headings and
`- ` lists.

The open question is what that panel is *for* once the page above it is
structured. Most likely it should show only what has no card of its own — "My
Notes" and the extraction footer — rather than a second copy of the recipe. That
is a design decision, not a bug fix, so it needs a call before any code.

### P2 — Dense meal-planner board overflow and scrolling

On a populated iPad planner board, long recipe names and multi-recipe plates can
run outside their day/meal cells or below the fixed viewport. The current
"whole-week at a glance" constraint is useful for an empty week, but it must
not make planned food unreachable.

Make the board itself vertically scrollable when its slots grow, keep the
planner chrome and recipe shelf stable, and constrain card/bundle text to its
own column so it cannot overlap the next day. Preserve the seven-day overview
and the existing ledger-only card mutations; this is a presentation change,
not a change to cook or serving semantics. Cover a dense plate in
`tests/e2e/test_planner_touch.py`: its cards must remain contained and the
board must expose any excess height through scrolling.

### P3 — Three-finger drag for planner UI elements on macOS

Drag on the planner is Sortable.js pointer-based; three-finger drag is a macOS
trackpad accessibility gesture (System Settings → Accessibility → Pointer
Control), which synthesises a drag from a three-finger swipe. Whether this "just
works" depends on whether Sortable's pointer handling sees those events. Needs a
test on the machine before deciding if there's code to write.

### P3 — Extractor puts durations in the ingredients array

A boiled-egg recipe lists "boiling time for eggs" as an ingredient. Unlike the
grouped-sections bug above this is an *extraction*-time fault — the LLM emitted a
time into `ingredients` — so the fix belongs in the prompt
(`prompts/recipe_extraction.py`) and/or `lib/ingredient_validator.py`, which
already exists to reject implausible rows. Before writing a rule, grep the corpus
for time-shaped ingredient rows to find out whether this is systemic or a one-off;
that needs vault access.

### P3 — Obsidian vault / web app parity

The vault is reported as messy, with the web app as the primary interface and the
vault valued for browsing raw data. That's consistent with the existing
generated-read-only-view pattern (`Inventory.md`, `Use It Up.md`, `Cook Now.md`),
so the work is auditing which notes are generated-and-current vs. stale hand-made
leftovers, then either generating or archiving each. Broad; needs a vault
inventory pass before it can be scoped.

---

## Usage feedback — 2026-08-01 (meal planner, iPad landscape)

Five items from an annotated screenshot of `/meal-planner` at iPad size, on a
week where only Sunday has anything planned. Ordered by priority. Nothing here
is a crash — the board is doing arithmetic correctly and saying it badly, which
is why every item below is a rendering or layout question rather than a data
one. Three are confirmed from the screenshot alone; two are marked as needing a
check on the device, and say what to check.

### P2 — A placed serving and an unplaced one look like the same chip

Reported as **"incorrect servings"** and **"should be more than one"**, circling
the `🍽×1` chip under *Smashed Beef Kabobs* and under *150 Calorie Chicken Summer
Rolls* — the latter a recipe the sidebar shows as **8 srv**.

The arithmetic is right. Two different objects are stacked in that cell
(`templates/meal_planner.html`):

- `makeServingChip` → `🍽×1` — **one serving placed on this day**.
- `makeUnassignedChip` → `+7` — **seven servings cooked and not yet placed
  anywhere**.

1 + 7 = the 8 servings the recipe yields, so the board is telling the truth. But
the two chips are the same shape, the same size and the same pill, separated only
by a `+` prefix, `border-style: dashed`, `color: var(--text-muted)`, and a
`title` tooltip — and a tooltip is unreachable on a touch device, which is where
this screenshot was taken. Read at a glance the pair says "1", so a 4-serving
cook looks like a 1-serving cook.

The fix is legibility, not counting: make "placed" and "unplaced" visually
different in kind rather than in degree, and say the total somewhere. Do **not**
change what the numbers mean — `makeUnassignedChip`'s empty `placementId` is
load-bearing (dropping one *creates* a placement; dropping a `🍽×` chip *moves*
an existing one), so merging the two chip types would break the drag semantics.

### P2 — The bottom dock covers the board's own bottom row

The **Use It Up** dock (`.panel-dock`, `position: fixed; right: 16px; bottom:
16px`) sits on top of the day-totals row, hiding **Saturday's and Sunday's**
totals cells outright in the screenshot. Sunday is the only day with food on it,
so the one populated totals cell on the whole board is the one you cannot see.

This is the same collision the panel-height cap fixed *within* the dock
(`use-it-up-by-item`, 2026-07-30) — two fixed-position things at the same corner,
neither aware of the other. The dock needs to reserve space at the bottom of the
scroll area rather than float over it.

### P3 — The day-totals row reads "—" everywhere, so it looks broken

Marked **"missing calories"** and **"macros"** against the row of dashes along
the bottom. Mon–Fri have nothing planned, so `—` is literally correct there —
but combined with the item above (Sat/Sun hidden under the dock) every cell the
user can see is a dash, and a row that is *always* empty reads as a feature that
never worked rather than as "nothing planned yet".

**The meal-bundle half of this is fixed (2026-08-03, `plates-ledger-native`).** A
plate now expands to one ordinary cook per sub-recipe sharing `cooks.bundle_id`,
so it contributes its macros to the row like any other cook — still without
writing any macro into the ledger, which was the constraint. What remains is the
narrower question this entry opened with: whether an empty day should say
`0 kcal` or `—`, and what the row should *say* when it genuinely cannot total
something. That case is now more common, not less: `day_totals` applies the full
`eligible_macros` gate, so a day whose only recipe is untrusted totals zero and
names the exclusion rather than showing a figure.

### P3 — Wasted vertical space above the board

The band between the top toolbar and the day headers is mostly empty: the week
nav is centred with wide empty gutters, and the legend occupies one line at the
far left. On a landscape iPad that band costs roughly a row of grid height, which
is exactly what the portrait shelf work (`planner-shelf-and-tap-to-assign`,
2026-07-30) was buying back in the other orientation. Landscape was explicitly
left untouched by that branch — this is the follow-up.

### P3 — Half the board legend isn't wanted

**"The ×N on a card is how much you cooked."** — marked *"don't care"*. That
sentence is the second half of `#board-help` in `templates/meal_planner.html`,
added by `planner-discoverability` (#67). The first half — what a chip is and
where it can go — was not marked, so this is a trim rather than a revert. Note
the interaction with the first item above: if placed-vs-unplaced chips become
visually self-explanatory, more of this legend can go.

### Needs a check on the device before any code

- **"Don't see trash can."** `#trash-target` exists, is wired into the same
  Sortable group as the chips, and is revealed by `body.dragging-serving` at
  `z-index: 200` — above the dock's `50` — so on paper it should appear. Three
  candidates worth eliminating in person: it only exists *during* a drag while
  the legend advertises it as a place you can aim for; the touch drag needs a
  200 ms hold (`delay: 200, delayOnTouchOnly`) before `onStart` fires at all; and
  it lands at `right: 24px; bottom: 96px`, immediately above the dock that item 2
  says is already crowding that corner.

---

## Infrastructure — 2026-08-01

### ~~A cold AI sidecar hung the page, and e2e couldn't run from a worktree~~ FIXED

**Fixed 2026-08-01.** Six e2e tests had been failing on `main`
(4 × `test_prep_page.py`, 2 × `test_dark_mode.py::recipe_card.html`), found while
merging #66/#68/#69 — they predate all three. One root cause with three faces:

- **The hang.** `/recipe-card/<name>` → `recipe_grid.build_grid()` and `/prep` →
  `task_extractor.extract_tasks()` each try Claude, then Ollama, then a non-LLM
  fallback they only reach *after* the wait. Both Ollama calls were a hardcoded
  `timeout=120` and the Anthropic SDK carries a multi-minute default, behind a
  30 s browser navigation timeout. Only **5 of 252** recipes have a
  `.grid.json` sidecar, so nearly every recipe card is a cold render.
- **The kill switch that wasn't.** `tests/e2e/conftest.py` promised "never let a
  test hit the paid APIs or a live LLM" and enforced it by blanking
  `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`. **Ollama needs no key**, so the local
  tier was reached anyway and the browser tests raced a model.
- **The harness couldn't leave `main`.** `vault/` and `data/` are git-ignored, so
  they exist only in the main checkout, and both `conftest.py` and
  `test_live_state.py` resolved them relative to themselves — so the browser
  suite died on `FileNotFoundError` in any `.worktrees/` branch, which is the
  mandated workflow in this repo.

New `lib/llm_gate.py` is the one authority: `allowed()` (honouring
`KITCHENOS_NO_LLM`) and `budget_s(default)`, which returns a single
`WEB_BUDGET_S` deadline shared by the whole Flask request and the caller's own
timeout outside one. Keyed on `has_request_context()` rather than a parameter, so
a new AI-on-render path is bounded without its author knowing the rule exists.
`tests/e2e/_paths.data_root()` walks `git rev-parse --git-common-dir` back to the
main checkout for *data only* — code still comes from the worktree under test.

Found while reading, and fixed with it: **both sidecars cached the fallback.**
Keyed on mtime alone, a heuristic sidecar reads fresh forever, so one cold render
permanently prevented the AI grid from ever being built for that recipe. Capping
the wait would have made that fire on every cold page load. `build_grid` no
longer writes a heuristic at all (it needs no model, so there's nothing to save);
`extract_tasks` still persists one reached off a request — that one is genuine,
and the sidecar also carries `done` flags — but not one the budget forced.

3408 → 3433 unit tests, e2e 108 → **124 passing, 0 failing**, and the browser
suite dropped from 267 s to 92 s now that it isn't waiting on models.

---

## Salvaged Python-side backlog

Unbuilt feature ideas worth keeping. These were salvaged from stale feature
branches before those branches were deleted — each entry records the source
branch + commit so the original implementation is recoverable from git's
reflog / object store (`git show <sha>`) until garbage-collected.

Branches whose every idea was already built (`refine-local-plan`,
`recipe-link-detection`, `recipe-update-system`, `reprocess-button`) were
deleted with nothing to preserve.

### Inventory: spatial zone + shelf layout

**Source:** `claude/kitchen-inventory-system-EdBZI` @ `f19dcec` (2026-04-25)
**Status today:** GAP, and now the concrete next inventory step — see
"Native inventory: zone + shelf layout" above. `main` has flat location
categories only (`fridge/freezer/pantry/counter/other` in `lib/inventory.py`).

Model the kitchen as a zone → shelf → group hierarchy instead of flat
categories. Items route to a specific shelf; `Inventory.md` and the UI group by
shelf. Branch introduced `config/storage_locations.json` (declarative layout +
per-group defaults), `Location/Shelf/Group` dataclasses, and `route_item()`.

- Declarative kitchen-layout schema (zones, shelves, item groups)
- Per-shelf grouping in the rendered inventory + a sidebar zone picker
- Native equivalent: the shipped `InventoryView` (see Done/Shipped) organized
  by zone/shelf instead of flat category

### Inventory: markdown receipt-paste ingestion

**Source:** `claude/kitchen-inventory-system-EdBZI` @ `f19dcec`
**Status today:** DONE via a different path. `lib/receipt_paster.py` +
`POST /api/inventory/paste` (preview-then-commit) + `paste_inventory.py` CLI
already ship this on `main` — see `CLAUDE.md` / `docs/API.md`. Kept here only
for branch-provenance completeness; no further work needed.

### Inventory: expiry tracking + default expiry windows

**Source:** `claude/kitchen-inventory-system-EdBZI` @ `f19dcec`
**Status today:** DONE. `config/expiry_windows.json` (`by_item`/`by_category`
default windows) + `lib/expiry.py:compute_expires`/`expiry_status` ship on
`main`, and the native inventory cleanup screen (Done/Shipped above) surfaces
the UI warnings this item asked for. Kept for branch-provenance completeness.

### Inventory: printable kitchen labels

**Source:** `claude/kitchen-inventory-system-EdBZI` @ `f19dcec`
**Status today:** GAP. No label generation in `main`.

Generate a printable `Kitchen Labels.md` (shelf/zone labels) from the layout
config. Branch had `templates/labels_template.py`, `manage_inventory.py
--labels`, and `scripts/generate_labels.py`. Lowest priority of the set — blocked
on the zone+shelf layout landing first (labels need real shelf/zone data).

---

### Ingredients: ML parser with confidence scoring

**Source:** `feature/ingredient-parsing` @ `9247a01` (2026-01-08)
**Status today:** **Done / opt-in.** `main` ships `lib/ingredient_ml.py`
(`ingredient-parser-nlp`, needs Python 3.11+, `requirements-ml.txt`) as an
optional fast-path returning `{amount, unit, item, preparation, confidence}`.
`lib/ingredient_parser.py:parse_ingredient_best()` uses it only when
`KITCHENOS_ML_INGREDIENTS=1` and confident, falling back to the rule-based
parser + cleaner otherwise (which already emits explicit `needs_review` flags
for low-confidence / edge cases). Off by default. This closes the branch idea —
no further work needed; the "optional fast-path, not a replacement" framing the
branch recommended is exactly how it shipped.

---

### Meal plan: timed calendar events

**Source:** `feature/timed-meal-events` @ `bbb5ec1` (2026-01-10)
**Status today:** **Done.** `main`'s calendar sync (`lib/ics_generator.py`,
`sync_calendar.py`) emits a separate 30-minute timed event per meal slot
(breakfast 8:00, lunch 12:00, snack 15:00, dinner 19:30 — see `MEAL_TIMES` in
`lib/ics_generator.py`), marked `TRANSP:TRANSPARENT` (shown as free). Matches
what the branch proposed; no further work needed.

> Note: the branch also *removed* `MealEntry` / `flatten_to_recipes()` from the
> parser — that dropped composite `[[Meal: Bundle]]` expansion and was a
> regression that was correctly **not** ported. `main` keeps composite-meal
> expansion.
