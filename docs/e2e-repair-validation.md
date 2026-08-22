# e2e repair — validation packet

You are a **validator**. You run the commands below in order and compare output to the
literal strings given. You do **not** fix anything. If any expected string is missing,
**STOP**, copy the exact actual output (the summary line plus any `FAILED …` lines and the
first `E   ` assertion line for each), map it with the triage table in §5, and report. Do
not retry more than once, do not edit files, do not `git` anything but the read-only
commands shown.

Working directory for every command: the worktree holding branch `e2e-repair`. From the
main checkout that is `/Users/chaseeasterling/Dev/KitchenOS/.worktrees/e2e-repair`
(if that worktree is gone, use the checkout where `git branch --show-current` prints
`e2e-repair`, or `main` after merge).

Python is always the main checkout's venv: `/Users/chaseeasterling/Dev/KitchenOS/.venv/bin/python`
(a worktree has no `.venv` of its own). `PY` below means that path.

**Do not restart the API LaunchAgent.** pytest boots its own server on a free port against
copies of the data; `com.kitchenos.api` on :5001 is irrelevant to every command here.

---

## 1. Pre-flight

```bash
cd /Users/chaseeasterling/Dev/KitchenOS/.worktrees/e2e-repair
git branch --show-current
git status --short
```
Expected: `e2e-repair` on its own line; `git status --short` prints **nothing** (clean tree).
If either differs → STOP, report the actual branch/status. (Another agent session moves
branches in the *main* checkout; this worktree should not be affected, but check.)

Confirm the data the harness copies exists (it lives only in the main checkout):
```bash
ls /Users/chaseeasterling/Dev/KitchenOS/vault/KitchenOS/Recipes | head -1
ls -la /Users/chaseeasterling/Dev/KitchenOS/data/kitchenos.db
```
Expected: a `.md` filename; a file size > 0. If missing → STOP ("harness data absent"), this
is an environment problem, not a repair failure.

## 2. Unit suite (must not regress)

```bash
PY=/Users/chaseeasterling/Dev/KitchenOS/.venv/bin/python
$PY -m pytest tests/ -q --ignore=tests/e2e -p no:cacheprovider 2>&1 | tail -2
```
Expected summary line contains: `4064 passed, 1 skipped`
(4065 collected: the 4058 of the brief plus **seven new tests** —
`tests/test_cook_now.py::TestGenerate::test_per_group_limit_keeps_every_group_reachable`
and the six in `tests/test_daily_self_clean.py`;
the 1 skipped is `tests/test_shopping_list_generator.py:49: No meal plan for 2026-W04`, a
data-dependent skip that predates this branch.)

## 3. Each repaired test ALONE (order-dependence was one of the defects)

Run each line separately. Each must print `1 passed`.

```bash
PY=/Users/chaseeasterling/Dev/KitchenOS/.venv/bin/python
$PY -m pytest -q -m e2e --tb=short -p no:cacheprovider "tests/e2e/test_planner_touch.py::TestTapToAssign::test_tap_a_recipe_then_a_slot_assigns_it"
$PY -m pytest -q -m e2e --tb=short -p no:cacheprovider "tests/e2e/test_bulk_inventory.py::test_extending_a_lapsed_row_moves_it_out_of_the_expired_block"
$PY -m pytest -q -m e2e --tb=short -p no:cacheprovider "tests/e2e/test_cook_now_filter.py::test_toggling_desserts_reveals_them_without_refetching"
$PY -m pytest -q -m e2e --tb=short -p no:cacheprovider "tests/e2e/test_verify_merged_batch.py::TestFractionalSubRecipe::test_1_5_survives_save_and_reopen"
$PY -m pytest -q -m e2e --tb=short -p no:cacheprovider "tests/e2e/test_weekly_loop.py::test_marking_a_plan_card_cooked_creates_a_ledger_row"
$PY -m pytest -q -m e2e --tb=short -p no:cacheprovider "tests/e2e/test_weekly_loop.py::test_cook_verdict_reaches_the_recipe_note"
$PY -m pytest -q -m e2e --tb=short -p no:cacheprovider "tests/e2e/test_cook_now_filter.py::test_clicking_a_row_opens_that_recipe"
```
(The seventh was not in the brief: it read the recipe page's `<h1>` while it still said
"Loading…" — the same wait-on-the-wrong-signal defect as #5 — and surfaced once the suite
ran under load. It now waits for the title.)
Expected, **each**: `1 passed` (the cook-now one may instead print `1 skipped` **only** if the
skip reason is `no dessert recipes in the vault copy` — report that as PASS-WITH-NOTE).
Anything else → STOP and report which node-id, with its `E   ` lines.

