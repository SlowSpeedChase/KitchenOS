import SwiftUI

@main
struct KitchenOSSiriApp: App {
    var body: some Scene {
        WindowGroup {
            TabView {
                SmartSearchView()
                    .tabItem { Label("Search", systemImage: "sparkles") }
                SettingsView()
                    .tabItem { Label("Settings", systemImage: "gearshape") }
            }
        }
    }
}
