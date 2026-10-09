import XCTest
@testable import KitchenOSKit

@MainActor private final class FakeControlsCoordinator: AppleIntegrationControlling {
    var commands: [AppleIntegrationCommand] = []
    var permissionRequests = 0
    var destinationReads = 0
    var permission: AppleAuthorization = .denied
    let report = SyncReport(created: 0, updated: 0, deleted: 0, queued: 3, conflicts: 1, unavailable: 2, lastSuccess: nil)
    func readStatus() async throws -> IntegrationStatus {
        IntegrationStatus(modelVersion: 1, configured: false, connected: false, paused: false, settingsRevision: 9,
            report: report, permissions: [:], destinations: [:], scopes: [], conflicts: [])
    }
    func perform(_ command: AppleIntegrationCommand) async throws -> SyncReport { commands.append(command); return report }
    func requestAccess(for domain: AppleDomain) async throws -> AppleAuthorization { permissionRequests += 1; return permission }
    func destinations(for domain: AppleDomain) async throws -> [AppleDestination] { destinationReads += 1; return [] }
    func createDestination(name: String, domain: AppleDomain) async throws -> AppleDestination { .init(id:"id",title:name) }
}
@MainActor final class AppleIntegrationControlsTests: XCTestCase {
    func testLoadingSettingsCannotConnectPublishOrPrompt() async {
        let coordinator = FakeControlsCoordinator(); let controls = AppleIntegrationControls(coordinator: coordinator)
        await controls.load()
        XCTAssertTrue(coordinator.commands.isEmpty)
        XCTAssertEqual(coordinator.permissionRequests, 0)
        XCTAssertEqual(coordinator.destinationReads, 0)
        XCTAssertTrue(controls.message.contains("3 queued"))
        XCTAssertTrue(controls.message.contains("1 conflicts"))
        XCTAssertTrue(controls.message.contains("2 unavailable"))
    }
    func testDeniedPermissionDoesNotListDestinationsOrPublish() async {
        let coordinator = FakeControlsCoordinator(); let controls = AppleIntegrationControls(coordinator: coordinator)
        await controls.requestPermission(.shopping)
        XCTAssertEqual(controls.permissions[.shopping], .denied)
        XCTAssertEqual(controls.destinations[.shopping], [])
        XCTAssertEqual(coordinator.destinationReads, 0)
        XCTAssertTrue(coordinator.commands.isEmpty)
        XCTAssertTrue(controls.message.contains("System Settings"))
    }
    func testConflictActionUsesPresentedConflictRevisionAndAllowedChoice() async throws {
        let id = UUID(); let token = UUID()
        let data = Data("{\"conflict_id\":\"\(id)\",\"token\":\"\(token)\",\"field\":\"completed\",\"revision\":17,\"source\":{\"title\":\"Limes\",\"fields\":{\"completed\":true}},\"apple\":{\"title\":\"Limes\",\"fields\":{\"completed\":false}},\"choices\":[\"keep_kitchenos\",\"keep_apple\"]}".utf8)
        let conflict = try JSONDecoder().decode(AppleConflictDetail.self, from: data)
        let coordinator = FakeControlsCoordinator(); let controls = AppleIntegrationControls(coordinator: coordinator)
        XCTAssertEqual(conflict.value(apple:false), "Completed")
        XCTAssertEqual(conflict.value(apple:true), "Incomplete")
        await controls.resolve(conflict, choice:.restore)
        XCTAssertTrue(coordinator.commands.isEmpty)
        await controls.resolve(conflict, choice:.keepApple)
        XCTAssertEqual(coordinator.commands.count, 1)
        guard case let .resolve(actual, choice, revision) = coordinator.commands[0] else { return XCTFail("Wrong command") }
        XCTAssertEqual(actual,id); XCTAssertEqual(choice,.keepApple); XCTAssertEqual(revision,17)
    }
    func testUnsupportedAppleEvidenceCanStillBeReviewed() throws {
        let data = Data("{\"conflict_id\":\"\(UUID())\",\"token\":\"\(UUID())\",\"field\":\"duration_minutes\",\"revision\":1,\"source\":{\"title\":\"Dinner\",\"fields\":{\"duration_minutes\":60}},\"apple\":{\"fields\":{\"duration_minutes\":1440}},\"choices\":[\"keep_manual\"]}".utf8)
        let conflict = try JSONDecoder().decode(AppleConflictDetail.self, from: data)
        XCTAssertFalse(conflict.value(apple:true).isEmpty)
    }
}
