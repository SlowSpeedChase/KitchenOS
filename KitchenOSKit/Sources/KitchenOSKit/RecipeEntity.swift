import AppIntents
import CoreSpotlight
import Foundation
import UniformTypeIdentifiers

public struct RecipeEntity: AppEntity, IndexedEntity, Identifiable {
    public var id: String          // recipe name
    public var cuisine: String?
    public var proteinName: String?
    public var ingredientItems: [String]?

    public init(id: String, cuisine: String? = nil, proteinName: String? = nil,
                ingredientItems: [String]? = nil) {
        self.id = id; self.cuisine = cuisine; self.proteinName = proteinName
        self.ingredientItems = ingredientItems
    }

    public init(_ summary: RecipeSummary) {
        self.id = summary.name; self.cuisine = summary.cuisine; self.proteinName = summary.protein
        self.ingredientItems = summary.ingredientItems
    }

    public static var typeDisplayRepresentation: TypeDisplayRepresentation { "Recipe" }

    public var displayRepresentation: DisplayRepresentation {
        DisplayRepresentation(title: "\(id)", subtitle: cuisine.map { "\($0)" })
    }

    /// Feeds the system semantic index so Siri/Spotlight match recipes by meaning.
    public var attributeSet: CSSearchableItemAttributeSet {
        let set = CSSearchableItemAttributeSet(contentType: .text)
        set.title = id
        set.displayName = id
        let facets = [cuisine, proteinName].compactMap { $0 }
        if !facets.isEmpty {
            set.contentDescription = facets.joined(separator: " · ")
        }
        let keywords = facets + (ingredientItems ?? [])
        if !keywords.isEmpty {
            set.keywords = keywords
        }
        return set
    }

    public static var defaultQuery = RecipeEntityQuery()
}

// RecipeEntity conforms to IndexedEntity (semantic index) above. Indexing is driven both
// manually via RecipeIndexer (app launch + Settings button) and by the system through the
// IndexedEntityQuery conformance below (iOS/macOS 27 floor).
public struct RecipeEntityQuery: EntityStringQuery {
    public init() {}

    private func client() -> KitchenOSClient {
        KitchenOSClient(config: .resolved())
    }

    // Siri resolves a typed/spoken name → matching entities.
    public func entities(matching string: String) async throws -> [RecipeEntity] {
        let matches = try await client().findRecipes(ingredient: string)
        return matches.map(RecipeEntity.init)
    }

    // Required: resolve specific ids back to entities.
    public func entities(for identifiers: [String]) async throws -> [RecipeEntity] {
        identifiers.map { RecipeEntity(id: $0) }
    }

    public func suggestedEntities() async throws -> [RecipeEntity] { [] }
}

// System-driven reindex hooks (iOS/macOS 27): the OS calls these on its own schedule.
// The corpus is small (~252 recipes) and the server returns the full index in one call,
// so a targeted per-id reindex would cost the same round-trip — both hooks do a full pass.
extension RecipeEntityQuery: IndexedEntityQuery {
    public func reindexAllEntities(indexDescription: CSSearchableIndexDescription) async throws {
        try await RecipeIndexer.reindexAll()
    }

    public func reindexEntities(for identifiers: [String],
                                indexDescription: CSSearchableIndexDescription) async throws {
        try await RecipeIndexer.reindexAll()
    }
}
