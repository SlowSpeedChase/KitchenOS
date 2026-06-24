import Foundation

/// Lightweight identifiable wrapper around a recipe name, used to drive
/// `.sheet(item:)` recipe-detail presentation (Spotlight tap, Cook, Plan).
struct RecipeRef: Identifiable {
    let id: String
}
