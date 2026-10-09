# KitchenOS Mac: Reminders, Calendar, and App Intents

**TL;DR:** Extend the existing native Mac app. Shopping and prep reminders sync completion in both directions; scheduled cooking syncs time changes in both directions. App buttons and Mac Shortcuts use the same operations. Preserve KitchenOS's ledger and inventory rules, prevent duplicate exports, and surface conflicting edits.

Status: approved by Chase on October 8, 2026. Implementation planning follows; no product code or personal Apple data has been changed for this request.

## Intended outcome and assumptions

Chase wants a Mac KitchenOS app with App Intents that can put useful kitchen work into Apple Reminders and Calendar. The response “Yes” to the send-only versus two-way question is interpreted as choosing two-way synchronization.

Success means publishing shopping/prep tasks and scheduled cooking, changing supported fields in either app, and seeing those changes survive refresh without duplicate Apple items, lost servings, or unintended inventory changes.

Use the existing SwiftUI Mac app and local Python server. One designated Mac owns the Apple integration. iPhone, web, and Obsidian remain KitchenOS clients; Apple's account sync distributes the exported items. The Mac app reconciles while it and the server are running. Closing a window leaves the app running; quitting or sleeping pauses synchronization until the next launch/wake. Settings reports this limitation, pending changes, and the last successful sync. Launch at login remains optional.

## Approach and alternatives

**Recommended: add an EventKit bridge to the existing app.** The Python server owns KitchenOS domain state and durable sync bookkeeping. The native app owns EventKit permissions and Apple item access. Native buttons and App Intents call the same application service.

- Shortcuts-only workflows offer a quicker initial export, but spread identity, retries, and return updates across user-created shortcuts.
- A separate companion/background application introduces another installation, permission identity, and lifecycle. It is unnecessary for this release.

This intentionally extends the September calendar-planning design, which excluded Apple writeback. Its calendar snapshots, privacy protections, and ledger constraints remain prerequisites. The current branch contains related uncommitted implementation; preserve that baseline and unrelated changes when preparing the implementation checkout.

## Setup and scope

Add Apple Integration to existing native settings with separate Reminders/Calendar permission state, shopping/prep list selections, cooking calendar selection, pause and Sync Now controls, last success, pending work, and actionable errors/conflicts.

Request access in the foreground with an explanation of the intended use. Full Calendar access is needed for existing availability reading and reconciliation; full Reminders access is needed for completion reading and updates. Denying one permission does not disable the other integration. No Apple content goes to an LLM.

Let the user choose writable destinations or create dedicated KitchenOS destinations. Store identifiers, not names. A missing or read-only destination pauses its domain; never silently substitute another list/calendar.

Connecting does not publish historical data. Send Shopping List, Send Prep Tasks, and Sync Cooking Calendar activate their selected week/domain. Default to the current local week and display its date range. Activated scopes reconcile until paused, disconnected, or archived. Archiving preserves Apple items and stops synchronization for that scope. Completed historical items are not automatically purged.

Register one Mac installation as the bridge owner. Backend ownership generations reject stale imports and acknowledgements. A second installation cannot start publishing automatically. Owner replacement requires stopping/disconnecting the previous writer and recovering existing ownership markers before enabling creation; a server token alone cannot fence a write already in flight to EventKit.

## Shopping reminders

- Export only real buy-list checkboxes, never plain-bullet Already Have items. A missing list is generated through the existing pantry-aware path without invoking pantry-spending confirmation.
- Completing or reopening a linked reminder toggles its exact KitchenOS shopping checkbox. Changes from KitchenOS or Obsidian flow back to Apple.
- Completion records shopping progress only. It never adds inventory, decrements pantry stock, infers a receipt, or logs cooking.
- Each reminder contains readable quantity/name text and a link back to its KitchenOS shopping week/item.

### Durable row identity

Add hidden IDs to purchase checkbox rows and teach every consumer to strip them from display/item text. Markdown remains authoritative for membership, title, quantity, and checked state. Database records store identity and synchronization state, not a second shopping-demand or inventory database.

Generated identity is derived from week, normalized ingredient, and the aggregator's unit bucket: volume, weight, count, no-amount, or exact unknown unit. Amount and rendered title are not keys. A removed/reintroduced demand receives a new export generation so an old completion callback cannot complete new demand.

Manual rows receive UUIDs; identical manually entered lines remain distinct. An explicitly tagged manual row remains manual even if its wording matches generated demand. Initial migration assigns current generated identity to one unambiguous matching row and UUIDs to additional manual occurrences. Ambiguous provenance requires review instead of guessing. Migration occurs on explicit activation or a normal save, never an unrelated read.

Validate row-ID uniqueness within each week. A copied hidden ID pauses the affected rows as an identity conflict; never update the first matching row or all matches. A hand edit that changes a generated row's ingredient or aggregation bucket cannot retain that food's completion/export identity. Preserve the edited row and flag a regeneration conflict. Resolution either keeps the edit as a new manual UUID or restores the generated row; completion is never transferred to a different ingredient. Compare other hand-edited content with the last generated payload before regeneration, preserving edits for review rather than overwriting them.

