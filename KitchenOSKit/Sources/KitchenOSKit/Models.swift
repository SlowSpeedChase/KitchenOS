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

// MARK: - Stock (inventory, pantry, shopping)

/// One inventory row. Field names match `lib/inventory.py`'s dataclass, so the
/// same struct decodes `GET /api/inventory` and encodes `POST /api/inventory/add`.
public struct InventoryItem: Codable, Sendable, Hashable, Identifiable {
    public var name: String
    public var quantity: Double
    public var unit: String
    public var category: String
    public var location: String
    public var purchased: String?
    public var source: String
    public var notes: String

    public var id: String { "\(name)|\(unit)|\(location)" }

    public init(name: String, quantity: Double, unit: String = "ct",
                category: String = "other", location: String = "pantry",
                purchased: String? = nil, source: String = "manual", notes: String = "") {
        self.name = name; self.quantity = quantity; self.unit = unit
        self.category = category; self.location = location
        self.purchased = purchased; self.source = source; self.notes = notes
    }

    /// Tolerant decode: only `name` is required; everything else falls back to
    /// the same defaults as the Python dataclass. Lets us decode both the full
    /// `/api/inventory` payload and name-only lists.
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        name = try c.decode(String.self, forKey: .name)
        quantity = (try? c.decode(Double.self, forKey: .quantity)) ?? 0
        unit = (try? c.decode(String.self, forKey: .unit)) ?? "ct"
        category = (try? c.decode(String.self, forKey: .category)) ?? "other"
        location = (try? c.decode(String.self, forKey: .location)) ?? "pantry"
        purchased = try c.decodeIfPresent(String.self, forKey: .purchased)
        source = (try? c.decode(String.self, forKey: .source)) ?? "manual"
        notes = (try? c.decode(String.self, forKey: .notes)) ?? ""
    }
}

/// Pantry line as returned by `GET /api/pantry` (`{item, amount, unit}`).
public struct PantryItem: Codable, Sendable, Hashable {
    public let item: String
    public let amount: String?
    public let unit: String?

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        item = (try? c.decode(String.self, forKey: .item)) ?? ""
        amount = try c.decodeFlexibleString(forKey: .amount)
        unit = try c.decodeIfPresent(String.self, forKey: .unit)
    }
}

/// `{amount, unit}` sub-record used in shopping-list lines.
public struct ShoppingAmount: Codable, Sendable, Hashable {
    public let amount: String?
    public let unit: String?

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        amount = try c.decodeFlexibleString(forKey: .amount)
        unit = try c.decodeIfPresent(String.self, forKey: .unit)
    }

    public var display: String {
        [amount, unit].compactMap { $0 }.joined(separator: " ")
    }
}

public struct ShoppingLine: Codable, Sendable, Hashable {
    public let item: String
    public let needed: ShoppingAmount?
    public let fromPantry: ShoppingAmount?
    public let toBuy: ShoppingAmount?
    public let display: String?
    public let warning: String?

    enum CodingKeys: String, CodingKey {
        case item, needed, display, warning
        case fromPantry = "from_pantry"
        case toBuy = "to_buy"
    }
}

public struct ShoppingPreview: Codable, Sendable {
    public let success: Bool
    public let items: [String]?
    public let lines: [ShoppingLine]?
    public let recipes: [String]?
    public let error: String?
}

// MARK: - Composite meals

public struct SubRecipe: Codable, Sendable, Hashable, Identifiable {
    public var recipe: String
    public var servings: Int
    public var id: String { recipe }

    public init(recipe: String, servings: Int = 1) {
        self.recipe = recipe; self.servings = servings
    }
}

/// A composite meal (`vault/Meals/<name>.meal.md`). `body` is write-only — the
/// list/detail endpoints don't return it, so it decodes as nil.
public struct Meal: Codable, Sendable, Hashable, Identifiable {
    public var name: String
    public var description: String
    public var tags: [String]
    public var subRecipes: [SubRecipe]
    public var body: String?

    public var id: String { name }

    enum CodingKeys: String, CodingKey {
        case name, description, tags, body
        case subRecipes = "sub_recipes"
    }

    public init(name: String, description: String = "", tags: [String] = [],
                subRecipes: [SubRecipe] = [], body: String? = nil) {
        self.name = name; self.description = description; self.tags = tags
        self.subRecipes = subRecipes; self.body = body
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        name = try c.decode(String.self, forKey: .name)
        description = (try? c.decode(String.self, forKey: .description)) ?? ""
        tags = (try? c.decode([String].self, forKey: .tags)) ?? []
        subRecipes = (try? c.decode([SubRecipe].self, forKey: .subRecipes)) ?? []
        body = try c.decodeIfPresent(String.self, forKey: .body)
    }
}

// MARK: - Prep tasks

public struct PrepTask: Codable, Sendable, Hashable, Identifiable {
    public let id: String
    public let recipe: String
    public let day: String
    public let slot: String
    public let step: Int?
    public let text: String
    public let type: String?
    public let timeMinutes: Int?
    public let canDoAhead: Bool
    public let dependsOn: [String]?
    public var done: Bool

    enum CodingKeys: String, CodingKey {
        case id, recipe, day, slot, step, text, type, done
        case timeMinutes = "time_minutes"
        case canDoAhead = "can_do_ahead"
        case dependsOn = "depends_on"
    }
}

public struct TasksPayload: Codable, Sendable {
    public let week: String?
    public let generatedAt: String?
    public let tasks: [PrepTask]

    enum CodingKeys: String, CodingKey {
        case week, tasks
        case generatedAt = "generated_at"
    }
}

public struct ByIngredientsResponse: Codable, Sendable {
    public let matches: [Suggestion]
}
