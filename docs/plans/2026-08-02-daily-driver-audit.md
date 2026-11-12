# KitchenOS — End-to-End Audit & Daily-Driver Plan

**Date:** 2026-08-02 · **Branch audited:** `main` @ `592dac4` · **Method:** live-state measurement
against the running system, plus five parallel read-only code audits (one per stage).
**Goal being judged against:** *"a daily driver that helps me plan and cook."* Bells and
whistles explicitly deferred.

Every number here was measured today. Nothing is estimated.

---

## 1. The verdict in one paragraph

KitchenOS has every part a daily driver needs and almost none of the connections. Capture is
dead at the front door, the numbers in the middle are wrong *and* certified trustworthy, the
planner's headline assist silently stopped working, cooking records nothing, and the shopping
list is roughly one-third noise. None of this presents as a failure. **That is the actual
finding:** the system was built to degrade gracefully, and it has degraded so gracefully that
it no longer tells you when it isn't working.

---

## 2. The through-line: ten silent failures

Every stage produced at least one defect that fails without an error, a log line, or a
changed pixel. This is one pathology, not ten bugs.

| # | What broke | How it presents |
|---|---|---|
| 1 | Batch-extract lacks Full Disk Access | Empty directory listing → "Not a URL" forever |
| 2 | `analyze_failures.sh` can't find `claude` | 276 × silent exit; *"Analysis agent triggered"* printed anyway |
| 3 | Suggest disabled on board weeks | Early `return`, no toast — tap does nothing |
| 4 | `/reprocess` points at a deleted path | `FileNotFoundError` → generic error page |
| 5 | SDK retries defeat `llm_gate` | 8s budget becomes 11–25s, no signal |
| 6 | Obsidian "Add to Meal Plan" on a board week | Wikilink written, then erased by next regen |
| 7 | Wrong macros | `nutrition_coverage: 1.0`, `needs_review: false` |
| 8 | `apply_decisions` (the only decrement path) | Dead code — its caller is never called |
| 9 | `prune_expired` behind an early `return` | Ran 4 times ever; comment says "Daily" |
| 10 | `macro_eligible` gates on coverage | Certifies the least plausible recipes |

**Implication for the plan:** a status surface that can distinguish *"working"* from *"quietly
not working"* is not polish. It is the thing that would have caught all ten. It is Phase 1.

---

## 3. Stage-by-stage findings

### 3.1 Capture — dead at the front door

- **725 hourly batch runs over 30 days produced 18 recipes.** 719 runs captured zero.
- **Share-sheet capture is 100% dead.** Share-sheet URLs live in a Reminders Core Data
  attachment; reading it needs Full Disk Access on the shim launchd execs
  (`ops/agents/KitchenOS · Batch Extract`), not on `.venv/bin/python`. A TCC denial returns an
  *empty listing*, not an error — `lib/reminders_url.py:51`. 73 consecutive warnings logged.
- **Instagram: 282 failures, 0 successes.** Needs `INSTAGRAM_COOKIES_FROM_BROWSER`; absent
  from `.env`. The code already emits the exact fix string.
- **The queue never drains.** No attempt counter exists (`batch_extract.py:294-298`,
  `:352-365`). Permanently-dead items are retried hourly forever, generating a failure JSON
  and a (broken) AI analysis trigger each time.
- **`/reprocess` — the Re-extract button in all 252 recipe notes — has never worked** since
  the macOS 27 rebuild. `api_server.py:1219` hardcodes `cwd='/Users/chaseeasterling/GitHub/KitchenOS'`.
  The sibling `/extract` at `:917` resolves dynamically. *Verified: path does not exist.*
- **`/refresh` silently strips data.** Rebuilds frontmatter without `banner`, `nutrition_*`,
  `short_title`, `fit_*`, `meal_occasion` (`api_server.py:1135-1154`), then writes the fixed
  template keys over the file.
- **`needs_review` is 249/252 (99%) — pure noise.** Three producers force it; one is a
  hardcode at `lib/crouton_parser.py:126` for all 122 Crouton imports. Nothing consumes or
  clears it.

