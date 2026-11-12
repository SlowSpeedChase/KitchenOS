import XCTest
@testable import KitchenOSKit

final class AppleIntegrationClientTests: XCTestCase {
    let id = UUID(uuidString: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")!
    let report = #"{"created":0,"updated":0,"deleted":0,"queued":1,"conflicts":0,"unavailable":0,"last_success":null}"#
    override func tearDown() { MockURLProtocol.handler = nil }
    var statusJSON: String {
        #"{"model_version":1,"configured":true,"connected":true,"paused":false,"settings_revision":1,"report":REPORT,"permissions":{"shopping":"authorized"},"destinations":{"shopping":[{"id":"list","title":"Shopping"}]},"scopes":[],"conflicts":[]}"#.replacingOccurrences(of: "REPORT", with: report)
    }
    func testOwnerUsesLowercaseUUIDAndAuthenticatedEnvelope() async throws {
        let response = #"{"model_version":1,"context":{"owner_id":"aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee","owner_generation":2},"status":STATUS}"#.replacingOccurrences(of: "STATUS", with: statusJSON)
        MockURLProtocol.handler = { req in
            XCTAssertEqual(req.httpMethod, "POST")
            XCTAssertEqual(req.url?.path, "/api/apple-integration/owner")
            XCTAssertEqual(req.value(forHTTPHeaderField: "Authorization"), "Bearer secret")
            let body = try Self.body(req)
            XCTAssertEqual(body["owner_id"] as? String, "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
            XCTAssertEqual(Set(body.keys), ["owner_id"])
            return Self.response(req, response)
        }
        let context = try await AppleIntegrationClient(client: .mock(token: "secret")).registerOwner(id)
        XCTAssertEqual(context.ownerGeneration, 2)
    }
    func testConflictAndOversizedBatchPreserveHTTPStatus() async {
        for code in [409, 413] {
            MockURLProtocol.handler = { req in Self.response(req, "{}", code: code) }
            do { _ = try await AppleIntegrationClient(client: .mock()).status(); XCTFail("expected error") }
            catch { XCTAssertEqual(error as? KitchenOSError, .http(code)) }
        }
    }
    func testWorkDecodesRetryAndRetainedCollectionsWithoutConflatingThem() async throws {
        let response = #"{"model_version":1,"context":{"owner_id":"aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee","owner_generation":2},"items":[],"retained_items":[],"operations":[],"scopes":[],"report":REPORT,"paused":false,"retry_requests":[{"request_id":"aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee","observations":[]}]}"#.replacingOccurrences(of: "REPORT", with: report)
        MockURLProtocol.handler = { req in
            XCTAssertEqual(req.httpMethod, "GET")
            XCTAssertEqual(req.url?.query, "owner_id=aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee&owner_generation=2")
            return Self.response(req, response)
        }
        let work = try await AppleIntegrationClient(client: .mock()).work(context: BridgeContext(ownerID: id, ownerGeneration: 2))
        XCTAssertEqual(work.retryRequests.first?.requestID, id)
        XCTAssertTrue(work.items.isEmpty)
        XCTAssertTrue(work.retainedItems.isEmpty)
    }
    func testObservationAndAckUseFlatRequiredNullKeys() async throws {
        let obs = Observation(token: id, generation: 3, revision: 7, availability: .unavailable, locator: nil, title: nil, fields: AppleFields(), absenceConfirmed: false, issue: nil)
        let context = BridgeContext(ownerID: id, ownerGeneration: 2)
        MockURLProtocol.handler = { req in
            let body = try Self.body(req)
            XCTAssertEqual(body["complete"] as? Bool, true)
            XCTAssertEqual(body["request_id"] as? String, "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
            let observation = (body["observations"] as! [[String: Any]])[0]
            XCTAssertTrue(observation["locator"] is NSNull)
            XCTAssertTrue(observation["title"] is NSNull)
            XCTAssertTrue(observation["issue"] is NSNull)
            return Self.response(req, "{\"operations\":[],\"report\":\(self.report)}")
        }
        _ = try await AppleIntegrationClient(client: .mock()).observe([obs], context: context, requestID: id)
        MockURLProtocol.handler = { req in
            let body = try Self.body(req)
            XCTAssertEqual(req.url?.path, "/api/apple-integration/operations/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee/ack")
            XCTAssertTrue(body["locator"] is NSNull)
            XCTAssertTrue(body["observed_hash"] is NSNull)
            XCTAssertNotNil(body["context"])
            XCTAssertNil(body["ack"])
            return Self.response(req, "{\"report\":\(self.report)}")
        }
        _ = try await AppleIntegrationClient(client: .mock()).acknowledge(OperationAck(operationID: id, outcome: .deleted, locator: nil, observedFields: AppleFields(), observedHash: nil), context: context)
    }
    func testRemoveOwnedUsesFreshPerItemRevisionEnvelope() async throws {
        let obs = Observation(token: id, generation: 3, revision: 7, availability: .present, locator: Locator(calendarID: "list", itemID: "item", externalID: nil), title: "Buy", fields: AppleFields(completed: false, due: nil), absenceConfirmed: false, issue: nil)
        MockURLProtocol.handler = { req in
            let body = try Self.body(req)
            XCTAssertEqual(Set(body.keys), ["context", "request_id", "items"])
            let item = (body["items"] as! [[String: Any]])[0]
            XCTAssertEqual(item["expected_revision"] as? Int, 7)
            XCTAssertNotNil(item["observation"])
            return Self.response(req, #"{"operations":[]}"#)
        }
        _ = try await AppleIntegrationClient(client: .mock()).removeOwned([OwnedRemovalItem(token: id, expectedRevision: 7, observation: obs)], context: BridgeContext(ownerID: id, ownerGeneration: 2), requestID: id)
    }

    func testSettingsScopeConflictRestoreAndDisconnectEnvelopes() async throws {
        let client = AppleIntegrationClient(client: .mock())
        let context = BridgeContext(ownerID: id, ownerGeneration: 2)
        MockURLProtocol.handler = { req in
            let body = try Self.body(req)
            switch req.url!.path {
            case "/api/apple-integration/settings":
                XCTAssertEqual(req.httpMethod, "PUT"); XCTAssertEqual(Set(body.keys), ["paused", "expected_revision"])
                XCTAssertEqual(body["expected_revision"] as? Int, 4)
                return Self.response(req, self.statusJSON)
            case "/api/apple-integration/owner":
                XCTAssertEqual(req.httpMethod, "DELETE"); XCTAssertEqual(Set(body.keys), ["context"])
                return Self.response(req, self.statusJSON)
            case "/api/apple-integration/scopes/prep/2026-W41":
                XCTAssertEqual(req.httpMethod, "PUT"); XCTAssertEqual(body["expected_revision"] as? Int, 0)
                XCTAssertEqual(body["destination_id"] as? String, "list")
            case "/api/apple-integration/conflicts/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee/resolve":
                XCTAssertEqual(Set(body.keys), ["choice", "expected_revision"])
                XCTAssertEqual(body["choice"] as? String, "keep_manual")
            case "/api/apple-integration/items/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee/restore":
                XCTAssertEqual(Set(body.keys), ["expected_revision"])
                XCTAssertEqual(body["expected_revision"] as? Int, 9)
            default: XCTFail("Unexpected route")
            }
            return Self.response(req, "{\"report\":\(self.report)}")
        }
        _ = try await client.setPaused(true, expectedRevision: 4)
        _ = try await client.setScope(ScopeRequest(domain: .prep, week: "2026-W41", destinationID: "list", state: .active, expectedRevision: 0))
        _ = try await client.resolve(ConflictResolution(conflictID: id, choice: .keepManual, expectedRevision: 5))
        _ = try await client.restore(token: id, expectedRevision: 9)
        _ = try await client.disconnect(context: context)
    }
    func testUnknownModelVersionFailsDecoding() async {
        MockURLProtocol.handler = { req in Self.response(req, self.statusJSON.replacingOccurrences(of: "\"model_version\":1", with: "\"model_version\":2")) }
        do { _ = try await AppleIntegrationClient(client: .mock()).status(); XCTFail("expected rejection") }
        catch { XCTAssertEqual(error as? KitchenOSError, .decoding) }
    }
    static func body(_ req: URLRequest) throws -> [String: Any] {
        if let data = req.httpBody { return try JSONSerialization.jsonObject(with: data) as! [String: Any] }
        let stream = req.httpBodyStream!; stream.open(); defer { stream.close() }
        var data = Data(); var buffer = [UInt8](repeating: 0, count: 4096)
        while stream.hasBytesAvailable { let n = stream.read(&buffer, maxLength: buffer.count); if n <= 0 { break }; data.append(buffer, count: n) }
        return try JSONSerialization.jsonObject(with: data) as! [String: Any]
    }
    static func response(_ req: URLRequest, _ body: String, code: Int = 200) -> (HTTPURLResponse, Data) {
        (HTTPURLResponse(url: req.url!, statusCode: code, httpVersion: nil, headerFields: nil)!, Data(body.utf8))
    }
}
