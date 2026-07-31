# Move a Scheduled Cook by Dragging Its Card — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the planner's cook card be dragged (or tapped) from one day/meal slot to another, carrying the servings eaten at that slot with it.

**Architecture:** One new ledger function, `serving_ledger.move_cook()`, does the whole move inside a single `BEGIN IMMEDIATE` transaction — it re-anchors the cook row and re-points that cook's `slot` placements sitting at the *old* anchor, merging into any placement already at the destination. It is exposed as `POST /api/cooks/<id>/move`. The planner's grid Sortable stops excluding `.cook-card` in board mode and branches to that endpoint before reaching the legacy `saveMealPlan()` path. A "Move to another slot" action in the card sheet reuses the existing armed / assign-bar machinery as the single-pointer route.

**Tech Stack:** Python 3.11 + Flask (`api_server.py`), SQLite (`data/kitchenos.db`), vanilla JS + SortableJS in a Jinja template, pytest + Playwright.

**Spec:** `docs/superpowers/specs/2026-07-31-move-cook-by-drag-design.md`

## Global Constraints

- **Python 3.11, always via `.venv/bin/python`.** Unit suite: `.venv/bin/python -m pytest`. E2E is deselected by default (`pytest.ini` sets `addopts = -m "not e2e"`); run it explicitly with `.venv/bin/pytest tests/e2e -m e2e -v`.
- **Work in the worktree** `/Users/chaseeasterling/Dev/KitchenOS/.worktrees/move-cook-by-drag` on branch `move-cook-by-drag`. All paths below are relative to it. `.venv` is git-ignored, so it does not come with a worktree — it has already been symlinked to the main checkout's (`ln -s /Users/chaseeasterling/Dev/KitchenOS/.venv .venv`), and `.venv/bin/python -m pytest tests/test_serving_ledger.py` is confirmed green there (30 passed). Run every command with the worktree as CWD.
- **A recipe's name is its identity.** `cooks.recipe`, the meal-plan Markdown, and the task-ID hash all key on it. `display_name` / `short_title` are for rendering only — never key anything on them.
- **`data/kitchenos.db` is the single source of truth**; the weekly Markdown is a regenerated view. Any endpoint that mutates the ledger calls `_regen_weeks()` afterward.
- **No external assets in templates.** `tests/test_no_external_assets.py` fails on any CDN link. SortableJS is already vendored — do not add a script tag.
- **Restart the API LaunchAgent after editing `lib/`, `templates/`, or `prompts/`**, or the running server serves stale code:
  ```bash
  launchctl unload ~/Library/LaunchAgents/com.kitchenos.api.plist
  launchctl load ~/Library/LaunchAgents/com.kitchenos.api.plist
  ```
  (Not needed for the unit suite or the e2e harness, both of which start their own server.)
- **Commit convention:**
  ```
  type: short description

  Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
  ```
- **Test dates are load-bearing.** `2026-07-07` (Tue), `2026-07-08` (Wed) and `2026-07-09` (Thu) are all in ISO week `2026-W28`; `2026-07-20` is in `2026-W30`. A cook whose `date` falls outside its `week` is filed correctly but renders on no board at all — that is what the out-of-week test pins.

---

### Task 1: `move_cook()` in the serving ledger

**Files:**
- Modify: `lib/serving_ledger.py` — insert after `move_servings()` (ends line 337), before `cooks_for_week()`
- Test: `tests/test_serving_ledger.py` — append

**Interfaces:**
- Consumes: existing module privates `_validate_placement`, `_write_txn`, `_merge_or_insert`, `get_cook`, `MEALS`, `_date`
- Produces: `serving_ledger.move_cook(cook_id: int, date: str, meal: str) -> dict` — returns the full cook dict (same shape as `get_cook`: cook columns plus `placements` list and `unassigned` float). Raises `ValueError` for an unknown cook, a bad meal, a bad date, or a date outside the cook's week.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_serving_ledger.py`. `_mk_cook()` already exists at the top of that file and creates Chili in week `2026-W28`, anchored Tue `2026-07-07` dinner, 6 servings produced, 1 placed at the anchor.

