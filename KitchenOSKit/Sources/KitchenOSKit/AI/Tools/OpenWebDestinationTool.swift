import Foundation
import FoundationModels

public enum PendingWebNavigation: Equatable, Sendable {
    case none
    case destination(WebDestination)
    case clarification(String)
}

/// One reply owns one selection. No saved "last recipe" and no last-writer-wins target.
public final class PendingWebDestinationStore: @unchecked Sendable {
    private let lock = NSLock()
    private var value: PendingWebNavigation = .none
    private var allowed = false

    public init() {}

    public func begin(request: String) {
        lock.lock(); defer { lock.unlock() }
        value = .none
        let request = request.lowercased()
        allowed = request.range(of: #"\b(open|show)\b"#, options: .regularExpression) != nil
        guard allowed else { return }
        if request.range(of: #"\b(?:don't|do not|never)\s+(?:open|show)\b"#, options: .regularExpression) != nil {
            allowed = false
        } else if request.range(of: #"\bnext\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b"#, options: .regularExpression) != nil {
            value = .clarification("Do you mean that day this week or next week?")
        } else if request.range(of: #"^\s*(?:please\s+)?(?:open|show)(?:\s+me)?\s+(?:that|it|this)(?:\s+(?:recipe|page|one))?\s*[.!?]?\s*$"#, options: .regularExpression) != nil {
            value = .clarification("Which recipe or meal-plan day would you like to open?")
        }
    }

    var canNavigate: Bool {
        lock.lock(); defer { lock.unlock() }
        if case .clarification = value { return false }
        return allowed
    }

    public func set(_ destination: WebDestination) {
        lock.lock(); defer { lock.unlock() }
        guard allowed else { return }
        switch value {
        case .none: value = .destination(destination)
        case .destination(let existing) where existing != destination:
            value = .clarification("Which one would you like me to open first?")
        default: break
        }
    }

    func clarify(_ message: String) {
        lock.lock(); defer { lock.unlock() }
        if allowed { value = .clarification(message) }
    }

    public func clear() {
        lock.lock(); defer { lock.unlock() }
        value = .none
        allowed = false
    }

    public func take() -> PendingWebNavigation {
        lock.lock(); defer { lock.unlock() }
        defer { value = .none; allowed = false }
        return value
    }
}

@Generable(description: "A saved recipe or meal-plan day to show in the browser, only when the user explicitly asks to open or show it.")
public struct OpenWebDestinationArguments: Sendable {
    @Guide(description: "recipe or meal_plan; never a URL")
    public var kind: String
    @Guide(description: "For recipe only: the real recipe name found in this conversation. Otherwise nil.")
    public var recipeName: String?
    @Guide(description: "For meal_plan only: today, tomorrow, a weekday name, or an exact YYYY-MM-DD date. Otherwise nil. Clarify ambiguous next Friday before calling.")
    public var day: String?
    @Guide(description: "For a weekday: 0 for this ISO week, 1 only for explicit next week. Otherwise nil.")
    public var weekOffset: Int?
}

public struct OpenWebDestinationTool: Tool {
    public let name = "openWebDestination"
    public let description = "Resolve a saved recipe or meal-plan day for an explicit open/show request. This records a target; it does not open a browser or change data. Never call for ordinary questions."
    private let client: KitchenOSClient
    private let store: PendingWebDestinationStore
    private let now: @Sendable () -> Date
    private let calendar: Calendar

    public init(client: KitchenOSClient, store: PendingWebDestinationStore,
                now: @escaping @Sendable () -> Date = { Date() },
                calendar: Calendar = WeekDate.isoCalendar()) {
        self.client = client; self.store = store; self.now = now; self.calendar = calendar
    }

    public func call(arguments: OpenWebDestinationArguments) async throws -> String {
        do { try Task.checkCancellation() }
        catch { store.clear(); throw error }
        guard store.canNavigate else {
            return "No navigation was recorded. Ask which recipe or day if the request is unclear; ordinary questions stay spoken."
        }
        do {
            let destination: WebDestination
            switch arguments.kind {
            case "recipe":
                guard let name = arguments.recipeName, arguments.day == nil, arguments.weekOffset == nil else {
                    return clarification("Which saved recipe would you like to open?")
                }
                let recipes = try await client.findRecipes(ingredient: "")
                let canonical = try RecipeNavigationResolver.resolve(name: name, recipes: recipes)
                destination = .recipe(name: canonical)
            case "meal_plan":
                guard arguments.recipeName == nil, let day = arguments.day else {
                    return clarification("Which meal-plan day would you like to open?")
                }
                let reference: WebDayReference
                switch day.lowercased() {
                case "today": reference = .today
                case "tomorrow": reference = .tomorrow
                default:
                    if let weekday = DayOfWeek(rawValue: day.lowercased()) {
                        reference = .weekday(weekday, weekOffset: arguments.weekOffset ?? 0)
                    } else {
                        reference = .exact(day)
                    }
                }
                destination = .mealPlan(date: try WebDayResolver.resolve(reference, now: now(), calendar: calendar))
            default: return clarification("Would you like to open a saved recipe or a meal-plan day?")
            }
            try Task.checkCancellation()
            store.set(destination)
            switch destination {
            case .recipe(let name): return "Ready to open \(name) in the browser after any required confirmation. It has not opened yet."
            case .mealPlan(let date): return "Ready to open the meal plan for \(date) in the browser after any required confirmation. It has not opened yet."
            }
        } catch RecipeNavigationError.ambiguous(let names) {
            return clarification("Which recipe do you mean: \(names.prefix(3).joined(separator: ", "))?")
        } catch RecipeNavigationError.missing {
            return clarification("I couldn't find that saved recipe. Which recipe would you like to open?")
        } catch is RecipeNavigationError {
            return clarification("Please give me the name of a saved recipe.")
        } catch is WebDayResolutionError {
            return clarification("Please give me a valid date, or say which day this week or next week.")
        } catch {
            store.clear()
            try Task.checkCancellation()
            throw error
        }
    }

    private func clarification(_ message: String) -> String {
        store.clarify(message)
        return message
    }
}
