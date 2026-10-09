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
}

public extension AppleItemStore {
    func availabilityCalendars() async throws -> [AppleDestination] { try await destinations(for: .cooking) }
}

public extension AppleOwnership {
    /// Archived exports retain their strict marker but are omitted from active work.
    /// A copied marker can hide availability; this read-only policy grants no write authority.
    static func excludesFromAvailability(url: URL?, notes: String?) -> Bool { !tokens(url: url, notes: notes).isEmpty }
}
