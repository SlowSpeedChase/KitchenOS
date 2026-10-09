import Foundation

/// Uses the shared authenticated transport; HTTP 409/413 remain KitchenOSError.http.
public struct AppleIntegrationClient: Sendable {
    private let client: KitchenOSClient
    private let prefix = "/api/apple-integration"
    public init(client: KitchenOSClient) { self.client = client }

    public func link(token: UUID) async throws -> KitchenOSItemLink {
        try await client.getJSON(client.baseURL.appendingPathComponent(prefix + "/links/" + token.uuidString.lowercased()))
    }
    public func items(domain: AppleDomain, week: String) async throws -> [AppleItemDetail] {
        guard WeekDate.date(forWeekID: week) != nil else { throw AppleIntegrationError.invalidDate }
        var url = URLComponents(url: client.baseURL.appendingPathComponent(prefix + "/items"), resolvingAgainstBaseURL: false)!
        url.queryItems = [URLQueryItem(name: "domain", value: domain.rawValue), URLQueryItem(name: "week", value: week)]
        struct Response: Decodable { let items: [AppleItemDetail] }
        let response: Response = try await client.getJSON(url.url!)
        return response.items
    }
    public func conflict(_ id: UUID) async throws -> AppleConflictDetail {
        try await client.getJSON(client.baseURL.appendingPathComponent(prefix + "/conflicts/" + id.uuidString.lowercased()))
    }
    public func registerOwner(_ id: UUID, permissions: [String: AppleAuthorization]? = nil,
                              destinations: [String: [AppleDestination]]? = nil) async throws -> BridgeContext {
        struct Request: Encodable { let owner_id: String; let permissions: [String: AppleAuthorization]?; let destinations: [String: [AppleDestination]]? }
        struct Response: Decodable { let model_version: Int; let context: BridgeContext; let status: IntegrationStatus }
        let response: Response = try await send("/owner", body: Request(owner_id: id.uuidString.lowercased(), permissions: permissions, destinations: destinations))
        guard response.model_version == 1 else { throw AppleIntegrationError.unsupportedVersion }
        return response.context
    }
    public func setScope(_ request: ScopeRequest) async throws -> SyncReport {
        let response: ReportResponse = try await send("/scopes/\(request.domain.rawValue)/\(request.week)", method: "PUT", body: request)
        return response.report
    }
    public func status() async throws -> IntegrationStatus {
        try await client.getJSON(client.baseURL.appendingPathComponent(prefix + "/status"))
    }
    public func work(context: BridgeContext) async throws -> WorkBatch {
        var url = URLComponents(url: client.baseURL.appendingPathComponent(prefix + "/work"), resolvingAgainstBaseURL: false)!
        url.queryItems = [URLQueryItem(name: "owner_id", value: context.ownerID.uuidString.lowercased()), URLQueryItem(name: "owner_generation", value: String(context.ownerGeneration))]
        return try await client.getJSON(url.url!)
    }
    public func observe(_ observations: [Observation], context: BridgeContext, requestID: UUID) async throws -> [AppleOperation] {
        struct Request: Encodable { let context: BridgeContext; let request_id: String; let complete = true; let observations: [Observation] }
        guard observations.count <= 5000, Set(observations.map(\.token)).count == observations.count else { throw AppleIntegrationError.batchTooLarge }
        let response: OperationsResponse = try await send("/observations", body: Request(context: context, request_id: requestID.uuidString.lowercased(), observations: observations))
        return response.operations
    }
    public func acknowledge(_ ack: OperationAck, context: BridgeContext) async throws -> SyncReport {
        struct Request: Encodable {
            let ack: OperationAck; let context: BridgeContext
            enum CodingKeys: String, CodingKey { case context }
            func encode(to encoder: Encoder) throws {
                try ack.encode(to: encoder)
                var c = encoder.container(keyedBy: CodingKeys.self); try c.encode(context, forKey: .context)
            }
        }
        let response: ReportResponse = try await send("/operations/\(ack.operationID.uuidString.lowercased())/ack", body: Request(ack: ack, context: context))
        return response.report
    }
    public func resolve(_ resolution: ConflictResolution) async throws -> SyncReport {
        struct Request: Encodable { let choice: AppleConflictChoice; let expected_revision: Int }
        let response: ReportResponse = try await send("/conflicts/\(resolution.conflictID.uuidString.lowercased())/resolve", body: Request(choice: resolution.choice, expected_revision: resolution.expectedRevision))
        return response.report
    }
    public func setPaused(_ paused: Bool, expectedRevision: Int) async throws -> SyncReport {
        struct Request: Encodable { let paused: Bool; let expected_revision: Int }
        let response: IntegrationStatus = try await send("/settings", method: "PUT", body: Request(paused: paused, expected_revision: expectedRevision))
        return response.report
    }
    public func disconnect(context: BridgeContext) async throws -> SyncReport {
        struct Request: Encodable { let context: BridgeContext }
        let response: IntegrationStatus = try await send("/owner", method: "DELETE", body: Request(context: context))
        return response.report
    }
    public func restore(token: UUID, expectedRevision: Int) async throws -> SyncReport {
        struct Request: Encodable { let expected_revision: Int }
        let response: ReportResponse = try await send("/items/\(token.uuidString.lowercased())/restore", body: Request(expected_revision: expectedRevision))
        return response.report
    }
    public func removeOwned(_ items: [OwnedRemovalItem], context: BridgeContext, requestID: UUID) async throws -> [AppleOperation] {
        struct Request: Encodable { let context: BridgeContext; let request_id: String; let items: [OwnedRemovalItem] }
        guard items.count <= 5000, Set(items.map(\.token)).count == items.count else { throw AppleIntegrationError.batchTooLarge }
        for item in items {
            guard item.token == item.observation.token, item.expectedRevision == item.observation.revision,
                  item.observation.availability == .present, item.observation.issue == nil else { throw AppleIntegrationError.identityAmbiguous }
        }
        let response: OperationsResponse = try await send("/items/remove-owned", body: Request(context: context, request_id: requestID.uuidString.lowercased(), items: items))
        return response.operations
    }
    private struct ReportResponse: Decodable { let report: SyncReport }
    private struct OperationsResponse: Decodable { let operations: [AppleOperation] }
    private func send<B: Encodable, R: Decodable>(_ path: String, method: String = "POST", body: B) async throws -> R {
        guard try JSONEncoder().encode(body).count <= 2 * 1024 * 1024 else { throw AppleIntegrationError.batchTooLarge }
        return try await client.postEncoding(path: prefix + path, method: method, body: body)
    }
}
