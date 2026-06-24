import XCTest
@testable import KitchenOSKit

final class ReceiptsClientTests: XCTestCase {
    override func tearDown() { MockURLProtocol.handler = nil }

    func testTripsDecode() async throws {
        MockURLProtocol.handler = { req in
            XCTAssertEqual(req.url?.path, "/api/receipts/trips")
            let body = """
            [{"id":7,"date":"2026-06-20","store":"HEB","source":"email",
              "total_cents":4231,"needs_review":0}]
            """.data(using: .utf8)!
            return (HTTPURLResponse(url: req.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!, body)
        }
        let client = KitchenOSClient.mock()
        let trips = try await client.trips()
        XCTAssertEqual(trips.first?.id, 7)
        XCTAssertEqual(trips.first?.totalCents, 4231)
        XCTAssertFalse(trips.first?.needsReview ?? true)
    }

    func testTripDetailDecodesPurchases() async throws {
        MockURLProtocol.handler = { req in
            XCTAssertEqual(req.url?.path, "/api/receipts/trips/7")
            let body = """
            {"trip":{"id":7,"date":"2026-06-20","store":"HEB","total_cents":4231,"needs_review":0},
             "purchases":[{"raw_name":"GV WHL MLK 1G","canonical_name":"whole milk",
               "quantity":1,"unit":"gal","unit_price_cents":399,"total_cents":399,"category":"dairy"}]}
            """.data(using: .utf8)!
            return (HTTPURLResponse(url: req.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!, body)
        }
        let client = KitchenOSClient.mock()
        let d = try await client.trip(id: 7)
        XCTAssertEqual(d.trip.id, 7)
        XCTAssertEqual(d.purchases.first?.canonicalName, "whole milk")
        XCTAssertEqual(d.purchases.first?.unitPriceCents, 399)
    }

    func testPriceTrendsDecode() async throws {
        MockURLProtocol.handler = { req in
            XCTAssertEqual(req.url?.path, "/api/price/trends")
            let body = """
            {"weeks":[{"week":"2026-W25","spend_cents":4231}],
             "by_category":[{"category":"dairy","spend_cents":1200}],
             "average_trip_cents":4231,"trip_count":1,
             "trends":[{"item":"whole milk","current_cents":399,"avg90_cents":380,
                        "unit":"gal","direction":"up"}]}
            """.data(using: .utf8)!
            return (HTTPURLResponse(url: req.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!, body)
        }
        let client = KitchenOSClient.mock()
        let p = try await client.priceTrends()
        XCTAssertEqual(p.weeks?.first?.spendCents, 4231)
        XCTAssertEqual(p.trends?.first?.direction, "up")
        XCTAssertEqual(p.byCategory?.first?.category, "dairy")
    }
}
