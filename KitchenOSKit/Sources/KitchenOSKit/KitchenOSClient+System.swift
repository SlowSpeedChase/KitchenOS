import Foundation

public extension KitchenOSClient {
    /// Full system-health snapshot (Ollama, vault, recent recipes, run logs).
    func systemHealth() async throws -> SystemHealth {
        try await getJSON(baseURL.appendingPathComponent("/api/system-health"))
    }

    /// Structured nutrition dashboard for a week.
    func nutrition(week: String) async throws -> NutritionDashboard {
        try await getJSON(baseURL.appendingPathComponent("/api/nutrition/\(week)"))
    }

    /// Server-side extraction via `POST /extract` (works on iOS too, unlike the
    /// local macOS Process path). Returns the saved recipe name.
    @discardableResult
    func extract(url: String) async throws -> String {
        struct Result: Decodable { let status: String; let recipe: String?; let message: String? }
        let result: Result = try await postDecoding(path: "/extract", object: ["url": url])
        guard result.status == "success", let recipe = result.recipe else {
            throw KitchenOSError.http(500)
        }
        return recipe
    }
}
