# Inventory Cleanup Screen Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface date-added and expiration per item in the native iPad app's inventory screen, and make pruning expired / used-up items easy.

**Architecture:** The Flask backend already returns `purchased` and `expires` on `GET /api/inventory`; we add a computed `expiry_status` field (reusing `lib/expiry.py:expiry_status()` so it agrees with `Inventory.md`). The Swift `KitchenOSKit` package gains `expires`/`expiryStatus` on `InventoryItem` plus pure presentation helpers (badge emoji, sort rank, secondary-line text). The `KitchenOSSiri` app's `InventoryView` consumes those helpers to render dates + badges, sort the worst items to the top of each category, and remove an item when its quantity is stepped to 0.

**Tech Stack:** Python 3.11 / Flask (backend), Swift / SwiftUI (`KitchenOSKit` library + `KitchenOSSiri` app), `swift test` + `pytest`.

## Global Constraints

- **Python 3.11**; all Python commands run via `.venv/bin/python` / `.venv/bin/pytest`.
- **Backend changes must be additive** — the new `expiry_status` field must not change the existing `/api/inventory` request shape, filters, or break existing consumers.
- **Swift decode stays tolerant** — only `name` is required; every other field falls back to a default (matches the existing `InventoryItem.init(from:)` pattern). New fields decode via `decodeIfPresent`.
- **Single source of truth for expiry thresholds** — never hardcode the "≤3 days = soon" rule in Swift; it comes from the server's `expiry_status`.
- **Expiry status vocabulary:** `"expired"`, `"soon"`, `"ok"`, or `null`/absent. Badge shows 🔴 for `expired`, 🟡 for `soon`, nothing otherwise.
- **DB in tests** points at a temp file via the `tmp_db` fixture (`KITCHENOS_DB`); vault via `tmp_vault`.

---

### Task 1: Backend — add `expiry_status` to `GET /api/inventory`

**Files:**
- Modify: `api_server.py` (the `api_inventory_list` handler, ~line 1534)
- Test: `tests/test_api_server.py`

**Interfaces:**
- Consumes: `lib.expiry.expiry_status(expires: Optional[str]) -> Optional[str]` (existing), `lib.inventory.read_inventory()`, `InventoryItem.to_dict()`.
- Produces: each item dict in the `GET /api/inventory` JSON array now carries an extra key `expiry_status` with value `"expired"`/`"soon"`/`"ok"`/`null`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_api_server.py`:

```python
# ---------------------------------------------------------------------------
# /api/inventory — computed expiry_status field (additive)
# ---------------------------------------------------------------------------

