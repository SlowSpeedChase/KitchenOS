import AppIntents
import CoreSpotlight
import Foundation
import UniformTypeIdentifiers

public struct RecipeEntity: AppEntity, IndexedEntity, Identifiable {
    public var id: String          // recipe name
    public var cuisine: String?
    public var proteinName: String?

    public init(id: String, cuisine: String? = nil, proteinName: String? = nil) {
        self.id = id; self.cuisine = cuisine; self.proteinName = proteinName
    }

    public init(_ summary: RecipeSummary) {
        self.id = summary.name; self.cuisine = summary.cuisine; self.proteinName = summary.protein
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
            set.keywords = facets
        }
        return set
    }

    public static var defaultQuery = RecipeEntityQuery()
}

// Note: RecipeEntity conforms to IndexedEntity (semantic index) above; indexing is driven
// manually via RecipeIndexer (app launch + Settings button). The system-driven
// IndexedEntityQuery reindex hooks require iOS/macOS 27 (CSSearchableIndexDescription) —
// a future enhancement if we raise the floor.
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
