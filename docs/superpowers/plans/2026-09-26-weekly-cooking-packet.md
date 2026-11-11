# Weekly Cooking Packet Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a saved, mobile-editable, printable weekly cooking packet generated from real cooks, recipes, inventory, schedules, and on-demand H-E-B/Costco lookups.

**Architecture:** Store one versioned packet and sparse edits per ISO week in SQLite. Build drafts in focused pure modules, run classification and retailer network work only in explicit background refresh jobs, and render the same committed packet into mobile and print views. Extend recipe bodies with optional phase headings while preserving the flat instruction contract used by current consumers.

**Tech Stack:** Python 3.11, Flask, SQLite, Markdown recipe files, vanilla JavaScript/CSS, requests, BeautifulSoup, pytest, Playwright.

**Spec:** `docs/superpowers/specs/2026-09-25-weekly-cooking-packet-design.md`

## Global Constraints

- The isolated branch does not contain the main checkout's uncommitted calendar work. Task 0 adds only the cook-schedule storage and API contract this feature consumes; it does not import calendar snapshots or calendar UI.
- Use `.venv/bin/python` for Python commands and Python 3.11 syntax.
- `data/kitchenos.db` remains the single source of truth for packets, inventory, purchases, cooks, placements, and schedules.
- Never decrement inventory, record purchases, assign servings, or rewrite legacy recipes while generating a packet.
- No page render or print request may call an LLM or retailer; only explicit background refresh jobs may do so, through `llm_gate` and bounded network timeouts.
- A recipe name remains its identity. Phase headings live in the Markdown body and add no frontmatter key.
- Escape server-rendered strings and use DOM `textContent` for recipe, product, retailer, and note content.
- `/cooking-packet` and `/print/cooking-packet` require `?week=` and belong in `NOT_BOOKMARKABLE`; do not add dead generic bookmarks.
- Tests must use the isolated database and vault fixtures. Real W40 verification runs only against explicit copies.
- Restart `com.kitchenos.api` after changing `lib/`, templates, prompts, or API routes.

## Review Focus

- The same inventory item exists in two locations: credit the required quantity once, allocate it across real rows, and show each contributing location.
- A recipe disappears after packet edits were saved: preserve those edits under Needs review instead of applying them to another item or dropping them.
- A mobile client saves revision N after another save created N+1: return a conflict and preserve the newer packet.
- One retailer times out while the other succeeds: commit the successful results, retain the failed retailer's previous timestamped snapshot, and label it stale.
- Recipe or retailer text contains HTML/script content or exceeds bounds: render it as text and reject oversized documents before any write.

## File Structure

- `lib/cooking_packet_store.py`: packet schema validation, SQLite repository, sparse edit merge, optimistic revisions, retailer preferences.
- `lib/recipe_phases.py`: canonical phases, legacy phase classification, shared-prep validation, production-task scheduling.
- `lib/cooking_packet_builder.py`: cooks/schedules/recipes/shopping/inventory composition into one versioned draft.
- `lib/cooking_packet_jobs.py`: bounded in-process refresh operations and idempotent request IDs.
- `lib/cooking_packet_render.py`: escaped print fragment and small server-rendered screen summaries.
- `lib/store_lookup/`: retailer candidate model, H-E-B and Costco adapters, deterministic recommendation policy.
- `templates/cooking_packet.html`, `static/cooking-packet.css`, `static/cooking-packet.js`: mobile editing surface.
- `templates/print_cooking_packet.html`: print shell using the saved packet renderer.
- Existing parser, template, prompt, planner, API, registry, and documentation files change only at their integration points.

---

### Task 0: Cook-schedule prerequisite

**Files:**
- Create: `lib/cook_schedule.py`
- Modify: `lib/inventory_db.py`
- Modify: `lib/serving_ledger.py`
- Modify: `api_server.py`
- Create: `tests/test_cook_schedule.py`

**Interfaces:**
- Produces: `cook_schedule.validate(date: str, start: str, timezone: str, duration_minutes: int) -> str`, `serving_ledger.schedules_for_week(week: str) -> list[dict]`, `serving_ledger.schedule_cook(cook_id: int, *, date: str, meal: str, start: str, timezone: str, duration_minutes: int, servings_to_eat: float) -> dict`, and `POST /api/cooks/<id>/schedule`.
- The API body contains exactly `date`, `meal`, `start`, `timezone`, `duration_minutes`, and `servings_to_eat`.

