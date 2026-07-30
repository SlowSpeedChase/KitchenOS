# Completed: iOS "Auto" location — stop claiming the user confirmed a shelf

**Completed:** 2026-07-29
**Branch:** `ios-auto-location`
**Duration:** same day

## Summary
Closes finding #1 of `2026-07-29-inventory-location-visibility.md`. The iOS add sheet defaulted its
Location Picker to `"pantry"` and always serialised it, so `/api/inventory/add` took the explicit
branch and stamped `location_source: manual` — "a placement the user confirmed" — for a form default
nobody had touched. App-added rows therefore never consulted the placement router and could never
show the unsure `?` marker that `/review` and `Inventory.md` both render.

The Picker now defaults to **Auto**, which omits the key entirely.

## Key Changes
- **`NewInventoryItem` in `KitchenOSKit/Sources/KitchenOSKit/Models.swift`** — the add-path payload,
  with `location: String?`. `nil` is dropped by the synthesized encoder, so "unspecified" is
  representable in the type system instead of encoded as a magic empty string.
- **`addInventory` now takes `[NewInventoryItem]`** rather than `[InventoryItem]`, and the
  `InventoryItem` overload was **removed rather than kept** — leaving it would have preserved the
  exact footgun, since that model's `location` is non-optional and could only ever send *something*.
- **`InventoryAddSheet`** — `location` state is `String?` defaulting to `nil`, the Picker gained an
  `Auto` row tagged `String?.none`, and a footnote explains what Auto does while it is selected.
- **`docs/API.md`** — the `/api/inventory/add` row now documents that `location` *is* the provenance
  declaration, so callers must omit it unless the user chose the shelf.
- **`CLAUDE.md`** — the `location_source` invariant gained the client-side rule, including "don't
  add an `addInventory` overload taking `InventoryItem`".

## Why a separate type rather than optionalising `InventoryItem.location`
`InventoryItem` is the *read* model: a row from `/api/inventory` always has a location, and its
`location` feeds `id` (`name|unit|location`), the row subline, and the `updateInventory` /
`removeInventory` calls. Making it optional would have rippled into identity and both mutation paths
to express something only the create path needs. The add and read shapes genuinely differ — one can
omit location, the other always carries it plus `location_source` — so they are now two types.

## Verification
- **RED observed first**: the new tests failed to compile (`cannot find 'NewInventoryItem' in
  scope`) before the type existed.
- **KitchenOSKit suite: 69 tests, 0 failures**, including three new ones — an unspecified location
  omits the key *entirely* (asserted on key absence, not on `null`/`""`), an explicit location is
  still sent so a deliberate pick still records `manual`, and the draft's default `location` is
  `nil`. That last one guards the actual regression one layer down.
- **App builds clean for both destinations** — `xcodebuild -scheme KitchenOSSiri -destination
  'platform=macOS'` and `-destination 'generic/platform=iOS'` both **BUILD SUCCEEDED**.
- All 26 app source files additionally typecheck against the built module via `swiftc -typecheck`.
- **End-to-end against an isolated server** (copies of the DB and storage table, free port), which
  is the only check that proves the fix rather than the intent:

  | what the client sent | location | `location_source` |
  |---|---|---|
  | `location: "pantry"` — the old untouched Picker default | pantry | `manual` ← the bug |
  | key omitted, category `other` | pantry | `default` ← renders as unsure |
  | key omitted, category `dairy` | fridge | `category` ← router resolved it |
  | `location: "freezer"` — a deliberate pick | freezer | `manual` ← correct |

  Note the first and third land on the *same shelf* with opposite provenance. That is the entire
  point: the row now asks to be checked instead of posing as confirmed.

## Not Done
- **`KitchenOSKit` still doesn't decode `location_source`** (finding #2), so the native inventory
  screen still can't render the `?` that `/review` and `Inventory.md` show. This change makes
  app-added rows *honest*; it doesn't yet make them *visible* in the app. Three views still disagree
  about what is known.
- Finding #3 (an exact `by_item` hit and a fuzzy token-subset hit both report `item`) and #4
  (`load_table()` re-parses per call) are untouched.
- The app itself has not been reinstalled on the device — free-team signing expires in ~7 days, so
  the fix reaches the phone on the next `xcodebuild` + `devicectl` pass.

## Lessons Learned
- **`xcodebuild -target` does not resolve SPM package dependencies; `-scheme` does.** Building the
  target directly failed with `Unable to resolve module dependency: 'KitchenOSKit'`, which looked
  exactly like pre-existing breakage — unmodified `main` failed the same way, which seemed to
  confirm it. It was the invocation, not the project. `xcodebuild -list` reports no schemes because
  xcodegen doesn't write shared scheme files, which makes `-target` look like the only option.
  `docs/OPERATIONS.md` had `-scheme` right all along.
- **The type system was the right place to fix a data-honesty bug.** The server can't tell a
  deliberate `"pantry"` from a defaulted one, and no amount of server validation could. Making
  "unspecified" representable — and deleting the overload that could only send *something* — means
  the next client can't reintroduce it by accident.
