import SwiftUI

/// Every top-level destination in the KitchenOS app, grouped for the sidebar.
/// The `Extraction` row is macOS-only (it can spawn the local Python pipeline).
enum SidebarSection: String, CaseIterable, Identifiable, Hashable {
    case search, recipes, meals, nutrition          // Cook
    case mealPlan, plannerBoard, shoppingList, tasks // Plan
    case inventory, pantry, receipts                 // Stock
    case extraction, systemHealth, settings          // System

    var id: String { rawValue }

    var title: String {
        switch self {
        case .search: "Search"
        case .recipes: "Recipes"
        case .meals: "Meals"
        case .nutrition: "Nutrition"
        case .mealPlan: "Meal Plan"
        case .plannerBoard: "Planner Board"
        case .shoppingList: "Shopping List"
        case .tasks: "Tasks"
        case .inventory: "Inventory"
        case .pantry: "Pantry"
        case .receipts: "Receipts"
        case .extraction: "Extraction"
        case .systemHealth: "System Health"
        case .settings: "Settings"
        }
    }

    var systemImage: String {
        switch self {
        case .search: "sparkles"
        case .recipes: "book"
        case .meals: "fork.knife"
        case .nutrition: "flame"
        case .mealPlan: "calendar"
        case .plannerBoard: "rectangle.grid.3x2"
        case .shoppingList: "cart"
        case .tasks: "checklist"
        case .inventory: "shippingbox"
        case .pantry: "cabinet"
        case .receipts: "receipt"
        case .extraction: "arrow.down.doc"
        case .systemHealth: "heart.text.square"
        case .settings: "gearshape"
        }
    }

    /// Sidebar groups, in display order. Extraction is filtered out off-macOS.
    static let groups: [(label: String, items: [SidebarSection])] = [
        ("Cook", [.search, .recipes, .meals, .nutrition]),
        ("Plan", [.mealPlan, .plannerBoard, .shoppingList, .tasks]),
        ("Stock", [.inventory, .pantry, .receipts]),
        ("System", [.extraction, .systemHealth, .settings]),
    ]

    /// Sections available on the current platform.
    static var available: Set<SidebarSection> {
        #if os(macOS)
        return Set(allCases)
        #else
        return Set(allCases).subtracting([.extraction])
        #endif
    }
}