- [ ] **Step 1: Write failing schedule tests**

```python
def test_retry_only_places_first_serving_once(tmp_db):
    cook = create_unscheduled_cook(servings=8)
    schedule_cook(cook["id"], **valid_args(servings_to_eat=1))
    schedule_cook(cook["id"], **valid_args(servings_to_eat=1))
    saved = get_cook(cook["id"])
    assert sum(p["count"] for p in saved["placements"]) == 1
    assert saved["unassigned"] == 7

def test_generic_move_removes_stale_timed_schedule(tmp_db):
    cook = create_unscheduled_cook(servings=8)
    schedule_cook(cook["id"], **valid_args())
    move_cook(cook["id"], "2026-09-23", "dinner")
    assert schedules_for_week("2026-W39") == []

def test_invalid_offset_date_or_duration_rolls_back(tmp_db):
    cook = create_unscheduled_cook(servings=8)
    with pytest.raises(ValueError):
        schedule_cook(cook["id"], **valid_args(start="2026-09-23T19:00:00-05:00"))
    assert get_cook(cook["id"])["date"] is None
```

- [ ] **Step 2: Run the tests and verify missing schedule APIs**

Run: `.venv/bin/python -m pytest tests/test_cook_schedule.py -v`

- [ ] **Step 3: Implement the minimal schedule dependency**

Add `cook_schedule(cook_id PRIMARY KEY REFERENCES cooks(id) ON DELETE CASCADE, start, timezone, duration_minutes CHECK 15..360)`. Validate IANA timezone, offset-aware timestamp, matching local date, 15-minute start/duration increments, finish by midnight, finite positive servings, same cook week, uncooked single recipe, and capacity. The transaction moves the cook, creates only the first placement for a previously unscheduled cook, and upserts timing. Generic date/meal changes remove stale timing.

- [ ] **Step 4: Run schedule and ledger regressions**

Run: `.venv/bin/python -m pytest tests/test_cook_schedule.py tests/test_serving_ledger.py tests/test_api_ledger.py -v`
Expected: PASS with retries and concurrent requests producing one initial placement.

- [ ] **Step 5: Commit**

```bash
git add lib/cook_schedule.py lib/inventory_db.py lib/serving_ledger.py api_server.py tests/test_cook_schedule.py
git commit -m "feat: persist cooking schedules"
```

### Task 1: Packet persistence and edit merging

**Files:**
- Create: `lib/cooking_packet_store.py`
- Modify: `lib/inventory_db.py`
- Create: `tests/test_cooking_packet_store.py`
- Modify: `tests/test_inventory_db.py`

**Interfaces:**
- Produces: `get_packet(week: str) -> dict | None`, `replace_generated(week: str, generated: dict, request_id: str | None = None) -> dict`, `patch_packet(week: str, expected_revision: int, changes: list[dict], status: str | None = None) -> dict`, `replace_store_snapshot(week: str, expected_revision: int, snapshot: dict) -> dict`, and `retailer_preferences() -> dict[str, dict]`.
- Edit changes have exact shape `{"item_id": str, "field": str, "value": JSONValue}`; checkbox state is field `done`.

- [ ] **Step 1: Write the failing schema and repository tests**

```python
def test_new_database_has_packet_tables(tmp_db):
    assert table_names() >= {"cooking_packets", "retailer_preferences"}
    assert retailer_preferences()["heb"]["location_id"] == "425"
    assert retailer_preferences()["costco"]["location_id"] == "681"

def test_replace_preserves_edits_and_orphans_removed_source(tmp_db):
    first = replace_generated("2026-W40", draft(ids=["cook:58"]))
    patch_packet("2026-W40", first["revision"], [{"item_id":"cook:58","field":"text","value":"Mine"}])
    saved = replace_generated("2026-W40", draft(ids=[]))
    assert saved["needs_review"][0]["item_id"] == "cook:58"

def test_stale_revision_cannot_overwrite_newer_edit(tmp_db):
    packet = replace_generated("2026-W40", draft())
    patch_packet("2026-W40", packet["revision"], [])
    with pytest.raises(RevisionConflict):
        patch_packet("2026-W40", packet["revision"], [])
```

