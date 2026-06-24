import Foundation
import FoundationModels

/// A proposed (not-yet-applied) addition to the meal plan, surfaced for user confirmation.
public struct PendingMealAddition: Sendable, Equatable {
    public var recipe: String
    public var day: String
    public var meal: String
    public init(recipe: String, day: String, meal: String) {
        self.recipe = recipe; self.day = day; self.meal = meal
    }
}

@Generable(description: "Arguments to propose adding a recipe to the meal plan.")
public struct AddToMealPlanArguments: Sendable {
    @Guide(description: "Recipe name to add.")
    public var recipe: String
    @Guide(description: "Day name, e.g. Thursday.")
    public var day: String
    @Guide(description: "Meal slot: breakfast, lunch, snack, or dinner.")
    public var meal: String
}

/// Tool: PROPOSE adding a recipe to the plan. It never writes — it records a pending
/// proposal that the app surfaces for explicit user confirmation (the safe write path).
public struct AddToMealPlanTool: Tool {
    public let name = "proposeAddToMealPlan"
    public let description = "Propose adding a recipe to a specific day and meal. This does not modify anything; the user must tap Confirm in the app to apply it."

    let onPropose: @Sendable (PendingMealAddition) -> Void
    public init(onPropose: @escaping @Sendable (PendingMealAddition) -> Void) {
        self.onPropose = onPropose
    }

    public func call(arguments: AddToMealPlanArguments) async throws -> String {
        let p = PendingMealAddition(recipe: arguments.recipe, day: arguments.day, meal: arguments.meal)
        onPropose(p)
        return "Proposed adding \(p.recipe) to \(p.day) \(p.meal). Tell the user to tap Confirm to apply it — do not claim it is done yet."
    }
}
