# Calendar and meal planning inside KitchenOS

Status: implemented, independently reviewed, tested and installed September 19, 2026. Native Mac sync verified against the real selected calendars. iOS build and mobile browser verified; physical iOS device verification remains.

## Intended outcome

Chase wants KitchenOS to make it possible to choose a realistic cooking time without mentally reconstructing the week or asking Codex to inspect Calendar. The immediate example is scheduling The Sexy Skillet Lasagna to use ricotta already on hand. Its existing planned cook must be reused, not duplicated.

Success means seeing firm commitments, flexible Time Blocking, all-day context, and planned cooking together; selecting an opening; and seeing the meal persist in the normal plan after reload.

## Approved behavior

- Use the two already selected calendars: iCloud for commitments and Time Blocking for flexible plans.
- Focus cooking opportunities on noon through the evening; morning events do not automatically rule out a day.
- Show timed events and flexible blocks separately, with names and times.
- Put all-day events above the timeline. Let the user classify each as “Blocks cooking” or “Background information.”
- Show unscheduled meals beside the week and allow selecting an opening to schedule one.
- Label estimated cooking durations honestly. Keep calendar details local to KitchenOS.

## Why the current implementation is insufficient

The native app currently reduces all events to one status per day before upload. The server cannot explain a busy day or show openings. An all-day event named Validator spans September 21–27 and currently blocks the week; its meaning is unknown. Treating it as a background note without user input would be an unsupported assumption. A payment reminder on iCloud also illustrates why all-day context needs an explicit distinction.

The ledger stores a cook's date and meal, not its preparation time. Moving a never-scheduled cook currently does not create a serving placement. The new action must account for both, rather than only drawing a temporary block.

## Product surface

Extend the existing /meal-planner with a “Calendar” view beside the current meal grid. Native Meal Plan and Planner Board provide access to the same planning view through the configured KitchenOS server, avoiding a second implementation of scheduling rules. Existing native daily labels continue using the compatibility API.

Desktop: week timeline with noon–10pm visible, all-day strip above, and an unscheduled-meal tray alongside. The late-evening portion through midnight remains accessible by expanding the time range. Mobile: date navigation and a readable single-day timeline, with the same meal tray below. No drag operation is required: select meal, select opening, review time and servings, then Schedule meal. Existing grid interactions remain available.

Use solid timed blocks for firm commitments and a distinct patterned or outlined treatment for flexible blocks, accompanied by text labels. All event names are rendered as text, never trusted HTML. Selecting an event reveals its exact interval and calendar role. Locations, attendees, descriptions and links are excluded.

All-day items default to “Needs your choice”; display potential gaps as conditional until blocking/background status is resolved. This replaces the unexplained blanket-busy presentation without silently declaring the day free. Persist the choice for that event occurrence across syncs; offer no automatic recurrence-wide rule in this version.

The default view is the selected planner week. The lasagna appears as an unscheduled meal using its existing ledger ID. No day is assigned during installation or migration.

## Opening suggestions

Use deterministic interval arithmetic in the syncing device's IANA timezone, not an LLM. Merge overlapping firm commitments, clip to the visible date, and subtract already scheduled cooking blocks. A user-classified blocking all-day event blocks the day; an unresolved all-day event makes suggestions conditional.

Flexible blocks remain visible. Rank gaps that avoid them ahead of gaps that overlap them; show “Overlaps Time Blocking” for the latter. Do not pretend those blocks are confirmed free time. Show exact adjacent events so the user can judge travel or recovery time; do not invent travel durations.

Cooking duration precedence: a positive recipe total_time, then positive prep_time plus cook_time when both exist, otherwise a clearly labeled editable 90-minute planning estimate. For the lasagna, the source timing fields are missing, so use “90 min · planning estimate.” This is a reserved window, not a claimed measured recipe duration. Offer 15-minute start increments and 15–360 minute duration in 15-minute steps. User edits apply only to this planned cook.

## Local calendar data flow

The already authorized Mac app remains the only uploader, retaining the localhost-only sync guard. Add a versioned event snapshot alongside the existing status payload. Keep the old endpoint working for native labels and older clients; an old status-only upload must not fabricate or refresh detailed event data.

Sync the next 35 local dates every five minutes while the Mac app is open. Publish snapshot coverage start/end, timezone, generation time, selected-calendar identity fingerprint, and event occurrences. Each occurrence contains only an opaque identity, title (maximum 300 characters), start/end, all-day flag, and role (firm/flexible). Build identity from a hash of calendar identity plus external event identity plus occurrence start, never title; separate recurring occurrences and calendar switches must not inherit each other's overrides accidentally. End times are exclusive. Normalize all-day dates in the source timezone.

