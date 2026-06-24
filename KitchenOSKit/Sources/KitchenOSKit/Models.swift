import Foundation

public struct RecipeSummary: Codable, Sendable, Hashable {
    public let name: String
    public let cuisine: String?
    public let protein: String?
    public let image: String?
    public let ingredientItems: [String]?
    public let nutritionCalories: Double?
    public let nutritionProtein: Double?
    public let nutritionCarbs: Double?
    public let nutritionFat: Double?

    enum CodingKeys: String, CodingKey {
        case name, cuisine, protein, image
        case ingredientItems = "ingredient_items"
        case nutritionCalories = "nutrition_calories"
        case nutritionProtein = "nutrition_protein"
        case nutritionCarbs = "nutrition_carbs"
        case nutritionFat = "nutrition_fat"
    }

    public init(name: String, cuisine: String? = nil, protein: String? = nil,
                image: String? = nil, ingredientItems: [String]? = nil,
                nutritionCalories: Double? = nil, nutritionProtein: Double? = nil,
                nutritionCarbs: Double? = nil, nutritionFat: Double? = nil) {
        self.name = name; self.cuisine = cuisine; self.protein = protein
        self.image = image; self.ingredientItems = ingredientItems
        self.nutritionCalories = nutritionCalories; self.nutritionProtein = nutritionProtein
        self.nutritionCarbs = nutritionCarbs; self.nutritionFat = nutritionFat
    }
}

public struct RecipeDetail: Codable, Sendable {
    public let title: String
    public let servings: Int?
    public let nutritionCalories: Double?
    public let nutritionProtein: Double?
    public let nutritionCarbs: Double?
    public let nutritionFat: Double?

    enum CodingKeys: String, CodingKey {
        case title, servings
        case nutritionCalories = "nutrition_calories"
        case nutritionProtein = "nutrition_protein"
        case nutritionCarbs = "nutrition_carbs"
        case nutritionFat = "nutrition_fat"
    }
}

public struct MealSlotValue: Codable, Sendable, Hashable {
    public var name: String
    public var servings: Int
    public var kind: String

    public init(name: String, servings: Int = 1, kind: String = "recipe") {
        self.name = name; self.servings = servings; self.kind = kind
    }
}

public struct MealPlanDay: Codable, Sendable {
    public var day: String
    public var date: String
    public var breakfast: MealSlotValue?
    public var lunch: MealSlotValue?
    public var snack: MealSlotValue?
    public var dinner: MealSlotValue?
}

public struct MealPlan: Codable, Sendable {
    public let week: String
    public var days: [MealPlanDay]
}

public struct Suggestion: Codable, Sendable {
    public let name: String
    public let score: Double?
    public let sharedIngredients: [String]?

    enum CodingKeys: String, CodingKey {
        case name, score
        case sharedIngredients = "shared_ingredients"
    }
}

public struct SuggestResponse: Codable, Sendable {
    public let suggestion: Suggestion?
    public let message: String?
}
