import XCTest
@testable import KitchenOSKit

final class AppleIntegrationModelsTests: XCTestCase {
    func testDueDateOnlyDoesNotShiftOnDST() throws {
        let due = try DueValue(date: "2026-11-01")
        let components = try due.dateComponents()
        XCTAssertEqual(components.year, 2026)
        XCTAssertEqual(components.month, 11)
        XCTAssertEqual(components.day, 1)
        XCTAssertNil(components.hour)
        XCTAssertNil(components.timeZone)
        XCTAssertEqual(try DueValue(components: components), due)
        let json = try JSONSerialization.jsonObject(with: JSONEncoder().encode(due)) as! [String: Any]
        XCTAssertTrue(json["time"] is NSNull)
        XCTAssertTrue(json["timezone"] is NSNull)
    }
    func testMalformedDatesAndNonexistentWallTimesAreRejected() throws {
        for value in ["2026-02-29", "2026-11-31", "2026-1-01"] { XCTAssertThrowsError(try DueValue(date: value)) }
        XCTAssertThrowsError(try DueValue(date: "2026-03-08", time: "02:30", timezone: "America/Chicago"))
        XCTAssertThrowsError(try DueValue(date: "2026-11-01", time: "01:30"))
        XCTAssertThrowsError(try DueValue(date: "2026-11-01", timezone: "America/Chicago"))
        XCTAssertThrowsError(try JSONDecoder().decode(DueValue.self, from: Data(#"{"date":"2026-02-30","time":null,"timezone":null}"#.utf8)))
    }
    func testNullDueClearsAndAbsentDueDoesNotClear() throws {
        let data = try JSONEncoder().encode(AppleFields(completed: false, due: nil))
        let json = try JSONSerialization.jsonObject(with: data) as! [String: Any]
        XCTAssertTrue(json["due"] is NSNull)
        XCTAssertTrue(try JSONDecoder().decode(AppleFields.self, from: data).hasDue)
        XCTAssertFalse(try JSONDecoder().decode(AppleFields.self, from: Data("{}".utf8)).hasDue)
    }
    func testCanonicalHashCoversTitleAndUnicode() throws {
        XCTAssertEqual(try AppleFields(completed: false, due: nil).canonicalHash(title: "Café / soup"), "99cabfcb54fd309118f2e556f857a46c4b0a081ca76f41788a7678db1e8f9cfb")
    }
    func testLocatorRecoveryOutsideWeekDoesNotDelete() {
        XCTAssertEqual(AppleLookupDecision.resolve(domain: .cooking, hadLocator: true, matches: 0, readable: true, complete: true), .unavailable)
        XCTAssertEqual(AppleLookupDecision.resolve(domain: .cooking, hadLocator: true, matches: 1, readable: true, complete: false), .present)
        XCTAssertEqual(AppleLookupDecision.resolve(domain: .shopping, hadLocator: true, matches: 2, readable: true, complete: true), .ambiguous)
        XCTAssertEqual(AppleLookupDecision.resolve(domain: .shopping, hadLocator: true, matches: 0, readable: false, complete: true), .unavailable)
    }
    func testExactOwnershipMarkerDoesNotAcceptLookalikes() {
        let token = UUID(uuidString: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")!
        XCTAssertEqual(AppleOwnership.token(in: "kitchenos-native://item/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"), token)
        for value in ["kitchenos://item/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", "kitchenos-native://item/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee?delete=1", "kitchenos-native://item/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee/extra"] { XCTAssertNil(AppleOwnership.token(in: value)) }
    }
    func testFirstSaveFoundByMarkerRequiresRecoveryInsteadOfCreation() {
        XCTAssertEqual(AppleLookupDecision.resolve(domain: .cooking, hadLocator: false, matches: 1, readable: true, complete: true), .present)
        XCTAssertEqual(AppleLookupDecision.resolve(domain: .cooking, hadLocator: false, matches: 0, readable: true, complete: true), .newItem)
        XCTAssertEqual(AppleLookupDecision.resolve(domain: .shopping, hadLocator: true, matches: 0, readable: true, complete: false), .unavailable)
        XCTAssertEqual(AppleLookupDecision.resolve(domain: .shopping, hadLocator: true, matches: 0, readable: true, complete: true), .missing)
    }
    func testCookingInstantRejectsMalformedDateAndMissingOffset() throws {
        XCTAssertThrowsError(try AppleFields(start: "2026-02-30T10:00:00Z", timezone: "UTC", durationMinutes: 30))
        XCTAssertThrowsError(try AppleFields(start: "2026-10-09T10:00:00", timezone: "UTC", durationMinutes: 30))
        XCTAssertThrowsError(try AppleFields(start: "2026-10-09T10:00:00Z", timezone: "UTC", durationMinutes: 17))
    }

    func testMissingNullableWireKeysAreNotInterpretedAsNull() throws {
        XCTAssertThrowsError(try JSONDecoder().decode(Locator.self, from: Data(#"{"calendar_id":"list","item_id":"item"}"#.utf8)))
        XCTAssertThrowsError(try JSONDecoder().decode(DueValue.self, from: Data(#"{"date":"2026-11-01"}"#.utf8)))
        XCTAssertNoThrow(try JSONDecoder().decode(Locator.self, from: Data(#"{"calendar_id":"list","item_id":"item","external_id":null}"#.utf8)))
    }

}