Continue ignoring cancelled, declined, and explicitly free events. Reject malformed snapshots atomically, with bounds of 5,000 occurrences and 2 MiB. A truncated or failed EventKit read must not be published as a complete snapshot. Invalid or unavailable source data yields unknown, not an empty/free week.

Store one complete snapshot in kitchenos.db, with occurrence overrides in a separate table. Replace snapshot transactionally. Purge obsolete occurrence overrides after their dates leave the retained coverage. Disconnect clears event details and overrides. A confirmed calendar-selection change clears old detailed coverage and choices before accepting new data. Permission loss clears details on the next successful server contact; when offline the server still expires them after six hours.

Serve no event titles from stale snapshots. Display “Calendar needs refresh” and the last successful sync timestamp. Keep meal scheduling usable manually during outages without showing asserted conflict-free openings. Browsing outside coverage shows unknown and preserves the meal grid.

The expanded titles/times sharing is within the existing local KitchenOS installation, including the user's authenticated LAN/Tailscale access. No cloud service, model prompt, debug log, or generated Obsidian note receives event details. Use the existing token gate and safe response handling; raw calendar contents must not appear in exception messages.

## Contracts and ownership

- Extend KitchenOSKit calendar types and CookingCalendarSync for event snapshots. Update connection copy to disclose event names/times, replacing the old “Only daily availability” text.
- Add POST /api/planning-calendar/snapshot for the versioned bounded upload, GET /api/planning-calendar/<week> for fresh event occurrences, all-day choices and cooking blocks, and PUT /api/planning-calendar/occurrences/<opaque-id> for a blocking/background choice. All use the token gate. Reject overrides for absent or stale occurrences.
- Put snapshot validation/persistence in lib/planning_calendar.py and gap calculation in lib/cooking_windows.py. Use inventory_db migrations for any new columns or indexes on existing tables.
- Add POST /api/cooks/<id>/schedule for atomic scheduling: date, meal, timezone-aware start, duration_minutes, and servings_to_eat for first placement. Store preparation time in a new cook_schedule table keyed by cook ID with cascading deletion, not in recipe metadata.
- Schedule inside one database transaction. Reuse the existing internal ledger move routine for anchor/placement movement. For an unscheduled cook, create the requested initial slot placement within remaining yield capacity. A repeated identical request must not add another serving or cook. Moving a scheduled cook preserves existing home-serving counts and unrelated leftovers. Validate the cook's existing week, date/time alignment, capacity, and start/end bounds before writes.
- Cross-week moves remain unsupported by this action, matching the ledger's immutable week invariant; explain this in the UI. Bundle cards continue through the existing bundle API and are not offered by the first version's timed single-recipe scheduling tray. Their existing meal placements remain visible.
- Existing move and delete paths must keep cook_schedule consistent: remove timed metadata when a generic date/meal move makes it invalid; delete via cascade. Never leave a timed block pointing at a different day from its cook. Do not alter scales, recipe identities, nutrition, inventory, or cooked_at when scheduling.
- Regenerate affected meal-plan views from committed ledger state. Preparing a meal and eating its servings remain separate concepts. Display the meal in its usual day/meal slot and its preparation block on the timeline. No Apple Calendar writeback or meal-calendar ICS behavior change in this version.

## Validation

- Swift: event filtering, opaque occurrence identity, DST, timezone conversion, exclusive all-day end boundaries, empty complete snapshot versus unavailable source, and backward-compatible status publishing.
- Python: payload bounds and rollback; old-client compatibility; freshness/coverage; cancelled/free events excluded before upload; role distinction; overlapping intervals; unresolved/all-day overrides; occurrence changes; token enforcement; safe string handling.
- Ledger integration: first unscheduled lasagna placement, retry idempotence, existing servings moved once, capacity rollback, same-week enforcement, timed-data cleanup on generic move/delete, no inventory consumption or cooked flags.
- Browser: populated week, narrow layout, keyboard meal/time selection, all-day choice, refreshing gaps, conflict explanation, save/reload, failures, stale calendar, and week-navigation races. Test hostile event titles as literal text.
- Build macOS and iOS, test against isolated vault/database copies, then install the verified native build and restart the API. Verify the real calendar view and shared LAN/Tailscale address before handing it over. Never modify the real calendar or schedule a meal merely to test the feature.

## Scope limits

No meal recommendations, nutritional recalculation, automatic reshuffling, purchase changes, inventory cleanup, calendar edits, or new standalone website. Ricotta amount and the meaning of Validator remain user facts to establish through the actual planning controls. The first deliverable is a usable KitchenOS calendar-planning flow for single-recipe cooks.
