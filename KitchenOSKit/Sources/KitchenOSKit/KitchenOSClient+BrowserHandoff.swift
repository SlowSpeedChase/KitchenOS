import Foundation

public struct BrowserHandoffResponse: Decodable, Sendable {
    public let handoffPath: String
    public let expiresAt: TimeInterval
    enum CodingKeys: String, CodingKey {
        case handoffPath = "handoff_path"
        case expiresAt = "expires_at"
    }
}

/// Minting never follows redirects: the bearer and POST body stay at the configured origin.
final class BrowserHandoffRedirectPolicy: NSObject, URLSessionTaskDelegate, @unchecked Sendable {
    func urlSession(_ session: URLSession, task: URLSessionTask,
                    willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest,
                    completionHandler: @escaping (URLRequest?) -> Void) {
        completionHandler(nil)
    }
}

extension WebDestination {
    func validate() throws {
        switch self {
        case .recipe(let name):
            _ = try RecipeNavigationResolver.resolve(name: name, recipes: [RecipeSummary(name: name)])
        case .mealPlan(let date):
            _ = try WebDayResolver.resolve(.exact(date))
        }
    }
}

extension KitchenOSClient {
    public func createBrowserHandoff(destination: WebDestination) async throws -> BrowserHandoffResponse {
        try destination.validate()
        // Validate the configured origin before sending any credential.
        _ = try WebDestination.handoffURL(relativePath: "/browser/open#code=" + String(repeating: "a", count: 43), baseURL: baseURL)
        let data = try await browserHandoffData(destination)
        let response: BrowserHandoffResponse
        do { response = try JSONDecoder().decode(BrowserHandoffResponse.self, from: data) }
        catch { throw KitchenOSError.decoding }
        _ = try WebDestination.handoffURL(relativePath: response.handoffPath, baseURL: baseURL)
        guard response.expiresAt.isFinite, response.expiresAt > 0 else { throw KitchenOSError.decoding }
        return response
    }
}
