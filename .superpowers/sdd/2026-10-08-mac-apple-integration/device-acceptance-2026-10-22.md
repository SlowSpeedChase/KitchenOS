# Isolated Mac mini device acceptance — 2026-10-22

## Scope and current state

The separate `KitchenOS Apple Bridge Test 850e343.app` (`com.kitchenos.applebridge.acceptance`) used an isolated API on port 5051, a temporary vault and SQLite database under `/private/tmp/KitchenOS-AppleBridge-Mini-850e343-20261021`, and destinations named `KitchenOS Bridge 850e343 ... Test`. The installed production app and API on port 5001, the original checkout, personal Reminders/Calendar items, and production vault/database were not changed. A temporary test shortcut was later created for the App Intent execution attempt below. The complete command and observation record is in that temporary root's `acceptance.md`.

**Latest checkpoint:** all five signed-app action methods passed separate Xcode 27
`AppIntentsTesting` runs. The synthetic cook is scheduled for October 22 at 18:00
America/Chicago for 60 minutes, dinner, placement 1; it remains uncooked at scale 1
and four servings. Temporary inventory/purchases/trips have zero rows. Only the
isolated port-5051 API was restarted from reviewed Python fix `4bb7260`, after a
temporary SQLite backup; production port 5001 (PID 947) was unchanged. The separate
Apple Development-signed bundle has `TeamIdentifier=XZJ6358HHF`, CDHash
`b4d051116188412bb99242bf5e247ac3734ed3d3`. Final API status is connected/unpaused,
**0 queued / 0 conflicts / 0 unavailable**, with
`last_success=2026-10-22T19:58:26.468044Z` after the later EventKit read-back.
Freshly refreshed Settings shows prep Active Export 2 and cooking Active Export 4, with zero conflicts. Bridge
acknowledgements/observations support their locators; these current items have
not been directly visually checked in Apple Reminders/Calendar.

Earlier sections below retain their checkpoint evidence. Unscheduled-cook,
unrun-action and pending-Xcode-authorization statements describe earlier states
and are superseded by the final execution section.

## Live checks

- Full Reminders and Calendar access were authorized for the distinct test app. Shopping completion/reopening and prep completion/due changes round-tripped. Clearing and then setting the prep due date preserved its task and meal. Paused sync withheld changes until resume. Restart replay retained one owned item per active scope without a duplicate. Closing the last app window did not stop background sync. No reminder action changed inventory, purchases, trips, cooked state, or servings.
- The generation-1 cooking event was verified by title, dedicated calendar, exact ownership URL token, generation, and locator. Moving and resizing it in Calendar from Oct 22, 18:00–19:00 to 19:00–20:30 imported `2026-10-22T19:00:00-05:00`, `America/Chicago`, and 90 minutes into `cook_schedule` without changing its cook or other domains.
- `DELETE /api/cooks/1/schedule` on the isolated API removed only that reservation. The bridge acknowledged an exact owned-event deletion; the event disappeared from Calendar, while the cook, dinner placement, scale, servings, and uncooked state remained.
- A newly exported generation-2 event was deleted in Calendar after checking its exact test calendar and ownership token. The adapter submitted `availability: unavailable` with `absence_confirmed: false`; the cook reservation remained. Public EventKit cannot establish global Calendar absence from an unlocatable event. An explicit `Keep Apple item separate` review cleared the resulting retained-generation conflict before a fresh generation-3 export. Repeating that exact test produced a current active unavailable observation; the corrected isolated API reported `unavailable: 1`, and a fresh Settings load displayed 1. Explicitly unscheduling the synthetic cook retired the item and returned API and fresh Settings status to 0.
- The earlier ad-hoc separate app package contained all five Mac integration actions as discoverable App Intent metadata. While that ad-hoc build was installed, searching the action library for the exact separate app name `KitchenOS Apple Bridge Test 850e343` displayed `Send Shopping List to Reminders`, `Send Prep Tasks to Reminders`, `Sync Cooking Calendar`, `Schedule Cooking`, and `Sync KitchenOS` alongside existing recipe actions. This confirmed live action-library discovery at that checkpoint; the later shopping-only execution is recorded below. An empty `New Shortcut 2` (zero actions) created during navigation was removed after explicit user confirmation of Shortcuts’ iCloud deletion warning. `All Shortcuts` returned from 201 to 200, and the blank item was absent.