- [ ] **Step 2: Run the tests and confirm missing-table/module failures**

Run: `.venv/bin/python -m pytest tests/test_inventory_db.py tests/test_cooking_packet_store.py -v`

- [ ] **Step 3: Add the tables and repository**

Add `cooking_packets` and `retailer_preferences` to `_SCHEMA`. Validate week keys, document version `1`, status, allowed edit paths, a 2 MiB serialized-document limit, at most 2,000 generated items, and string values no longer than 10,000 characters. Use `BEGIN IMMEDIATE`, read the committed row after writes, and seed the approved stores idempotently.

- [ ] **Step 4: Run the focused tests**

Run: `.venv/bin/python -m pytest tests/test_inventory_db.py tests/test_cooking_packet_store.py -v`
Expected: PASS, including rollback after invalid or oversized documents.

- [ ] **Step 5: Commit**

```bash
git add lib/inventory_db.py lib/cooking_packet_store.py tests/test_inventory_db.py tests/test_cooking_packet_store.py
git commit -m "feat: persist weekly cooking packets"
```

### Task 2: Native recipe instruction phases

**Files:**
- Modify: `lib/recipe_parser.py:261-282`
- Modify: `templates/recipe_template.py:283-483`
- Modify: `prompts/recipe_extraction.py`
- Modify: `extract_recipe.py:53-79`
- Modify: `tests/test_recipe_parser.py`
- Modify: `tests/test_recipe_template.py`
- Create: `tests/test_instruction_normalization.py`

**Interfaces:**
- Produces: `parse_instruction_phases(body: str) -> dict[str, list[dict]]` and `normalize_instruction_phase(value) -> str | None`.
- `parse_recipe_body()` continues returning flat `instructions` and additionally returns `instruction_phases`; every flat instruction may carry canonical `phase`.

- [ ] **Step 1: Write failing parser, formatter, and prompt tests**

```python
def test_phase_headings_preserve_one_flat_global_order():
    body = "## Instructions\n\n### Cook\n\n1. Simmer.\n\n### Reheat\n\n1. Warm gently."
    parsed = parse_recipe_body(body)
    assert [x["step"] for x in parsed["instructions"]] == [1, 2]
    assert [x["phase"] for x in parsed["instructions"]] == ["cook", "reheat"]

def test_legacy_instructions_keep_their_current_shape():
    assert parse_recipe_body(legacy_body)["instructions"] == legacy_expected

def test_template_writes_phase_heading_once_per_transition():
    assert rendered.count("### Finish and Taste") == 1
```

- [ ] **Step 2: Run the focused tests and verify the new assertions fail**

Run: `.venv/bin/python -m pytest tests/test_recipe_parser.py tests/test_recipe_template.py tests/test_instruction_normalization.py -v`

- [ ] **Step 3: Implement phase parsing and future-recipe output**

Use canonical keys `prep_or_flavor_base`, `cook`, `finish_and_taste`, `freeze_and_store`, and `reheat`. Number parsed instructions by document order so headings that restart at 1 cannot collide. Preserve the legacy flat result. Add nullable `phase` to both extraction prompt schemas and make the template emit headings only when phases are present.

- [ ] **Step 4: Run focused tests plus the recipe corpus guard**

Run: `.venv/bin/python -m pytest tests/test_recipe_parser.py tests/test_recipe_template.py tests/test_instruction_normalization.py tests/e2e/test_recipe_corpus_schema.py -v`
Expected: PASS with no frontmatter drift and no legacy recipe rewrite.

- [ ] **Step 5: Commit**

```bash
git add lib/recipe_parser.py templates/recipe_template.py prompts/recipe_extraction.py extract_recipe.py tests/test_recipe_parser.py tests/test_recipe_template.py tests/test_instruction_normalization.py
git commit -m "feat: structure future recipe instructions by phase"
```

### Task 3: Base packet draft from cooks, schedules, shopping, and locations

**Files:**
- Create: `lib/cooking_packet_builder.py`
- Modify: `lib/inventory_db.py`
- Create: `tests/test_cooking_packet_builder.py`

**Interfaces:**
- Consumes: Task 1 repository document version and Task 2 phase parser.
- Produces: `build_week_draft(week: str, recipes_dir: Path, *, inventory_rows: list[dict] | None = None, now: datetime | None = None) -> dict`, `allocate_pull_sources(lines: list[dict], inventory_rows: list[dict]) -> list[dict]`, and `inventory_db.fetch_inventory_rows_with_ids() -> list[dict]`.

