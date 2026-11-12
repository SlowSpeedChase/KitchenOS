import XCTest
@testable import KitchenOSKit

final class AppleConflictDetailTests: XCTestCase {
    private func detail(_ field: String, source: [String: Any], apple: [String: Any]?) throws -> AppleConflictDetail {
        let value: [String: Any] = ["conflict_id": UUID().uuidString, "token": UUID().uuidString, "revision": 3,
            "field": field, "source": ["title": "Same title", "fields": source],
            "apple": apple.map { ["title": "Same title", "fields": $0] as [String: Any] } as Any? ?? NSNull(),
            "choices": ["keep_manual"]]
        return try JSONDecoder().decode(AppleConflictDetail.self, from: JSONSerialization.data(withJSONObject: value))
    }
    func testReminderRecoveryShowsCompletionAndDueWithIdenticalTitles() throws {
        let conflict = try detail("recovery", source: ["completed": false, "due": NSNull()],
            apple: ["completed": true, "due": ["date": "2026-10-10", "time": "18:30", "timezone": "America/Chicago"]])
        XCTAssertEqual(conflict.label, "Previous sync values are unavailable")
        let source = conflict.value(apple: false), apple = conflict.value(apple: true)
        XCTAssertTrue(source.contains("Completion: Incomplete"))
        XCTAssertTrue(source.contains("Due date: None"))
        XCTAssertTrue(apple.contains("Completion: Completed"))
        XCTAssertTrue(apple.contains("Due date:"))
        XCTAssertTrue(apple.contains("2026-10-10")); XCTAssertTrue(apple.contains("18:30")); XCTAssertTrue(apple.contains("America/Chicago"))
        XCTAssertNotEqual(source, apple)
    }
    func testCookingRecoveryShowsEveryImportableField() throws {
        let conflict = try detail("recovery", source: ["start": "2026-10-10T18:00:00-05:00", "duration_minutes": 60, "timezone": "America/Chicago"],
            apple: ["start": "2026-10-10T19:30:00-04:00", "duration_minutes": 90, "timezone": "America/New_York"])
        let source = conflict.value(apple: false), apple = conflict.value(apple: true)
        XCTAssertTrue(source.contains("Start time: 2026-10-10T18:00:00-05:00"))
        XCTAssertTrue(source.contains("Duration (minutes): 60"))
        XCTAssertTrue(source.contains("Timezone: America/Chicago"))
        XCTAssertTrue(apple.contains("Start time: 2026-10-10T19:30:00-04:00"))
        XCTAssertTrue(apple.contains("Duration (minutes): 90"))
        XCTAssertTrue(apple.contains("Timezone: America/New_York"))
    }
    func testSourceRecoveryExplainsReasonAndRetainsAvailableEvidence() throws {
        let conflict = try detail("source_recovery", source: ["completed": false, "due": NSNull()], apple: ["completed": true])
        XCTAssertEqual(conflict.label, "A KitchenOS source change could not be recovered safely")
        XCTAssertTrue(conflict.value(apple: false).contains("Completion: Incomplete"))
        XCTAssertTrue(conflict.value(apple: true).contains("Completion: Completed"))
        XCTAssertTrue(conflict.value(apple: true).contains("Due date: Unavailable"))
        let unavailable = try detail("source_recovery", source: [:], apple: nil)
        XCTAssertEqual(unavailable.value(apple: true), "Unavailable")
        XCTAssertEqual(unavailable.value(apple: false), "No recorded field values")
    }
    func testOrdinaryFieldConflictStillShowsOnlyItsSelectedField() throws {
        let conflict = try detail("completed", source: ["completed": false, "due": NSNull()], apple: ["completed": true, "due": NSNull()])
        XCTAssertEqual(conflict.value(apple: false), "Incomplete")
        XCTAssertEqual(conflict.value(apple: true), "Completed")
    }
    func testRetiredUnavailableExplainsDetachmentWithoutClaimingAppleDeletion() throws {
        let conflict = try detail("retired_unavailable", source: ["start": "2026-10-10T18:00:00-05:00"], apple: nil)
        XCTAssertEqual(conflict.label, "Retired Apple item could not be verified")
        XCTAssertEqual(conflict.choices, [.keepManual])
        XCTAssertEqual(conflict.choiceLabel(.keepManual), "Keep Apple item separate")
        XCTAssertEqual(conflict.value(apple: true), "Identity unavailable")
        let explanation = try XCTUnwrap(conflict.retiredUnavailableExplanation)
        XCTAssertTrue(explanation.contains("may still exist"))
        XCTAssertTrue(explanation.contains("without changing or deleting"))
    }

    private func shoppingDetail(removed: Bool) throws -> AppleConflictDetail {
        let payload: [String: Any] = [
            "conflict_id": UUID().uuidString, "token": UUID().uuidString, "revision": 4,
            "field": "shopping_amount_changed",
            "source": ["title": "9 lime", "fields": ["completed": false]],
            "apple": NSNull(), "choices": ["keep_kitchenos", "keep_manual"],
            "shopping_demand": ["state": removed ? "removed" : "active", "text": removed ? NSNull() : "3 lime" as Any]
        ]
        return try JSONDecoder().decode(AppleConflictDetail.self, from: JSONSerialization.data(withJSONObject: payload))
    }

    func testRemovedShoppingDemandExplainsRemovalAndMapsTheActualChoice() throws {
        let conflict = try shoppingDetail(removed: true)
        XCTAssertEqual(conflict.shoppingDemand?.state, .removed)
        XCTAssertEqual(conflict.choiceLabel(.keepKitchenOS), "Remove item from shopping list")
        XCTAssertTrue(conflict.value(apple: false).contains("9 lime"))
        XCTAssertTrue(conflict.value(apple: false).contains("No longer needed"))
        XCTAssertTrue(try XCTUnwrap(conflict.shoppingExplanation).contains("completed reminders stay as history"))
        XCTAssertFalse(conflict.choiceLabel(.keepKitchenOS).contains("reopen"))
    }

    func testActiveShoppingDemandShowsEditedAndGeneratedAmountsBeforeReopening() throws {
        let conflict = try shoppingDetail(removed: false)
        XCTAssertEqual(conflict.shoppingDemand?.state, .active)
        XCTAssertEqual(conflict.choiceLabel(.keepKitchenOS), "Accept quantity and reopen")
        XCTAssertTrue(conflict.value(apple: false).contains("Edited list item: 9 lime"))
        XCTAssertTrue(conflict.value(apple: false).contains("Generated demand: 3 lime"))
        XCTAssertTrue(try XCTUnwrap(conflict.shoppingExplanation).contains("replaces the edited text"))
        XCTAssertEqual(conflict.choiceLabel(.keepManual), "Keep as a separate manual shopping item")
    }
}