Regeneration preserves row IDs and completion. Update an incomplete row's existing reminder when quantity changes. Equivalent unit conversions are not demand changes. If a completed row's required quantity changes, retain its completion and show Shopping Amount Changed for review; do not silently hide a changed need or reopen the purchase. The conflict must remain visible in both the shopping screen and integration status until resolved.

When generated demand disappears, retire its link and remove only its unchanged, incomplete owned reminder. Preserve completed Apple reminders as history. Concurrent Apple changes require conflict resolution. Reappearing demand starts incomplete with a new export generation.

## Prep reminders

Use structured task IDs with week context: `prep:<week>:<task_id>`. Completion/reopening uses the existing task-state operation, protected by sync revision checks and the task cache freshness rules. Stable IDs retain their completion during regeneration.

Use actual planned dates without inventing alarm times. Undated tasks remain undated until the user supplies a date. Changing a reminder due date stores a link-level override shown in KitchenOS; it does not move a meal or rewrite recipe instructions. Shopping reminders may use the same optional due-date override.

Task IDs include recipe, day, slot, and step. Moving a meal can retire one task and create another. Preserve completed history and do not transfer completion by matching titles. An unchanged incomplete retired task's owned reminder may be removed; a concurrently edited reminder requires review.

## Cooking events

Publish one nonrecurring event per eligible, uncooked, single-recipe cook with a valid `cook_schedule`. Use the stored preparation start, IANA timezone, duration, display title, and KitchenOS link. Unscheduled meals receive no invented times. Bundle timed scheduling stays outside this release because the existing scheduling API rejects bundle members; existing meal/bundle planning remains usable.

KitchenOS schedule changes update the same Apple event. Calendar moves/resizes invoke the validated ledger scheduling operation, never the legacy meal-plan PUT or direct meal-plan Markdown edits. A same-week date change moves the anchor and appropriate serving placements through the ledger, retaining meal slot and serving counts. Scales, unrelated leftovers, inventory, derived nutrition, and cooked state remain unchanged.

Existing constraints remain: 15-minute start increments; 15–360 minute durations in 15-minute steps; finish by midnight; no cross-week moves; no scheduling cooked rows or bundle members. Interpret incoming instants in the cook's configured timezone. All-day/recurring conversions and moves to unsupported dates are conflicts, not silently accepted schedules.

An invalid Calendar edit remains visible in Apple and as a KitchenOS conflict. Do not silently snap it back or change the ledger. Resolution restores the KitchenOS time or uses a valid replacement chosen in KitchenOS.

Deleting an owned Apple event removes only its timed reservation. Add a transactional `unschedule_cook` operation and authenticated `DELETE /api/cooks/<id>/schedule`; preserve the cook, meal slot, serving placements, scale, and ingredients. Explicit rescheduling creates a new export generation. Deleting a KitchenOS cook retires its event unless concurrent Apple changes require review. Finishing a cook freezes its event as history.

Exclude owned cooking events from incoming external-calendar busy snapshots, because their intervals already come from `cook_schedule`. Identify ownership by marker, never by title. Preserve legacy ICS publishing for installations that do not use native export. Explain duplicate representations if the same meals are subscribed via ICS and published natively; do not remove existing subscriptions automatically.

## Supported edits and deletions

Two-way fields are reminder completion, optional reminder due-date overrides, and cooking start/duration. Recipe identity, ingredients, yield, and nutrition remain KitchenOS-owned.

User title/note edits in Apple remain in Apple and do not rename recipes. Keep an explicit display override when Apple changes a title so a later generated-title update cannot silently erase it. Preserve unrelated user fields when updating supported fields. A removed ownership marker triggers recovery/review rather than title-based reassociation.

Deleting a reminder in Apple suppresses that export without deleting the KitchenOS row/task; restoring it is explicit. Arbitrary newly authored Apple items are not imported as KitchenOS meals/tasks. Never clear a whole list/calendar. Each mutation verifies ownership of the specific object.

Disconnect stops writes and preserves Apple items. Removing owned items is a separate explicit action. Moving an item to another destination is not treated as deletion: update its locator after finding its ownership marker in readable destinations, or request review when it cannot be located safely.

## Synchronization and persistence

Use a focused integration module and migrations in `data/kitchenos.db`. Preserve domain authorities: ledger for cooks/schedules, task sidecars for prep completion, and editable shopping notes. Store enabled scopes, destinations, bridge owner, logical IDs, export generations, EventKit locators, field-level common values, revisions, pending operations, suppressions/tombstones, and conflicts. Do not store a duplicate pantry or nutrition rollup.

EventKit IDs are locators, not logical identity. Each exported object carries an opaque stable ownership token in a public EventKit field, such as an app-link URL. Resolve by recorded ID, then search for the exact marker before creating. Duplicate markers, account churn, lost markers, and ambiguous objects require recovery rather than title matching. Do not read Apple's private database.

Compare each supported field against its last acknowledged common value. A one-sided change propagates; identical changes converge; different changes to one field require a user choice. Independent fields can merge. Do not use wall-clock last-write-wins. Identical callbacks and notifications do not advance revisions. Validate expected item revision, export generation, and bridge owner before applying mutations.