- [ ] **Step 1: Write failing W40-shaped builder tests**

```python
def test_unassigned_cooks_are_packet_recipes(tmp_db, tmp_vault):
    add_cook("Soup", week="2026-W40", placements=[])
    packet = build_week_draft("2026-W40", tmp_vault / "Recipes")
    assert [r["recipe"] for r in packet["recipe_cards"]] == ["Soup"]

def test_duplicate_inventory_locations_credit_once_and_name_both(tmp_db):
    rows = [stock(1, "corn", 1, "can", "pantry"), stock(2, "corn", 1, "can", "garage")]
    pulls = allocate_pull_sources([need("corn", 2, "can")], rows)
    assert sum(float(x["amount"]) for x in pulls) == 2
    assert {x["location"] for x in pulls} == {"pantry", "garage"}

def test_building_draft_does_not_change_inventory(tmp_db):
    before = fetch_inventory_rows_with_ids()
    build_week_draft("2026-W40", recipes_dir)
    assert fetch_inventory_rows_with_ids() == before
```

- [ ] **Step 2: Run the tests and confirm the builder APIs are missing**

Run: `.venv/bin/python -m pytest tests/test_cooking_packet_builder.py -v`

- [ ] **Step 3: Implement deterministic draft composition**

Read `cooks_for_week()` and `schedules_for_week()`, call the existing shopping-list generator with the aggregated pantry view, and allocate credited quantities back to raw inventory rows sorted by expiry then row ID. Include source warnings, stable IDs, recipe phases, cook schedules, equipment, freeze/reheat notes, and a date range ending on the week's Sunday. Never read placements as a prerequisite for including a cook.

- [ ] **Step 4: Run builder and shopping regression tests**

Run: `.venv/bin/python -m pytest tests/test_cooking_packet_builder.py tests/test_shopping_from_cooks.py tests/test_pantry.py -v`
Expected: PASS with no inventory writes.

- [ ] **Step 5: Commit**

```bash
git add lib/inventory_db.py lib/cooking_packet_builder.py tests/test_cooking_packet_builder.py
git commit -m "feat: assemble cooking packet drafts"
```

### Task 4: Legacy phase classification, shared prep, and production schedule

**Files:**
- Create: `lib/recipe_phases.py`
- Create: `prompts/cooking_packet.py`
- Create: `tests/test_recipe_phases.py`
- Modify: `lib/cooking_packet_builder.py`
- Modify: `tests/test_cooking_packet_builder.py`

**Interfaces:**
- Produces: `classify_legacy_steps(recipe: str, instructions: list[dict]) -> dict`, `build_shared_prep(recipes: list[dict], proposer: Callable | None = None) -> list[dict]`, and `build_production_schedule(cooks: list[dict], shared_prep: list[dict], storage_tasks: list[dict]) -> list[dict]`.
- Classifier result includes `phase`, `can_do_ahead`, `duration_minutes`, `depends_on`, `confidence`, and `needs_review` for every source instruction.

- [ ] **Step 1: Write failing safety and scheduling tests**

```python
def test_matching_black_eyed_pea_steps_merge_and_sum_amounts():
    assert shared_names(two_matching_bean_recipes()) == ["Cook black-eyed peas"]

def test_different_pressure_time_or_release_stays_separate():
    assert len(build_shared_prep(incompatible_pressure_recipes())) == 2

def test_raw_chicken_tasks_never_merge():
    assert all(len(x["recipes"]) == 1 for x in build_shared_prep(raw_chicken_recipes()))

def test_dependency_chain_walks_back_from_first_cook_day():
    schedule = build_production_schedule(tuesday_cook(), soak_then_cook_beans(), [])
    assert [x["date"] for x in schedule[:2]] == ["2026-09-27", "2026-09-28"]
```

- [ ] **Step 2: Run and verify the new module/tests fail**

Run: `.venv/bin/python -m pytest tests/test_recipe_phases.py tests/test_cooking_packet_builder.py -v`

- [ ] **Step 3: Implement bounded classification and deterministic validation**

