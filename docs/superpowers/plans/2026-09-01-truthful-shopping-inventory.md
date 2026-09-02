# Truthful Shopping Inventory Comparison Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make shopping-list inventory credits precision-first, visible, and safe on the live W36 plan.

**Architecture:** Keep `find_match` as the broad candidate finder used by discovery, but add a strict authorization layer inside `split_against_pantry`. Shopping lines carry a disposition and matched-row evidence; Markdown renders actual credits separately from uncertain candidates. Ingredient demand is repaired deterministically before aggregation.

**Tech Stack:** Python 3.11, Flask, Markdown templates, pytest, SQLite inventory fixtures.

**Spec:** `docs/superpowers/specs/2026-09-01-truthful-shopping-inventory-design.md`

## Global Constraints

- A false automatic credit is never accepted to improve recall.
- Generation does not mutate inventory.
- Existing broad discovery matching remains unchanged.
- Every inventory-matched demand line is visible in the verification section and
  excluded from the checkbox list sent to Reminders.
- SQLite remains the inventory source of truth.

---

### Task 1: Precision-first inventory reconciliation

**Files:**
- Modify: `lib/pantry.py`
- Test: `tests/test_pantry.py`

**Interfaces:**
- Consumes: `find_match(item_name, pantry)` and `unit_compatibility(pantry_unit, recipe_unit)`.
- Produces: `split_against_pantry(...) -> {from_pantry, to_buy, warning, status, matched_inventory}`.

- [x] **Step 1: Add failing W36-derived reconciliation tests**

Add parametrized cases asserting canned chicken, garlic powder, caramelized onion,
fried potatoes, and frozen banana are `review`, receive no credit, retain full
`to_buy`, and name the matched row in `matched_inventory`. Add a case asserting
`1 ct eggs` cannot credit `3 each eggs`.

- [x] **Step 2: Run the focused tests and verify failure**

Run: `../../.venv/bin/python -m pytest tests/test_pantry.py -q`
Expected: new disposition/metadata assertions fail against the current broad credit behavior.

- [x] **Step 3: Implement strict credit authorization**

Add a shopping-identity comparison based on `ingredient_normalizer.normalize_name`.
Keep `find_match` unchanged, but allow subtraction only when normalized identities
are equal. Return `review` with the full demand when the broad candidate is merely
related, when an inventory `ct` faces a non-`ct` demand, or when units are not
convertible. Return `credited` for exact convertible full/partial matches and
`buy` when no candidate exists.

- [x] **Step 4: Exclude expired inventory rows**

Update `load_pantry` to omit rows whose ISO `expires` date is before today. Add a
temporary-DB test proving the row remains stored but is absent from the pantry view.

- [x] **Step 5: Run the pantry tests**

Run: `../../.venv/bin/python -m pytest tests/test_pantry.py -q`
Expected: all pass.

### Task 2: Honest shopping-line metadata and note sections

**Files:**
- Modify: `lib/shopping_list_generator.py`
- Modify: `templates/shopping_list_template.py`
- Modify: `api_server.py`
- Test: `tests/test_shopping_list_generator.py`
- Test: `tests/test_shopping_list_template.py`
- Test: `tests/test_api_endpoints.py`

**Interfaces:**
- Consumes: the expanded `split_against_pantry` result from Task 1.
- Produces: `inventory_notes(lines) -> {credited: list[str], review: list[str]}` and template parameter `check_pantry`.

- [x] **Step 1: Add failing line and note tests**

Assert `compute_lines` preserves `status` and `matched_inventory`. Assert
`inventory_notes` puts only `credited` lines under `credited`, and puts related
or unit-uncertain lines under `review` with the matched inventory name and a
“still on the list” explanation.

- [x] **Step 2: Add failing Markdown and endpoint tests**

Assert the template renders `## Already have` only for credits and `## Check
pantry` for review notes. Assert review bullets are plain bullets and the same
item remains an unchecked checkbox. Assert `/generate-shopping-list` passes both
note collections to the template.

- [x] **Step 3: Run focused tests and verify failure**

Run: `../../.venv/bin/python -m pytest tests/test_shopping_list_generator.py tests/test_shopping_list_template.py tests/test_api_endpoints.py -q`
Expected: missing disposition propagation, `inventory_notes`, and `check_pantry` assertions fail.

- [x] **Step 4: Implement metadata propagation and split note rendering**

Thread `status` and `matched_inventory` through `compute_lines`. Add
`inventory_notes`; keep `on_hand_notes` as a compatibility wrapper returning only
credited notes. Extend `generate_shopping_list_markdown` with `check_pantry` and
update `/generate-shopping-list` to pass both collections.

- [x] **Step 5: Run focused tests**

Run: `../../.venv/bin/python -m pytest tests/test_shopping_list_generator.py tests/test_shopping_list_template.py tests/test_api_endpoints.py -q`
Expected: all pass.

### Task 3: Repair shopping demand before comparison

