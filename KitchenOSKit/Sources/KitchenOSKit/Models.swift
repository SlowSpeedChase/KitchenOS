import Foundation

public struct RecipeSummary: Codable, Sendable, Hashable {
    public let name: String
    public let cuisine: String?
    public let protein: String?
    public let image: String?
    public let ingredientItems: [String]?

    enum CodingKeys: String, CodingKey {
        case name, cuisine, protein, image
        case ingredientItems = "ingredient_items"
    }
}

/// One ingredient row. `amount` arrives as either a string ("1 1/2") or a
/// number from the source data, so it is decoded flexibly into a String.
public struct Ingredient: Codable, Sendable, Hashable {
    public let amount: String?
    public let unit: String?
    public let item: String
    public let inferred: Bool?

    enum CodingKeys: String, CodingKey { case amount, unit, item, inferred }

    public init(amount: String?, unit: String?, item: String, inferred: Bool? = nil) {
        self.amount = amount; self.unit = unit; self.item = item; self.inferred = inferred
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        amount = try c.decodeFlexibleString(forKey: .amount)
        unit = try c.decodeIfPresent(String.self, forKey: .unit)
        item = (try? c.decode(String.self, forKey: .item)) ?? ""
        inferred = try c.decodeIfPresent(Bool.self, forKey: .inferred)
    }
}

public struct InstructionStep: Codable, Sendable, Hashable {
    public let step: Int
    public let text: String
    public let time: String?

    public init(step: Int, text: String, time: String? = nil) {
        self.step = step; self.text = text; self.time = time
    }
}

public struct RecipeDetail: Codable, Sendable {
    public let title: String
    public let cuisine: String?
    public let protein: String?
    public let dishType: String?
    public let difficulty: String?
    public let servings: Int?
    public let prepTime: String?
    public let cookTime: String?
    public let totalTime: String?
    public let dietary: [String]?
    public let equipment: [String]?
    public let mealOccasion: [String]?
    public let nutritionCalories: Double?
    public let nutritionProtein: Double?
    public let nutritionCarbs: Double?
    public let nutritionFat: Double?
    public let seasonalIngredients: [String]?
    public let sourceURL: String?
    public let needsReview: Bool?
    public let description: String?
    public let ingredients: [Ingredient]?
    public let instructions: [InstructionStep]?
    public let videoTips: [String]?

    enum CodingKeys: String, CodingKey {
        case title, cuisine, protein, difficulty, servings, dietary, equipment
        case description, ingredients, instructions
        case dishType = "dish_type"
        case prepTime = "prep_time"
        case cookTime = "cook_time"
        case totalTime = "total_time"
        case mealOccasion = "meal_occasion"
        case nutritionCalories = "nutrition_calories"
        case nutritionProtein = "nutrition_protein"
        case nutritionCarbs = "nutrition_carbs"
        case nutritionFat = "nutrition_fat"
        case seasonalIngredients = "seasonal_ingredients"
        case sourceURL = "source_url"
        case needsReview = "needs_review"
        case videoTips = "video_tips"
    }
}

extension KeyedDecodingContainer {
    /// Decode a value that may be encoded as a String, Int, Double, or null
    /// into an optional String (trimmed; empty/null → nil).
    func decodeFlexibleString(forKey key: Key) throws -> String? {
        if let s = try? decodeIfPresent(String.self, forKey: key) {
            let t = s.trimmingCharacters(in: .whitespaces)
            return t.isEmpty ? nil : t
        }
        if let i = try? decode(Int.self, forKey: key) { return String(i) }
        if let d = try? decode(Double.self, forKey: key) {
            return d == d.rounded() ? String(Int(d)) : String(d)
        }
        return nil
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
