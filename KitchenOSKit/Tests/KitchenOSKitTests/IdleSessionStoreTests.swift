import XCTest
@testable import KitchenOSKit

final class Counter { var value = 0 }

@MainActor
final class IdleSessionStoreTests: XCTestCase {
    func testReusesInstanceWithinTimeout() {
        let store = IdleSessionStore<Counter>(idleTimeout: 300)
        let t0 = Date(timeIntervalSince1970: 1_000_000)
        var makes = 0
        let a = store.current(now: t0) { makes += 1; return Counter() }
        let b = store.current(now: t0.addingTimeInterval(299)) { makes += 1; return Counter() }
        XCTAssertTrue(a === b)
        XCTAssertEqual(makes, 1)
    }

    func testMakesFreshInstanceAfterIdleTimeout() {
        let store = IdleSessionStore<Counter>(idleTimeout: 300)
        let t0 = Date(timeIntervalSince1970: 1_000_000)
        let a = store.current(now: t0) { Counter() }
        let b = store.current(now: t0.addingTimeInterval(301)) { Counter() }
        XCTAssertFalse(a === b)
    }

    func testTouchExtendsTheWindow() {
        let store = IdleSessionStore<Counter>(idleTimeout: 300)
        let t0 = Date(timeIntervalSince1970: 1_000_000)
        let a = store.current(now: t0) { Counter() }
        _ = store.current(now: t0.addingTimeInterval(200)) { Counter() }
        let c = store.current(now: t0.addingTimeInterval(450)) { Counter() }
        XCTAssertTrue(a === c)   // 450 is only 250 past the last touch at 200
    }

    func testResetForcesFreshInstance() {
        let store = IdleSessionStore<Counter>(idleTimeout: 300)
        let t0 = Date(timeIntervalSince1970: 1_000_000)
        let a = store.current(now: t0) { Counter() }
        store.reset()
        let b = store.current(now: t0) { Counter() }
        XCTAssertFalse(a === b)
    }
}
