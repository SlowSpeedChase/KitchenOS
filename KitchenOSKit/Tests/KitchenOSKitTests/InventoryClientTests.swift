import XCTest
@testable import KitchenOSKit

final class InventoryClientTests: XCTestCase {
    override func tearDown() { MockURLProtocol.handler = nil }

    func testInventoryDecodesAndFiltersByCategory() async throws {
        MockURLProtocol.handler = { req in
            XCTAssertEqual(req.url?.path, "/api/inventory")
            XCTAssertEqual(req.url?.query, "category=dairy")
            let body = #"[{"name":"Milk","quantity":1.0,"unit":"gal","category":"dairy","location":"fridge","source":"manual","notes":""}]"#
                .data(using: .utf8)!
            return (HTTPURLResponse(url: req.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!, body)
        }
        let client = KitchenOSClient.mock()
        let items = try await client.inventory(category: "dairy")
        XCTAssertEqual(items.first?.name, "Milk")
        XCTAssertEqual(items.first?.location, "fridge")
        XCTAssertEqual(items.first?.quantity, 1.0)
    }

    func testAddInventoryEncodesItemsWrapper() async throws {
        MockURLProtocol.handler = { req in
            XCTAssertEqual(req.url?.path, "/api/inventory/add")
            XCTAssertEqual(req.httpMethod, "POST")
            let body = req.bodyData()
            let json = try! JSONSerialization.jsonObject(with: body) as! [String: Any]
            let items = json["items"] as! [[String: Any]]
            XCTAssertEqual(items.first?["name"] as? String, "Eggs")
            return (HTTPURLResponse(url: req.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!,
                    #"{"status":"ok"}"#.data(using: .utf8)!)
        }
        let client = KitchenOSClient.mock()
        try await client.addInventory([NewInventoryItem(name: "Eggs", quantity: 12, unit: "ct")])
    }

    // MARK: Placement provenance
    //
    // The server decides location with `if raw.get('location')` and stamps an
    // explicit one `manual` — "a placement you confirmed". So sending a location
    // the user never chose records a confirmed placement that never happened, and
    // the `?` unsure marker can never appear for an app-added row. These two tests
    // pin the only thing that prevents that: the key's presence.

    func testUnspecifiedLocationOmitsTheKeyEntirely() async throws {
        // Not "location": null and not "location": "" — the key must be ABSENT.
        // The server's truthiness check would forgive both today, but the whole
        // point of this feature is not relying on a coincidence for honesty.
        MockURLProtocol.handler = { req in
            let json = try! JSONSerialization.jsonObject(with: req.bodyData()) as! [String: Any]
            let item = (json["items"] as! [[String: Any]]).first!
            XCTAssertFalse(item.keys.contains("location"),
                           "an unspecified location must be omitted, got \(item)")
            XCTAssertEqual(item["name"] as? String, "Psyllium Husk")
            return (HTTPURLResponse(url: req.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!,
                    #"{"status":"ok"}"#.data(using: .utf8)!)
        }
        let client = KitchenOSClient.mock()
        try await client.addInventory([
            NewInventoryItem(name: "Psyllium Husk", quantity: 1, unit: "ct", category: "other")
        ])
    }

    func testExplicitLocationIsStillSent() async throws {
        // The other half: when the user genuinely picks a shelf, that has to reach
        // the server so it records as `manual`. Omitting it always would trade one
        // dishonesty for another.
        MockURLProtocol.handler = { req in
            let json = try! JSONSerialization.jsonObject(with: req.bodyData()) as! [String: Any]
            let item = (json["items"] as! [[String: Any]]).first!
            XCTAssertEqual(item["location"] as? String, "freezer")
            return (HTTPURLResponse(url: req.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!,
                    #"{"status":"ok"}"#.data(using: .utf8)!)
        }
        let client = KitchenOSClient.mock()
        try await client.addInventory([
            NewInventoryItem(name: "Frozen Peas", quantity: 1, unit: "bag",
                             category: "frozen", location: "freezer")
        ])
    }

    func testDefaultDraftLocationIsNil() {
        // Guards the actual regression: a non-nil default here is precisely the
        // `@State private var location = "pantry"` bug, one layer down.
        XCTAssertNil(NewInventoryItem(name: "Anything", quantity: 1).location)
    }

    func testUpdateInventorySendsQuantity() async throws {
        MockURLProtocol.handler = { req in
            XCTAssertEqual(req.url?.path, "/api/inventory/update")
            let json = try! JSONSerialization.jsonObject(with: req.bodyData()) as! [String: Any]
            XCTAssertEqual(json["name"] as? String, "Milk")
            XCTAssertEqual(json["quantity"] as? Double, 0.5)
            return (HTTPURLResponse(url: req.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!,
                    #"{"status":"updated"}"#.data(using: .utf8)!)
        }
        let client = KitchenOSClient.mock()
        try await client.updateInventory(name: "Milk", quantity: 0.5, location: "fridge")
    }

    func testPantryUnwrapsItems() async throws {
        MockURLProtocol.handler = { req in
            XCTAssertEqual(req.url?.path, "/api/pantry")
            let body = #"{"items":[{"item":"Rice","amount":"2","unit":"lb"}]}"#.data(using: .utf8)!
            return (HTTPURLResponse(url: req.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!, body)
        }
        let client = KitchenOSClient.mock()
        let items = try await client.pantry()
        XCTAssertEqual(items.first?.item, "Rice")
        XCTAssertEqual(items.first?.amount, "2")
    }

    func testShoppingPreviewDecodesSplitLines() async throws {
        MockURLProtocol.handler = { req in
            XCTAssertEqual(req.url?.path, "/api/shopping-list/preview")
            let json = try! JSONSerialization.jsonObject(with: req.bodyData()) as! [String: Any]
            XCTAssertEqual(json["week"] as? String, "2026-W26")
            let body = """
            {"success":true,"items":["2 lb rice"],
             "lines":[{"item":"rice","needed":{"amount":"2","unit":"lb"},
                       "from_pantry":null,"to_buy":{"amount":"2","unit":"lb"},
                       "display":"2 lb rice","warning":null}],
             "recipes":["Fried Rice"]}
            """.data(using: .utf8)!
            return (HTTPURLResponse(url: req.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!, body)
        }
        let client = KitchenOSClient.mock()
        let p = try await client.previewShoppingList(week: "2026-W26")
        XCTAssertTrue(p.success)
        XCTAssertEqual(p.lines?.first?.toBuy?.display, "2 lb")
        XCTAssertNil(p.lines?.first?.fromPantry)
    }
}

private extension URLRequest {
    /// Read the body whether it was set directly or via an input stream
    /// (URLProtocol receives streamed bodies).
    func bodyData() -> Data {
        if let httpBody { return httpBody }
        guard let stream = httpBodyStream else { return Data() }
        stream.open()
        defer { stream.close() }
        var data = Data()
        let bufSize = 1024
        let buf = UnsafeMutablePointer<UInt8>.allocate(capacity: bufSize)
        defer { buf.deallocate() }
        while stream.hasBytesAvailable {
            let read = stream.read(buf, maxLength: bufSize)
            if read <= 0 { break }
            data.append(buf, count: read)
        }
        return data
    }
}
