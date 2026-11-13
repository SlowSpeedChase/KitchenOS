# Landing log — plan `docs/superpowers/plans/2026-11-10-land-unmerged-work.md`

## Map drift found at A0 (2026-11-11)

The plan's map was stale by the time execution started:

- `origin/main` had moved to `6e9f482` (PRs #82 `fix/recipe-add-to-plan`, #83 `feat/print-recipes`, #84 dislike guard all merged). Local `main` (`e72aafb`) is behind; not moved.
- **`fix/recipe-add-to-plan` is merged (PR #82)** and its worktree is clean → Task A4 Step 1 and Task C5 are moot.
- New branch `release/mac-apple-plus-recipe-add` (`.worktrees/release-recipe-add`) combines `21bf60b` + recipe-add + origin/main. Local tip `80e8908` was unpushed (remote at `21a6d8b`). This is a second route to Task C3 — decide which one lands.
- Extra detached worktree `~/.codex/worktrees/weekly-cooking-packet` @ `34e4563` (3 doc commits ahead of main).
- Main checkout: 62 dirty entries (61 + new untracked `.claude/worktrees/`).

## Baseline (origin/main @ 6e9f482)

- Unit suite: **4346 passed, 1 failed, 1 skipped, 139 deselected** (28 s).
  - Pre-existing failure: `tests/e2e/test_recipe_corpus_schema.py::test_the_corpus_has_no_schema_violations` (validates the live vault corpus; it runs in the default selection despite its `e2e/` path). Not investigated — out of scope for Phase A.
- Ruff: **162 errors**.
- Bar for later tasks: ≥ 4346 passing, no failures beyond the corpus-schema one, ruff ≤ 162.

## Environment notes

- The Claude Code sandbox blocks writing `.claude/agents/*` and `.mcp.json`, so `git worktree add` must run unsandboxed in this repo.
- Browser tests (`tests/test_cooking_packet_render.py`) can't launch Chromium inside the sandbox; they pass when run unsandboxed.
- `gh` fails TLS in the sandbox (x509 OSStatus -26276); PR steps need it unsandboxed.

## A1 — detached Mac Apple work → branch (2026-11-11)

- `~/.codex/worktrees/mac-apple-integration/KitchenOS` switched to new branch `codex/mac-apple-integration` @ `21bf60b`, pushed to origin.
- Untracked there (left as-is): `AGENTS.md`, `output/`.

## A2 — snapshots (2026-11-11)

| Checkout | Backup branch (pushed) | Untracked tarball | Dirty count before/after |
|---|---|---|---|
| main checkout | `backup/2026-11-10-main-checkout` @ `93e2c73` | `~/KitchenOS-backups-2026-11-10/main-checkout-untracked.tgz` (10 MB, includes `.claude/worktrees/`, `output/`) | 62 / 62 |
| weekly-cooking-packet | `backup/2026-11-10-weekly-cooking-packet` @ `3caabb0` | `weekly-cooking-packet-untracked.tgz` (33 KB) | 20 / 20 |
| receipt-openai | `backup/2026-11-10-receipt-openai` @ `8f569b9` | `receipt-openai-untracked.tgz` | 9 / 9 |
| recipe-add-to-plan | — skipped, clean (merged as PR #82) | — | 0 |

## A3 — weekly-cooking-packet committed (2026-11-11)

- Tests as found (7 files): **521 passed** (499 in sandbox + 22 browser tests that pass unsandboxed).
- Commit `874f471` "wip: cooking packet API, render, jobs and templates…", pushed to `origin/codex/weekly-cooking-packet`. Only cooking-packet / recipe_phases / conftest / web_dashboard test / docs paths were staged.

## A4 — receipt-openai committed (2026-11-11)

- Commit `1b247ab` "wip: OpenAI receipt extraction…", pushed to `origin/codex/receipt-openai`. 9 files: `.env.example`, `README.md`, `docs/ARCHITECTURE.md`, `ingest_receipts.py`, `lib/receipt_parser.py`, `prompts/receipt_extraction.py`, `requirements.txt`, `tests/test_receipt_parser.py`, `tests/test_receipt_openai.py`.
- recipe-add-to-plan: nothing to do (merged, PR #82).

## A5 — main checkout classification (2026-11-11)

Method note: the plan's script uses `git diff <branch> -- <file>`, which ignores untracked files and reported every one as DIFF. Re-run with a direct content compare (`git show <branch>:<file> | cmp - <file>`), plus a per-file count of lines that exist in the working copy but in none of `codex/mac-apple-integration`, `codex/receipt-openai`, `origin/main`.

### UNIQUE — exists nowhere else; Task C7 must carry these

| File | Verdict | Reason |
|---|---|---|
| `lib/health_assertions.py` | UNIQUE | `check_api_billing()` — a /system-health check for exhausted Anthropic credits. **Overlaps Task B2** (enrichment health); reconcile the two before writing B2. |
| `lib/failure_logger.py` | UNIQUE | `api_billing` error category + `_API_BILLING_PATTERNS` (feeds the check above). |
| `templates/system_health.html` | UNIQUE | colours `api_billing` red (one line). |
| `config/item_aliases.json` | UNIQUE | 179 learned alias lines. |
| `config/storage_locations.json` | UNIQUE | 2 learned placements (`creamy peanut butter`, `onion and chive cream cheese`). |
| `AGENTS.md` | UNIQUE | untracked; Task D2. |
| `docs/superpowers/plans/2026-09-05-calendar-opportunities.md` | UNIQUE | untracked plan, on no branch. |
| `docs/superpowers/plans/2026-09-24-phone-surface-and-connectivity.md` | UNIQUE | untracked plan, on no branch. |
| `docs/superpowers/specs/2026-10-09-food-observation-capture-design.md` | UNIQUE | untracked spec, on no branch. |
| `docs/superpowers/plans/2026-11-10-land-unmerged-work.md` | UNIQUE | this plan; Task D3 commits it. |

No branch anywhere contains `api_billing` (checked origin/main, mac-apple, release, weekly-cooking-packet).

### SAME — byte-identical copy already committed

- In `codex/receipt-openai` (`1b247ab`): `.env.example`, `README.md`, `ingest_receipts.py`, `lib/receipt_parser.py`, `prompts/receipt_extraction.py`, `requirements.txt`, `tests/test_receipt_parser.py`, `tests/test_receipt_openai.py`.
- In `codex/mac-apple-integration` (and the release branch): `KitchenOSKit/Package.swift`, `KitchenOSKit/Sources/KitchenOSKit/CookingAvailability.swift`, `…/Resources/planning-auth.js`, `KitchenOSKit/Tests/KitchenOSKitTests/CookingAvailabilityTests.swift`, `KitchenOSSiri/Sources/CookingAvailabilityModel.swift`, `KitchenOSSiri/Sources/MealPlan/MealPlanView.swift`, `…/PlannerBoardView.swift`, `lib/recipe_schema.py`, `lib/cooking_availability.py`, `lib/cooking_windows.py`, `lib/planning_calendar.py`, `docs/superpowers/plans/2026-09-19-calendar-meal-planning.md`, `docs/superpowers/specs/2026-09-19-calendar-meal-planning-design.md`, `tests/e2e/test_cooking_availability.py`, `tests/test_cooking_availability.py`, `tests/test_cooking_windows.py`, `tests/test_planning_calendar.py`.

### SUPERSEDED — earlier draft of calendar work that the Apple branch rewrote

The working copy has a few lines the Apple branch lacks, but the Apple branch has far more lines the working copy lacks (e.g. `serving_ledger.schedule_*`: working copy requires `servings_to_eat`, Apple branch evolved it to `float | None` + `expected_unplaced`). Read as an older iteration. Preserved in `backup/2026-11-10-main-checkout` regardless.

| File | WC-only lines | Apple-only lines |
|---|---|---|
| `KitchenOSSiri/Sources/CookingCalendarSettings.swift` | 80 | 65 — **largest rewrite; worth a human glance in C7** (WC draft used EventKit directly with an `isLocalServer` guard) |
| `docs/superpowers/plans/2026-10-15-siri-web-navigation.md` | 34 | 57 |
| `docs/ARCHITECTURE.md` | 17 | 245 |
| `static/planning-calendar.js` | 16 | 80 |
| `lib/serving_ledger.py` | 16 | 125 |
| `docs/OPERATIONS.md` | 6 | 326 |
| `templates/meal_planner.html` | 4 | 76 |
| `KitchenOSSiri/Sources/MealPlan/PlanningCalendarWebView.swift` | 3 | 9 |
| `docs/API.md` | 2 | 449 |
| `KitchenOSKit/Sources/KitchenOSKit/PlanningWebPolicy.swift` | 2 | 3 |
| `KitchenOSSiri/Info-macOS.plist` | 1 | 8 |
| `KitchenOSSiri/Sources/KitchenOSSiriApp.swift` | 1 | 4 |
| `api_server.py` | 1 | 300 |
| `tests/test_cook_schedule.py`, `lib/inventory_db.py`, `KitchenOSSiri/Info-iOS.plist`, `KitchenOSKit/Tests/KitchenOSKitTests/PlanningCalendarTests.swift`, `KitchenOSKit/Sources/KitchenOSKit/PlanningCalendar.swift`, `tests/e2e/test_planning_calendar.py`, `static/planning-calendar.css`, `docs/superpowers/specs/2026-10-15-siri-web-navigation-design.md`, `KitchenOSSiri/Sources/SettingsView.swift` | 0 | >0 — pure subsets |

### Untracked noise (in the tarball; not code)

`.agents/skills/*`, `.codex/*`, `.claude/worktrees/{modest-mclaren-74c3fa,sleepy-robinson-b2b8e9}` (30 MB, nested Claude worktrees), `.playwright-mcp/`, `output/` (food-playlist import, PDFs, recipe review). Task D3 adds the ignore rules.

## Phase A status: COMPLETE (2026-11-11)

Nothing is now held only in a working tree: every dirty checkout has a pushed backup branch + tarball, and the two WIP branches are committed and pushed.

## B1 — production checks (2026-11-12)

Checked directly rather than asking:

- **API server: up.** `curl localhost:5001/health` → 200 `{"status":"ok"}`; `com.kitchenos.api` running. `logs/server.log` is just stale (last line 2026-09-27) — not an outage.
- **Nightly enrichment: still failing.** `logs/enrich-latest.json` (written 2026-11-12 03:00): 255 complete, **215 error**, all "credit balance is too low".
- **yt-dlp:** still `2026.06.09` (Instagram TLS error unaddressed).
- **Human decision: credits are not a priority right now.** Enrichment left failing on purpose; no agent disabled.

## B2 — SKIPPED by human decision (2026-11-12)

Nothing depends on it (it only adds a /system-health report). Not built. The main checkout's unique `api_billing` work (`lib/health_assertions.check_api_billing`, `lib/failure_logger` `api_billing` category, `templates/system_health.html` badge) is still only in the main checkout + `backup/2026-11-10-main-checkout` — Task C7 must still carry or consciously drop it. Note for whoever picks it up: that code is untested, reads `failure_logs` entries as whole log files (`categories`) while `check_instagram_cookies` reads the same list as individual failures (`error`), and puts `rate_limit_error` under billing (a rate limit is not exhausted credit).

The empty `fix/enrichment-health` branch was renamed to `docs/retry-cap-status` for B3.

## B3 — retry cap recorded as shipped (2026-11-12)

- Shipped in `870c5e9` (2026-08-24); 9 `dead_letter`/`retry` tests pass.
- **Plan correction:** the cap is a flat `MAX_RETRIES = 5`, *not* category-aware — `_should_dead_letter` ignores the category it is passed. The Done note says so.
- Commit `dda306c`; draft PR https://github.com/SlowSpeedChase/KitchenOS/pull/87.
- `origin/main` moved again during Phase B: now `a24663b` (#85 local FDC resolver). Re-baseline before Phase C.

## Phase B status: COMPLETE (B2 skipped) — 2026-11-12

## Phase C re-baseline (origin/main @ db40f81, 2026-11-12)

- Unit: **4374 passed**, 1 failed (pre-existing `test_recipe_corpus_schema`), ruff **162**. PR #87 (B3) merged.

## C1 — food-density-gaps (2026-11-12)

- Merged origin/main cleanly → `7915753`. Unit 4381 passed (+7), `-k density` 10 passed, ruff 162.
- PR https://github.com/SlowSpeedChase/KitchenOS/pull/88 — **awaiting human merge**.

## C2 part 1 — fix/recipe-obsidian-link (2026-11-12)

- Prepared in parallel with C1 (independent files) to save a review round-trip.
- Merge conflict in `templates/recipe_detail.html` against #82 (recipe add-to-plan): kept the server-filled Obsidian link, dropped the old header button (#82 moved it), made the moved button start `disabled` until load. `tests/e2e/test_recipe_load_failure.py` updated for the button's new name ("Add to meal plan").
- Unit 4376 passed, `test_recipe_detail.py` 7 passed, e2e (load-failure + add-to-plan) **11 passed**, ruff 162.
- PR https://github.com/SlowSpeedChase/KitchenOS/pull/89 — **awaiting human merge**.
- Next: `codex/siri-web-navigation` (stacked on this; 73 files / ~5.6k lines vs main) once #89 merges.

## C2 part 2 + C3 — combined into one PR (#90) — 2026-11-12

- Found: `codex/siri-web-navigation`'s feature commit `e5299e9` is already an ancestor of `codex/mac-apple-integration`; the Siri branch's only unique commit was docs `40656fc`. User chose **one PR**.
- Cherry-picked `40656fc` → `0152325`; merged origin/main → `a5595a0` (conflicts: docs/API.md [kept both; /api/cooks row = main's dislike text + branch schedule rows], recipe_detail.html + test_recipe_load_failure.py [= main's add-plan row, branch's readOnly guards], plan doc [ours]).
- Ruff was 450 (branch-new files full of `a; b`). `ruff format` on branch-ADDED files only + F401/F841/E741/E402 fixes → **162**. Accidental F841 fixes on 8 out-of-scope test files reverted.
- New e2e failure `test_planner_library::test_info_button_opens_the_preview_without_navigating` — race with `setPlannerView` writing `view=` via replaceState; fixed `_open()` to wait for it (`a1031a7`). 3/3 green.
- Verification: Python 4,948 passed; e2e all green; Swift 223 passed.
- Plan boxes all unticked, but branch acceptance log shows implementation + signed-test-app App Intent runs complete; remaining = human device gates (listed in PR).
- `4ba76c0` (restore-browser-access) is NOT on main yet but IS in #90 → delete `codex/restore-browser-access` and `codex/siri-web-navigation` only after #90 merges.
- PR https://github.com/SlowSpeedChase/KitchenOS/pull/90 (draft).

## 2026-11-12 — "resolve all conflicts, repair failing tests"

- **#86** `fix/review-status-schema` (main's only failing test: corpus `review_status`/`reviewed` keys, producer `.agents/skills/recipe-review`) — merged main, 4,384 pass, pushed.
- **#91** `codex/receipt-openai` (C4) — clean merge; 19 receipt tests, no network (OpenAI client monkeypatched); env vars in `.env.example`; WIP commit message left as-is (already pushed → amend needs force-push).
- **#90** got `2923883`: `tests/e2e/test_cooking_availability.py` was missing `pytestmark = e2e`, ran in the unit suite, left pytest-playwright's session loop running → broke later `sync_playwright()` fixtures.
- **#92** `codex/weekly-cooking-packet` (C6) — merged main (doc add/add → branch superset) and #90. Duplicate cook-scheduling implementations: #90's wins; removed packet's old `schedule_cook`, duplicate POST route, `lib/cook_schedule.py`; kept conn-aware `schedules_for_week`. Fixed `inventory_db._migrate` unconditional `retailer_preferences` INSERT taking the write lock on every connect (15 `database is locked` failures). llm_gate verified. **Plan tasks 7–9 NOT built** (store lookup, store refresh, planner link + API docs) — flagged in PR.
- **#93** `ios27-new-siri` (C8) — merged main (BRANCH-STATUS.md → ours) and #90 (project.yml → scalar "27.0"; AskKitchenOSIntent → #90's finish() + branch's background task/session + decline clears proposal, new Swift test).
- **Combined simulation** main+#86+#90+#91+#92+#93 merges clean in that order: unit 5,499 pass, e2e 171 pass, Swift 232 pass, macOS + iOS Sim builds succeed, ruff 162.
- Merge order: **#86 → #90 → #91 → #92 → #93**. Remaining: C7 (main-checkout leftovers, human gate), Phase D/E.
