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
        try await client.addInventory([InventoryItem(name: "Eggs", quantity: 12, unit: "ct")])
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
