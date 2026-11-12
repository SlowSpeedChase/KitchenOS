import Foundation

public struct SavedShoppingRow: Decodable, Sendable, Identifiable {
    public let id: String
    public let text: String
    public let completed: Bool
    public let issue: String?
}
public struct SavedShoppingList: Decodable, Sendable {
    public let rows: [SavedShoppingRow]
    public let contentHash: String
    enum CodingKeys: String, CodingKey { case rows; case contentHash = "content_hash" }
}
public extension KitchenOSClient {
    func savedShoppingList(week: String) async throws -> SavedShoppingList {
        guard WeekDate.date(forWeekID: week) != nil else { throw AppleIntegrationError.invalidDate }
        return try await getJSON(baseURL.appendingPathComponent("/api/shopping-list/saved/" + week))
    }
    func completeShoppingRow(week: String, rowID: String, completed: Bool, expectedHash: String, operationID: UUID = UUID()) async throws -> SavedShoppingList {
        guard WeekDate.date(forWeekID: week) != nil else { throw AppleIntegrationError.invalidDate }
        struct Request: Encodable { let row_id: String; let completed: Bool; let expected_hash: String; let operation_id: String }
        return try await postEncoding(path: "/api/shopping-list/saved/" + week + "/completion", method: "POST", body: Request(row_id: rowID, completed: completed, expected_hash: expectedHash, operation_id: operationID.uuidString.lowercased()))
    }
    func savedTasks(week: String) async throws -> TasksPayload {
        guard WeekDate.date(forWeekID: week) != nil else { throw AppleIntegrationError.invalidDate }
        return try await getJSON(baseURL.appendingPathComponent("/api/tasks/" + week + "/saved"))
    }
}
