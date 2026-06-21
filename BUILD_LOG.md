# Build Log — Siri / App Intents

Running record of autonomous/assisted build sessions. Newest entries at the top.
Each entry: what ran, what passed/failed, what committed, and anything that blocked.

## How this is used

- **Plan A (overnight-runnable):** `docs/superpowers/plans/2026-06-21-siri-backend-phase0.md`
- The executing run appends one section per task: tests run + result, commit hash,
  and a STOP note if it hits anything outside its scoped permissions.
- Branch: `siri-app-intents`. Nothing is pushed.

---

## Session log

### 2026-06-21 — Plan A (backend Phase 0), assisted hands-off run

**Done & committed (clean, isolated — only `api_server.py` + new test files):**
- Task 1 — ingredient filter on `GET /api/recipes?ingredient=` — `8b7d922`. 4/4 tests pass.
- Task 2 — optional bearer-token auth (`require_token`, localhost-exempt) on the 5
  Siri-facing routes — `6b2edb5`. 5/5 tests pass.
- Targeted regression (api + recipes + recipe_index): **69 passed.**

**Paused before Task 3 (docs) — needs a human decision:**
- The working tree was **already dirty before this session**: ~15 files carry an
  uncommitted **path-migration** changeset (`~/KitchenOS/` & `~/GitHub/KitchenOS/` →
  `~/Dev/KitchenOS/`) across `CLAUDE.md`, `README.md`, `batch_extract.py`,
  `generate_meal_plan.py`, `ingest_receipts.py`, `ops/*.plist`, `requirements.txt`,
  `sync_calendar.py`, `scripts/update_dashboard_canvas.py`. **Not created by this run.**
- My Task 3 doc edits to `CLAUDE.md` (ingredient param + `KITCHENOS_API_TOKEN`) are
  currently **intermingled** with that pre-existing `CLAUDE.md` path edit — so I did
  NOT `git add` it, to avoid bundling unrelated work under a Siri commit.

**Full-suite failures (5) — INVESTIGATED: all pre-existing in committed code, NOT
caused by Plan A or by the uncommitted changeset:**
- Root cause: a **"snack" meal-slot** added to the data model without updating older
  tests.
  - `test_ics_generator` (3): `format_day_summary` now emits `B / L / S / D`; tests
    assert the old `B / L / D`. `lib/ics_generator.py` is unmodified → change is committed.
  - `test_sync_calendar` (1): same snack staleness in `collect_all_days`. The only
    working-tree edit to `sync_calendar.py` is a `setproctitle(...)` line in `__main__`,
    which cannot affect the tested function.
  - `test_normalizer` (1): module and test both unmodified → committed behavior.
- The uncommitted changeset is **path-migration + `setproctitle` (`__main__` blocks
  only)** — it does not touch any tested function.
- Recommendation: these stale tests should be fixed in a separate cleanup, independent
  of the Siri work.

**Resolution (same session):**
- Pre-existing changeset committed on its own — `6082fb3` "chore: migrate paths to
  ~/Dev and set LaunchAgent proctitles" (peeled my doc edits out of CLAUDE.md first so
  they wouldn't bundle).
- Task 3 docs committed clean — `835b08c` "docs: document ingredient filter and
  KITCHENOS_API_TOKEN".
- Stale snack-slot tests fixed — `test: update stale tests for snack slot, MealEntry,
  and unwrapped unknowns`. **Full suite now: 665 passed, 1 skipped, 0 failed.**

**Plan A: COMPLETE.** All three tasks committed; tree clean; full suite green.

### 2026-06-21 — Plan B Phase 1 (KitchenOSKit Swift package), executed on the Mac

Toolchain: Swift 6.4, Xcode 27, macOS 27. All 7 tasks built + committed; `swift test`
green (9 tests).

- Task 1 — package skeleton + CredentialStore (Keychain/in-memory) + KitchenOSConfig.
- Task 2 — Codable models (RecipeSummary/Detail, MealPlan/Day/SlotValue, Suggestion).
- Task 3 — WeekDate ISO week-id helper.
- Task 4 — async KitchenOSClient + MockURLProtocol tests (ingredient query, bearer, HTTP error).
- Task 5 — DayOfWeek/MealSlot AppEnums + RecipeEntity (EntityStringQuery).
- Task 6 — five App Intents. **Platform floor raised to macOS 15 / iOS 18** (tools 6.0,
  Swift 5 language mode) to use the non-deprecated
  `requestConfirmation(actionName:dialog:)` for the add-to-plan confirmation gate.
- Task 7 — AppShortcutsProvider with Siri phrases.

**Plan B Phase 1: COMPLETE** (builds clean, tests green). Remaining: **Phase 2**
(Xcode project + macOS/iPad app targets + signing + on-device Siri) — interactive,
must be done in Xcode.
