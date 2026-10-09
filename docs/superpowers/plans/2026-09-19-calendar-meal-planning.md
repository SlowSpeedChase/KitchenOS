# Calendar meal planning implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Choose a cooking opening from real calendar context and schedule an existing meal inside KitchenOS.

**Architecture:** The server Mac publishes minimal EventKit occurrences to SQLite. Python derives conditional cooking openings, the existing web planner renders them, and atomic serving-ledger actions persist meal preparation times. Native plan screens open the same authenticated planning view.

**Tech Stack:** Existing Python virtual environment, Flask, SQLite, Swift/EventKit/SwiftUI/WebKit, vanilla JavaScript, pytest/Playwright, XCTest. No new runtime dependencies.

**Spec:** `docs/superpowers/specs/2026-09-19-calendar-meal-planning-design.md`, approved in conversation September 19, 2026.

## Global constraints

- Use the two already selected calendars: iCloud for commitments and Time Blocking for flexible plans.
- No event details go to cloud services, model prompts, generated notes, or logs.
- End times are exclusive; use the syncing device's IANA timezone.
- Unknown or stale data never becomes an asserted free day. Six-hour snapshot expiry; 35-date coverage.
- No Apple Calendar writeback or meal-calendar ICS behavior change in this version.
- No changes to recipe identity, scale, nutrition, inventory or cooked_at when scheduling.
- Existing ledger invariants and cross-week restrictions remain in force.
- Preserve all unrelated working-tree edits. The earlier calendar feature is present but uncommitted; a clean HEAD worktree alone does not contain the starting implementation.
- Run Python via `.venv/bin/python`. Use isolated test databases/vaults. Preview servers bind to 0.0.0.0; share only a verified reachable LAN/Tailscale address.
- Commit only task-owned files after the repository completion workflow and any required approval; never stage the entire dirty checkout.

## Review focus

1. An older native client uploads daily statuses after a detailed snapshot: detailed freshness must not advance (Task 1).
2. The user changes selected calendars while a request is in flight: old responses and all-day choices must not overwrite the new selection (Tasks 1 and 2).
3. Double-tap, retry, or two concurrent schedule requests: only one initial serving placement and one preparation block (Task 4).
4. A generic cook move or patch bypasses the calendar UI: no preparation block survives on the wrong day (Task 4).
5. An event title resembles executable HTML or a token-bearing native web view navigates externally: render text and never forward credentials (Tasks 5 and 6).

## Task 1 — Versioned local snapshots and all-day choices

**Files:** create `lib/planning_calendar.py`, `tests/test_planning_calendar.py`; modify `lib/inventory_db.py`, `api_server.py`, `docs/API.md`.

**Interfaces:**

- `save_snapshot(payload: dict, *, now=None) -> dict`
- `read_week(week: str, *, now=None) -> dict`
- `set_occurrence_choice(occurrence_id: str, choice: str, revision: str) -> dict`
- `clear_snapshot() -> None`
- `register_routes(app, require_token) -> None`

POST `/api/planning-calendar/snapshot` accepts exactly:

```json
{"version":1,"selection_id":"sha256hex","generated_at":"2026-09-19T23:45:00Z","timezone":"America/Chicago","coverage_start":"2026-09-19","coverage_end":"2026-10-24","events":[{"id":"sha256hex","title":"Validator","start":"2026-09-21T00:00:00-05:00","end":"2026-09-28T00:00:00-05:00","all_day":true,"role":"firm"}]}
```

`coverage_end` is exclusive. A clear request is exactly `{"version":1,"clear":true}`. Read response: `week`, `timezone`, `fresh`, `synced_at`, `revision`, `coverage_start`, `coverage_end`, `events`, `choices`; stale/unavailable responses have empty `events` and `choices`. `revision` is server-generated on each accepted snapshot. PUT occurrence body: `{"choice":"background","revision":"..."}`; choices are `background` or `blocking`. Reject missing/stale occurrences and stale revision with 409.

- [ ] Write route and persistence tests first; use this baseline fixture in `tests/test_planning_calendar.py`:

