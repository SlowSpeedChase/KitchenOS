# Device acceptance follow-up: unavailable status

## Finding

In the isolated Mac test, deleting only a verified generation-2 cooking event made
the native adapter submit `availability: unavailable` and
`absence_confirmed: false`. The server preserved the cook's reservation as
required, but a fresh `GET /api/apple-integration/status` returned
`report.unavailable: 0`. Settings therefore displayed `0 unavailable` after
reload even though the active item's stored observation was unavailable and
`last_success` had not advanced. No personal event or production API was used
to reproduce this report bug.

## Change

`_report()` now derives a current-known unavailable count from stored
observations of active, latest-generation items in active scopes. It accepts
an unavailable/uncertain-missing/issue observation only when its revision still
matches the item. The report uses the larger of that durable count and a
transient unavailable count supplied by the current reconciliation. The status
read remains local SQLite work; it performs no EventKit or source reads.

`docs/API.md` defines this meaning for the status, work, and observation
response envelopes.

## Rulings and cost if wrong

1. **Keep current known unavailability visible in status.** A stored active
   current-revision observation counts even after the request that recorded it
   ends. Cost if wrong: Settings can claim `0 unavailable` while a linked
   Calendar event cannot be found, inviting a mistaken clean-sync conclusion.
2. **Reject stale and out-of-scope observations.** Source revision changes,
   retirement, and paused/archived scopes remove an old observation from this
   status count; only the latest generation qualifies. Cost if wrong: users see
   a persistent warning for work that is no longer the current active export.
3. **Take the maximum of durable and transient unavailable counts.** Current
   work can report an unreadable source scope that has no item observation;
   status can report a known uncertain item between passes. Cost if wrong:
   overwriting one count hides an unavailable condition, while summing them can
   double-count the same item and overstate affected work.
4. **Keep status read-only.** The counter is a view of journal evidence, not a
   new inference that an Apple object was deleted. Cost if wrong: status polling
   could trigger Apple reads or falsely unschedule a cook; public EventKit still
   cannot prove global absence of an unlocatable Calendar event.

## Verification

- RED: `test_status_retains_only_current_active_unavailability` failed at
  `GET /status` with actual `0`, expected `1` after a real unavailable
  observation (one expected failure).
- GREEN: that test passed after the report change. It also checks that work
  retains the current count, source revision changes clear stale evidence,
  paused scopes clear the visible count, and retirement clears it.
- Apple bridge Python group: **166 passed**.
- Full Python suite: **4,593 passed, 1 skipped, 137 deselected**. Nine existing
  `XMLParsedAsHTMLWarning` warnings remained.
- Imports (`extract_recipe`, `main`, `api_server`, service) and
  `git diff --check` exited 0.
- Finish-feature key-function check found no new or renamed public function.
  `AGENTS.md` has no `lib/apple_integration/service.py` key-function entry;
  this internal `_report` change does not add one.

Device acceptance after an isolated API restart is for the controller; this
worker did not touch the temporary test database or Apple stores.
