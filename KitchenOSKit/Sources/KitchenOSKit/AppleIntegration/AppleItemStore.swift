import Foundation

@MainActor public protocol AppleItemStore {
    func authorization(for domain: AppleDomain) -> AppleAuthorization
    /// Call only from explicit foreground setup, never from background reconciliation.
    func requestAccess(for domain: AppleDomain) async throws -> AppleAuthorization
    func destinations(for domain: AppleDomain) async throws -> [AppleDestination]
    /// Reader selection includes read-only calendars. Writer destinations stay writable-only.
    func availabilityCalendars() async throws -> [AppleDestination]
    func createDestination(name: String, domain: AppleDomain) async throws -> AppleDestination
    func observe(_ items: [SyncItem]) async throws -> [Observation]
    func apply(_ operation: AppleOperation) async throws -> OperationAck
    func availabilitySnapshot(firmID: String, flexibleID: String, excludingOwnedTokens: Set<UUID>) async throws -> PlanningCalendarSnapshot
}

/// The same conservative decision is used by the EventKit adapter and package tests.
public enum AppleLookupDecision: Equatable, Sendable {
    case present, newItem, missing, unavailable, ambiguous
    public static func resolve(domain: AppleDomain, hadLocator: Bool, matches: Int, readable: Bool, complete: Bool) -> Self {
        guard readable else { return .unavailable }
        if matches > 1 { return .ambiguous }
        if matches == 1 { return .present }
        guard complete else { return .unavailable }
        if !hadLocator { return .newItem }
        // No bounded Calendar query proves global absence after an arbitrary move.
        return domain == .cooking ? .unavailable : .missing
    }
}

public enum AppleOwnership {
    public static func url(for token: UUID) -> URL {
        URL(string: "kitchenos-native://item/" + token.uuidString.lowercased())!
    }
    public static func token(in value: String) -> UUID? {
        let prefix = "kitchenos-native://item/"
        guard value.hasPrefix(prefix), let token = UUID(uuidString: String(value.dropFirst(prefix.count))),
              url(for: token).absoluteString == value else { return nil }
        return token
    }
    /// A standalone exact marker line is accepted; user prose is never rewritten.
    public static func tokens(url: URL?, notes: String?) -> Set<UUID> {
        var values = Set((notes ?? "").components(separatedBy: .newlines).compactMap { token(in: $0) })
        if let url, let token = token(in: url.absoluteString) { values.insert(token) }
        return values
    }
    /// Only exact standalone ownership markers and blank lines are managed.
    /// A user's prose must survive retirement even when title and fields match.
    public static func hasUserNotes(_ notes: String?) -> Bool {
        (notes ?? "").components(separatedBy: .newlines).contains { line in
            !line.trimmingCharacters(in: .whitespaces).isEmpty && token(in: line) == nil
        }
    }
}

public extension AppleItemStore {
    func availabilityCalendars() async throws -> [AppleDestination] { try await destinations(for: .cooking) }
}

public extension AppleOwnership {
    /// An uncertain pass cannot prove that a marked event still mirrors its
    /// ledger cook. Count all marked events as external busy until converged.
    static func availabilityExclusions(_ linked: Set<UUID>, status: IntegrationStatus?, syncReport: SyncReport?) -> Set<UUID> {
        guard let status, let syncReport, status.configured, status.connected, !status.paused,
              status.report.lastSuccess != nil, syncReport.lastSuccess != nil,
              status.report.queued == 0, status.report.conflicts == 0, status.report.unavailable == 0,
              syncReport.queued == 0, syncReport.conflicts == 0, syncReport.unavailable == 0
        else { return [] }
        return linked
    }
    /// Linked active exports already exist in the cooking ledger. Detached manual
    /// and archived Apple events remain external busy time, even with our marker.
    /// Multiple distinct markers on one object never grant an exclusion.
    static func excludesFromAvailability(url: URL?, notes: String?, excludingOwnedTokens: Set<UUID>) -> Bool {
        let markers = tokens(url: url, notes: notes)
        return markers.count == 1 && markers.first.map(excludingOwnedTokens.contains) == true
    }
}