```python
from datetime import datetime, timezone
from lib import planning_calendar as pc

NOW = datetime(2026, 9, 19, 23, 45, tzinfo=timezone.utc)
def snapshot():
    return dict(version=1, selection_id='a'*64, generated_at=NOW.isoformat(),
                timezone='America/Chicago', coverage_start='2026-09-19',
                coverage_end='2026-10-24', events=[dict(id='b'*64,
                title='Validator', start='2026-09-21T00:00:00-05:00',
                end='2026-09-28T00:00:00-05:00', all_day=True, role='firm')])

def test_all_day_choice_survives_refresh(tmp_db):
    pc.save_snapshot(snapshot(), now=NOW)
    view = pc.read_week('2026-W39', now=NOW)
    pc.set_occurrence_choice('b'*64, 'background', view['revision'])
    pc.save_snapshot(snapshot(), now=NOW)
    assert pc.read_week('2026-W39', now=NOW)['choices']['b'*64] == 'background'
```

Supply an injectable `now` to choice validation too, or use a frozen-clock fixture, so the test does not depend on wall time. Test expiry exactly six hours, out-of-coverage weeks, malformed timestamps, unknown timezone, duplicate IDs, unknown keys, title >300 characters, >5,000 events, >2 MiB HTTP body, selection changes, late old snapshots, and all-day end exclusivity. Verify an old `/api/cooking-availability` write cannot change detailed `synced_at`.

- [ ] Run `.venv/bin/python -m pytest tests/test_planning_calendar.py -q` and confirm the expected missing-feature failures.
- [ ] Implement atomic storage with these new tables; indexes on existing migrated columns belong in `_migrate`, not `_SCHEMA`:

```sql
CREATE TABLE IF NOT EXISTS planning_calendar_snapshot (
 id INTEGER PRIMARY KEY CHECK(id=1), payload_json TEXT NOT NULL,
 received_at TEXT NOT NULL, revision TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS planning_calendar_choices (
 selection_id TEXT NOT NULL, occurrence_id TEXT NOT NULL,
 occurrence_end TEXT NOT NULL, choice TEXT NOT NULL CHECK(choice IN ('blocking','background')),
 PRIMARY KEY(selection_id, occurrence_id)
);
```

Validate before taking the transaction. Check event intervals overlap coverage, positive duration, offset-aware ISO timestamps, and real ISO week/date values. Require `generated_at` no more than five minutes ahead of receipt time; reject older generation times for the same selection. For a different selection, accept only a generation time at least as recent as the stored snapshot. Generate revision with `uuid.uuid4().hex`. Use server receipt time for expiry. Preserve choices only for occurrence IDs still represented in valid coverage; clear on selection change/disconnect. Read and override operations use one coherent database transaction. Never interpolate event strings into SQL or include them in error responses.

- [ ] Register the three routes with the existing token decorator. Bound request reads before JSON parsing and return 400 invalid input, 409 stale state, 413 oversized body. Keep the existing daily endpoint independent and unchanged.
- [ ] Run new tests plus `tests/test_cooking_availability.py` and `tests/test_inventory_db.py`; update API documentation with the exact payloads and privacy/freshness contract.

## Task 2 — Native event publishing

**Files:** create `KitchenOSKit/Sources/KitchenOSKit/PlanningCalendar.swift`, `KitchenOSKit/Tests/KitchenOSKitTests/PlanningCalendarTests.swift`; modify `KitchenOSSiri/Sources/CookingCalendarSettings.swift` and connection copy.

**Interfaces:** `PlanningCalendarEvent: Codable` matching Task 1; `PlanningCalendarSnapshot: Encodable`; `KitchenOSClient.syncPlanningCalendar(_ snapshot: PlanningCalendarSnapshot) async throws`; `KitchenOSClient.clearPlanningCalendar() async throws`. Event times serialize with explicit offsets or UTC; timezone is a separate IANA identifier.

- [ ] Add fixture-driven XCTest cases before production code. Expose a pure identity helper for testing:

```swift
func testOccurrenceIdentitySeparatesCalendarAndRecurrence() {
    let a = PlanningCalendarEvent.identity(calendarID: "firm", eventID: "series", occurrence: "2026-09-21T12:00:00Z")
    let b = PlanningCalendarEvent.identity(calendarID: "firm", eventID: "series", occurrence: "2026-09-22T12:00:00Z")
    let c = PlanningCalendarEvent.identity(calendarID: "flex", eventID: "series", occurrence: "2026-09-21T12:00:00Z")
    XCTAssertNotEqual(a, b)
    XCTAssertNotEqual(a, c)
    XCTAssertEqual(a.count, 64)
}
```

Test strict title truncation to 300 Unicode characters, recurring/all-day instances, DST boundary dates, selected-role mapping, exclusion of cancelled/free/declined events, >5,000 events refusing upload rather than truncating, and the JSON request shape through `MockURLProtocol`.

- [ ] Run `swift test --package-path KitchenOSKit --filter PlanningCalendarTests` and confirm failure before implementation.
- [ ] Encode identity inputs as a JSON array, then SHA256 using CryptoKit; do not concatenate ambiguous delimiters. Prefer external event identifier with calendar item identifier fallback. Make missing usable identity a failed detailed sync, not a random ID each refresh. Generate the selected-calendar fingerprint from ordered firm/flexible IDs.

```swift
let identityBytes = try JSONEncoder().encode([calendarID, eventID, occurrence])
let identity = SHA256.hash(data: identityBytes).map { String(format: "%02x", $0) }.joined()
```

Build both legacy daily statuses and detailed occurrences from the same successfully loaded, filtered EventKit result. Keep the localhost/macOS restriction. Capture selection and generation at read start; check selection again before publishing. Serialize uploads through the existing `working` guard. Do not publish a complete empty event snapshot on access/query failure.

- [ ] Make calendar selectors draft state until Save. On a confirmed selection change, serialize clearing old details/choices before publishing the new selection. Persist a pending-clear flag until both clear endpoints succeed. Permission loss and Disconnect clear both detailed and legacy data; retry failed clears on future refresh. A 404 detailed endpoint from an old server shows a specific upgrade-needed message while legacy publishing continues.
- [ ] Update disclosure to “Event names and times from these calendars are shared with your local KitchenOS server.” Never send event descriptions, attendees, locations, URLs or raw calendar IDs. Run all Swift package tests and build macOS.

## Task 3 — Conditional cooking windows and duration estimates

**Files:** create `lib/cooking_windows.py`, `tests/test_cooking_windows.py`; extend `lib/planning_calendar.py` read route.

**Interfaces:** `suggest_windows(day: str, timezone_name: str, events: list, choices: dict, schedules: list, duration_minutes: int) -> list[dict]`; `recipe_duration(metadata: dict) -> dict` returns `minutes` and `source` (`recipe`, `estimate`). Window fields: `start`, `end`, `overlaps_flexible`, `unresolved_all_day_ids`, `adjacent_event_ids`. Query parameter `duration_minutes` defaults to 90; 15–360 inclusive, multiples of 15. Server rejects booleans, NaN and infinity wherever numeric values are expected.

- [ ] Write tests for the approved motivating case:

```python
from lib.cooking_windows import suggest_windows, recipe_duration

def test_unknown_time_uses_honest_estimate():
    assert recipe_duration({'total_time': None, 'prep_time': None, 'cook_time': None}) == {'minutes':90, 'source':'estimate'}

def test_all_day_is_conditional_until_classified():
    event = dict(id='b'*64, title='Validator', start='2026-09-22T00:00:00-05:00',
                 end='2026-09-23T00:00:00-05:00', all_day=True, role='firm')
    windows = suggest_windows('2026-09-22', 'America/Chicago', [event], {}, [], 90)
    assert windows and all(w['unresolved_all_day_ids'] == ['b'*64] for w in windows)
    assert suggest_windows('2026-09-22', 'America/Chicago', [event], {event['id']:'blocking'}, [], 90) == []
```