```python
# --- move_cook: dragging a scheduled card to another slot -------------------


def test_move_cook_takes_its_home_servings(tmp_db):
    cook = _mk_cook()
    moved = sl.move_cook(cook["id"], "2026-07-09", "lunch")

    assert (moved["date"], moved["meal"]) == ("2026-07-09", "lunch")
    slots = [p for p in moved["placements"] if p["destination"] == "slot"]
    assert len(slots) == 1
    assert (slots[0]["date"], slots[0]["meal"], slots[0]["count"]) == \
        ("2026-07-09", "lunch", 1.0)


def test_move_cook_leaves_leftovers_where_they_are(tmp_db):
    """A serving parked in another cell is a planned leftover, not part of the
    card being dragged."""
    cook = _mk_cook()
    sl.add_placement(cook["id"], "slot", 1.0, date="2026-07-08", meal="lunch")

    moved = sl.move_cook(cook["id"], "2026-07-09", "dinner")

    away = [p for p in moved["placements"]
            if (p["date"], p["meal"]) == ("2026-07-08", "lunch")]
    assert len(away) == 1 and away[0]["count"] == 1.0


def test_move_cook_merges_into_a_leftover_already_at_the_destination(tmp_db):
    """`placements` has no UNIQUE constraint, so an unmerged arrival would show
    as two chips of the same recipe in one cell."""
    cook = _mk_cook()
    sl.add_placement(cook["id"], "slot", 2.0, date="2026-07-09", meal="dinner")

    moved = sl.move_cook(cook["id"], "2026-07-09", "dinner")

    there = [p for p in moved["placements"]
             if (p["date"], p["meal"]) == ("2026-07-09", "dinner")]
    assert len(there) == 1, "the arriving serving must merge, not duplicate"
    assert there[0]["count"] == 3.0


def test_move_cook_anchors_a_cook_that_never_had_a_slot(tmp_db):
    """An unscheduled cook has no card to drag, but the endpoint is public and
    a NULL old anchor must not match every placement."""
    cook = sl.create_cook(recipe="Chili", week="2026-W28",
                          servings_produced=4.0)
    sl.add_placement(cook["id"], "freezer", 2.0)

    moved = sl.move_cook(cook["id"], "2026-07-09", "dinner")

    assert (moved["date"], moved["meal"]) == ("2026-07-09", "dinner")
    frozen = [p for p in moved["placements"] if p["destination"] == "freezer"]
    assert len(frozen) == 1 and frozen[0]["count"] == 2.0, \
        "a freezer placement is not a home serving"
    assert [p for p in moved["placements"] if p["destination"] == "slot"] == []


def test_move_cook_to_the_same_slot_is_a_no_op(tmp_db):
    cook = _mk_cook()
    moved = sl.move_cook(cook["id"], "2026-07-07", "dinner")

    assert (moved["date"], moved["meal"]) == ("2026-07-07", "dinner")
    assert len(moved["placements"]) == 1
    assert moved["placements"][0]["count"] == 1.0


def test_move_cook_rejects_a_bad_meal(tmp_db):
    cook = _mk_cook()
    with pytest.raises(ValueError):
        sl.move_cook(cook["id"], "2026-07-09", "brunch")


def test_move_cook_rejects_a_bad_date(tmp_db):
    cook = _mk_cook()
    with pytest.raises(ValueError):
        sl.move_cook(cook["id"], "07/09/2026", "dinner")


def test_move_cook_rejects_a_date_outside_the_cooks_week(tmp_db):
    """`cooks.week` is not updatable and `week_board()` filters on it, so a cook
    whose date left its week would render on no board at all."""
    cook = _mk_cook()                      # week 2026-W28
    with pytest.raises(ValueError, match="week"):
        sl.move_cook(cook["id"], "2026-07-20", "dinner")   # 2026-W30


def test_move_cook_rejects_an_unknown_cook(tmp_db):
    with pytest.raises(ValueError):
        sl.move_cook(9999, "2026-07-09", "dinner")


def test_move_cook_does_not_change_the_total_placed(tmp_db):
    cook = _mk_cook()
    sl.add_placement(cook["id"], "slot", 2.0, date="2026-07-08", meal="lunch")
    before = sum(p["count"] for p in sl.get_cook(cook["id"])["placements"])

    moved = sl.move_cook(cook["id"], "2026-07-09", "dinner")

    assert sum(p["count"] for p in moved["placements"]) == before
    assert moved["unassigned"] == 3.0
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd /Users/chaseeasterling/Dev/KitchenOS/.worktrees/move-cook-by-drag
.venv/bin/python -m pytest tests/test_serving_ledger.py -k move_cook -v
```

