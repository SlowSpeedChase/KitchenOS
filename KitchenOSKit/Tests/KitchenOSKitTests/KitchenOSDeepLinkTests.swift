import XCTest
@testable import KitchenOSKit

@MainActor final class KitchenOSDeepLinkTests: XCTestCase {
    let token = UUID(uuidString: "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA")!
    func testStrictRoundTripAndRejectsLegacyAndArbitraryRoutes() {
        let link = KitchenOSDeepLink.item(token: token)
        XCTAssertEqual(link.url.absoluteString, "kitchenos-native://item/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
        XCTAssertEqual(KitchenOSDeepLink(url: link.url), link)
        for text in ["kitchenos://item/\(token)", "https://item/\(token)", "kitchenos-native://item/../\(token)", "kitchenos-native://item/\(token)/", "kitchenos-native://user@item/\(token)", "kitchenos-native://item:123/\(token)", "kitchenos-native://item/\(token)?delete=true", "kitchenos-native://item/\(token)#x", "kitchenos-native://item/%61aaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "kitchenos-native://else/\(token)"] {
            XCTAssertNil(KitchenOSDeepLink(url: URL(string: text)! ), text)
        }
    }
    func testISOWeeksRoundTripAtYearBoundary() {
        for week in ["2020-W53", "2021-W01", "2026-W53", "2027-W01"] {
            XCTAssertEqual(WeekDate.date(forWeekID: week).map { WeekDate.weekID(for: $0) }, week)
        }
        for week in ["2021-W53", "2026-W00", "2026-W54", "2026-W1", "0000-W01", "../2026-W41"] {
            XCTAssertNil(WeekDate.date(forWeekID: week))
        }
    }
    func testCookFocusIsTypedAndEscaped() {
        let base = URL(string:"http://localhost:5001")!
        let url = PlanningWebPolicy.plannerURL(base: base, week: "2026-W41", focusCookID: 42)!
        XCTAssertTrue(url.query!.contains("focusCookID=42"))
        XCTAssertNil(PlanningWebPolicy.plannerURL(base: base, week: "2021-W53", focusCookID: 42))
        XCTAssertNil(PlanningWebPolicy.plannerURL(base: base, week: "2026-W41", focusCookID: -1))
    }
    func testLinkReadsOnlyAndRepeatedOpenReplacesDestination() async throws {
        var readCount = 0
        MockURLProtocol.handler = { request in
            XCTAssertEqual(request.httpMethod, "GET")
            XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer test-token")
            XCTAssertEqual(request.url!.path, "/api/apple-integration/links/\(self.token.uuidString.lowercased())")
            readCount += 1
            let data = Data("{\"domain\":\"shopping\",\"week\":\"2026-W41\",\"source_id\":\"manual:row\(readCount)\",\"state\":\"active\"}".utf8)
            return (HTTPURLResponse(url: request.url!, statusCode:200,httpVersion:nil,headerFields:nil)!, data)
        }
        defer { MockURLProtocol.handler = nil }
        let router = KitchenOSItemRouter(client: AppleIntegrationClient(client: .mock(token:"test-token")))
        await router.open(.item(token:token))
        XCTAssertEqual(router.destination, .shopping(week:"2026-W41", rowID:"manual:row1"))
        await router.open(.item(token:token))
        XCTAssertEqual(router.destination, .shopping(week:"2026-W41", rowID:"manual:row2"))
        XCTAssertEqual(readCount, 2)
    }
    func testHistoryAndMalformedSourcesExplainWithoutRoutingOrWriting() async throws {
        for (state, source) in [("history","manual:row"), ("retired","manual:row"), ("active","../else")] {
            MockURLProtocol.handler = { request in
                XCTAssertEqual(request.httpMethod,"GET")
                return (HTTPURLResponse(url:request.url!,statusCode:200,httpVersion:nil,headerFields:nil)!, Data("{\"domain\":\"shopping\",\"week\":\"2026-W41\",\"source_id\":\"\(source)\",\"state\":\"\(state)\"}".utf8))
            }
            let router = KitchenOSItemRouter(client: AppleIntegrationClient(client: .mock()))
            await router.open(.item(token:token))
            XCTAssertNil(router.destination)
            XCTAssertFalse(router.message.isEmpty)
        }
        MockURLProtocol.handler = { request in
            XCTAssertEqual(request.httpMethod,"GET")
            return (HTTPURLResponse(url:request.url!,statusCode:409,httpVersion:nil,headerFields:nil)!,Data("{}".utf8))
        }
        let router = KitchenOSItemRouter(client: AppleIntegrationClient(client:.mock()))
        await router.open(.item(token:token))
        XCTAssertNil(router.destination); XCTAssertFalse(router.message.isEmpty)
        MockURLProtocol.handler = nil
    }
}
