import Foundation

/// A saved identity or civil date, never a model-supplied URL or credential.
public enum WebDestination: Codable, Equatable, Sendable {
    case recipe(name: String)
    case mealPlan(date: String)

    private enum CodingKeys: String, CodingKey {
        case kind, name, date
    }

    private struct JSONKey: CodingKey {
        let stringValue: String
        let intValue: Int? = nil
        init?(stringValue: String) { self.stringValue = stringValue }
        init?(intValue: Int) { return nil }
    }

    public init(from decoder: Decoder) throws {
        let fields = try decoder.container(keyedBy: JSONKey.self)
        let container = try decoder.container(keyedBy: CodingKeys.self)
        let kind = try container.decode(String.self, forKey: .kind)
        let expected: Set<String>
        switch kind {
        case "recipe": expected = ["kind", "name"]
        case "meal_plan": expected = ["kind", "date"]
        default:
            throw DecodingError.dataCorruptedError(forKey: .kind, in: container, debugDescription: "Unknown web destination kind")
        }
        guard Set(fields.allKeys.map(\.stringValue)) == expected else {
            throw DecodingError.dataCorrupted(.init(codingPath: decoder.codingPath, debugDescription: "Unexpected web destination fields"))
        }
        switch kind {
        case "recipe": self = .recipe(name: try container.decode(String.self, forKey: .name))
        default: self = .mealPlan(date: try container.decode(String.self, forKey: .date))
        }
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        switch self {
        case .recipe(let name):
            try container.encode("recipe", forKey: .kind)
            try container.encode(name, forKey: .name)
        case .mealPlan(let date):
            try container.encode("meal_plan", forKey: .kind)
            try container.encode(date, forKey: .date)
        }
    }

    /// Only the server's one-use bootstrap fragment may be joined to the configured origin.
    public static func handoffURL(relativePath: String, baseURL: URL) throws -> URL {
        guard var origin = URLComponents(url: baseURL, resolvingAgainstBaseURL: false),
              let scheme = origin.scheme?.lowercased(), ["http", "https"].contains(scheme),
              let host = origin.host, !host.isEmpty,
              origin.user == nil, origin.password == nil,
              origin.query == nil, origin.fragment == nil,
              origin.percentEncodedPath.isEmpty || origin.percentEncodedPath == "/" else {
            throw WebDestinationError.invalidBaseURL
        }
        let prefix = "/browser/open#code="
        guard relativePath.hasPrefix(prefix) else { throw WebDestinationError.invalidHandoffURL }
        let code = relativePath.dropFirst(prefix.count)
        let validBytes = code.utf8.allSatisfy {
            (65...90).contains($0) || (97...122).contains($0) || (48...57).contains($0) || $0 == 45 || $0 == 95
        }
        guard code.utf8.count == 43, validBytes else { throw WebDestinationError.invalidHandoffURL }
        origin.path = "/browser/open"
        origin.fragment = "code=\(code)"
        guard let url = origin.url else { throw WebDestinationError.invalidHandoffURL }
        return url
    }
}

public enum WebDestinationError: Error, Equatable, Sendable {
    case invalidBaseURL
    case invalidHandoffURL
}
