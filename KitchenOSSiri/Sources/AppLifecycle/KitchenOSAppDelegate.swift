#if os(macOS)
import AppKit

@MainActor final class KitchenOSAppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        AppleIntegrationCoordinator.shared.start()
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }
    func applicationWillTerminate(_ notification: Notification) {
        AppleIntegrationCoordinator.shared.stop()
    }
}
#endif