**Ingredient census, 2,760 rows:** 143 rows apply a count unit (`whole`) to a liquid or powder
("1 whole protein powder"); 52 carry garbage units (`minutes`, `°f`, `calories`, `sqirt`); 7
are durations, not ingredients. Root cause: `import_crouton.py` — **48% of the corpus** —
never calls the ingredient validator at all, and `ingredient_parser.py:307-308` manufactures
`unit: "whole"` for anything unparseable. `ingredient_cleaner.py` *detects* these and then
discards the flags before they reach the file (`:244`).

### 3.2 Nutrition — wrong, and trusted

The highest-stakes finding in the audit.

- **45/248 recipes (18%) fail trivial plausibility bounds. 35 of those 45 (78%) pass
  `macro_eligible`.** 152/247 (62%) carry at least one line-level resolution defect.
- **The suggester recommends its own worst data.** Measured against real targets (190 g P /
  2300 kcal, empty day): ranks 1–4 are Chipotle Burrito (178 g protein/serving), Tofu Scramble
  (229 g), PB Coffee Smoothie (244 g), Earl Grey Pie (153 g) — the four most broken recipes in
  the corpus, all `nutrition_unknown: false`, surfaced with *"Adds 244g protein toward your
  remaining 190g today."* With `macro_fit ≥ 0.5` the macro tier returns the top pick
  **directly, bypassing Claude** (`lib/meal_suggester.py:619-624`).

**Five root causes, each verified:**

1. **Portion-ledger package weights** (67 recipes). `protein powder | whole | 300 g`, an Ollama
   guess from 2026-07-10. The band check is `if g > 300.0` (`lib/fdc_local.py:191`) — **300.0
   exactly passes**, and Ollama answers round numbers. No ceiling at all for `can`
   (`refried beans | can | 800 g`) or non-bulk `whole` (`monterey jack | whole | 454 g`).
2. **Every egg scores as dried egg white** — 51 lines in **49 recipes (20% of corpus)**.
   `_STOPWORDS` deletes "raw"/"fresh" from both stored names and queries
   (`fdc_local.py:23-29`), then a Foundation rank bonus puts "Egg, white, dried" (79.9 p/100g)
   above "Egg, whole, raw, fresh" (12.6). **6.3× protein per egg.**
3. **`resolution_guard.vet` is never called on the primary resolver** —
   `nutrition_engine.py:197` returns before the vet at `:264`, which guards only the secondary
   network path. Yields `ground cumin → Flaxseed, ground` (×11), `butter bean purée → Butter,
   stick` (5,134 kcal, double-counted).
4. **Frying medium counted as eaten** (15 recipes). 4,032 of the Chick-Fil-A nuggets'
   4,561 kcal/serving is fryer oil.
5. **Unresolved-but-caloric silently contributes zero** (48 recipes) — Mac And Greens: 7 kcal.

**The trust gate.** `macro_eligible` tests three things: calories non-null, `coverage ≥ 0.8`,
`servings` non-null. Coverage means *"did every line match some food and get some grams"* —
every failure mode above **increases** it. The engine *does* compute `sanity_flags`, and
nothing downstream reads them (`meal_planner.html:2209` documents deliberately ignoring the
flag because it fires on 146/252).

> **Correction to an assumption we started with:** an Atwater 4/4/9 consistency check is
> useless here — it flags exactly **1** recipe, because kcal and macros derive from the same
> wrong grams and are wrong *proportionally*. The validator must use absolute bounds.

**Proposed validator** — `kcal ∉ [50, 1200] ∨ protein > 70g ∨ (protein·4 > 0.65·kcal ∧ kcal > 200)`.
Flags **45/248 (18.1%)** and catches every disaster traced above.

**Cruelest detail:** `/nutrition-review` sorts *ascending* by coverage (`api_server.py:3045`),
so the coverage-1.0 catastrophes sit at the **bottom** of the queue built to catch them.

### 3.3 Plan — the assist is off, and looking writes files

- **P0: suggest is dead on any week with a cook.** `templates/meal_planner.html:5173` returns (was :5070 before that block was deleted)
  early, silently, when `weekBoard.cooks.length > 0`. One dropped recipe converts a week to
  board mode — so the feature dies on contact, while `/plan-week` step 1 instructs you to
  "tap a blank slot and hit suggest." *Verified.*
