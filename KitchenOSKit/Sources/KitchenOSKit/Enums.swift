import AppIntents

public enum DayOfWeek: String, AppEnum, CaseIterable {
    case monday, tuesday, wednesday, thursday, friday, saturday, sunday

    public var title: String { rawValue.capitalized }

    public static var typeDisplayRepresentation: TypeDisplayRepresentation { "Day" }
    public static var caseDisplayRepresentations: [DayOfWeek: DisplayRepresentation] {
        Dictionary(uniqueKeysWithValues: allCases.map { ($0, DisplayRepresentation(stringLiteral: $0.title)) })
    }
}

public enum MealSlot: String, AppEnum, CaseIterable {
    case breakfast, lunch, snack, dinner

    public var title: String { rawValue.capitalized }

    public static var typeDisplayRepresentation: TypeDisplayRepresentation { "Meal" }
    public static var caseDisplayRepresentations: [MealSlot: DisplayRepresentation] {
        Dictionary(uniqueKeysWithValues: allCases.map { ($0, DisplayRepresentation(stringLiteral: $0.title)) })
    }
}