Persist an operation ID before an Apple save, include the ownership marker on first creation, and acknowledge only after success. A crash after save but before acknowledgement recovers the existing object by marker. Serialize manual, intent, and periodic requests; debounce EventKit notifications. After restart, fetch current server/Apple state before replay. Retry transient failures with bounded backoff.

Reconcile on launch, activation/wake, EventKit change, successful KitchenOS operations, and the existing periodic refresh cadence. An offline Mac does not create new exports from stale desired state. Permission loss, incomplete reads, missing destinations, and outages mean unavailable, never mass deletion. Infer deletion only after a complete successful read with established visibility and ownership; uncertain absence requires review.

Protect shopping-note and prep-sidecar edits with content revisions, the existing server locking discipline, and atomic file replacement. Reconcile external file edits before remote updates and check the input hash again immediately before replacement. Preserve recoverable before/after content in pending operations; a detected race pauses the item and exposes both versions for recovery. Do not claim that arbitrary external editors participate in the server lock.

A hash check and atomic replacement do not provide filesystem compare-and-swap: an external editor can write between them. Test that interleaving, retain recoverable content available to the bridge, and describe concurrent external editing as a limitation rather than promising lossless synchronization with every editor.

SQLite and Markdown cannot share a transaction. Use durable pending-operation records, deterministic replay, and detection of already-applied file changes. Do not hold DB transactions across EventKit or network operations. Domain updates and their generated views must finish or recover before reporting synchronized success.

## App Intents and API boundaries

Add typed actions: Send Shopping List to Reminders, Send Prep Tasks to Reminders, Sync Cooking Calendar, Schedule Cooking, and Sync KitchenOS. Use structured week/date and cook parameters/entities. Native buttons and intents share one service and return useful counts plus explicit queued, partial, or conflict outcomes.

Schedule Cooking uses the ledger, not the existing legacy add-to-plan client path. Add stable native deep-link routes for exported shopping items, prep tasks, and cooks; opening a link resolves identity, selects the relevant view, and never mutates domain state by itself.

First-run permission/destination needs continue in the foreground app. Once configured, intents execute without opening a full window when supported. Verify actions in the Mac Shortcuts action library and document creating named shortcuts; do not promise iPhone-style automatic App Shortcut phrase registration on Mac. Keep iOS building and able to show integration status without introducing a second EventKit writer.

Add bounded, versioned, authenticated endpoints under `/api/apple-integration` for setup/scopes, desired objects, operation acknowledgements, observed edits, conflict resolution, and status. Enforce revisions, owner/export generations, idempotency keys, payload bounds, and existing authorization. Mac reconciliation remains restricted to its local configured server. Other authorized KitchenOS clients use ordinary domain APIs and can read status.

When native integration is enabled, existing web/MCP shopping/prep send commands enqueue the same durable requests and report queued versus delivered honestly. Preserve argv-safe AppleScript fallback for installations without native integration, but never run both writers for a linked scope. Token-gate legacy sender/task mutation routes touched by this work. Recipe extraction's separate Reminders inbox is outside this change.

## Validation and delivery

- Fake EventKit stores and isolated DB/vault fixtures: create/update/retry, crash after save, identifier churn, duplicate/lost markers, foreign same-title items, manual shopping duplicates, quantity changes after completion, and note/sidecar races.
- Round trips: completion/reopening, due overrides, suppress/restore, task-ID changes, archived scopes, and completed history. Assert no inventory, purchase, or cooking-log mutations from shopping completion.
- Calendar: valid moves/resizes, deleting only the reservation, serving preservation, invalid/cross-week/all-day/recurring/DST edits, source deletion conflicts, and owned-event exclusion from busy snapshots.
- Failures: denied/revoked permissions, incomplete stores, missing/read-only destinations, offline/restart recovery, old bridge owners, simultaneous callers, partial results, and API authentication.
- Build macOS and iOS; run relevant Swift/Python tests. Verify App Intent metadata and discovery, then exercise a named Mac Shortcut end to end using dedicated test destinations. Obtain explicit permission before creating test data in personal Apple stores.
- Update README, API, architecture, and operations documentation. Install the verified Mac build through the existing deployment process and restart the API after implementation. Verify signing/persistence instead of assuming iOS provisioning limitations apply to Mac.

Implementation phases are identity/reconciliation/setup, shopping/prep round trips, Calendar round trips, and App Intent/installed-app acceptance. A detailed implementation plan follows review of this written design.

## References

- [Existing calendar-planning design](2026-09-19-calendar-meal-planning-design.md)
- [Existing Siri/App Intents design](2026-06-21-siri-app-intents-voice-design.md)
- [Apple: accessing EventKit](https://developer.apple.com/documentation/eventkit/accessing-the-event-store)
- [Apple: App Shortcuts platform considerations](https://developer.apple.com/design/human-interface-guidelines/app-shortcuts)
- [Apple: verifying App Intents](https://developer.apple.com/documentation/appintents/verifying-your-app-intents-implementation)