Add tests for background all-day events, firm overlaps, flexible overlap ranking, morning ending exactly noon, midnight-exclusive boundaries, DST dates, cross-midnight events, scheduled cooking conflicts, title-independent ranking, and durations longer than any opening.

- [ ] Run focused tests to establish failures. Implement with `zoneinfo.ZoneInfo`, timezone-aware datetimes, merged half-open occupied intervals, and 15-minute candidate starts between local noon and midnight. End must not exceed the local day boundary. Rank non-flexible-overlapping candidates first, then chronological; annotate rather than hide flexible conflicts. All-day classification applies to both calendar roles, with unresolved choices remaining conditional.

```python
# Half-open intervals overlap only when both strict inequalities hold.
def overlaps(start, end, other_start, other_end):
    return start < other_end and end > other_start
```

- [ ] Duration handling: accept only finite positive numeric minute metadata; round recipe values up to the next 15 minutes within 15–360. Missing or invalid metadata produces 90/estimate. Do not parse arbitrary prose or infer duration from duplicated imported instructions.
- [ ] Extend week response with per-day `windows`, `covered`, and `unresolved_all_day_ids`. For stale or uncovered dates return no suggested windows, retaining manual scheduling. Read recipes through existing parser/path helpers. Run the window tests and snapshot tests together.

## Task 4 — Atomic scheduling on the serving ledger

**Files:** modify `lib/serving_ledger.py`, `lib/inventory_db.py`, `api_server.py`; create `tests/test_cook_schedule.py`.

**Interface:** `schedule_cook(cook_id: int, *, date: str, meal: str, start: str, timezone: str, duration_minutes: int, servings_to_eat: float) -> dict`. API `POST /api/cooks/<id>/schedule` consumes those keyword fields. Add `schedules_for_week(week: str) -> list[dict]`, consumed by Task 3 and week response.

- [ ] Write the central idempotence regression first:

```python
from lib import serving_ledger as sl

def test_scheduling_unscheduled_cook_is_idempotent(tmp_db):
    cook = sl.create_cook(recipe='The Sexy Skillet Lasagna', week='2026-W39', servings_produced=8)
    args = dict(date='2026-09-22', meal='dinner', start='2026-09-22T19:00:00-05:00',
                timezone='America/Chicago', duration_minutes=90, servings_to_eat=1)
    sl.schedule_cook(cook['id'], **args)
    sl.schedule_cook(cook['id'], **args)
    saved = sl.get_cook(cook['id'])
    assert saved['date'] == '2026-09-22'
    assert sum(p['count'] for p in saved['placements']) == 1
    assert saved['unassigned'] == 7
    assert saved['cooked_at'] is None
    assert len(sl.schedules_for_week('2026-W39')) == 1
```

Add tests for concurrent requests, rollback on overcapacity, fractional placements, existing home servings/leftovers preserved, unchanged inventory and recipe scale, missing cook, bundle/cooked-cook rejection, cross-week rejection, timezone/date mismatch, non-15-minute start, invalid duration/servings including NaN, and generic move/PATCH/delete cleanup.

- [ ] Run tests and confirm missing scheduling behavior. Add the new table:

```sql
CREATE TABLE IF NOT EXISTS cook_schedule (
 cook_id INTEGER PRIMARY KEY REFERENCES cooks(id) ON DELETE CASCADE,
 start TEXT NOT NULL, timezone TEXT NOT NULL,
 duration_minutes INTEGER NOT NULL CHECK(duration_minutes BETWEEN 15 AND 360)
);
```

- [ ] Validate the target in its explicit IANA timezone; ensure offset matches that timezone at that instant, date equals cook date, interval stays within the local day, and date belongs to the cook's immutable week. Manual morning scheduling remains possible; automatic suggestions stay noon onward.
- [ ] Under `_write_txn`, inspect the current row before moving. Reuse `_move_cook_in_txn`. If the original anchor was absent, call `_check_capacity` and `_merge_or_insert` once for the requested initial serving. Reject negative/zero/nonfinite servings. If already anchored, preserve serving counts; the schedule action is not a serving editor. UPSERT one cook_schedule row in that same transaction. Retry only updates that row.
- [ ] Delete timed metadata in `_move_cook_in_txn` when the anchor changes, and in `update_cook` when date/meal changes; schedule_cook UPSERTs its new metadata afterward. Cascade on deletion. Existing bundle moves inherit cleanup from their internal helper. Calls that change neither date nor meal keep time metadata.
- [ ] Add the authenticated route using `_ledger_error`, then `_regen_weeks` after commit. Return saved cook and schedule. No inventory or cooked-status path is called. Conflict warnings come from the planning view; manual scheduling remains allowed after the user sees a conflict. Run ledger, week-view, schedule, snapshot and window tests.

