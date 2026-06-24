import SwiftUI
import KitchenOSKit
import CoreSpotlight

@main
struct KitchenOSSiriApp: App {
    @StateObject private var router = RecipeRouter.shared

    var body: some Scene {
        WindowGroup {
            TabView {
                AssistantView()
                    .tabItem { Label("Assistant", systemImage: "bubble.left.and.bubble.right") }
                MealPlanView()
                    .tabItem { Label("Plan", systemImage: "calendar") }
                CookView()
                    .tabItem { Label("Cook", systemImage: "frying.pan") }
                SmartSearchView()
                    .tabItem { Label("Search", systemImage: "sparkles") }
                SettingsView()
                    .tabItem { Label("Settings", systemImage: "gearshape") }
            }
            // Refresh the semantic index once per launch (best-effort).
            .task { try? await RecipeIndexer.reindexAll() }
            // A tapped recipe (Spotlight result / OpenRecipeIntent) shows its detail.
            .sheet(item: Binding(get: { router.selectedRecipe.map(RecipeRef.init) },
                                 set: { router.selectedRecipe = $0?.id })) { ref in
                RecipeDetailView(name: ref.id)
            }
            // Fallback for tapped Spotlight items if the open intent didn't route.
            .onContinueUserActivity(CSSearchableItemActionType) { activity in
                if let id = activity.userInfo?[CSSearchableItemActivityIdentifier] as? String {
                    router.open(id)
                }
            }
        }
    }
}
