import Foundation
@testable import KitchenOSKit

/// Deterministic service test double; never imports EventKit or opens a store.
@MainActor final class FakeAppleItemStore: AppleItemStore {
    var permission: AppleAuthorization = .authorized
    var permissionRequests: [AppleDomain] = []
    var writeCalls: [AppleOperation] = []
    var observations: [UUID: Observation] = [:]
    var applied: OperationAck?
    var availableDestinations: [AppleDestination] = []
    func authorization(for domain: AppleDomain) -> AppleAuthorization { permission }
    func requestAccess(for domain: AppleDomain) async throws -> AppleAuthorization { permissionRequests.append(domain); return permission }
    func destinations(for domain: AppleDomain) async throws -> [AppleDestination] { availableDestinations }
    func createDestination(name: String, domain: AppleDomain) async throws -> AppleDestination { AppleDestination(id: "fake", title: name) }
    func observe(_ items: [SyncItem]) async throws -> [Observation] {
        try items.map { item in
            guard let observation = observations[item.token] else { throw AppleIntegrationError.unavailable }
            return observation
        }
    }
    func apply(_ operation: AppleOperation) async throws -> OperationAck {
        writeCalls.append(operation)
        guard let applied else { throw AppleIntegrationError.unavailable }
        return applied
    }
    func availabilitySnapshot(firmID: String, flexibleID: String, excludingOwnedTokens: Set<UUID>) async throws -> PlanningCalendarSnapshot { throw AppleIntegrationError.unavailable }
}
