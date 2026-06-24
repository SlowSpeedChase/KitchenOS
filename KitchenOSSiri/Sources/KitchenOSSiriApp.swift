import SwiftUI
import KitchenOSKit

@main
struct KitchenOSSiriApp: App {
    var body: some Scene {
        WindowGroup {
            TabView {
                AssistantView()
                    .tabItem { Label("Assistant", systemImage: "bubble.left.and.bubble.right") }
                SmartSearchView()
                    .tabItem { Label("Search", systemImage: "sparkles") }
                SettingsView()
                    .tabItem { Label("Settings", systemImage: "gearshape") }
            }
            // Refresh the semantic index once per launch (best-effort).
            .task { try? await RecipeIndexer.reindexAll() }
        }
    }
}