Expected: 10 failures, all `AttributeError: module 'lib.serving_ledger' has no attribute 'move_cook'`.

- [ ] **Step 3: Implement `move_cook()`**

Insert into `lib/serving_ledger.py` immediately after `move_servings()` and before `def cooks_for_week`:

```python
def move_cook(cook_id: int, date: str, meal: str) -> dict:
    """Re-anchor a cook to another slot, taking its home servings with it.

    The card and the servings eaten *at* it move together; slot placements in
    other cells are planned leftovers and stay where they are. Moving the
    anchor alone would strand a card in a slot with no servings beside an
    orphaned foreign chip, which reads as a bug rather than as a plan.

    Total placed is conserved, so no capacity check is needed — the same
    reasoning ``move_servings`` records.
    """
    _validate_placement("slot", date, meal)
    conn = inventory_db.connect()
    try:
        with _write_txn(conn):
            row = conn.execute("SELECT * FROM cooks WHERE id = ?",
                               (cook_id,)).fetchone()
            if row is None:
                raise ValueError(f"cook {cook_id} not found")
            # `week` is not in _COOK_FIELDS and cooks_for_week() filters on it,
            # so a cook whose date left its week renders on no board at all.
            # Reject rather than half-apply: the grid shows one week, so a drag
            # cannot produce this, but the endpoint is public.
            year, week_no, _ = _date.fromisoformat(date).isocalendar()
            if f"{year}-W{week_no:02d}" != row["week"]:
                raise ValueError(
                    f"date {date} falls outside the cook's week {row['week']}")

            old_date, old_meal = row["date"], row["meal"]
            if (old_date, old_meal) != (date, meal):
                conn.execute("UPDATE cooks SET date = ?, meal = ? WHERE id = ?",
                             (date, meal, cook_id))
                # `IS` rather than `=` so a NULL old anchor matches nothing
                # instead of everything — an unscheduled cook has no home
                # servings to bring along.
                movers = conn.execute(
                    "SELECT * FROM placements WHERE cook_id = ?"
                    " AND destination = 'slot' AND date IS ? AND meal IS ?",
                    (cook_id, old_date, old_meal),
                ).fetchall()
                for p in movers:
                    conn.execute("DELETE FROM placements WHERE id = ?",
                                 (p["id"],))
                    _merge_or_insert(conn, cook_id, "slot", date, meal,
                                     float(p["count"]))
    finally:
        conn.close()
    return get_cook(cook_id)
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
.venv/bin/python -m pytest tests/test_serving_ledger.py -v
```

Expected: PASS — the 10 new tests plus every pre-existing test in the file.

- [ ] **Step 5: Run the whole unit suite (the ledger has many consumers)**

```bash
.venv/bin/python -m pytest -q
```

Expected: no new failures versus `main`.

- [ ] **Step 6: Commit**

```bash
git add lib/serving_ledger.py tests/test_serving_ledger.py
git commit -m "$(cat <<'EOF'
feat: move a cook to another slot, home servings included

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: `POST /api/cooks/<id>/move`

**Files:**
- Modify: `api_server.py` — insert after `api_cook_update` (ends ~line 1386), before `api_cook_delete`
- Modify: `docs/API.md` — add a row after the `/api/cooks/<int:cook_id>` DELETE row (line 104)
- Test: `tests/test_api_ledger.py` — append

**Interfaces:**
- Consumes: `serving_ledger.move_cook(cook_id, date, meal)` from Task 1; existing `_ledger_error`, `_regen_weeks`, `_sync_cook_history`, `require_token`
- Produces: `POST /api/cooks/<int:cook_id>/move`, body `{"date": "YYYY-MM-DD", "meal": "breakfast|lunch|snack|dinner"}`, returning the cook JSON (200). 404 unknown cook; 400 bad meal / bad date / date outside the cook's week; 503 on a locked DB (via `_ledger_error`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_api_ledger.py`. `_create_cook(client)` already exists there and posts Chili in `2026-W28` anchored `2026-07-07` dinner.