def test_inventory_list_includes_expiry_status(client, tmp_vault, tmp_db):
    # An always-expired perishable, and a no-expiry household item.
    client.post("/api/inventory/add", json={"items": [
        {"name": "old milk", "quantity": 1, "unit": "gal", "category": "dairy",
         "location": "fridge", "expires": "2020-01-01"},
        {"name": "dish soap", "quantity": 1, "unit": "ct", "category": "household",
         "location": "pantry"},
    ]})

    resp = client.get("/api/inventory")
    assert resp.status_code == 200
    by_name = {i["name"]: i for i in resp.get_json()}

    assert by_name["old milk"]["expiry_status"] == "expired"
    # No expiry configured for household → null/None, but the key is present.
    assert "expiry_status" in by_name["dish soap"]
    assert by_name["dish soap"]["expiry_status"] is None
    # Field is additive — existing keys still present.
    assert by_name["old milk"]["expires"] == "2020-01-01"
    assert by_name["old milk"]["purchased"] is not None or "purchased" in by_name["old milk"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_api_server.py::test_inventory_list_includes_expiry_status -v`
Expected: FAIL — `KeyError: 'expiry_status'` (the field isn't in the response yet).

- [ ] **Step 3: Write minimal implementation**

In `api_server.py`, replace the `api_inventory_list` body's return so each dict gets a computed status:

```python
@app.route('/api/inventory', methods=['GET'])
def api_inventory_list():
    """List inventory items, with optional category/location filters."""
    from lib.inventory import read_inventory
    from lib.expiry import expiry_status

    items = read_inventory()
    category = (request.args.get('category') or '').lower().strip()
    location = (request.args.get('location') or '').lower().strip()
    if category:
        items = [i for i in items if i.category == category]
    if location:
        items = [i for i in items if i.location == location]

    payload = []
    for i in items:
        d = i.to_dict()
        d["expiry_status"] = expiry_status(d.get("expires"))
        payload.append(d)
    return jsonify(payload)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_api_server.py::test_inventory_list_includes_expiry_status -v`
Expected: PASS.

- [ ] **Step 5: Run the inventory + expiry test files to check no regression**

Run: `.venv/bin/pytest tests/test_api_server.py tests/test_expiry.py tests/test_inventory.py -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add api_server.py tests/test_api_server.py
git commit -m "feat(api): expose computed expiry_status on GET /api/inventory

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Swift model — add `expires` + `expiryStatus` to `InventoryItem`

**Files:**
- Modify: `KitchenOSKit/Sources/KitchenOSKit/Models.swift` (the `InventoryItem` struct, ~lines 171-205)
- Test: `KitchenOSKit/Tests/KitchenOSKitTests/ModelsTests.swift`

**Interfaces:**
- Produces: `InventoryItem.expires: String?` and `InventoryItem.expiryStatus: String?`, both decoded via `decodeIfPresent`. The `init(...)` memberwise initializer gains two trailing optional params (default `nil`) so existing call sites (e.g. `InventoryAddSheet`) keep compiling unchanged.

- [ ] **Step 1: Write the failing test**

Add to `KitchenOSKit/Tests/KitchenOSKitTests/ModelsTests.swift` (inside the existing test type):

```swift
func testDecodeInventoryItemWithExpiry() throws {
    let json = Data("""
    {"name":"old milk","quantity":1,"unit":"gal","category":"dairy",
     "location":"fridge","purchased":"2026-06-13","expires":"2026-06-23",
     "expiry_status":"expired","source":"receipt","notes":""}
    """.utf8)
    let item = try JSONDecoder().decode(InventoryItem.self, from: json)
    XCTAssertEqual(item.expires, "2026-06-23")
    XCTAssertEqual(item.expiryStatus, "expired")
    XCTAssertEqual(item.purchased, "2026-06-13")
}

func testDecodeInventoryItemWithoutExpiryFields() throws {
    // Back-compat: name-only payloads still decode; new fields are nil.
    let json = Data(#"{"name":"rice"}"#.utf8)
    let item = try JSONDecoder().decode(InventoryItem.self, from: json)
    XCTAssertNil(item.expires)
    XCTAssertNil(item.expiryStatus)
    XCTAssertEqual(item.name, "rice")
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd KitchenOSKit && swift test --filter ModelsTests/testDecodeInventoryItemWithExpiry`
Expected: FAIL to compile — `value of type 'InventoryItem' has no member 'expires'`.

- [ ] **Step 3: Write minimal implementation**

In `Models.swift`, update the `InventoryItem` struct. Add the two stored properties after `notes`:

```swift
    public var notes: String
    public var expires: String?
    public var expiryStatus: String?
```

Update the memberwise initializer signature and body (add the two trailing params + assignments):

```swift
    public init(name: String, quantity: Double, unit: String = "ct",
                category: String = "other", location: String = "pantry",
                purchased: String? = nil, source: String = "manual", notes: String = "",
                expires: String? = nil, expiryStatus: String? = nil) {
        self.name = name; self.quantity = quantity; self.unit = unit
        self.category = category; self.location = location
        self.purchased = purchased; self.source = source; self.notes = notes
        self.expires = expires; self.expiryStatus = expiryStatus
    }
```

Update the custom `init(from:)` to decode the two new fields (add after the `notes` line). Note `expiry_status` is snake_case in JSON, so add an explicit `CodingKeys` entry:

```swift
        notes = (try? c.decode(String.self, forKey: .notes)) ?? ""
        expires = try c.decodeIfPresent(String.self, forKey: .expires)
        expiryStatus = try c.decodeIfPresent(String.self, forKey: .expiryStatus)
```

Swift auto-synthesizes `CodingKeys` from property names, but `expiryStatus` must map to `expiry_status`. Add an explicit `CodingKeys` enum inside the struct (Swift drops synthesis once you decode manually, but keep it explicit to be safe):

```swift
    enum CodingKeys: String, CodingKey {
        case name, quantity, unit, category, location, purchased, source, notes, expires
        case expiryStatus = "expiry_status"
    }
```

> If a `CodingKeys` enum already exists in the struct, just add the `expires` and `expiryStatus = "expiry_status"` cases instead of creating a new one.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd KitchenOSKit && swift test --filter ModelsTests`
Expected: PASS (both new tests + existing ones).

- [ ] **Step 5: Build the app target to confirm call sites still compile**

Run: `cd KitchenOSKit && swift build`
Expected: builds clean (the memberwise `init` defaults keep `InventoryAddSheet`'s call valid).

- [ ] **Step 6: Commit**

```bash
git add KitchenOSKit/Sources/KitchenOSKit/Models.swift KitchenOSKit/Tests/KitchenOSKitTests/ModelsTests.swift
git commit -m "feat(kit): add expires + expiryStatus to InventoryItem

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Swift presentation helpers — badge, sort rank, secondary line

**Files:**
- Create: `KitchenOSKit/Sources/KitchenOSKit/InventoryItem+Display.swift`
- Test: `KitchenOSKit/Tests/KitchenOSKitTests/InventoryDisplayTests.swift`

**Interfaces:**
- Consumes: `InventoryItem.expires`, `InventoryItem.expiryStatus`, `InventoryItem.purchased` (from Task 2).
- Produces, all as members of `InventoryItem` (pure, no I/O):
  - `var expiryBadge: String?` → `"🔴"` when `expiryStatus == "expired"`, `"🟡"` when `"soon"`, else `nil`.
  - `var expiryRank: Int` → `0` expired, `1` soon, `2` everything else (for sorting worst-first).
  - `var inventorySecondaryLine: String` → e.g. `"Added Jun 13 · Exp Jun 23 🔴"`, `"Added Jun 13 · No expiry"`, `"Exp Jun 23 🟡"` (no purchased), or `"No expiry"` (neither). Dates formatted `MMM d` with `en_US_POSIX` locale for determinism.

- [ ] **Step 1: Write the failing test**

Create `KitchenOSKit/Tests/KitchenOSKitTests/InventoryDisplayTests.swift`:

```swift
import XCTest
@testable import KitchenOSKit

final class InventoryDisplayTests: XCTestCase {

    private func item(purchased: String? = nil, expires: String? = nil,
                      status: String? = nil) -> InventoryItem {
        InventoryItem(name: "x", quantity: 1, purchased: purchased,
                      expires: expires, expiryStatus: status)
    }

    func testBadge() {
        XCTAssertEqual(item(status: "expired").expiryBadge, "🔴")
        XCTAssertEqual(item(status: "soon").expiryBadge, "🟡")
        XCTAssertNil(item(status: "ok").expiryBadge)
        XCTAssertNil(item(status: nil).expiryBadge)
    }

    func testRank() {
        XCTAssertEqual(item(status: "expired").expiryRank, 0)
        XCTAssertEqual(item(status: "soon").expiryRank, 1)
        XCTAssertEqual(item(status: "ok").expiryRank, 2)
        XCTAssertEqual(item(status: nil).expiryRank, 2)
    }

    func testSecondaryLineFull() {
        let line = item(purchased: "2026-06-13", expires: "2026-06-23",
                        status: "expired").inventorySecondaryLine
        XCTAssertEqual(line, "Added Jun 13 · Exp Jun 23 🔴")
    }

    func testSecondaryLineNoExpiry() {
        let line = item(purchased: "2026-06-13").inventorySecondaryLine
        XCTAssertEqual(line, "Added Jun 13 · No expiry")
    }

    func testSecondaryLineNoPurchased() {
        let line = item(expires: "2026-06-23", status: "soon").inventorySecondaryLine
        XCTAssertEqual(line, "Exp Jun 23 🟡")
    }

    func testSecondaryLineNeither() {
        XCTAssertEqual(item().inventorySecondaryLine, "No expiry")
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd KitchenOSKit && swift test --filter InventoryDisplayTests`
Expected: FAIL to compile — `value of type 'InventoryItem' has no member 'expiryBadge'`.

- [ ] **Step 3: Write minimal implementation**

Create `KitchenOSKit/Sources/KitchenOSKit/InventoryItem+Display.swift`:

```swift
import Foundation

/// Presentation helpers for inventory rows. Pure (no I/O) so they unit-test
/// cleanly; the SwiftUI view in KitchenOSSiri renders from these.
public extension InventoryItem {

    /// Emoji flag for the row: 🔴 expired, 🟡 soon, nil otherwise.
    var expiryBadge: String? {
        switch expiryStatus {
        case "expired": return "🔴"
        case "soon": return "🟡"
        default: return nil
        }
    }

    /// Sort key so the items worth tossing rise to the top of their group:
    /// 0 = expired, 1 = soon, 2 = everything else.
    var expiryRank: Int {
        switch expiryStatus {
        case "expired": return 0
        case "soon": return 1
        default: return 2
        }
    }

    /// "Added Jun 13 · Exp Jun 23 🔴" — segments omitted when their date is nil.
    var inventorySecondaryLine: String {
        var parts: [String] = []
        if let added = Self.shortDate(purchased) {
            parts.append("Added \(added)")
        }
        if let exp = Self.shortDate(expires) {
            var seg = "Exp \(exp)"
            if let badge = expiryBadge { seg += " \(badge)" }
            parts.append(seg)
        } else {
            parts.append("No expiry")
        }
        return parts.joined(separator: " · ")
    }

    /// ISO date string → "MMM d" (e.g. "Jun 13"), or nil if absent/unparseable.
    static func shortDate(_ iso: String?) -> String? {
        guard let iso, !iso.isEmpty else { return nil }
        let parser = DateFormatter()
        parser.locale = Locale(identifier: "en_US_POSIX")
        parser.dateFormat = "yyyy-MM-dd"
        guard let date = parser.date(from: iso) else { return nil }
        let out = DateFormatter()
        out.locale = Locale(identifier: "en_US_POSIX")
        out.dateFormat = "MMM d"
        return out.string(from: date)
    }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd KitchenOSKit && swift test --filter InventoryDisplayTests`
Expected: PASS (all six assertions).

- [ ] **Step 5: Run the full Kit test suite for no regression**

Run: `cd KitchenOSKit && swift test`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add KitchenOSKit/Sources/KitchenOSKit/InventoryItem+Display.swift KitchenOSKit/Tests/KitchenOSKitTests/InventoryDisplayTests.swift
git commit -m "feat(kit): inventory row display helpers (badge, rank, secondary line)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Wire `InventoryView` — dates, badges, worst-first sort, step-to-0 removes

**Files:**
- Modify: `KitchenOSSiri/Sources/Inventory/InventoryView.swift`

**Interfaces:**
- Consumes: `InventoryItem.inventorySecondaryLine`, `InventoryItem.expiryRank` (Task 3); existing `remove(_:)` and `update(_:quantity:)` methods on the view.
- Produces: no new public API; UI-only changes. Verified manually (the app target has no unit-test bundle).

- [ ] **Step 1: Sort each category group worst-first**

In `InventoryView.swift`, change the `grouped` computed property so items within a category sort by `expiryRank` then name:

```swift
    private var grouped: [(category: String, items: [InventoryItem])] {
        Dictionary(grouping: items, by: \.category)
            .map { (category: $0.key,
                    items: $0.value.sorted {
                        ($0.expiryRank, $0.name) < ($1.expiryRank, $1.name)
                    }) }
            .sorted { $0.category < $1.category }
    }
```

- [ ] **Step 2: Show the secondary line (dates + badge) in each row**

In the `row(_:)` function, replace the location-only caption `VStack` with name + the secondary line:

```swift
            VStack(alignment: .leading, spacing: 2) {
                Text(item.name)
                Text(item.inventorySecondaryLine)
                    .font(.caption).foregroundStyle(.secondary)
                Text(item.location)
                    .font(.caption2).foregroundStyle(.tertiary)
            }
```

- [ ] **Step 3: Make stepping quantity to 0 remove the item**

In the same `row(_:)`, change the `Stepper`'s `set` closure so a non-positive quantity removes the item instead of updating to 0:

```swift
            Stepper(value: Binding(
                get: { item.quantity },
                set: { newQty in
                    Task {
                        if newQty <= 0 {
                            await remove(item)
                        } else {
                            await update(item, quantity: newQty)
                        }
                    }
                }
            ), in: 0...999, step: 1) {
                Text("\(formatQty(item.quantity)) \(item.unit)")
                    .font(.callout).monospacedDigit()
            }
            .labelsHidden()
```

- [ ] **Step 4: Build the app**

Run: `cd KitchenOSKit && swift build` (builds the library the app depends on), then build the app in Xcode (`KitchenOSSiri`) or via `xcodebuild` if the project is configured for it.
Expected: compiles clean.

- [ ] **Step 5: Manual verification on iPad / simulator**

With the API server running (`curl http://localhost:5001/health` returns ok), launch the app and open Inventory. Confirm:
- Each row shows "Added … · Exp … 🔴/🟡" (or "No expiry" for shelf-stable items).
- Within a category, expired items appear above soon, above the rest.
- Badges (🔴/🟡) match what `Inventory.md` flags for the same items.
- Trash button and swipe-to-delete remove an item.
- Stepping an item's quantity down to 0 removes it from the list (not a zero-qty row).

- [ ] **Step 6: Commit**

```bash
git add KitchenOSSiri/Sources/Inventory/InventoryView.swift
git commit -m "feat(app): inventory rows show dates + expiry badges, step-to-0 removes

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Documentation

**Files:**
- Modify: `CLAUDE.md` (the `/api/inventory` description and/or Endpoints notes)

**Interfaces:** none (docs only).

- [ ] **Step 1: Update the `/api/inventory` contract note**

In `CLAUDE.md`, find where `/api/inventory` / inventory endpoints are described (the "Endpoints" table or the Receipt → Inventory section). Add a one-line note that `GET /api/inventory` now returns a computed `expiry_status` (`expired`/`soon`/`ok`/`null`) per item, derived from `lib/expiry.py:expiry_status()` (same logic as `Inventory.md`), and is consumed by the native app's inventory screen for date/badge display.

Example line to add to the Endpoints table:

```markdown
| `/api/inventory` (GET, `?category=&location=`) | Lists inventory items. Each item carries a computed `expiry_status` (`expired`/`soon`/`ok`/`null`) from `lib/expiry.py` — same thresholds as `Inventory.md`. Backs the native app's inventory cleanup screen. |
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: note computed expiry_status on GET /api/inventory

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review Notes

- **Spec coverage:** Backend `expiry_status` → Task 1. Swift `expires`/`expiryStatus` model fields → Task 2. Row UI (Added/Exp secondary line, badges, "No expiry") → Tasks 3+4. Within-category expired→soon→rest sort → Tasks 3 (`expiryRank`) + 4. Step-to-0 removal + existing trash/swipe → Task 4. Single-source-of-truth thresholds → Task 1 reuses `lib/expiry.py`. Docs → Task 5. All spec sections covered.
- **Out-of-scope items** (web UI, editing dates, soft-delete, bulk clear-expired) are intentionally not tasked.
- **Type consistency:** `expiryStatus` (Swift camelCase) ↔ `expiry_status` (JSON snake_case) bridged via `CodingKeys` in Task 2; helpers in Task 3 read those exact members; Task 4 calls `inventorySecondaryLine` / `expiryRank` exactly as named in Task 3.
