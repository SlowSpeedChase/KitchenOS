import Combine
import Foundation

/// Shared navigation target so an `OpenRecipeIntent` (e.g. a tapped Spotlight result) can
/// tell the UI which recipe to show.
@MainActor
public final class RecipeRouter: ObservableObject {
    public static let shared = RecipeRouter()
    @Published public var selectedRecipe: String?
    private init() {}
    public func open(_ name: String) { selectedRecipe = name }
}
