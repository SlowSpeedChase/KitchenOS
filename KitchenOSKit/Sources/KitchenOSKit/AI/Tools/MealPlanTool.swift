import Foundation
import FoundationModels

@Generable(description: "Arguments for reading the meal plan.")
public struct MealPlanToolArguments: Sendable {
    @Guide(description: "A specific day name like Monday, or nil for the whole week.")
    public var day: String?
}

/// Tool: read the current week's meal plan. Reuses `client.mealPlan` + `WeekDate`.
public struct MealPlanTool: Tool {
    public let name = "getMealPlan"
    public let description = "Read what is currently scheduled on the user's meal plan for this week."

    let client: KitchenOSClient
    public init(client: KitchenOSClient) { self.client = client }

    public func call(arguments: MealPlanToolArguments) async throws -> String {
        let plan = try await client.mealPlan(week: WeekDate.currentWeekID())
        let days: [MealPlanDay]
        if let wanted = arguments.day?.lowercased() {
            days = plan.days.filter { $0.day.lowercased() == wanted }
            if days.isEmpty { return "There's no \(arguments.day ?? "") on this week's plan." }
        } else {
            days = plan.days
        }
        return days.map(Self.describe).joined(separator: "\n")
    }

    static func describe(_ d: MealPlanDay) -> String {
        var meals: [String] = []
        if let b = d.breakfast?.name { meals.append("breakfast: \(b)") }
        if let l = d.lunch?.name { meals.append("lunch: \(l)") }
        if let s = d.snack?.name { meals.append("snack: \(s)") }
        if let n = d.dinner?.name { meals.append("dinner: \(n)") }
        return meals.isEmpty ? "\(d.day): nothing planned" : "\(d.day): " + meals.joined(separator: ", ")
    }
}
