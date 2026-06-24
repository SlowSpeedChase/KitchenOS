import Foundation

public extension KitchenOSClient {
    /// Add a recipe to a day/meal on a week's plan (GET → set slot → PUT).
    /// Shared by `AddRecipeToMealPlanIntent` and the assistant's confirmed add.
    /// Throws `KitchenOSError.http(404)` if the day isn't on the plan.
    func addRecipe(_ recipe: String, day: String, meal: MealSlot, week: String) async throws {
        var plan = try await mealPlan(week: week)
        guard let idx = plan.days.firstIndex(where: { $0.day.lowercased() == day.lowercased() }) else {
            throw KitchenOSError.http(404)
        }
        let slot = MealSlotValue(name: recipe)
        switch meal {
        case .breakfast: plan.days[idx].breakfast = slot
        case .lunch:     plan.days[idx].lunch = slot
        case .snack:     plan.days[idx].snack = slot
        case .dinner:    plan.days[idx].dinner = slot
        }
        try await putMealPlan(plan)
    }
}