**Files:**
- Modify: `lib/ingredient_normalizer.py`
- Modify: `lib/shopping_list_generator.py`
- Test: `tests/test_ingredient_normalizer.py`
- Test: `tests/test_shopping_list_generator.py`

**Interfaces:**
- Produces: complete comma-alternative grouping keys and `repair_shopping_ingredient(ing) -> dict` for embedded scoop measurements.

- [x] **Step 1: Add failing normalizer and demand-repair tests**

Assert `medium red, orange, or yellow bell pepper, diced` normalizes to `red,
orange, or yellow bell pepper`, while `red onion, thinly sliced` remains `red
onion`. Assert `1 whole one scoop protein powder` becomes `1 scoop protein
powder` and scales to `5 scoops protein powder`.

- [x] **Step 2: Add failing household-supply tests**

Assert water and ice lines receive `excluded`, have no `to_buy`, and do not appear
in generated `items`.

- [x] **Step 3: Run focused tests and verify failure**

Run: `../../.venv/bin/python -m pytest tests/test_ingredient_normalizer.py tests/test_shopping_list_generator.py -q`
Expected: bell pepper truncates, scoop remains embedded, and water remains shoppable.

- [x] **Step 4: Implement deterministic demand repair**

Preserve comma-separated alternative lists and remove only the final preparation
suffix. Add the scoop-prefix repair before multiplication/aggregation. Mark
normalized `water` and `ice` lines `excluded` in `compute_lines`.

- [x] **Step 5: Run focused tests**

Run: `../../.venv/bin/python -m pytest tests/test_ingredient_normalizer.py tests/test_shopping_list_generator.py -q`
Expected: all pass.

### Task 4: Documentation and live W36 verification

**Files:**
- Modify: `docs/API.md`
- Modify: `docs/workflows/end-to-end.md`
- Modify: `docs/plans/INDEX.md`
- Modify: `BRANCH-STATUS.md`

**Interfaces:**
- Verifies: canonical W36 note generated through `POST /generate-shopping-list`.

- [x] **Step 1: Update behavior documentation**

Document strict credit authorization, `Check pantry`, package-count uncertainty,
expired-row exclusion, and household-supply omission. Update the plan index from
the broad Phase 4 entry to this active branch.

- [x] **Step 2: Run targeted and full verification**

Run targeted tests from Tasks 1–3, then:

`../../.venv/bin/python -m pytest -q`

Expected: zero failures.

- [x] **Step 3: Restart the API and regenerate W36**

Restart `com.kitchenos.api`, POST `{"week":"2026-W36","use_pantry":true}` to
`/generate-shopping-list`, capture `/api/shopping-list/preview`, and compare the
saved note with the preview.

- [x] **Step 4: Audit all automatic credits**

Print every `status == "credited"` line with its matched inventory row and units.
Verify none of the known false pairs receive credit, review lines remain in
the inventory-match section, bell pepper is intact, scoop quantities are
repaired, and water/ice are absent.

- [x] **Step 5: Run diff and lint hygiene checks**

Run: `git diff --check`

Run the repository's configured Python lint command if present; otherwise run
`../../.venv/bin/python -m compileall -q lib api_server.py templates`.

- [x] **Step 6: Request code review and address findings**

Use `superpowers:requesting-code-review`, inspect every finding, and apply the
`superpowers:receiving-code-review` workflow before changing code in response.

### Task 5: Split purchase demand from every inventory match

**Files:**
- Modify: `lib/shopping_list_generator.py`
- Modify: `templates/shopping_list_template.py`
- Modify: `api_server.py`
- Test: `tests/test_shopping_list_generator.py`
- Test: `tests/test_shopping_list_template.py`
- Test: `tests/test_api_endpoints.py`

- [x] **Step 1: Add failing two-way split tests**

Assert unmatched demand appears under `Need to purchase`; every exact or broad
inventory match appears under `Inventory matches — verify` with needed amount,
matched row, and reason; and match lines are plain bullets excluded from the
Reminders parser.

- [x] **Step 2: Implement the user-approved split**

Add `shopping_sections`, pass generated purchase items and inventory matches
through the endpoint, preserve manual purchase-item provenance, and render the
two sections without mutating inventory.

- [x] **Step 3: Update behavioral documentation**

Replace the original three-surface output description with the approved two-way
split while retaining the internal precision-first dispositions.

- [x] **Step 4: Regenerate and audit W36**

Verify the saved note and Reminders parser contain only purchase checkboxes, all
inventory matches are visible as plain bullets, and pistachios are in the match
section rather than the purchase section.

- [x] **Step 5: Unify every shopping-list consumer**

Make `items` canonically purchase-only for the CLI, print packet, one-shot API,
and planner preview. Carry match notes through preview→confirm, use the full need
for “Buy fresh,” retain only the remainder after confirmed partial pantry use,
and preserve ambiguous manual quantity variants during legacy-note migration.