Use `llm_gate.allowed()` and `llm_gate.budget_s()` only from refresh workers. Fall back to a conservative keyword classifier with uncertain steps in an `instructions` group. Shared prep requires matching normalized ingredient, compatible units, method, pressure time, release and liquid ratio; refuse raw animal-protein merges. Topologically place do-ahead dependencies one day at a time before the earliest dependent cook, keep time-sensitive prep on cook day, and place unmolding/bagging one day after freezing.

- [ ] **Step 4: Run phase, builder, and task-ID regression tests**

Run: `.venv/bin/python -m pytest tests/test_recipe_phases.py tests/test_cooking_packet_builder.py tests/test_task_extractor.py -v`
Expected: PASS; legacy task IDs and flat instructions remain stable.

- [ ] **Step 5: Commit**

```bash
git add lib/recipe_phases.py prompts/cooking_packet.py lib/cooking_packet_builder.py tests/test_recipe_phases.py tests/test_cooking_packet_builder.py
git commit -m "feat: derive shared cooking prep and schedule"
```

### Task 4B: Separate freezer-bag ingredients from cook-day ingredients

**Files:**
- Modify: `lib/recipe_phases.py`
- Modify: `lib/cooking_packet_builder.py`
- Modify: `lib/cooking_packet_store.py`
- Modify: `tests/test_recipe_phases.py`
- Modify: `tests/test_cooking_packet_builder.py`
- Modify: `tests/test_cooking_packet_store.py`

**Interfaces:**
- Produces: `assign_ingredient_stages(recipe: str, ingredients: list[dict], instructions: list[dict], proposer: Callable | None = None) -> list[dict]`.
- Every returned ingredient retains its stable `item_id` and has exactly one `prep_stage`, `stage_source`, `stage_reason`, and `needs_review` value.
- `prep_stage` is editable through Task 1's exact sparse change shape.

- [ ] **Step 1: Write failing freezer-bag separation tests**

Cover explicit bag ingredients, add-at-cook-time liquid, post-release finish ingredients, serving garnishes/sides, prep-then-bag, separate freezing, contradictory evidence, unknown ingredients, stable IDs, model proposal validation, and one-stage-only output.

- [ ] **Step 2: Implement conservative stage assignment**

Use only the closed stages `bag_now`, `prep_then_bag`, `freeze_separately`, `add_at_cook_time`, `finish_after_cooking`, `serve_separately`, and `needs_review`. Explicit source wording can establish a stage. Bounded proposals may run only inside `classification_refresh()` and still pass deterministic validation. Unknown or conflicting evidence becomes `needs_review`, which is always kept out of the bag. Do not infer general food rules as recipe facts.

- [ ] **Step 3: Integrate the packet draft and edit store**

Stage every recipe-card ingredient exactly once. Preserve shopping requirements for every stage. Do not turn cook-time-only rows into freezer-session prep tasks. Add `prep_stage` to the packet edit allowlist without changing the exact `{item_id, field, value}` shape.

- [ ] **Step 4: Run focused regressions**

Run: `.venv/bin/python -m pytest tests/test_recipe_phases.py tests/test_cooking_packet_builder.py tests/test_cooking_packet_store.py -v`

- [ ] **Step 5: Commit**

```bash
git add lib/recipe_phases.py lib/cooking_packet_builder.py lib/cooking_packet_store.py tests/test_recipe_phases.py tests/test_cooking_packet_builder.py tests/test_cooking_packet_store.py
git commit -m "feat: separate freezer bag and cook day ingredients"
```

### Task 5: Mobile and print rendering

**Files:**
- Create: `lib/cooking_packet_render.py`
- Create: `templates/cooking_packet.html`
- Create: `templates/print_cooking_packet.html`
- Create: `static/cooking-packet.css`
- Create: `static/cooking-packet.js`
- Create: `tests/test_cooking_packet_render.py`

**Interfaces:**
- Consumes: Task 1 merged packet document.
- Produces: `render_print_packet(packet: dict) -> str`; screen JavaScript consumes `GET /api/cooking-packets/<week>`, sends Task 1 patch shapes for packet-only edits, and sends cook timing changes to existing `POST /api/cooks/<id>/schedule`.

**Freezer-prep amendment:** Before rendering, the builder assigns every ingredient exactly one closed `prep_stage`: `bag_now`, `prep_then_bag`, `freeze_separately`, `add_at_cook_time`, `finish_after_cooking`, `serve_separately`, or `needs_review`. Uncertain rows stay out of the bag. Ingredient stage edits use the existing exact sparse edit shape with field `prep_stage`.