## Follow-up fixes and verification

- `6df095b` retains current, active, current-revision unavailable observations in read-only status. An independent scoped review passed spec and quality. RED reproduced the 0-versus-1 bug; GREEN Apple bridge tests passed 166, and full Python passed 4,593 (1 skipped, 137 deselected; nine baseline XML warnings).
- `5d3fe24` makes Settings use fresh status for ongoing queued/conflict/unavailable counts while labeling higher command-only counts as `This attempt`. An independent scoped review passed spec and quality. RED covered both stale directions; GREEN focused Swift tests passed 6, full Swift package passed 171, both unsigned macOS and iOS Simulator builds succeeded, and full Python passed 4,593 (1 skipped, 137 deselected; nine baseline warnings).
- An interim ad-hoc rebuild changed the test app's designated requirement and lost its existing privacy grant; the original bundle was restored then. Since that checkpoint, the reviewed test build was signed with the existing Apple Development identity, installed separately, granted Calendar access, and showed the current Controls summary on-device. No production installation or TCC reset occurred.

## Rulings and cost if wrong

- **Treat a missing linked Calendar event as unavailable, not a confirmed deletion.** Cost if wrong: an event moved beyond readable EventKit search could silently erase a valid cook reservation.
- **Keep current unavailability visible across status reloads; distinguish the command result from current status.** Cost if wrong: Settings can report a clean state while a linked event is unlocatable, or keep warning after the item retires.
- **Restore the original authorized ad-hoc test binary after its rebuilt code hash changed.** Cost if wrong: a nonworking test installation could appear to have permission while EventKit requests remain unresolved; forcing privacy reset could affect grants outside this approved test.

## Remaining device acceptance

- Directly visually verify current prep generation 2 and cooking generation 4 in the dedicated Apple destinations. The final bridge evidence below establishes acknowledged exports, not a fresh Apple-app visual check.
- Repeat all-five live Shortcuts library discovery on the current signed build; earlier discovery used the ad-hoc installation. Siri, iPhone/personal-device acceptance and remaining provider/lifecycle cases in `docs/OPERATIONS.md` are pending.
- The exact temporary `KitchenOS Bridge 850e343 Intent Acceptance` shortcut is still present. Do not retry deletion through the unreliable selection path; the user declined further recovery of the unrelated personal shortcut. No cleanup is claimed.

## App Intent execution attempt — 2026-10-22

With the user's explicit isolated-action approval, the exact test app was connected to the temporary API on port 5051. Shopping and prep Reminders access was restored to full authorization in the separate app; Calendar was authorized. Fresh status showed all three dedicated test scopes connected, with zero queued writes, conflicts, or unavailable items. The synthetic cook remained uncooked and unscheduled, and the independent Cooking Calendar availability feature remained off.

A temporary Shortcuts item named `KitchenOS Bridge 850e343 Intent Acceptance` was created with only `Send Shopping List to Reminders`, parameterized to October 22, 2026. Running it in Shortcuts and then via `shortcuts run` produced the same “Shortcuts couldn’t communicate with the app” error. Neither invocation reached the isolated API or changed the synthetic Apple or KitchenOS items. The other four actions were not run because the shared launch boundary had failed.

Focused macOS `linkd` diagnostics at 12:22:59 and 12:24:07 reported `Unable to get teamId from com.kitchenos.applebridge.acceptance PID [9699]`, `Rejecting invalid client due to requiresValidatedBundle`, and `LNConnectionErrorDomain Code=1200 AppleEvents communication failed`. The installed bundle's code signature verifies on disk, but `codesign` reports `Signature=adhoc` and `TeamIdentifier=not set`. An initial sandboxed `security find-identity -v -p codesigning` check returned zero identities; the unsandboxed follow-up below corrected that environmental result. This is a signing barrier to live App Intent invocation, not evidence that the action's `perform` body failed. Merely rebuilding or ad-hoc signing again cannot verify execution.

