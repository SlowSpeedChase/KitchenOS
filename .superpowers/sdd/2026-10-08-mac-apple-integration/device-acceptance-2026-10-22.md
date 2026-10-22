# Isolated Mac mini device acceptance — 2026-10-22

## Scope and final state

The separate `KitchenOS Apple Bridge Test 850e343.app` (`com.kitchenos.applebridge.acceptance`) used an isolated API on port 5051, a temporary vault and SQLite database under `/private/tmp/KitchenOS-AppleBridge-Mini-850e343-20261021`, and destinations named `KitchenOS Bridge 850e343 ... Test`. The installed production app and API on port 5001, the original checkout, personal Apple items, and production vault/database were not changed. The complete command and observation record is in that temporary root's `acceptance.md`.

At the end, the synthetic cook has **no reservation**, remains uncooked with scale 1 and four servings, and the temporary inventory/purchases/trips tables have zero rows. The bridge has zero open conflicts and zero current unavailable items. The dedicated test destinations remain. The journal has one active shopping reminder; prep and cooking exports are retired, and the owned cooking event was removed. The separately installed test app is the exact previously authorized ad-hoc binary with its original code hash, and the isolated API was stopped after verification.

## Live checks

- Full Reminders and Calendar access were authorized for the distinct test app. Shopping completion/reopening and prep completion/due changes round-tripped. Clearing and then setting the prep due date preserved its task and meal. Paused sync withheld changes until resume. Restart replay retained one owned item per active scope without a duplicate. Closing the last app window did not stop background sync. No reminder action changed inventory, purchases, trips, cooked state, or servings.
- The generation-1 cooking event was verified by title, dedicated calendar, exact ownership URL token, generation, and locator. Moving and resizing it in Calendar from Oct 22, 18:00–19:00 to 19:00–20:30 imported `2026-10-22T19:00:00-05:00`, `America/Chicago`, and 90 minutes into `cook_schedule` without changing its cook or other domains.
- `DELETE /api/cooks/1/schedule` on the isolated API removed only that reservation. The bridge acknowledged an exact owned-event deletion; the event disappeared from Calendar, while the cook, dinner placement, scale, servings, and uncooked state remained.
- A newly exported generation-2 event was deleted in Calendar after checking its exact test calendar and ownership token. The adapter submitted `availability: unavailable` with `absence_confirmed: false`; the cook reservation remained. Public EventKit cannot establish global Calendar absence from an unlocatable event. An explicit `Keep Apple item separate` review cleared the resulting retained-generation conflict before a fresh generation-3 export. Repeating that exact test produced a current active unavailable observation; the corrected isolated API reported `unavailable: 1`, and a fresh Settings load displayed 1. Explicitly unscheduling the synthetic cook retired the item and returned API and fresh Settings status to 0.
- The separate app package contains all five Mac integration actions as discoverable App Intent metadata. Actual action-library discovery inside Shortcuts remains pending.

## Follow-up fixes and verification

- `6df095b` retains current, active, current-revision unavailable observations in read-only status. An independent scoped review passed spec and quality. RED reproduced the 0-versus-1 bug; GREEN Apple bridge tests passed 166, and full Python passed 4,593 (1 skipped, 137 deselected; nine baseline XML warnings).
- `5d3fe24` makes Settings use fresh status for ongoing queued/conflict/unavailable counts while labeling higher command-only counts as `This attempt`. An independent scoped review passed spec and quality. RED covered both stale directions; GREEN focused Swift tests passed 6, full Swift package passed 171, both unsigned macOS and iOS Simulator builds succeeded, and full Python passed 4,593 (1 skipped, 137 deselected; nine baseline warnings).
- The reviewed native build was installed briefly as an update to the separate test app. Its ad-hoc designated requirement changed with its code hash, so macOS did not reuse the existing Reminders/Calendar privacy grant. The exact prior test bundle was restored, signature-verified, and re-registered; its full permissions returned. The new Controls summary is therefore verified by Swift tests/build/review, not by live EventKit use of that rebuilt binary. A stable signing identity and fresh device authorization are needed for its installed-binary retest. No TCC reset or new privilege was used.

## Rulings and cost if wrong

- **Treat a missing linked Calendar event as unavailable, not a confirmed deletion.** Cost if wrong: an event moved beyond readable EventKit search could silently erase a valid cook reservation.
- **Keep current unavailability visible across status reloads; distinguish the command result from current status.** Cost if wrong: Settings can report a clean state while a linked event is unlocatable, or keep warning after the item retires.
- **Restore the original authorized ad-hoc test binary after its rebuilt code hash changed.** Cost if wrong: a nonworking test installation could appear to have permission while EventKit requests remain unresolved; forcing privacy reset could affect grants outside this approved test.

## Remaining device acceptance

- Verify the five named actions in the Mac Shortcuts action library and exercise them in the distinct test environment.
- Install and reauthorize a build with a stable signing identity, then confirm the reviewed Settings summary on-device immediately after sync and refresh. Until then, the working installed test app runs the older presentation code; repository source and both platform builds contain the fix.