- [ ] **Step 1: Write failing render-contract tests**

```python
def test_print_has_reference_packet_sections():
    html = render_print_packet(packet_fixture())
    for label in ("Weekly schedule", "Pull from home", "Shared prep", "Finish and taste", "Freeze and reheat"):
        assert label in html

def test_hostile_recipe_and_product_names_are_escaped():
    html = render_print_packet(packet_fixture(name='<script>alert(1)</script>'))
    assert "<script>" not in html and "&lt;script&gt;" in html
```

- [ ] **Step 2: Run the render tests and verify failure**

Run: `.venv/bin/python -m pytest tests/test_cooking_packet_render.py -v`

- [ ] **Step 3: Implement responsive and print presentation**

Mirror the reference PDF's navy/teal/gold hierarchy, Letter margins, schedule table, location columns, stage labels, phase cards, guidance boxes, repeated footer, and page counters. Lead every recipe with **Freezer prep**: **Put in the freezer bag now**, optional **Prep before bagging**, and a prominent **Keep out of the freezer bag** group split into cook-time, finish, serve, separate-freeze, and needs-review destinations. Do not show a generic ingredient list that implies everything is bagged. Each ingredient appears in exactly one destination. The mobile shell uses semantic collapsible sections, labeled controls, 44px touch targets, `aria-live`, visible focus, reduced motion, `textContent`, per-card Save, and persisted checkboxes. Reuse `static/print-action.js`.

- [ ] **Step 4: Run render tests and static accessibility contract checks**

Run: `.venv/bin/python -m pytest tests/test_cooking_packet_render.py tests/test_web_dashboard.py -v`
Expected: PASS with no unescaped user content.

- [ ] **Step 5: Commit**

```bash
git add lib/cooking_packet_render.py templates/cooking_packet.html templates/print_cooking_packet.html static/cooking-packet.css static/cooking-packet.js tests/test_cooking_packet_render.py
git commit -m "feat: render cooking packets for mobile and print"
```

### Task 6: Packet refresh jobs, APIs, and pages

**Files:**
- Create: `lib/cooking_packet_jobs.py`
- Modify: `api_server.py`
- Create: `tests/test_cooking_packet_jobs.py`
- Create: `tests/test_cooking_packet_api.py`
- Modify: `tests/conftest.py`

**Interfaces:**
- Consumes: Tasks 1, 3, 4, and 5.
- Produces: `start_operation(kind: str, week: str, request_id: str, worker: Callable[[], dict]) -> dict` and `get_operation(kind: str, week: str, operation_id: str) -> dict | None`, plus packet GET/PATCH/refresh routes and the two HTML page routes from the spec.

- [ ] **Step 1: Write failing job and API tests**

```python
def test_same_request_id_returns_same_operation():
    worker = lambda: {"revision": 2}
    first = start_operation("packet", "2026-W40", "abc", worker)
    second = start_operation("packet", "2026-W40", "abc", worker)
    assert first["id"] == second["id"]

def test_packet_patch_returns_409_for_stale_revision(client, packet):
    response = client.patch("/api/cooking-packets/2026-W40", json={"revision": packet["revision"] - 1, "changes": []})
    assert response.status_code == 409

def test_print_without_saved_packet_links_to_builder(client):
    response = client.get("/print/cooking-packet?week=2026-W40")
    assert response.status_code == 404 and b"Build cooking packet" in response.data
```

- [ ] **Step 2: Run and confirm missing route/module failures**

Run: `.venv/bin/python -m pytest tests/test_cooking_packet_jobs.py tests/test_cooking_packet_api.py -v`

- [ ] **Step 3: Implement bounded operations and packet routes**

Keep at most 100 terminal operations and one active operation per `(kind, week)`. Store no arbitrary exception text in client responses. Refresh workers commit only complete validated drafts. The page shell starts first generation through the same idempotent refresh API, polls to terminal state, then loads the committed packet. Add an autouse fixture that disables packet threads except in their focused tests.

- [ ] **Step 4: Run API, ledger, and job tests**