Afterward, the isolated SQLite database still had zero inventory, purchases, trips, cook reservations, or pending bridge operations; cook 1 remained at scale 1, four servings, and `cooked_at = NULL`. The separate test app and isolated API were stopped. Production port 5001 remained running and untouched. The user subsequently approved deleting that exact shortcut across iCloud devices. The first UI deletion controls did not respond and `shortcuts list` returned “Couldn’t communicate with a helper application.” During a later cleanup attempt, a different personal shortcut was removed; see the incident below. The KitchenOS test shortcut has **not** been deleted.

**Ruling:** Require a valid Team ID-signed build before treating Shortcuts action execution as device-verified. Cost if wrong: discoverable metadata could be mistaken for working invocation, and repeated ad-hoc tests would obscure an OS-level rejection.

## Signing identity follow-up — 2026-10-22

An unsandboxed, read-only `security find-identity -v -p codesigning` check found one valid Apple Development identity, with certificate-name suffix `83C595AYFY` (later codesign showed actual `TeamIdentifier=XZJ6358HHF`). Xcode beta → Apple Accounts → Personal Team → Manage Certificates showed the existing `Chase’s Mac mini` Apple Development certificate with a blank status, consistent with [Apple DTS's signing identity status explanation](https://developer.apple.com/forums/thread/801305). `project.yml` pins `XZJ6358HHF`, which at that checkpoint appeared different from the certificate-name suffix; the installed production app bears that TeamIdentifier. The distinct test bundle was still ad-hoc signed then; no signing, install, permission expansion, or App Intent invocation occurred during this read-only follow-up. This was a preliminary mismatch inference from the certificate label; the later signed-bundle TeamIdentifier verification below supersedes it.

**Ruling:** Do not infer that signing is unavailable from a sandboxed keychain result or that an available identity belongs to the project-pinned team. Cost if wrong: device acceptance could be abandoned unnecessarily, or a test app could be signed under an unintended team and misidentified as the production app.

## Shortcuts cleanup incident — 2026-10-22

The user approved deletion of the exact one-action `KitchenOS Bridge 850e343 Intent Acceptance` shortcut. After a normal Shortcuts app restart, its accessibility tree showed that test row selected and `All Shortcuts 201`. An Edit-menu click failed because the accessibility element became invalid. A subsequent Command-Delete and Return apparently acted on a different focused shortcut. After relaunch, `All Shortcuts` was 200 and `Share Sheet` fell from 25 to 24. The test shortcut remained as the first row. The personal `Download on Mac` shortcut (four actions, previously shown in the library) was absent; an exact Shortcuts search returned no results. This is an unintended deletion, and it may have synced to the user's other devices. No KitchenOS action was run by this cleanup attempt.

Apple's documented iCloud recovery categories do not include Shortcuts, and this Mac mini has no configured Time Machine destination or local snapshot. A targeted read-only filename search found no matching export or ZIP in Downloads, Desktop, Documents, or the isolated KitchenOS test directory. macOS denied read-only access to the protected Shortcuts database (`Operation not permitted`); no permission was expanded or private database content inspected. The user checked another device and found no copy, then said they do not care about this unrelated shortcut. Recovery work stopped. Further deletion of the KitchenOS test shortcut is suspended because Shortcuts selection and keyboard focus diverged during this attempt.

**Ruling:** Treat Shortcuts accessibility selection as unverified when menu or keyboard focus can diverge, and confirm the exact target in a visible deletion dialog before any further removal. Cost if wrong: another personal shortcut could be deleted across iCloud devices.

## Signed test app, recovery fix, and action boundary — 2026-10-22

A fresh unsandboxed signing check found the existing Apple Development identity with SHA prefix `CD9543BAF3A4C7DD7E06F96C6A4FC20677EE8CA5`. Although its certificate name ends in `83C595AYFY`, the separately installed `~/Applications/KitchenOS Apple Bridge Test 850e343.app` reports the project's `TeamIdentifier=XZJ6358HHF` and CDHash `b4d051116188412bb99242bf5e247ac3734ed3d3`. `codesign --verify --deep --strict` passed. No certificate was created or revoked. A Debug build initially lacked packaged App Intent metadata because of Xcode's debug dylib; rebuilding with `ENABLE_DEBUG_DYLIB=NO` yielded all five discoverable action records. This is metadata evidence for the current signed package. The live Shortcuts library displayed all five actions on the earlier ad-hoc installation; that all-five library check has not been repeated after signing. At this checkpoint the signed build had one shopping Shortcut invocation verified below; later harness execution is recorded in the final section.

The exact one-action shopping Shortcut subsequently exited 0 through `shortcuts run`, and the isolated API recorded shopping PUT, owner, observations, and work requests. This proves the shopping `perform` path reached the test API. At this checkpoint it did not prove full delivery to Apple and the other four actions had not been executed; the final section supersedes that execution status. The one-action test shortcut remains in the personal Shortcuts library because the earlier deletion path was unreliable.

Local fix `c234c32` passed fresh independent scoped **spec PASS / quality PASS** review. When a retired linked Apple object becomes unavailable or uncertain-missing, the server opens a `retired_unavailable` conflict with only `keep_manual`; it does not infer absence or mutate Apple or the cook. A later present observation cannot schedule deletion while review is open. The resolution checks the retirement generation, source revision, and locator before detaching the bridge link into history. The Apple object may still exist. After restarting only the isolated API with this reviewed source, the test app displayed the named synthetic soup's `Keep Apple item separate` choice. Selecting it cleared the sole test conflict without a cook or Apple mutation. The latest fresh pass advanced `last_success` to `2026-10-22T19:11:32.209618+00:00`; API and newly opened Settings both showed **0 queued / 0 conflicts / 0 unavailable**. The cook remains unscheduled and uncooked; inventory, purchases, and trips remain empty.

Post-fix verification: full Python **4,599 passed, 1 skipped, 137 deselected**, with nine unchanged XMLParsedAsHTMLWarning warnings; Swift package **172 passed**; unsigned macOS and iOS Simulator builds passed; import and `git diff --check` checks passed. Detailed logs are in `/private/tmp/KitchenOS-AppleBridge-Mini-850e343-20261021/logs/retired-unavailable-*`.

An independently reviewed temporary `AppIntentsTesting` UI harness is locked to the signed test app path, bundle ID, CDHash, port 5051, and the three test-only `2026-W43` scopes. Two CLI attempts stopped before any test method or API call. Focused `testmanagerd` diagnostic: `Writer daemon requires authentication to enable automation mode.` Xcode GUI's first run lacked its runner build; a normal build then failed debugger attach before a method. The user approved enabling UI testing for the exact Xcode Helper. At this checkpoint System Settings showed a password sheet for local entry. **Authorization and harness execution were pending then; the final section below supersedes this block.**

**Rulings and cost if wrong:**

- Verify the signed bundle's actual TeamIdentifier and packaged metadata, rather than inferring either from a certificate-name suffix or sandboxed keychain result. Cost if wrong: valid acceptance is abandoned or an app without discoverable actions is treated as ready.
- Keep retired unlocatable events in explicit, revision-fenced review. Cost if wrong: uncertain visibility or a stale choice could delete an Apple event or mutate a cook, while `last_success` stalls or falsely advances.
- Treat the shopping Shortcut's API requests as invocation evidence only. Cost if wrong: a queued or incomplete Apple export could be reported as delivered.
- Treat UI runner authentication as a macOS test prerequisite, and require user approval for its broad automation permission. Cost if wrong: a harness failure is misdiagnosed as an App Intent failure or device control is expanded without authorization.

## Final signed App Intent execution — 2026-10-22

The user completed the previously approved password prompt locally. Device Control
and Data Access then showed only Apple-signed `com.apple.dt.Xcode-Helper` enabled
at `/Applications/Xcode-beta.app/Contents/Developer/Platforms/MacOSX.platform/Developer/Library/Xcode/Agents/Xcode Helper.app`.
The harness retained its exact signed test-app path/bundle/CDHash, port 5051,
permission, dedicated-destination and active `2026-W43` scope preconditions.

Each row is a separate one-method run (Chicago local time); each completed with
zero test failures:

| Harness method | Result | Time | Evidence under temporary `IntentHarness/` |
| --- | --- | --- | --- |
| test01 Send Shopping List to Reminders | PASS | 14:40:14 | `test01-after-helper.log` |
| test02 Send Prep Tasks to Reminders | PASS | 14:41:00 | `test02-after-helper.log` |
| test03 Sync Cooking Calendar | PASS | 14:41:39 | `test03-after-helper.log` |
| test04 typed Schedule Cooking | PASS | 14:42:27 | `test04-after-helper.log` |
| test02 Send Prep Tasks, settled rerun | PASS | 14:55:37 | `test02-after-settled.log` |
| test05 Sync KitchenOS | PASS | 14:55:51 | `test05-after-helper.log` |

The corresponding `results-after-helper-test01` through `test05.xcresult` and
`results-after-settled-test02.xcresult` bundles retain runner evidence. API logs
`api-after-recovery.log` and `api-after-history-fix.log` record shopping/prep/cooking
scope PUTs, exact cook lookup and schedule POST 200, and generic sync completion.
Typed Schedule Cooking addressed only synthetic cook 1. It saved the reservation,
but the original export was blocked by the source history bug; method PASS alone
did not prove Calendar delivery.

The initial prep action encountered an empty saved task set because the temporary
vault lacked the synthetic recipe instructions. A test-only recipe note for
`KitchenOS Bridge Test Soup 850e343` was added to the temporary vault; off-request
task extraction saved one prep task, `66ac08cddec3`. No production fixture or
source note was changed. Reviewed fix `4bb7260` orders cooking source state as
cooked → history; eligible uncooked scheduled single-recipe cook → active;
otherwise inherited history → history. It preserves historical fields while
allowing explicit rescheduling to create a replacement export generation.

After the backed-up temporary DB and isolated API restart, background sync at
14:53 created/acknowledged prep generation 2 and cooking generation 4. A prep
rerun at 14:53:04 stopped with `unsafeEnvironment` in preflight, before test-app
activation or `intent.run()`, because two transient background upserts were
queued. They settled; the 14:55 prep rerun and generic sync passed. This was a
preflight race, not an App Intent product failure. Neither the original prep nor
schedule method created these replacement exports inside its invocation.

Final active records each have a bridge locator in the exact dedicated destination:

| Domain | Destination ID | Active generation |
| --- | --- | --- |
| Shopping | `662183AE-35C9-454F-8B8F-835772411418` | 1 |
| Prep | `400F6CBD-537A-462E-A657-424502B5971C` | 2 |
| Cooking | `92C8C385-1392-47D4-A654-D7CF9B9D0737` | 4 |

Prep generation 1 is retired; cooking generation 1 is retired and generations
2–3 are history, all without current locators. Fresh Settings and API state agree
as recorded at the top of this report. Current exports are supported by EventKit
acknowledgements and observations, without a current direct Apple-app visual check.

A subsequent EventKit observation cycle at 14:58:25–26 independently read back
shopping generation 1, prep generation 2 and cooking generation 4 as
`availability: present`, `issue: null`, with the same exact locators, destinations
and expected synthetic fields. Journal rows 270–272 match each item's
`last_observation`; no operations were needed. Acknowledgement alone does not
write `last_observation`, so this later provider read-back is additional evidence
beyond the export acknowledgements. It still does not replace a direct Apple UI
visual check.

Fix verification recorded RED regression failures, focused **123 passed**, full
Python **4,601 passed / 1 skipped / 137 deselected / nine unchanged warnings**;
fresh independent review returned **spec PASS / quality PASS**, with **148 tests
passed** independently. The preceding **172 Swift tests** and unsigned macOS/iOS
Simulator builds remain valid checkpoints because no Swift changed; they were not
rerun after this Python-only fix. No production install, deployment, push,
production restart or personal Apple-item change occurred in this continuation.
The distinct test shortcut remains.

**Rulings and cost if wrong:**

- **Separate method PASS from actual export.** Verify ledger, generation, acknowledgement and current observation independently. Cost if wrong: a no-op action or later background export is misreported as delivery inside the action.
- **Keep the preflight queue guard.** Wait for background work to settle before rerunning. Cost if wrong: a transient queue race is called a product failure, or the harness writes during unsettled work.
- **Reactivate only eligible uncooked scheduled cooks ahead of history.** Cooked/deleted/ineligible historical records remain frozen. Cost if wrong: valid schedules never publish, or completed history is republished.
- **Regenerate temporary prep fixtures off-request.** Save task evidence before action acceptance. Cost if wrong: empty fixtures pass invocation while hiding missing delivery, or page rendering invokes extraction unnecessarily.
