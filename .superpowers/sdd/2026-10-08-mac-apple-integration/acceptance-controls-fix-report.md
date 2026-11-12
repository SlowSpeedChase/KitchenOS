# Device acceptance follow-up: native status summary

## Finding

After an isolated Calendar deletion, the backend's current-known status correctly
reported one unavailable owned event. The installed Mac app could briefly show
zero after **Sync now** or **Refresh connection**, then show one after leaving
and reopening Settings. The reverse also occurred after the test-only cook was
unscheduled: a command summary could retain one while current status was zero.
`AppleIntegrationControls.run()` loaded fresh status and then replaced its
message with the command report, whose counters can describe a different pass.

## Change

After a command, controls now read fresh status and apply it to their published
model. The primary summary retains the command's created/updated/deleted counts
but takes queued/conflicts/unavailable from that current status. If a command
reported a higher transient count, a separate `This attempt:` suffix shows it
without mislabeling it as the current warning count. A failed status read after
a command still follows the existing unconfirmed-action error path.

## Rulings and cost if wrong

1. **Use fresh status for ongoing warnings.** The server's read-only status is
   the current-known source for queued, conflict, and unavailable counts; an
   action result is not a replacement for it. Cost if wrong: Settings can show
   zero for an active missing Calendar event or retain a warning after its
   source item retires.
2. **Name higher command counts as transient.** Created, updated, and deleted
   remain the just-finished action's counts. A higher queued, conflict, or
   unavailable count from that action appears separately as `This attempt:`.
   Cost if wrong: hiding it would conceal a blocked sync, while merging it into
   the primary status would make retired work look currently unresolved.
3. **Keep failures conservative.** If the fresh status read fails after an
   action, do not claim a confirmed current state from the action report.
   Cost if wrong: a transient connection failure could appear as a clean sync.

## Verification

- RED: the focused Swift suite failed both new divergent-report tests before
  implementation; original tests remained green. Logs:
  `/private/tmp/kitchenos-controls-red.log` and
  `/private/tmp/kitchenos-controls-red2.log`.
- GREEN: focused `AppleIntegrationControlsTests` passed **6/6** after the
  change. Log: `/private/tmp/kitchenos-controls-green.log`.
- Full `swift test --package-path KitchenOSKit` passed **171/171**. Log:
  `/private/tmp/kitchenos-controls-swift-full.log`.
- Unsigned macOS and iOS Simulator `xcodebuild` commands both exited zero with
  `BUILD SUCCEEDED`. Logs: `/private/tmp/kitchenos-controls-macos.log` and
  `/private/tmp/kitchenos-controls-ios.log`. The macOS log retains only the
  existing `AppShell.swift:52` unreachable-default warning.
- Python imports and `git diff --check` exited zero. The full Python suite
  passed **4,593 tests**, with one skipped, 137 deselected, and the nine
  unchanged `XMLParsedAsHTMLWarning` warnings. Log:
  `/private/tmp/kitchenos-controls-python-full.log`.

This patch changes only shared UI status presentation and its tests; it does
not touch EventKit objects, the bridge's serialization, cook state, or any
personal Apple store.
