import Foundation

/// Subset of `GET /api/system-health` (`lib/health.get_system_health`).
/// Extra keys (failure_logs, reminders_queue) are ignored for resilience.
public struct SystemHealth: Codable, Sendable {
    public let generatedAt: String?
    public let ollama: OllamaHealth?
    public let vault: VaultHealth?
    public let recentRecipes: [RecentRecipe]?
    public let runLogs: [RunLog]?

    enum CodingKeys: String, CodingKey {
        case ollama, vault
        case generatedAt = "generated_at"
        case recentRecipes = "recent_recipes"
        case runLogs = "run_logs"
    }
}

public struct OllamaHealth: Codable, Sendable {
    public let alive: Bool
    public let error: String?
    public let models: [String]?
}

public struct VaultHealth: Codable, Sendable {
    public let exists: Bool
    public let path: String?
    public let writable: Bool
}

public struct RecentRecipe: Codable, Sendable, Hashable {
    public let name: String
    public let modifiedISO: String?

    enum CodingKeys: String, CodingKey {
        case name
        case modifiedISO = "modified_iso"
    }
}

public struct RunLog: Codable, Sendable, Hashable {
    public let timestamp: String?
    public let total: Int?
    public let succeeded: Int?
    public let failed: Int?
    public let invalid: Int?
    public let skippedDuplicate: Int?
    public let durationSeconds: Double?

    enum CodingKeys: String, CodingKey {
        case timestamp, total, succeeded, failed, invalid
        case skippedDuplicate = "skipped_duplicate"
        case durationSeconds = "duration_seconds"
    }
}
