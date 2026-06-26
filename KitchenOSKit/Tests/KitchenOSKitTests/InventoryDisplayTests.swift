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
