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
    func testOnlyOwnershipMarkerNotesAreSafeForAutomaticRetirement() throws {
        let marker = AppleOwnership.url(for: wireToken).absoluteString
        XCTAssertFalse(AppleOwnership.hasUserNotes(nil))
        XCTAssertFalse(AppleOwnership.hasUserNotes(marker + "\n \n"))
        XCTAssertTrue(AppleOwnership.hasUserNotes(marker + "\nRemember to ask Mom"))
        XCTAssertTrue(AppleOwnership.hasUserNotes("A note without a marker"))

        let observed = Observation(token: wireToken, generation: 1, revision: 1, availability: .present,
            locator: Locator(calendarID: "destination", itemID: "item", externalID: nil),
            title: "Buy", fields: AppleFields(completed: false, due: nil),
            absenceConfirmed: false, issue: nil, hasUserNotes: true)
        let encoded = try JSONSerialization.jsonObject(with: JSONEncoder().encode(observed)) as! [String: Any]
        XCTAssertEqual(encoded["has_user_notes"] as? Bool, true)
        XCTAssertEqual(try JSONDecoder().decode(Observation.self, from: JSONEncoder().encode(observed)).hasUserNotes, true)
        let legacy = Observation(token: wireToken, generation: 1, revision: 1, availability: .present,
            locator: Locator(calendarID: "destination", itemID: "item", externalID: nil),
            title: "Buy", fields: AppleFields(completed: false, due: nil),
            absenceConfirmed: false, issue: nil)
        let legacyWire = try JSONSerialization.jsonObject(with: JSONEncoder().encode(legacy)) as! [String: Any]
        XCTAssertNil(legacyWire["has_user_notes"])
        XCTAssertNil(try JSONDecoder().decode(Observation.self, from: JSONEncoder().encode(legacy)).hasUserNotes)
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

    private var wireToken: UUID { UUID(uuidString: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")! }
    private func sourceOperation(fields: AppleFields, title: String) -> AppleOperation {
        AppleOperation(operationID: wireToken, token: wireToken, generation: 1, revision: 1, action: .upsert,
                       destinationID: "destination", locator: nil, title: title, fields: fields, expectedAppleHash: nil)
    }
    private func londonSource() throws -> AppleFields {
        try AppleFields(start: "2026-12-10T18:00:00+00:00", timezone: "Europe/London", durationMinutes: 30)
    }
    private func utcReminderSource() throws -> AppleFields {
        AppleFields(completed: false, due: try DueValue(date: "2026-12-10", time: "18:00", timezone: "UTC"))
    }
    private func londonSnapshot(reference: AppleFields) throws -> AppleFields {
        let start = try AppleFields.instant("2026-12-10T18:00:00+00:00")
        return try AppleFieldMapping.cooking(start: start, end: start.addingTimeInterval(1800), timezone: TimeZone(identifier: "Europe/London")!, reference: reference)
    }
    private func utcReminderSnapshot(reference: AppleFields) throws -> AppleFields {
        try AppleFieldMapping.reminder(completed: false, dueComponents: reference.due!.dateComponents(), reference: reference)
    }
    func testWinterLondonCookingSavedAckMatchesPythonWire() throws {
        let source = try londonSource()
        let observed = try londonSnapshot(reference: source)
        let ack = OperationAck(operationID: wireToken, outcome: .saved,
            locator: Locator(calendarID: "destination", itemID: "item", externalID: nil),
            observedFields: observed, observedHash: try observed.canonicalHash(title: "Cook"))
        XCTAssertEqual(ack.observedFields.start, "2026-12-10T18:00:00+00:00")
        XCTAssertEqual(ack.observedFields, source)
        XCTAssertEqual(ack.observedHash, "28547ca9f70a6bd8b1e2c1cea812f27093f1a790f4dd109271d953ef21e4c997")
    }
    func testWinterLondonInterruptedFirstSaveObservationMatchesPendingOperation() throws {
        let operation = try sourceOperation(fields: londonSource(), title: "Cook")
        let observation = Observation(token: wireToken, generation: 1, revision: 1, availability: .present,
            locator: Locator(calendarID: "destination", itemID: "recovered", externalID: nil), title: "Cook",
            fields: try londonSnapshot(reference: operation.fields), absenceConfirmed: false, issue: nil)
        // Task 5's recovery boundary compares the full title/fields literally.
        XCTAssertEqual(observation.fields, operation.fields)
        XCTAssertEqual(observation.title, operation.title)
        XCTAssertEqual(try observation.fields.canonicalHash(title: observation.title!), "28547ca9f70a6bd8b1e2c1cea812f27093f1a790f4dd109271d953ef21e4c997")
    }
    func testUTCTimedReminderSavedAckPreservesWireAlias() throws {
        let source = try utcReminderSource()
        let observed = try utcReminderSnapshot(reference: source)
        let ack = OperationAck(operationID: wireToken, outcome: .saved,
            locator: Locator(calendarID: "destination", itemID: "item", externalID: nil),
            observedFields: observed, observedHash: try observed.canonicalHash(title: "Prep"))
        XCTAssertEqual(ack.observedFields.due?.timezone, "UTC")
        XCTAssertEqual(ack.observedFields, source)
        XCTAssertEqual(ack.observedHash, "61001196ed770346b30e3bcf71bb34020ac9312a37dfd94511423280874d1cd9")
    }
    func testUTCTimedReminderInterruptedFirstSaveObservationMatchesPendingOperation() throws {
        let operation = try sourceOperation(fields: utcReminderSource(), title: "Prep")
        let observation = Observation(token: wireToken, generation: 1, revision: 1, availability: .present,
            locator: Locator(calendarID: "destination", itemID: "recovered", externalID: nil), title: "Prep",
            fields: try utcReminderSnapshot(reference: operation.fields), absenceConfirmed: false, issue: nil)
        XCTAssertEqual(observation.fields, operation.fields)
        XCTAssertEqual(observation.title, operation.title)
        XCTAssertEqual(try observation.fields.canonicalHash(title: observation.title!), "61001196ed770346b30e3bcf71bb34020ac9312a37dfd94511423280874d1cd9")
    }
    func testEqualWinterOffsetDoesNotConcealRealTimezoneChange() throws {
        let source = try londonSource()
        let start = try AppleFields.instant("2026-12-10T18:00:00+00:00")
        let actual = try AppleFieldMapping.cooking(start: start, end: start.addingTimeInterval(1800), timezone: TimeZone(identifier: "GMT")!, reference: source)
        XCTAssertEqual(actual.timezone, "GMT")
        XCTAssertNotEqual(try actual.canonicalHash(title: "Cook"), "28547ca9f70a6bd8b1e2c1cea812f27093f1a790f4dd109271d953ef21e4c997")
    }
    func testPreservingTimezoneAliasDoesNotHideChangedReminderValues() throws {
        let source = try utcReminderSource()
        var components = try source.due!.dateComponents(); components.hour = 19
        let actual = try AppleFieldMapping.reminder(completed: true, dueComponents: components, reference: source)
        XCTAssertEqual(actual.completed, true)
        XCTAssertEqual(actual.due?.time, "19:00")
        XCTAssertNotEqual(try actual.canonicalHash(title: "Prep"), "61001196ed770346b30e3bcf71bb34020ac9312a37dfd94511423280874d1cd9")
    }

    func testUTCCookingAliasSurvivesSavedAndRecoveredFieldHash() throws {
        let source = try AppleFields(start: "2026-12-10T18:00:00+00:00", timezone: "UTC", durationMinutes: 30)
        let start = try AppleFields.instant(source.start!)
        let observed = try AppleFieldMapping.cooking(start: start, end: start.addingTimeInterval(1800), timezone: TimeZone(identifier: "UTC")!, reference: source)
        XCTAssertEqual(observed, source)
        XCTAssertEqual(try observed.canonicalHash(title: "Cook"), "08fe535cecb1b22f6809d6302f48584cef47c21221de3dde7e82386a82e5bbf6")
    }
    func testExpectedHashUsesPreviousAliasWhenProposedTimezoneChanges() throws {
        let previous = try utcReminderSource()
        let proposed = AppleFields(completed: false, due: try DueValue(date: "2026-12-10", time: "12:00", timezone: "America/Chicago"))
        let freshComponents = try previous.due!.dateComponents()
        let fresh = try AppleFieldMapping.reminder(completed: false, dueComponents: freshComponents, reference: previous)
        XCTAssertEqual(try fresh.canonicalHash(title: "Prep"), "61001196ed770346b30e3bcf71bb34020ac9312a37dfd94511423280874d1cd9")
        // Using a proposed new zone to spell the old object cannot authorize its write.
        let wrongReference = try AppleFieldMapping.reminder(completed: false, dueComponents: freshComponents, reference: proposed)
        XCTAssertNotEqual(try wrongReference.canonicalHash(title: "Prep"), "61001196ed770346b30e3bcf71bb34020ac9312a37dfd94511423280874d1cd9")
    }

}