- **`GET /api/meal-plan/<week>` writes a file** (`api_server.py:1254-1264`), and planner nav
  calls it per click with unbounded prev/next. `2026-W52`, `2027-W01`, `2030-W20` are output
  of a live code path — and `sync_calendar.py` globs them into your subscribed calendar.
- **Obsidian "Add to Meal Plan" into a board week loses the recipe.** `api_server.py:2000-2023`
  writes a wikilink with no ledger guard; the next chip drag's regen erases it, and
  legacy-import skips weeks that already have cooks. No trace.
- **"Add to this week" creates invisible cooks.** They render only inside the *Freezer* tab's
  Unscheduled tray, so the add looks like it failed and you re-click. Cooks 20/21 are
  identical 3 seconds apart; 22/27 are the same recipe re-added a day later. There is no
  idempotency on `POST /api/cooks`.
- **Two official numbers for the same day.** Vault `2026-W32.md` says Monday = 2390 kcal; the
  ledger API says 580. Markdown regenerates only on ledger mutations, so the Aug 1 nutrition
  backfill fixed the DB and left the note lying.
- **Composite meals: ~1,000 LOC, zero uses, unreachable.** `Meals/` does not exist. Board mode
  *rejects meal drops with a toast* (`meal_planner.html:2553-2560`) and every week you plan is
  a board week — so the feature cannot be reached from the only flow in use, while still
  appearing in the drag handler, tap-to-assign, card sheet, save serialization, and suggest
  flattening.

  > **Corrected 2026-08-03.** Two of these were already stale when written and are now
  > resolved. `Meals/` *did* exist — the `plates` branch seeded 16 hand-authored plates into
  > `vault/KitchenOS/Meals/` the same day this audit was written. And the resolution inverted:
  > composite meals were **kept and made ledger-native**, not removed. A plate now expands to
  > one ordinary cook per sub-recipe sharing `cooks.bundle_id`, both refusals are gone, and its
  > macros land in the day-totals row. See `docs/completed/2026-08-03-plates-ledger-native.md`.
- **Cross-week write bug:** `navigateWeek` doesn't cancel the pending `debounceSave`
  (`meal_planner.html:4269-4283`); editing a legacy week and clicking next within 500 ms
  serializes week A's cards into week B's file.

### 3.4 Cook — the flagship page is the slowest, and the loop measures the wrong thing

- **`/prep` takes 11.2s; every other page is under 0.25s.** Cause: `llm_gate`'s budget is
  passed as the SDK's `timeout=`, which is **per-attempt**, and the SDK defaults to
  `max_retries=2`. Neither `task_extractor.py` nor `recipe_grid.py` passes `max_retries=0`
  (*verified: zero occurrences in `lib/`*). Worst case ≈25s before Ollama is even considered.
  The page renders synchronously — the user sees a blank tab for the duration.
- **It re-arms constantly.** `week_view.py:119` rewrites the plan `.md` unconditionally on
  *every* ledger mutation — including a PATCH that only records a verdict and changes nothing
  in the markdown. The tasks sidecar is mtime-keyed. **Recording a verdict re-arms an
  11-second render.**
- **Recipe-card sidecar coverage is effectively 0/252.** Only 5 exist, and all 5 are stale
  right now, because the nightly enrich agent rewrote 68 recipe files.
- **The feedback loop mismeasures.** `cook_history.py:55` sets `cook_count` from planned rows
  and prefers the planned date over `cooked_at` — your two never-cooked floating Ginger-Lime
  cooks produce `cook_count: 2`. Ten recipes carry `last_cooked` against two real cooks.
- **The whole verdict apparatus is write-only.** `cook_count`, `make_again_count`,
  `observed_servings`, `last_cooked` are consumed by **nothing** repo-wide. The verdict-nudge
  agent works correctly, delivering Reminders that point at a two-taps-deep control which
  rewards you with nothing.
- **"Mark cooked" bundles a scary inventory-subtraction `confirm()`** into what should be a
  memory act, and the 🍳 button is `display:none` on touch — on the phone, at the stove, it's
  two non-obvious taps plus a dialog. Hence 2 of 16.
