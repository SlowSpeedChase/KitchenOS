import Foundation

/// Macro tuple (calories + grams). Matches the JSON from `GET /api/nutrition/<week>`.
public struct Macros: Codable, Sendable, Hashable {
    public let calories: Int
    public let protein: Int
    public let carbs: Int
    public let fat: Int
}

/// One day's macros. Null macros when the day has no meals.
public struct DayMacros: Codable, Sendable, Hashable, Identifiable {
    public let day: String
    public let date: String
    public let hasMeals: Bool
    public let calories: Int?
    public let protein: Int?
    public let carbs: Int?
    public let fat: Int?

    public var id: String { date }

    enum CodingKeys: String, CodingKey {
        case day, date, calories, protein, carbs, fat
        case hasMeals = "has_meals"
    }
}

public struct NutritionDashboard: Codable, Sendable {
    public let week: String
    public let weekLabel: String?
    public let targets: Macros?
    public let days: [DayMacros]
    public let averages: Macros?
    public let warnings: [String]?

    enum CodingKeys: String, CodingKey {
        case week, targets, days, averages, warnings
        case weekLabel = "week_label"
    }
}