```python
# --- POST /api/cooks/<id>/move ---------------------------------------------


def test_move_cook_endpoint_moves_card_and_home_servings(client, tmp_db, tmp_vault):
    cook = _create_cook(client).get_json()

    resp = client.post(f"/api/cooks/{cook['id']}/move",
                       json={"date": "2026-07-09", "meal": "lunch"})

    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert (body["date"], body["meal"]) == ("2026-07-09", "lunch")
    slots = [p for p in body["placements"] if p["destination"] == "slot"]
    assert len(slots) == 1
    assert (slots[0]["date"], slots[0]["meal"]) == ("2026-07-09", "lunch")


def test_move_unknown_cook_returns_404(client, tmp_db, tmp_vault):
    resp = client.post("/api/cooks/9999/move",
                       json={"date": "2026-07-09", "meal": "dinner"})
    assert resp.status_code == 404


def test_move_cook_with_a_bad_meal_returns_400(client, tmp_db, tmp_vault):
    cook = _create_cook(client).get_json()
    resp = client.post(f"/api/cooks/{cook['id']}/move",
                       json={"date": "2026-07-09", "meal": "brunch"})
    assert resp.status_code == 400


def test_move_cook_outside_its_week_returns_400(client, tmp_db, tmp_vault):
    cook = _create_cook(client).get_json()
    resp = client.post(f"/api/cooks/{cook['id']}/move",
                       json={"date": "2026-07-20", "meal": "dinner"})
    assert resp.status_code == 400


def test_move_cook_regenerates_the_week_markdown(client, tmp_db, tmp_vault):
    """The Markdown is a view of the ledger; a move that doesn't regenerate it
    leaves the vault disagreeing with the board."""
    cook = _create_cook(client).get_json()
    plan = tmp_vault / "Meal Plans" / "2026-W28.md"

    client.post(f"/api/cooks/{cook['id']}/move",
                json={"date": "2026-07-09", "meal": "lunch"})

    assert plan.exists()
    text = plan.read_text()
    assert "Chili" in text
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.venv/bin/python -m pytest tests/test_api_ledger.py -k move_ -v
```

Expected: the four new `move_cook`/`move_unknown` tests fail with 404 (Flask has no such route) — note `test_move_endpoint` (pre-existing, placements) still passes and is a different test.

- [ ] **Step 3: Implement the route**

Insert into `api_server.py` between `api_cook_update` and `api_cook_delete`:

```python
@app.route('/api/cooks/<int:cook_id>/move', methods=['POST'])
@require_token
@_ledger_error
def api_cook_move(cook_id):
    """Move a scheduled cook to another slot, home servings included.

    Distinct from PATCH /api/cooks/<id>, which is a field-setter: this rewrites
    placement rows as well, so it says so in its name rather than making
    {"date": ...} mean two different things depending on the caller.
    """
    from lib import serving_ledger
    data = request.get_json(force=True, silent=True) or {}
    cook = serving_ledger.get_cook(cook_id)
    if cook is None:
        return jsonify({"error": "cook not found"}), 404
    cook = serving_ledger.move_cook(cook_id, data.get('date'), data.get('meal'))
    # One week, not two: move_cook rejects a date outside the cook's week.
    _regen_weeks(cook["week"])
    _sync_cook_history(cook["recipe"])
    return jsonify(cook)
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
.venv/bin/python -m pytest tests/test_api_ledger.py -v
```

Expected: PASS, including every pre-existing test in the file.

- [ ] **Step 5: Document the endpoint**

In `docs/API.md`, add immediately after the `/api/cooks/<int:cook_id>` DELETE row:

```markdown
| `/api/cooks/<int:cook_id>/move` 🔒 | POST | Move a scheduled cook to another slot. Body `date` + `meal`. Re-anchors the cook **and** re-points the slot placements sitting at its old anchor, merging into any placement already at the destination; placements in other cells (planned leftovers) are left alone. Rejects a `date` outside the cook's `week` with a `400` — `cooks.week` is not updatable and `week_board()` filters on it, so such a cook would render on no board at all. |
```

- [ ] **Step 6: Verify the docs test still passes**

```bash
.venv/bin/python -m pytest tests/test_web_dashboard.py -q
```

Expected: PASS. (This endpoint is an API route, not a browsable page, so it needs no `SECTIONS` / `NOT_BOOKMARKABLE` entry — that registry covers pages served through `_serve_page_with_claude_bar`.)

- [ ] **Step 7: Commit**

