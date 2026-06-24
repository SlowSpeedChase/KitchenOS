import Foundation

public extension KitchenOSClient {
    // MARK: Composite meals

    func meals() async throws -> [Meal] {
        struct Wrapper: Decodable { let meals: [Meal] }
        let wrapped: Wrapper = try await getJSON(baseURL.appendingPathComponent("/api/meals"))
        return wrapped.meals
    }

    func meal(name: String) async throws -> Meal {
        try await getJSON(baseURL.appendingPathComponent("/api/meals/\(name)"))
    }

    @discardableResult
    func createMeal(_ meal: Meal) async throws -> Meal {
        try await postEncoding(path: "/api/meals", method: "POST", body: meal)
    }

    @discardableResult
    func updateMeal(name: String, _ meal: Meal) async throws -> Meal {
        try await postEncoding(path: "/api/meals/\(name)", method: "PUT", body: meal)
    }

    func deleteMeal(name: String) async throws {
        try await sendIgnoringBody(path: "/api/meals/\(name)", method: "DELETE")
    }

    // MARK: Prep tasks

    func tasks(week: String, force: Bool = false) async throws -> TasksPayload {
        var comps = URLComponents(url: baseURL.appendingPathComponent("/api/tasks/\(week)"),
                                  resolvingAgainstBaseURL: false)!
        if force { comps.queryItems = [URLQueryItem(name: "force", value: "1")] }
        return try await getJSON(comps.url!)
    }

    func markTask(week: String, taskId: String, done: Bool) async throws {
        try await postRawJSON(path: "/api/tasks/\(week)/\(taskId)/done", object: ["done": done])
    }
}
