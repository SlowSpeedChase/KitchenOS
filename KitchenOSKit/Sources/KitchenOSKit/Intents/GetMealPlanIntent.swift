import AppIntents

public struct GetMealPlanIntent: AppIntent {
    public static var title: LocalizedStringResource = "Get Meal Plan"
    public static var description = IntentDescription("Read what's on the KitchenOS meal plan.")

    @Parameter(title: "Day")
    public var day: DayOfWeek?

    public init() {}

    public func perform() async throws -> some IntentResult & ProvidesDialog {
        let client = KitchenOSClient(config: .resolved())
        let week = WeekDate.currentWeekID()
        let plan: MealPlan
        do { plan = try await client.mealPlan(week: week) }
        catch KitchenOSError.unreachable { return .result(dialog: "I can't reach KitchenOS right now.") }

        if let day {
            guard let d = plan.days.first(where: { $0.day.lowercased() == day.title.lowercased() }) else {
                return .result(dialog: "I couldn't find \(day.title) on this week's plan.")
            }
            return .result(dialog: IntentDialog(stringLiteral: Self.describe(d)))
        }
        let summary = plan.days.map(Self.describe).joined(separator: "; ")
        return .result(dialog: IntentDialog(stringLiteral: "This week: \(summary)"))
    }

    static func describe(_ d: MealPlanDay) -> String {
        var meals: [String] = []
        if let b = d.breakfast?.name { meals.append("breakfast \(b)") }
        if let l = d.lunch?.name { meals.append("lunch \(l)") }
        if let s = d.snack?.name { meals.append("snack \(s)") }
        if let n = d.dinner?.name { meals.append("dinner \(n)") }
        return meals.isEmpty ? "\(d.day) is empty" : "\(d.day): " + meals.joined(separator: ", ")
    }
}