```bash
git add api_server.py tests/test_api_ledger.py docs/API.md
git commit -m "$(cat <<'EOF'
feat: expose the cook move as POST /api/cooks/<id>/move

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Cook cards drag on the board

**Files:**
- Modify: `templates/meal_planner.html` — `initGridSortables()` at line 2392; new `moveCookCard()` after `handleChipDrop()` (ends line 3227)
- Modify: `CLAUDE.md` — the "Inventory rows are containers" block is unrelated; edit the invariant sentence quoted in Step 5

**Interfaces:**
- Consumes: `POST /api/cooks/<id>/move` from Task 2; existing page globals `boardMode`, `ledgerBusy`, `currentWeek`, `dayDates`, `loadWeekBoard()`, `showToast()`
- Produces: `moveCookCard(card, cell)` — async, no return value; used again by Task 4's tap route. Reads `card.dataset.cookId` and the cell's `dataset.day` / `dataset.meal`.

- [ ] **Step 1: Add `moveCookCard()`**

Insert into `templates/meal_planner.html` immediately after `handleChipDrop()` closes (line 3227) and before `function wireChipSortables()`:

```javascript
        // Dragging a cook card re-anchors the cook and brings the servings
        // eaten at that slot with it (POST /api/cooks/<id>/move). Deliberately
        // NOT the legacy grid path: that ends in saveMealPlan(), which PUTs
        // scale-less meal-plan data over ledger-authored Markdown.
        async function moveCookCard(card, cell) {
            const cookId = card.dataset.cookId;
            if (!cookId) return;
            const date = dayDates[cell.dataset.day];
            const meal = cell.dataset.meal;

            if (ledgerBusy) {
                // Sortable already moved the node; the in-flight mutation's
                // loadWeekBoard() re-render restores truth.
                showToast('Busy — try again', 'error');
                await loadWeekBoard(currentWeek);
                return;
            }
            ledgerBusy = true;
            try {
                const resp = await fetch(`/api/cooks/${cookId}/move`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ date, meal })
                });
                if (!resp.ok) {
                    const err = await resp.json().catch(() => ({}));
                    showToast(err.error || 'Failed to move the meal', 'error');
                }
            } catch (err) {
                showToast('Failed to move the meal', 'error');
            } finally {
                // Always reload, even on failure, so the DOM Sortable already
                // mutated snaps back to server truth. No manual node removal:
                // renderBoardIfActive() clears every .cook-card unconditionally.
                await loadWeekBoard(currentWeek);
                ledgerBusy = false;
            }
        }
```

- [ ] **Step 2: Let cook cards drag in board mode**

In `initGridSortables()`, replace the comment and `draggable` line (lines 2400-2406):

```javascript
                        // A cook card must never reach debounceSave()/saveMealPlan(),
                        // which PUTs scale-less legacy meal-plan data over
                        // ledger-authored Markdown. It used to be excluded from the
                        // drag entirely; it is now draggable in board mode and
                        // branches to the ledger API in onAdd/onEnd below, before
                        // anything legacy runs. Legacy weeks keep the exclusion —
                        // there is no cook to move there.
                        draggable: boardMode ? '.grid-card' : '.grid-card:not(.cook-card)',
                        // A press on a card's own controls actuates them; it does not
                        // drag the card. preventOnFilter stays false for the reason the
                        // sidebar Sortable documents: Sortable otherwise swallows a
                        // filtered element's click on touch. Cook cards carry
                        // .scale-btn, legacy grid cards carry .servings-btn.
                        filter: '.remove-btn, .scale-btn, .servings-btn, .cooked-btn, .card-menu-btn',
                        preventOnFilter: false,
```

- [ ] **Step 3: Branch out of the legacy path in `onAdd` and `onEnd`**

In the same `Sortable.create` call, make the cook-card branch the **first** thing `onAdd` does — insert directly after `const item = evt.item;`:

```javascript
                            // First, before anything that can reach debounceSave().
                            if (item.classList.contains('cook-card')) {
                                moveCookCard(item, cell);
                                return;
                            }
```

Then guard `onEnd` (lines 2470-2477) so a cook card never triggers a legacy save:

```javascript
                        onEnd: function(evt) {
                            suppressCardTapUntil = Date.now() + 400;
                            if (evt.from !== evt.to) {
                                updateCellState(evt.from);
                                updateCellState(evt.to);
                                // onAdd already routed a cook card to the ledger;
                                // debounceSave() here would follow it with a legacy PUT.
                                if (!evt.item.classList.contains('cook-card')) {
                                    debounceSave();
                                }
                            }
                        }
