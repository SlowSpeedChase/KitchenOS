import AppIntents
import Foundation

public enum WebNavigationKind: String, AppEnum {
    case recipe, mealPlan
    public static var typeDisplayRepresentation: TypeDisplayRepresentation { "KitchenOS page" }
    public static var caseDisplayRepresentations: [WebNavigationKind: DisplayRepresentation] {
        [.recipe: "Recipe", .mealPlan: "Meal-plan day"]
    }
}

/// A foreground continuation of Ask KitchenOS, with typed fields and no model-provided URL.
public struct OpenKitchenOSWebIntent: AppIntent {
    public static var title: LocalizedStringResource = "Open KitchenOS Web Page"
    public static var isDiscoverable: Bool = false
    public static var supportedModes: IntentModes { .foreground(.immediate) }

    @Parameter(title: "Page") public var kind: WebNavigationKind
    @Parameter(title: "Recipe") public var recipeName: String?
    @Parameter(title: "Date") public var date: String?

    public init() {}
    public init(destination: WebDestination) {
        switch destination {
        case .recipe(let name): kind = .recipe; recipeName = name; date = nil
        case .mealPlan(let value): kind = .mealPlan; recipeName = nil; date = value
        }
    }

    private func destination() throws -> WebDestination {
        let value: WebDestination
        switch kind {
        case .recipe:
            guard let recipeName, date == nil else { throw BrowserOpenError.invalidDestination }
            value = .recipe(name: recipeName)
        case .mealPlan:
            guard let date, recipeName == nil else { throw BrowserOpenError.invalidDestination }
            value = .mealPlan(date: date)
        }
        try value.validate()
        return value
    }

    @MainActor func open(client: KitchenOSClient, opener: WebBrowserOpener) async throws -> String {
        try await open(baseURL: client.baseURL,
                       mint: { try await client.createBrowserHandoff(destination: $0) }, opener: opener)
    }

    /// The asynchronous mint operation and browser dispatch have a cancellation boundary.
    @MainActor func open(baseURL: URL,
                         mint: (WebDestination) async throws -> BrowserHandoffResponse,
                         opener: WebBrowserOpener) async throws -> String {
        try Task.checkCancellation()
        let destination = try destination()
        let response = try await mint(destination)
        let url = try WebDestination.handoffURL(relativePath: response.handoffPath, baseURL: baseURL)
        try Task.checkCancellation()
        guard await opener.open(url) else { throw BrowserOpenError.declined }
        switch destination {
        case .recipe(let name): return "Opened \(name) in your browser."
        case .mealPlan(let date): return "Opened the meal plan for \(date) in your browser."
        }
    }

    @MainActor public func perform() async throws -> some IntentResult & ProvidesDialog {
        do {
            let message = try await open(client: KitchenOSClient(config: .resolved()), opener: WebBrowserOpener())
            return .result(dialog: IntentDialog(stringLiteral: message))
        } catch is CancellationError {
            throw CancellationError()
        } catch BrowserOpenError.declined {
            return .result(dialog: "Your browser couldn't open the KitchenOS page. Try opening it again.")
        } catch KitchenOSError.unreachable {
            return .result(dialog: "I can't reach KitchenOS. Check your connection and try again.")
        } catch KitchenOSError.http(401) {
            return .result(dialog: "KitchenOS needs its connection credentials updated in the native app.")
        } catch KitchenOSError.http(404) {
            return .result(dialog: "That saved recipe is no longer available.")
        } catch {
            return .result(dialog: "I couldn't open that KitchenOS page. Check the connection settings and try again.")
        }
    }
}
