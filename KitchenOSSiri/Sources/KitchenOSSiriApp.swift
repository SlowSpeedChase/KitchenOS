import SwiftUI

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
        }
    }
}
