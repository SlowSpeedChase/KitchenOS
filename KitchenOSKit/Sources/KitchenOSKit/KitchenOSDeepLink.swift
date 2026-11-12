import Foundation
import Combine

public enum KitchenOSDeepLink: Equatable, Sendable {
    case item(token: UUID)
    public init?(url: URL) {
        guard let c = URLComponents(url: url, resolvingAgainstBaseURL: false),
              c.scheme == "kitchenos-native", c.host == "item", c.user == nil,
              c.password == nil, c.port == nil, c.query == nil, c.fragment == nil,
              c.percentEncodedPath.range(of: #"^/[A-Fa-f0-9]{8}-[A-Fa-f0-9]{4}-[A-Fa-f0-9]{4}-[A-Fa-f0-9]{4}-[A-Fa-f0-9]{12}$"#, options: .regularExpression) != nil,
              let id = UUID(uuidString: String(c.percentEncodedPath.dropFirst())) else { return nil }
        self = .item(token: id)
    }
    public var url: URL {
        switch self { case let .item(token): return URL(string: "kitchenos-native://item/" + token.uuidString.lowercased())! }
    }
}

public enum KitchenOSItemDestination: Equatable, Sendable {
    case shopping(week: String, rowID: String)
    case prep(week: String, taskID: String)
    case cooking(week: String, cookID: Int)
}

public struct KitchenOSItemLink: Decodable, Sendable {
    public let domain: AppleDomain
    public let week: String
    public let sourceID: String
    public let state: AppleItemState
    enum CodingKeys: String, CodingKey { case domain, week, state; case sourceID = "source_id" }
    public var destination: KitchenOSItemDestination? {
        guard WeekDate.date(forWeekID: week) != nil, state != .history, state != .retired else { return nil }
        switch domain {
        case .shopping:
            guard sourceID.range(of: #"^(gen|manual):[A-Za-z0-9_-]{1,64}$"#, options: .regularExpression) != nil else { return nil }
            return .shopping(week: week, rowID: sourceID)
        case .prep:
            guard sourceID.range(of: #"^[a-f0-9]{12}$"#, options: .regularExpression) != nil else { return nil }
            return .prep(week: week, taskID: sourceID)
        case .cooking:
            guard sourceID.range(of: #"^cook:[1-9][0-9]*$"#, options: .regularExpression) != nil,
                  let id = Int(sourceID.dropFirst(5)), id <= 9_007_199_254_740_991 else { return nil }
            return .cooking(week: week, cookID: id)
        }
    }
}

/// Shared route state also makes repeated opens and stale network results testable.
/// Resolving a link only performs GET; it never activates or recreates a source.
@MainActor public final class KitchenOSItemRouter: ObservableObject {
    @Published public private(set) var destination: KitchenOSItemDestination?
    @Published public private(set) var message = ""
    @Published public private(set) var revision = 0
    private let clientProvider: () -> AppleIntegrationClient
    private var requestSerial = 0
    public init(client: AppleIntegrationClient) { self.clientProvider = { client } }
    public init(clientProvider: @escaping () -> AppleIntegrationClient) { self.clientProvider = clientProvider }
    public func open(_ link: KitchenOSDeepLink) async {
        requestSerial += 1; let serial = requestSerial
        destination = nil; message = "Opening item…"
        do {
            guard case let .item(token) = link else { return }
            let result = try await clientProvider().link(token: token)
            guard serial == requestSerial else { return }
            destination = result.destination
            message = destination == nil ? "This item is archived, missing, or no longer available. Open its week in KitchenOS to review the current plan." : ""
        } catch {
            guard serial == requestSerial else { return }
            message = "This item couldn’t be opened. It may have been removed, or the server may be unavailable. Check your connection and try again."
        }
        revision += 1
    }
}
