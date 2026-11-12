import Foundation
#if os(iOS)
import UIKit
#elseif os(macOS)
import AppKit
#endif

public enum BrowserOpenError: Error, Equatable {
    case declined
    case invalidDestination
}

/// Opens the user's default browser. The operation is injected in tests, never a fixed app.
@MainActor public struct WebBrowserOpener {
    private let operation: @MainActor (URL) async -> Bool

    public init(operation: @escaping @MainActor (URL) async -> Bool) {
        self.operation = operation
    }

    public init() {
        operation = { url in
            #if os(iOS)
            return await UIApplication.shared.open(url)
            #elseif os(macOS)
            return NSWorkspace.shared.open(url)
            #else
            return false
            #endif
        }
    }

    public func open(_ url: URL) async -> Bool { await operation(url) }
}