## Task 5 — Calendar view within the existing web planner

**Files:** modify `templates/meal_planner.html`; create `static/planning-calendar.js`, `static/planning-calendar.css`, `tests/e2e/test_planning_calendar.py`.

**Interface:** `window.KitchenPlanningCalendar.mount({root, week, onScheduled})`, `.setWeek(week)`, `.destroy()`. Module owns its request generation counter, abort controllers and refresh timer. Host supplies an `onScheduled` callback that reloads the existing week board. No calendar code calls legacy saveMealPlan/debounceSave.

- [ ] Add an isolated browser test using the existing `live_server` fixture and a temporary seeded cook. Intercept snapshot reads with literal fixture data and verify the real schedule endpoint writes the isolated DB. Pin this visible behavior:

```python
from playwright.sync_api import expect

def test_calendar_mode_is_keyboard_accessible(page, live_server):
    page.goto(live_server.url('/meal-planner?week=2026-W39&view=calendar'))
    expect(page.get_by_role('button', name='Calendar', exact=True)).to_have_attribute('aria-pressed', 'true')
    expect(page.get_by_text('Calendar needs refresh', exact=True)).to_be_visible()
    expect(page.get_by_role('button', name='Choose cooking time', exact=True)).to_be_visible()
```

Add fixture cases with the lasagna, conditional Validator event, Tuesday flexible Gym block and a literal `<img src=x onerror=alert(1)>` title. Assert text rendering, no injected img, all-day choice persistence, 90-minute estimate, schedule/reload with one cook/one serving, disabled duplicate submits, 409 refresh, midnight, and rapid week switching. Test keyboard-only at 390px and 1280px widths with no clipped controls.

- [ ] Run browser tests before building the UI. Add a Grid/Calendar switch, preserving the week query parameter. Calendar mode loads the module lazily and cleans up when leaving. Use existing design tokens, semantic buttons, labeled inputs, visible focus and polite status announcements.

```javascript
const title = document.createElement('span');
title.textContent = event.title;
const reply = await fetch(`/api/planning-calendar/${encodeURIComponent(week)}?duration_minutes=${duration}`, {signal});
if (generation !== currentGeneration) return;
```

- [ ] Build desktop seven-day lanes and an all-day strip; mobile displays one selected day with previous/next controls. Default noon–10pm, expand to midnight. Lay out overlapping events in parallel sublanes so labels remain readable. Event buttons show title, start/end and role in a detail area. Unresolved all-day controls explicitly offer the two approved choices. Re-fetch after a successful override; stale responses never paint another week.
- [ ] Populate the tray from `/api/week-board/<week>` cooks with no date, excluding bundle members and cooked rows. Keep dated meals visible from normal board data. Use existing recipe data for default duration. Select a meal and opening to show editable date/time, duration, meal slot and initial servings; display conflicts, unresolved all-day context and estimate source before Schedule meal.
- [ ] POST only to `/api/cooks/<id>/schedule`. Disable repeat submission while pending, report server errors inline, preserve choices on failure, and refresh both timeline and normal board on success. Periodic detailed refresh must not erase an open form or override selection. Empty/stale calendar offers manual time input with unknown-availability copy, not a blank screen. Run the new browser suite and the existing calendar and ledger browser regressions.

## Task 6 — Native entry, deployment and end-to-end review

