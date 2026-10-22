import Foundation
import Combine

@MainActor public protocol AppleIntegrationControlling: AnyObject {
    func readStatus() async throws -> IntegrationStatus
    func perform(_ command: AppleIntegrationCommand) async throws -> SyncReport
    func requestAccess(for domain: AppleDomain) async throws -> AppleAuthorization
    func destinations(for domain: AppleDomain) async throws -> [AppleDestination]
    func createDestination(name: String, domain: AppleDomain) async throws -> AppleDestination
}

@MainActor public final class AppleIntegrationControls: ObservableObject {
    @Published public private(set) var status: IntegrationStatus?
    @Published public private(set) var message = "Connect Apple integration, then send a selected week."
    @Published public private(set) var busy = false
    @Published public private(set) var permissions: [AppleDomain: AppleAuthorization] = [:]
    @Published public private(set) var destinations: [AppleDomain: [AppleDestination]] = [:]
    private let coordinator: any AppleIntegrationControlling
    public init(coordinator: any AppleIntegrationControlling) { self.coordinator = coordinator }
    public func load() async {
        do {
            applyStatus(try await coordinator.readStatus())
        } catch { message = "Couldn’t read integration status. Check your connection and try again." }
    }
    private func applyStatus(_ value: IntegrationStatus) {
        status = value
        for domain in AppleDomain.allCases {
            permissions[domain] = value.permissions[domain.rawValue] ?? .unknown
            destinations[domain] = value.destinations[domain.rawValue] ?? []
        }
        message = Self.summary(value.report, connected: value.connected, paused: value.paused)
    }
    public func requestPermission(_ domain: AppleDomain) async {
        guard !busy else { return }; busy = true; defer { busy = false }
        do {
            let permission = try await coordinator.requestAccess(for: domain)
            permissions[domain] = permission
            destinations[domain] = permission == .authorized ? try await coordinator.destinations(for: domain) : []
            message = permission == .authorized ? "Access granted. Choose a destination, then send the selected week." : "Access is unavailable. Allow full access in System Settings, then try again."
        } catch { message = "Couldn’t request access. Check System Settings and try again." }
    }
    public func reloadDestinations(_ domain: AppleDomain) async {
        do { destinations[domain] = try await coordinator.destinations(for: domain) }
        catch { destinations[domain] = []; message = "Destinations are unavailable. Check Apple permissions and try again." }
    }
    public func createDestination(_ name: String, domain: AppleDomain) async -> String? {
        guard !busy, !name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return nil }
        busy = true; defer { busy = false }
        do {
            let value = try await coordinator.createDestination(name: name, domain: domain)
            destinations[domain] = try await coordinator.destinations(for: domain)
            message = "Destination created. Send the selected week when you’re ready."
            return value.id
        } catch { message = "Couldn’t create a destination. Check Apple permissions and try again."; return nil }
    }
    public func run(_ command: AppleIntegrationCommand) async {
        guard !busy else { return }; busy = true; defer { busy = false }
        do {
            let report = try await coordinator.perform(command)
            let current = try await coordinator.readStatus()
            applyStatus(current)
            message = Self.commandSummary(report, current: current)
        } catch {
            await load()
            message = "The change wasn’t confirmed. Review the latest status and try again."
        }
    }
    public func resolve(_ conflict: AppleConflictDetail, choice: AppleConflictChoice) async {
        guard conflict.choices.contains(choice) else { return }
        await run(.resolve(conflict.conflictID, choice: choice, revision: conflict.revision))
    }
    public static func summary(_ report: SyncReport, connected: Bool, paused: Bool) -> String {
        let state = !connected ? "Disconnected" : paused ? "Paused" : "Connected"
        return "\(state) · \(report.created) created · \(report.updated) updated · \(report.deleted) removed · \(report.queued) queued · \(report.conflicts) conflicts · \(report.unavailable) unavailable"
    }
    private static func commandSummary(_ action: SyncReport, current: IntegrationStatus) -> String {
        let known = current.report
        let displayed = SyncReport(created: action.created, updated: action.updated, deleted: action.deleted,
                                   queued: known.queued, conflicts: known.conflicts, unavailable: known.unavailable,
                                   lastSuccess: known.lastSuccess)
        let primary = summary(displayed, connected: current.connected, paused: current.paused)
        var transient: [String] = []
        if action.queued > known.queued { transient.append("\(action.queued) queued") }
        if action.conflicts > known.conflicts { transient.append("\(action.conflicts) conflicts") }
        if action.unavailable > known.unavailable { transient.append("\(action.unavailable) unavailable") }
        return transient.isEmpty ? primary : primary + " · This attempt: " + transient.joined(separator: ", ")
    }
}