- **`/api/cook` and the ledger fork the truth** — the legacy grid button and MCP `cook_recipe`
  decrement inventory without stamping any `cooks` row, so those cooks are invisible to
  verdict-nudge and history forever.

### 3.5 Shop & Stock — the loop is open at both ends

- **`last_used` set on 0 of 213 rows; `use_count > 0` on 0.** The stamping code merged
  2026-07-27 and is running; `POST /api/cook` has been called **4 times ever**, the 2
  successes predating the merge. Since then, 12 new cook rows and **zero** marked cooked.
- **The designated decrement path is dead code.** `apply_decisions` is reachable only from
  `POST /api/shopping-list/confirm` with non-empty `decisions`. Its UI trigger,
  `startShoppingListFlow`, is **defined at `meal_planner.html:4923` and called from nowhere**
  (*verified: one occurrence in the entire codebase — its own definition*). The iOS app sends
  `decisions: []`. Only the Mac-only terminal prompt works.
- **Auto-age-out is fiction for 80% of stock.** `prune_expired` is called only from
  `generate_meal_plan.py:205`, which sits *after* the early `return` at `:166-168` — so it
  fires roughly once a week. It has run **4 times ever**. Compounding it,
  `config/expiry_windows.json:28` gives category `pantry` a **365-day** window: 173 of 213
  rows cannot age out for ≥11 months.
- **Inventory is unit-starved.** 185/213 rows are `ct` — the ingest default meaning "one
  package" — while recipes ask in tsp/cup/g. `unit_compatibility` correctly refuses, so ~17
  owned items land on every list.
- **The list is ~⅓ noise.** Simulated read-only against the real pantry: W31 → 55 lines, 52 on
  the buy list, 23 cross-unit warnings, and **5 of 7 credits are wrong** — including
  `sugar-free condensed milk` credited against `granulated sugar` (it vanishes from the list;
  you reach the stove without it), `garlic clove` credited against `Garlic powder`, and two
  items credited from stock that **expired 2026-07-31** because `load_pantry` discards
  `expires`.
- **Demand is inflated up to 3×** by duplicate cook rows (Smashed Beef Kabobs ×3).
- **The CLAUDE.md "zero occurrences" claim for the `unit_compatibility` delegation gap is now
  false** — there is 1 live hit, in this week's plan.
- **Receipt ingest is genuinely healthy** — UNIQUE `source_id` dedupe, atomic trip+purchases,
  hourly agent alive today. Caveat: trip→inventory is not one transaction, so a crash loses
  stock permanently behind the dedupe.

---

## 4. The plan

Sequenced so that each phase makes the next one's work verifiable. Phase 1 is deliberately
"make it honest" before "make it right" — an honest system that says *"I don't know"* is
usable today; a confident wrong one is not.

### Phase 0 — Unblock (you, ~30 min, no code)

1. Grant Full Disk Access to `ops/agents/KitchenOS · Batch Extract` (**the shim, not the
   interpreter**). Verify functionally — a TCC denial looks like success with empty results.
2. Add `INSTAGRAM_COOKIES_FROM_BROWSER=safari` to `.env`, logged into instagram.com there.
3. Delete junk data: ledger cook 5 + its placements, duplicate cooks 20/21, and the
   `2026-W52` / `2027-W01` / `2030-W20` plan files + sidecars.

### Phase 1 — Stop lying (~1–2 days, no backfill required)

The highest value-per-hour in the audit. Nothing here needs the corpus re-derived.

4. **Plausibility gate.** New `implausible()` beside `macro_eligible` in
   `lib/nutrition_quality.py`; make `macro_eligible` fail on it. Wire into
   `meal_suggester.rank_candidates`, `meal_nutrition._eligibility`,
   `serving_ledger.day_totals`. *Dethrones the entire measured top-4.*
5. **`day_totals` names what it excluded** rather than silently summing garbage.
6. **Dashboard honesty** — an unplanned week must not read as a starvation week; treat null
   calories as missing, not 0.