```

- [ ] **Step 4: Verify the template tests still pass**

```bash
.venv/bin/python -m pytest tests/test_meal_plan_template.py tests/test_no_external_assets.py -v
```

Expected: PASS.

- [ ] **Step 5: Promote the rule to a `CLAUDE.md` invariant**

`CLAUDE.md` says nothing about cook cards today — the rule lives only as the template comment Step 2 just rewrote. Promote it, because its enforcement stops being structural (the card simply was not draggable) and becomes a branch someone can delete without the tests obviously objecting.

Insert a new bullet in the invariants list immediately after the bullet beginning `- **Task-ID stability**` (find it with `grep -n "Task-ID stability" CLAUDE.md`):

```markdown
- **A cook card moves only through the ledger API.** The planner's grid Sortable ends in `debounceSave()` → `saveMealPlan()`, which PUTs scale-less legacy meal-plan data over ledger-authored Markdown. Cook cards used to be excluded from the drag outright (`draggable: '.grid-card:not(.cook-card)'`); they are now draggable in board mode and `onAdd` branches to `moveCookCard()` → `POST /api/cooks/<id>/move` as its *first* statement, with `onEnd`'s `debounceSave()` guarded to match. Every other card mutation (scale stepper, remove button, chip drags, the ⋮ sheet's move) is already a ledger call. Deleting either guard restores the clobber quietly — the week still renders, it just loses every scale on it.
```

- [ ] **Step 5b: Verify the docs are consistent**

```bash
grep -n "cook card" CLAUDE.md && grep -n "moveCookCard" templates/meal_planner.html
```

Expected: the new invariant in `CLAUDE.md`, and `moveCookCard` defined once and referenced from `onAdd`.

- [ ] **Step 6: Restart the API and try it by hand**

```bash
launchctl unload ~/Library/LaunchAgents/com.kitchenos.api.plist
launchctl load ~/Library/LaunchAgents/com.kitchenos.api.plist
curl -s http://localhost:5001/health
```

Then open `http://localhost:5001/meal-planner`, drag a cook card to another slot, and confirm: the card lands, its serving chip follows, and the week's Markdown in the vault reflects the new day.

- [ ] **Step 7: Commit**

```bash
git add templates/meal_planner.html CLAUDE.md
git commit -m "$(cat <<'EOF'
feat: drag a scheduled cook card to another slot

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: The single-pointer route

WCAG 2.2 SC 2.5.7 requires a non-drag path for every drag, and `tests/e2e/test_planner_touch.py::TestTapToAssign` already holds this page to it. A fingertip drag across a 28-cell grid is also the gesture least likely to survive contact with an iPad.

One thing not to "fix" on the way past: the grid cell's click handler only fires when `e.target` is the cell itself, its `.empty-label`, or its `.meal-label`, and `updateCellState()` hides `.empty-label` once a cell is occupied. An occupied destination is still tappable — the `.meal-label` is always rendered, and so is the cell's own padding. No change is needed there.

**Files:**
- Modify: `templates/meal_planner.html` — assign-bar markup (line 1952), `armRecipe()` (line 4089), `disarmRecipe()`, `placeArmedRecipe()` (line 4112), `openCardSheet()` (line 3937)
- Test: `tests/e2e/test_weekly_loop.py` — append

**Interfaces:**
- Consumes: `moveCookCard(card, cell)` from Task 3; existing `armRecipe`, `disarmRecipe`, `placeArmedRecipe`, `armedRecipe`, `displayNameFor`
- Produces: a card-sheet button labelled exactly `Move to another slot`, and an assign bar whose verb reads `Moving` for a cook card and `Placing` otherwise

- [ ] **Step 1: Give the assign bar a settable verb**

Replace line 1952 of `templates/meal_planner.html`:

```html
                <span class="assign-bar-text"><span id="assign-bar-verb">Placing</span> <span id="assign-bar-name"></span> — tap a slot</span>
```

- [ ] **Step 2: Set the verb when arming**

In `armRecipe()`, after the `assign-bar-name` assignment and before `document.getElementById('assign-bar').hidden = false;`:

```javascript
            // A move that announces itself as "Placing" looks like it is about
            // to duplicate the meal rather than relocate it.
            document.getElementById('assign-bar-verb').textContent =
                card.classList.contains('cook-card') ? 'Moving' : 'Placing';
```

- [ ] **Step 3: Route an armed cook card to the move**

In `placeArmedRecipe()`, insert directly after `disarmRecipe();` (before the `if (isMeal)` block):

```javascript
            // An armed cook card is already on the board — this is a move, not a
            // second cook of the same recipe.
            if (card.classList.contains('cook-card')) {
                await moveCookCard(card, cell);
                return;
            }
```

- [ ] **Step 4: Add the sheet action**

In `openCardSheet()`, insert after the `Open recipe` block and before the servings segment:

```javascript
            // The single-pointer path WCAG 2.2 SC 2.5.7 requires for the card
            // drag, and the only route into a move on a desktop mouse-less setup.
            if (card.classList.contains('cook-card') && card.dataset.cookId) {
                addAction('Move to another slot', () => armRecipe(card));
            }
```

- [ ] **Step 5: Write the failing e2e test**

Append to `tests/e2e/test_weekly_loop.py` (offsets 1-5 of `unique_week` are taken; use 6):

```python
def test_a_cook_can_be_moved_to_another_slot_by_tapping(live_server, page, page_errors):
    """The single-pointer alternative to the card drag (WCAG 2.2 SC 2.5.7).

    Driven through the UI because the ledger call is the easy half; the part
    that breaks is the armed state routing a cook card into a *move* rather
    than into createCook(), which would schedule the same meal twice.
    """
    from datetime import date as _date
    week, when = unique_week(6)
    target = _date.fromisocalendar(2099, 7, 5).isoformat()   # Friday, same week
    cook = _log_cook(live_server, week=week, recipe="E2E Move Cook",
                     produced=2, when=when, meal="dinner")

    page.goto(live_server.url(f"/meal-planner?week={week}"),
              wait_until="domcontentloaded")
    page.wait_for_selector(".cook-card", timeout=15_000)

    # ⋮ is the only route into the sheet on a desktop browser (tap-to-open is
    # gated on IS_TOUCH).
    page.locator(".cook-card .card-menu-btn").first.click()
    page.get_by_role("button", name="Move to another slot").click()

    page.wait_for_selector("#assign-bar:not([hidden])")
    assert "Moving" in page.inner_text("#assign-bar"), \
        "a move announced as 'Placing' reads as duplicating the meal"

    page.locator('.grid-cell[data-day="Friday"][data-meal="lunch"]').click()
    page.wait_for_timeout(2000)

    conn = sqlite3.connect(live_server.db)
    row = conn.execute("SELECT date, meal FROM cooks WHERE id = ?",
                       (cook["id"],)).fetchone()
    placements = conn.execute(
        "SELECT date, meal, count FROM placements WHERE cook_id = ?"
        " AND destination = 'slot'", (cook["id"],)).fetchall()
    conn.close()

    assert row == (target, "lunch"), "the tap route did not re-anchor the cook"
    assert placements == [(target, "lunch", 1.0)], \
        "the home serving must travel with the card"
    assert page_errors == [], f"planner raised: {page_errors}"
```

- [ ] **Step 6: Run it**

```bash
.venv/bin/pytest tests/e2e/test_weekly_loop.py -m e2e -k move -v
```

Expected: PASS. If Chromium is missing, install it first: `.venv/bin/python -m playwright install chromium`.

- [ ] **Step 7: Run the touch suite (the sheet grew a control, and every control has a tap floor)**

```bash
.venv/bin/pytest tests/e2e/test_planner_touch.py -m e2e -q
```

Expected: PASS. `TestTapTargets` sweeps every visible control for a 44 pt minimum — a new sheet button that renders short fails here.

- [ ] **Step 8: Commit**

```bash
git add templates/meal_planner.html tests/e2e/test_weekly_loop.py
git commit -m "$(cat <<'EOF'
feat: move a cook by tapping, not only by dragging

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: E2E coverage for the drag gesture itself

`forceFallback: true` means SortableJS listens to raw pointer events rather than the HTML5 drag API, so Playwright's `drag_to()` does nothing. The drag must be synthesised with stepped `mouse.move()` calls, past the 100 ms `delay` and the 5 px `touchStartThreshold`.

**Files:**
- Test: `tests/e2e/test_weekly_loop.py` — append

**Interfaces:**
- Consumes: everything from Tasks 1-4. No production code changes.
- Produces: nothing other tasks depend on.

- [ ] **Step 1: Write the test**

```python
def test_a_cook_can_be_dragged_to_another_slot(live_server, page, page_errors):
    """The drag itself. SortableJS runs with forceFallback, so it listens to raw
    pointer events and Playwright's drag_to() is a no-op here — the gesture has
    to be synthesised past the 100ms delay and the 5px touchStartThreshold.
    """
    from datetime import date as _date
    week, when = unique_week(7)
    target = _date.fromisocalendar(2099, 8, 5).isoformat()   # Friday, same week
    cook = _log_cook(live_server, week=week, recipe="E2E Drag Cook",
                     produced=2, when=when, meal="dinner")

    page.goto(live_server.url(f"/meal-planner?week={week}"),
              wait_until="domcontentloaded")
    page.wait_for_selector(".cook-card", timeout=15_000)

    card = page.locator(".cook-card").first.bounding_box()
    dest = page.locator(
        '.grid-cell[data-day="Friday"][data-meal="lunch"]').bounding_box()

    # Grab the card's lower edge, clear of the name link and the button row.
    page.mouse.move(card["x"] + card["width"] / 2, card["y"] + card["height"] - 4)
    page.mouse.down()
    page.wait_for_timeout(300)          # clear the 100ms hold-to-drag delay
    for i in range(1, 11):              # stepped, so Sortable hit-tests en route
        page.mouse.move(
            card["x"] + (dest["x"] + dest["width"] / 2 - card["x"]) * i / 10,
            card["y"] + (dest["y"] + dest["height"] / 2 - card["y"]) * i / 10,
        )
        page.wait_for_timeout(30)
    page.mouse.up()
    page.wait_for_timeout(2500)

    conn = sqlite3.connect(live_server.db)
    row = conn.execute("SELECT date, meal FROM cooks WHERE id = ?",
                       (cook["id"],)).fetchone()
    conn.close()

    assert row == (target, "lunch"), "the drag did not reach the ledger"
    assert page_errors == [], f"planner raised: {page_errors}"
```

Note `unique_week(7)` yields week `2099-W08`, so the target Friday is `date.fromisocalendar(2099, 8, 5)` — the week number is `offset + 1`.

- [ ] **Step 2: Run it three times to check it is not flaky**

```bash
for i in 1 2 3; do .venv/bin/pytest tests/e2e/test_weekly_loop.py -m e2e -k dragged -q || echo "RUN $i FAILED"; done
```

Expected: three passes. **If it fails intermittently, delete this test rather than leaving it quarantined**, and update the spec's Testing section to say the tap route (Task 4) carries the coverage. A test that fails one run in three teaches the next reader to ignore the suite.

- [ ] **Step 3: Run the full e2e suite**

```bash
.venv/bin/pytest tests/e2e -m e2e -q
```

Expected: no new failures versus `main`.

- [ ] **Step 4: Run the full unit suite**

```bash
.venv/bin/python -m pytest -q
```

Expected: no new failures versus `main`.

- [ ] **Step 5: Commit**

```bash
git add tests/e2e/test_weekly_loop.py
git commit -m "$(cat <<'EOF'
test: cover the cook-card drag end to end

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Acceptance criteria (from the spec)

Verify each before calling the branch done:

- [ ] Dragging a cook card to another slot moves the card and its home servings; the board shows the result without a manual refresh. *(Task 5 e2e, plus Task 3 Step 6 by hand)*
- [ ] A leftover chip of the same cook in another cell is left where it is. *(Task 1, `test_move_cook_leaves_leftovers_where_they_are`)*
- [ ] Dropping onto a cell that already holds a leftover of the same cook yields one merged chip. *(Task 1, `test_move_cook_merges_into_a_leftover_already_at_the_destination`)*
- [ ] Dragging a card never issues a legacy `PUT /api/meal-plan/<week>`. *(Task 3 Steps 2-3; confirm by hand with the browser network panel during Step 6)*
- [ ] Scale, verdict, and cook note survive the move. *(Task 1 updates only `date`/`meal`; spot-check in Step 6)*
- [ ] Pressing `+`/`−`/🍳/×/⋮ on a card still actuates the button and does not start a drag. *(Task 3 Step 2 filter; confirm by hand)*
- [ ] ⋮ → "Move to another slot" → tap a slot performs the same move; the bar reads "Moving". *(Task 4 e2e)*
- [ ] A failed move leaves the board showing server truth, not the dragged-to position. *(Task 3 `finally` block; confirm by stopping the API mid-drag, or trust the `test_move_cook_outside_its_week_returns_400` path)*