## 4. Full e2e suite (in one session, shared server)

```bash
PY=/Users/chaseeasterling/Dev/KitchenOS/.venv/bin/python
$PY -m pytest tests/e2e -q -m e2e --tb=short -p no:cacheprovider 2>&1 | tail -15
```
Expected summary line contains: `128 passed, 1 skipped`
and contains **no** `failed`. `xfailed`/`xpassed` counts may differ by ±1 (one
timing-sensitive non-strict xfail); that is not a failure. Runtime ≈ 2 minutes.
If any `FAILED` line appears → STOP, report every `FAILED …` line verbatim.

## 5. Triage table — what a failure would mean

| Failing node-id (or symptom) | Invalidates | Report as |
|---|---|---|
| `test_planner_touch.py::TestTapToAssign::test_tap_a_recipe_then_a_slot_assigns_it` — `starting from an empty slot` | Repair #1 (unique week via `tests/e2e/_weeks.py`; `_open(..., week=)`) | "R1: slot not empty on its own week — week claim or `?week=` routing broken" |
| Any test raising `RuntimeError: unique_week(N) is already owned by …` | Repair #1's shared helper — two tests claimed one offset | "R1: offset collision: <message>" |
| `test_bulk_inventory.py::test_extending_a_lapsed_row…` — `should sort above both healthy fillers` / `did not re-sort between the fillers` | Repair #2 (relative ordering) | "R2: /review expiry sort moved the rescued row wrongly" (product) |
| `test_cook_now_filter.py::test_toggling_desserts…` — `the Cook Now payload carried none` | Repair #3 (**product**: `/api/cook-now` caps per chip group) | "R3: per-group cap not in effect — check `api_server.py api_cook_now` passes `per_group=True`" |
| `tests/test_api_cook_now.py::test_limit_caps_each_chip_group` or `tests/test_cook_now.py::…test_per_group_limit…` | Repair #3 unit contract | "R3-unit: <E line>" |
| `test_verify_merged_batch.py::…test_1_5_survives_save_and_reopen` — `reopened editor shows` | Repair #4 (targets its own `.meal-card[data-name=…]`) | "R4: editor reopened wrong meal or lost 1.5" |
| same test — `servings came back as` | product round-trip (not touched by this branch) | "R4-product: /api/meals dropped the fraction" |
| same test — `page_errors` with `Failed to load meals TypeError: Failed to fetch` | Repair #4b (waits for the saved meal's card before navigating) | "R4b: navigated before the post-save reload finished" |
| `test_cook_now_filter.py::test_clicking_a_row_opens_that_recipe` — `Loading…` | Repair #7 (`expect(h1).to_contain_text`) | "R7: recipe title never replaced Loading…" (product if it times out at 15 s) |
| `test_weekly_loop.py::test_marking_a_plan_card_cooked…` — `left no ledger row` **alone but not in the suite** | Repair #5 (plain `click()`, no `force=True`) | "R5: click still not reaching the 🍳 handler on a cold server" |
| same — fails in the suite too | product: legacy-card → `/api/cook` → import-legacy → `/api/cooks` chain | "R5-product: ledger conversion broken" |
| `test_weekly_loop.py::test_cook_verdict_reaches_the_recipe_note` — `did not write observed yield` | Repair #6 (PATCH `cooked_at` before asserting) | "R6: cooked row did not sync `observed_servings`" (product `cook_history`) |
| same — `cook_count: 1` missing | another test cooked Creamy Garlic Tofu | "R6: median/count shifted — grep tests/e2e for that recipe" |
| `tests/test_daily_self_clean.py::…` | Repair #8 (**product**: `generate_meal_plan.refresh_inventory_views()` runs before the "file exists" return; `check_expiry_pruning` counts rows past the 3-day grace) | "R8: <E line>" |
| Unit summary ≠ `4064 passed, 1 skipped` | collection changed | report the line; if `4063 passed, 2 skipped` name the extra `SKIPPED` test (`-rs`) |
| `FileNotFoundError … vault/KitchenOS` | environment (harness data), not a repair | "ENV: data_root did not resolve to the main checkout" |
| Server boot timeout / `server exited with code` | environment (port/venv) | "ENV: <last 20 lines of the error>" |

Report format: one line per §2–§4 command — `PASS` or `FAIL: <expected> vs <actual>` — then
the triage rows that apply. Nothing else.