7. **Re-rank `/nutrition-review` by violation magnitude**, not ascending coverage.
8. **Fix the three dead controls:** `/reprocess` cwd (one line), `analyze_failures.sh` PATH
   (or delete the agent), `/refresh` frontmatter preservation.
9. **A status surface that can fail loudly** — extend `/system-health` to assert the ten
   silent failures above: is FDA readable, is the queue draining, when did prune last run, how
   many recipes are implausible, are sidecars fresh.

### Phase 2 — Close the loops (~2–3 days) — *this is what makes it a daily driver*

10. **Unbreak suggest on board weeks** — accept path creates a cook; delete the `:5070` block.
11. **`max_retries=0`** on the four LLM call sites + **`write_week_markdown` no-ops on
    unchanged content** + precompute tasks off-request. `/prep`: 11s → ~10ms, permanently.
12. **Consume on `cooked_at` transition, server-side**, so every surface that records a cook
    closes the loop once. Plus a nightly sweep for planned-and-passed cooks *(see Decision A)*.
13. **One-tap verdict card** on home and `/prep` — *"How was X? 👍 👎"* → single PATCH. Drop the
    scare `confirm()`; add 🍳 to `/recipe/<name>` and `/cook-now`.
14. **Fix `cook_history` semantics** (cooked ≠ planned) *before* anything consumes it, then
    make verdicts matter in suggester ranking.
15. **Idempotency on `POST /api/cooks`**; make `GET /api/meal-plan/<week>` read-only; guard
    `/add-to-meal-plan` on ledger weeks.

### Phase 3 — Fix the numbers (~2–3 days + backfills; offline re-derive is 3s)

16. Purge and re-band the portion ledger (`>` → `>=`, ceilings for `can` and non-bulk `whole`,
    extend `_BULK_SUBSTANCES`). *67 recipes.*
17. Call `resolution_guard.vet` on the fdc-local path; penalize candidate-only state words so
    "egg" resolves to whole raw egg. *~60 recipes including all 49 egg recipes.*
18. Frying-medium rule. *15 recipes.*
19. Corpus cleanup: `clean_ingredients.py --apply`, validation on the Crouton path, re-derive
    `needs_review` from real signals so it stops meaning nothing.

### Phase 4 — Make the list true (~2 days)

20. **Container-aware crediting** — a `ct` package against a tsp/cup ask becomes *"have a
    package — check quantity"*, not a buy line. *The single biggest accuracy win available
    without re-unitizing inventory.*
21. Staple-aware list; close the delegation gap; exclude expired stock from credits; fix the
    compound-food matcher (garlic powder ≠ garlic).
22. Un-trap `prune_expired` and re-tune the 365-day pantry window.

### Phase 5 — Simplify *(needs your decisions)*

23. Retire the legacy markdown week model *(Decision B)*.
24. ~~Remove composite-meal UI, keep the parser~~ **DONE, inverted (2026-08-03):** composite
    meals were kept and made ledger-native — a plate is now a bundle of ordinary cooks and
    contributes its macros to the day-totals row *(Decision C)*.
25. ~~Freeze the native app; collapse nav from 12 rows to ~6 in two tiers~~
    **RESOLVED, inverted (2026-08-12): keep at parity and invest** *(Decision D)* —
    the native app is the only possible Siri surface, so the nav-collapse premise
    (freeze it, shrink it) doesn't apply.

---

## 5. Decisions required

- **A — Consume-on-cook policy.** Auto-assume planned = cooked via a nightly sweep (honors
  "additive, never a chore"; risks depleting stock for a meal you skipped), or explicit-only
  (accurate, but the last 12 cooks say you won't tap it)?
- **B — Legacy week model.** Retire it now (M–L; deletes the four most fragile guards in the
  codebase) or keep paying the two-model tax on every planner change?
- **C — Composite meals.** Remove ~1,000 LOC of unreachable UI, or keep it?
- **D — Native app.** ~~Freeze (recommended) or keep at parity?~~ **Resolved
  2026-08-12: keep at parity and invest.** The native app is the only possible
  Siri surface; the iOS 27 new-Siri feature
  (`docs/superpowers/specs/2026-08-12-ios27-new-siri-design.md`) builds on it.
