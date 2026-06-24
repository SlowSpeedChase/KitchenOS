import Foundation
import FoundationModels

@Generable(description: "Arguments for suggesting a meal for a slot.")
public struct SuggestMealToolArguments: Sendable {
    @Guide(description: "Day name, e.g. Monday.")
    public var day: String
    @Guide(description: "Meal slot: breakfast, lunch, snack, or dinner.")
    public var meal: String
}

/// Tool: suggest a recipe for a given day/meal. Reuses `client.suggestMeal` + `WeekDate`.
public struct SuggestMealTool: Tool {
    public let name = "suggestMeal"
    public let description = "Suggest a recipe for a specific day and meal based on what is already planned."

    let client: KitchenOSClient
    public init(client: KitchenOSClient) { self.client = client }

    public func call(arguments: SuggestMealToolArguments) async throws -> String {
        let resp = try await client.suggestMeal(
            week: WeekDate.currentWeekID(),
            day: arguments.day,
            meal: arguments.meal
        )
        guard let s = resp.suggestion else {
            return resp.message ?? "No suggestion is available for that slot."
        }
        return "Suggested for \(arguments.meal) on \(arguments.day): \(s.name)."
    }
}
