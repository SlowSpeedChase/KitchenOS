import Foundation

public enum KitchenOSError: Error, Equatable {
    case unreachable
    case http(Int)
    case decoding
}

public final class KitchenOSClient: @unchecked Sendable {
    private let config: KitchenOSConfig
    private let session: URLSession
    private let decoder = JSONDecoder()
    private let encoder = JSONEncoder()

    public init(config: KitchenOSConfig, session: URLSession = .shared) {
        self.config = config
        self.session = session
    }

    public func findRecipes(ingredient: String) async throws -> [RecipeSummary] {
        var comps = URLComponents(url: config.baseURL.appendingPathComponent("/api/recipes"),
                                  resolvingAgainstBaseURL: false)!
        comps.queryItems = [URLQueryItem(name: "ingredient", value: ingredient)]
        return try await get(comps.url!)
    }

    public func recipeDetail(name: String) async throws -> RecipeDetail {
        let url = config.baseURL.appendingPathComponent("/api/recipes/\(name)")
        return try await get(url)
    }

    public func mealPlan(week: String) async throws -> MealPlan {
        let url = config.baseURL.appendingPathComponent("/api/meal-plan/\(week)")
        return try await get(url)
    }

    public func putMealPlan(_ plan: MealPlan) async throws {
        let url = config.baseURL.appendingPathComponent("/api/meal-plan/\(plan.week)")
        var req = request(url, method: "PUT")
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try encoder.encode(["days": plan.days])
        _ = try await send(req)
    }

    public func suggestMeal(week: String, day: String, meal: String,
                            skipIndex: Int = 0) async throws -> SuggestResponse {
        let url = config.baseURL.appendingPathComponent("/api/suggest-meal")
        var req = request(url, method: "POST")
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try JSONSerialization.data(withJSONObject: [
            "week": week, "day": day, "meal": meal, "skip_index": skipIndex,
        ])
        let data = try await send(req)
        return try decode(data)
    }

    // MARK: - Plumbing

    private func request(_ url: URL, method: String = "GET") -> URLRequest {
        var req = URLRequest(url: url)
        req.httpMethod = method
        req.timeoutInterval = 12
        if let token = config.credentials.token() {
            req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        return req
    }

    private func get<T: Decodable>(_ url: URL) async throws -> T {
        let data = try await send(request(url))
        return try decode(data)
    }

    @discardableResult
    private func send(_ req: URLRequest) async throws -> Data {
        let data: Data, response: URLResponse
        do { (data, response) = try await session.data(for: req) }
        catch { throw KitchenOSError.unreachable }
        guard let http = response as? HTTPURLResponse else { throw KitchenOSError.unreachable }
        guard (200..<300).contains(http.statusCode) else { throw KitchenOSError.http(http.statusCode) }
        return data
    }

    private func decode<T: Decodable>(_ data: Data) throws -> T {
        do { return try decoder.decode(T.self, from: data) }
        catch { throw KitchenOSError.decoding }
    }
}