Run: `.venv/bin/python -m pytest tests/test_cooking_packet_jobs.py tests/test_cooking_packet_api.py tests/test_api_ledger.py tests/test_cook_schedule.py -v`
Expected: PASS with cook schedule edits still going through the ledger API.

- [ ] **Step 5: Commit**

```bash
git add lib/cooking_packet_jobs.py api_server.py tests/test_cooking_packet_jobs.py tests/test_cooking_packet_api.py tests/conftest.py
git commit -m "feat: add cooking packet web workflow"
```

### Task 7: Retailer adapters and recommendation policy

**Files:**
- Create: `lib/store_lookup/__init__.py`
- Create: `lib/store_lookup/base.py`
- Create: `lib/store_lookup/heb.py`
- Create: `lib/store_lookup/costco.py`
- Create: `lib/store_lookup/policy.py`
- Create: `tests/test_store_lookup.py`
- Create: `tests/fixtures/store_lookup/heb_products.html`
- Create: `tests/fixtures/store_lookup/costco_products.html`

**Interfaces:**
- Produces: immutable `ProductCandidate`, `HEBAdapter.search(query: str, location_id: str, timeout_s: float) -> list[ProductCandidate]`, `CostcoAdapter.search(query: str, location_id: str, timeout_s: float) -> list[ProductCandidate]`, and `recommend(requirement: dict, heb: list[ProductCandidate], costco: list[ProductCandidate]) -> dict`.

- [ ] **Step 1: Write failing adapter and policy tests**

```python
def test_heb_owned_brand_wins_ordinary_quantity():
    assert recommend(one_can_need(), [heb_brand(), national_brand()], [costco_case()])["retailer"] == "heb"

def test_costco_only_wins_when_bulk_is_used_or_stores_well():
    assert recommend(large_freezable_need(), [heb_small()], [costco_case()])["retailer"] == "costco"
    assert recommend(one_fresh_need(), [heb_small()], [costco_case()])["retailer"] == "heb"

def test_unknown_costco_price_is_not_called_cheaper():
    assert "cheaper" not in recommend(one_can_need(), [heb_brand()], [costco_no_price()])["reason"].lower()
```

- [ ] **Step 2: Run the tests and verify missing adapters**

Run: `.venv/bin/python -m pytest tests/test_store_lookup.py -v`

- [ ] **Step 3: Implement official-site adapters and deterministic policy**

Inject the HTTP getter for tests, send a normal user agent, enforce connect/read timeouts and a 20-candidate cap, parse only product name/brand/package/price/unit price/URL/availability evidence, and discard malformed candidates. Use H-E-B store 425 and Costco warehouse 681 from Task 1 preferences. Catalog absence means `not_found_online`; absent Costco local price means `check_warehouse_price`.

- [ ] **Step 4: Run fixtures and a bounded manual smoke**

Run: `.venv/bin/python -m pytest tests/test_store_lookup.py -v`
Expected: PASS. Then run each adapter once for `coconut milk` with a 10-second timeout; success may return candidates, while a blocked site must return the documented unavailable result without crashing or guessing.

- [ ] **Step 5: Commit**

```bash
git add lib/store_lookup tests/test_store_lookup.py tests/fixtures/store_lookup
git commit -m "feat: recommend H-E-B and Costco products"
```

### Task 8: On-demand store refresh and partial-failure UI

**Files:**
- Modify: `lib/cooking_packet_jobs.py`
- Modify: `lib/cooking_packet_builder.py`
- Modify: `api_server.py`
- Modify: `static/cooking-packet.js`
- Modify: `templates/cooking_packet.html`
- Modify: `tests/test_cooking_packet_jobs.py`
- Modify: `tests/test_cooking_packet_api.py`
- Modify: `tests/test_cooking_packet_builder.py`

**Interfaces:**
- Consumes: Task 7 adapters/policy and Task 1 `replace_store_snapshot`.
- Produces: the store-refresh POST/status routes and merged snapshot fields `retailers.heb`, `retailers.costco`, `looked_up_at`, `stale`, and `warnings`.

- [ ] **Step 1: Write failing partial-success and stale-snapshot tests**

```python
def test_heb_success_and_costco_timeout_commit_independently(saved_snapshot):
    result = refresh_stores(heb=success(), costco=timeout())
    assert result["heb"]["stale"] is False
    assert result["costco"] == {**saved_snapshot["costco"], "stale": True}

def test_absent_heb_result_does_not_claim_out_of_stock():
    assert refresh_empty_heb()["status"] == "not_found_online"
```