**Files:** create `KitchenOSSiri/Sources/MealPlan/PlanningCalendarWebView.swift`; modify both native plan views, `docs/API.md`, `docs/ARCHITECTURE.md`, `docs/OPERATIONS.md`; extend Swift URL/credential-policy tests in `KitchenOSKit/Tests/KitchenOSKitTests/PlanningCalendarTests.swift`.

- [ ] Add “Plan with calendar” to native Meal Plan and Planner Board, passing the selected ISO week to the existing web route. Build URLs with URLComponents; never place bearer tokens in URLs.

```swift
var components = URLComponents(url: baseURL.appendingPathComponent("meal-planner"), resolvingAgainstBaseURL: false)!
components.queryItems = [URLQueryItem(name: "week", value: week), URLQueryItem(name: "view", value: "calendar")]
```

- [ ] Use an in-app WKWebView restricted to the configured server origin. For configured tokens, bridge authenticated same-origin API requests at document start using JSON-encoded values; scope the injected fetch wrapper to same-origin `/api/` requests, preserve caller Request/headers/options, and never forward auth externally. A navigation delegate opens external user-selected links outside the authenticated view and rejects unexpected main-frame navigation. Do not log injected script or tokens. Test origin/port mismatch, hostile URL strings, API header preservation, and no token in URL; verify with a local mock HTTP server that cross-origin navigation/fetch cannot receive Authorization. If the existing webview is replaced, discard its credential script and message handlers.
- [ ] Run all focused Python tests, full KitchenOSKit tests, browser flows, and macOS/iOS builds. Use existing virtual environment and app scheme. Review all task-owned diffs with the requesting-code-review skill; resolve ledger/privacy blockers before live use.

```sh
.venv/bin/python -m pytest tests/test_planning_calendar.py tests/test_cooking_windows.py tests/test_cook_schedule.py tests/test_cooking_availability.py tests/test_inventory_db.py tests/test_serving_ledger.py tests/test_week_view.py -q
swift test --package-path KitchenOSKit
.venv/bin/python -m pytest tests/e2e/test_planning_calendar.py tests/e2e/test_cooking_availability.py -q
xcodegen generate
xcodebuild build -scheme KitchenOSSiri -destination 'platform=macOS' -derivedDataPath /tmp/kitchenos-planning-build
xcodebuild build -scheme KitchenOSSiri -destination 'generic/platform=iOS Simulator' -derivedDataPath /tmp/kitchenos-planning-ios CODE_SIGNING_ALLOWED=NO
git diff --check
```

- [ ] Document the new snapshot contract, occurrence choices, local data retention, schedule transaction and freshness requirements. Update the spec status to implemented only after the feature is verified. This extends an existing page, so it adds no new bookmarkable route.
- [ ] Back up the installed native app and database before deployment. Install only `KitchenOS Native.app`; `KitchenOS.app` in the user's Applications folder is a Safari web app and must not be replaced. Restart `com.kitchenos.api` for Python/template changes; verify the service and actual calendar snapshot without changing calendar events or placing a real meal as a test.
- [ ] Use CUA to inspect the live Calendar view and confirm the existing lasagna is still unscheduled, named correctly, and offers planning controls. Show Validator as unresolved until the user classifies it. Obtain and verify the machine's reachable LAN/Tailscale planner address before sharing; preserve required authentication without exposing secrets.
- [ ] Complete the finish-feature checklist for the task-owned files. Report verification, any platform limits, changed files and the reachable planner link. Do not claim deployment or live sync succeeded from a build result alone.

## Execution recommendation and self-review

Recommend native execution: the six tasks share snapshot, occurrence and ledger interfaces tightly, making one implementer economical; use a fresh whole-change reviewer for privacy and placement invariants. Subagent-driven execution is also supported if the user prefers independent review after each task.

Coverage check: event detail transport (Tasks 1–2), all-day semantics and windows (Tasks 1/3), duration and recipe inference (Task 3), persistent placement/time correctness (Task 4), mobile/desktop interaction and failures (Task 5), native access/privacy/deployment (Task 6). All five review-focus risks have an owning test step. User approved native execution. Implemented and installed September 19, 2026; verification and rulings are recorded in the execution ledger.
