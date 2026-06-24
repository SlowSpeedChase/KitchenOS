import SwiftUI

/// Root navigation: a Mac-native sidebar (collapses to a stack on iPhone).
struct AppShell: View {
    @State private var selection: SidebarSection? = .search

    var body: some View {
        NavigationSplitView {
            List(selection: $selection) {
                ForEach(SidebarSection.groups, id: \.label) { group in
                    let items = group.items.filter { SidebarSection.available.contains($0) }
                    if !items.isEmpty {
                        Section(group.label) {
                            ForEach(items) { section in
                                Label(section.title, systemImage: section.systemImage)
                                    .tag(section)
                            }
                        }
                    }
                }
            }
            .navigationTitle("KitchenOS")
            #if os(macOS)
            .frame(minWidth: 200)
            #endif
        } detail: {
            NavigationStack {
                detail(for: selection ?? .search)
            }
        }
    }

    @ViewBuilder
    private func detail(for section: SidebarSection) -> some View {
        switch section {
        case .search: SmartSearchView()
        case .recipes: RecipeListView()
        case .mealPlan: MealPlanView()
        case .plannerBoard: PlannerBoardView()
        case .meals: MealsView()
        case .tasks: TasksView()
        case .nutrition: NutritionDashboardView()
        case .inventory: InventoryView()
        case .pantry: PantryView()
        case .receipts: ReceiptsView()
        case .shoppingList: ShoppingListView()
        case .systemHealth: SystemHealthView()
        case .settings: SettingsView()
        #if os(macOS)
        case .extraction: ExtractionView()
        #endif
        default:
            ComingSoonView(section: section)
        }
    }
}

/// Placeholder for sections whose native screens land in later phases.
struct ComingSoonView: View {
    let section: SidebarSection

    var body: some View {
        ContentUnavailableView(
            section.title,
            systemImage: section.systemImage,
            description: Text("This screen is coming soon.")
        )
        .navigationTitle(section.title)
    }
}
