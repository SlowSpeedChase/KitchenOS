import SwiftUI

@main
struct KitchenOSApp: App {
    var body: some Scene {
        MenuBarExtra("KitchenOS", systemImage: "fork.knife") {
            ContentView()
        }
        .menuBarExtraStyle(.window)
    }
}