- [ ] **Step 2: Run focused tests and verify failure**

Run: `.venv/bin/python -m pytest tests/test_cooking_packet_jobs.py tests/test_cooking_packet_api.py tests/test_cooking_packet_builder.py -v`

- [ ] **Step 3: Implement the two-retailer background refresh**

Run adapters independently, merge successful results with the previous snapshot for failures, commit once with optimistic revision handling, and return per-retailer progress. Update the mobile UI to name Hancock Center and North Austin, show timestamps/stale labels, distinguish unavailable from out of stock, and stop polling at terminal state or client timeout.

- [ ] **Step 4: Run all packet and store tests**

Run: `.venv/bin/python -m pytest tests/test_cooking_packet_store.py tests/test_cooking_packet_builder.py tests/test_cooking_packet_jobs.py tests/test_cooking_packet_api.py tests/test_store_lookup.py -v`
Expected: PASS, including one-retailer failure and idempotent retries.

- [ ] **Step 5: Commit**

```bash
git add lib/cooking_packet_jobs.py lib/cooking_packet_builder.py api_server.py static/cooking-packet.js templates/cooking_packet.html tests/test_cooking_packet_jobs.py tests/test_cooking_packet_api.py tests/test_cooking_packet_builder.py
git commit -m "feat: refresh cooking packet store picks"
```

### Task 9: Planner integration, browser verification, and operations

**Files:**
- Modify: `lib/plan_week.py`
- Modify: `templates/plan_week.html`
- Modify: `tests/test_plan_week.py`
- Modify: `tests/test_web_dashboard.py`
- Create: `tests/e2e/test_cooking_packet.py`
- Modify: `docs/API.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/OPERATIONS.md`

**Interfaces:**
- Consumes: all prior tasks.
- Produces: the fourth Plan your week action and the verified end-to-end mobile/print workflow.

- [ ] **Step 1: Write failing planner and browser tests**

```python
def test_plan_center_links_packet_with_exact_week():
    assert "/cooking-packet?week=2026-W40" in render_center("2026-W40")

def test_query_required_packet_pages_are_declared_unbookmarkable():
    assert {"/cooking-packet", "/print/cooking-packet"} <= set(NOT_BOOKMARKABLE)
```

The Playwright test must generate a packet, use a phone viewport, expand/edit/save/reload a section, check a prep box, verify stale retailer copy, and open the print view. It must assert no horizontal overflow and that print controls are hidden under print media.

- [ ] **Step 2: Run planner and browser tests and verify the missing-link failure**

Run: `.venv/bin/python -m pytest tests/test_plan_week.py tests/test_web_dashboard.py -v`

- [ ] **Step 3: Add the planner action, registry exemption, and operator documentation**

Keep the existing weekly print action. Document packet endpoints, DB ownership, explicit network/LLM refresh behavior, store configuration, restart requirements, and failure labels.

- [ ] **Step 4: Run unit, e2e, and real-copy verification**

Run: `.venv/bin/python -m pytest`

Run: `.venv/bin/python -m pytest tests/e2e/test_cooking_packet.py -m e2e -v`

Copy the live DB and vault into a temporary verification directory, build W40 there, and assert the four unassigned freezer cooks appear, both corn varieties are present at quantity 2 and credited once, shared bean prep appears, an edit survives refresh, and the print output paginates without clipped or overlapping content. Inspect phone and Letter screenshots.

- [ ] **Step 5: Run the KitchenOS finishing checklist**

Invoke `finish-feature`; apply any required Key Functions or operations-document updates, then rerun its dry-run extraction and targeted checks.

- [ ] **Step 6: Restart and verify the live service**

Restart `com.kitchenos.api`, verify `/health`, then open the packet through the reachable Tailscale planner URL on desktop and phone. Do not mutate the live packet during smoke verification unless the user explicitly asks to create it.

- [ ] **Step 7: Commit**

```bash
git add lib/plan_week.py templates/plan_week.html tests/test_plan_week.py tests/test_web_dashboard.py tests/e2e/test_cooking_packet.py docs/API.md docs/ARCHITECTURE.md docs/OPERATIONS.md
git commit -m "feat: integrate weekly cooking packets"
```
