import Foundation

public struct AppleItemDetail: Decodable, Sendable, Identifiable {
    public var id: UUID { item.token }
    public let item: SyncItem
    public let hasDueOverride: Bool
    public let dueOverride: DueValue?
    enum CodingKeys: String, CodingKey { case hasDueOverride = "has_due_override", dueOverride = "due_override" }
    public init(from decoder: Decoder) throws {
        item = try SyncItem(from: decoder)
        let c = try decoder.container(keyedBy: CodingKeys.self)
        hasDueOverride = try c.decode(Bool.self, forKey: .hasDueOverride)
        dueOverride = try c.decodeIfPresent(DueValue.self, forKey: .dueOverride)
    }
}
public struct AppleConflictDetail: Decodable, Sendable, Identifiable {
    public var id: UUID { conflictID }
    public let conflictID: UUID
    public let token: UUID
    public let field: String
    public let revision: Int
    public let source: ConflictSource
    public let apple: ConflictObservation?
    public let choices: [AppleConflictChoice]
    public let shoppingDemand: ShoppingDemand?
    enum CodingKeys: String, CodingKey {
        case token, field, revision, source, apple, choices
        case conflictID = "conflict_id", shoppingDemand = "shopping_demand"
    }
    public struct ShoppingDemand: Decodable, Sendable {
        public enum State: String, Decodable, Sendable { case active, removed }
        public let state: State
        public let text: String?
        enum CodingKeys: String, CodingKey { case state, text }
        public init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            state = try c.decode(State.self, forKey: .state)
            text = try c.decodeIfPresent(String.self, forKey: .text)
            guard state == .removed ? text == nil : text?.isEmpty == false else {
                throw DecodingError.dataCorruptedError(forKey: .text, in: c, debugDescription: "Generated demand must name an active item or an explicit removal")
            }
        }
    }
    public func choiceLabel(_ choice: AppleConflictChoice) -> String {
        if choice == .keepManual && field.hasPrefix("shopping_") {
            return "Keep as a separate manual shopping item"
        }
        if choice == .keepKitchenOS && field.hasPrefix("shopping_") {
            if shoppingDemand?.state == .removed { return "Remove item from shopping list" }
            if field == "shopping_amount_changed" { return "Accept quantity and reopen" }
            if field == "shopping_identity_changed" { return "Restore ingredient and reopen" }
        }
        return choice.label
    }
    public var shoppingExplanation: String? {
        guard field.hasPrefix("shopping_"), let demand = shoppingDemand else { return nil }
        if demand.state == .removed {
            return "This item is no longer needed by the generated list. Removing it retires its Apple link; unchanged incomplete reminders may be removed, and completed reminders stay as history. Keeping it as manual preserves the edited item and its completion."
        }
        return "Accepting the generated item replaces the edited text and reopens this item. Keeping it as manual preserves its text and completion under a new identity."
    }
    public struct ConflictSource: Decodable, Sendable { public let title: String; public let fields: [String: AppleDetailValue] }
    public struct ConflictObservation: Decodable, Sendable { public let title: String?; public let fields: [String: AppleDetailValue] }
    public var label: String {
        switch field {
        case "recovery": return "Previous sync values are unavailable"
        case "source_recovery": return "A KitchenOS source change could not be recovered safely"
        case "shopping_amount_changed": return "Shopping amount changed"
        case "shopping_identity_changed": return "Shopping item changed"
        case "completed": return "Completion changed"
        case "due": return "Due date changed"
        case "start": return "Cooking time changed"
        case "duration_minutes": return "Cooking duration changed"
        default: return "Item needs review"
        }
    }
    public func value(apple useApple: Bool) -> String {
        guard let fields = useApple ? apple?.fields : source.fields else { return "Unavailable" }
        if field.hasPrefix("shopping_") {
            if useApple { return apple?.title ?? "Unavailable" }
            guard let demand = shoppingDemand else { return source.title }
            let generated = demand.state == .removed ? "No longer needed" : demand.text ?? "Unavailable"
            return "Edited list item: \(source.title)\nGenerated demand: \(generated)"
        }
        if field == "recovery" || field == "source_recovery" {
            // Whole-item recovery can import every observed field. Equal titles
            // must never conceal different completion, due or cooking values.
            // Use both sides' keys so an absent value differs from explicit null.
            let keys = Set(source.fields.keys).union(apple.map { Array($0.fields.keys) } ?? []).sorted()
            guard !keys.isEmpty else { return "No recorded field values" }
            let labels = ["completed": "Completion", "due": "Due date", "start": "Start time",
                          "duration_minutes": "Duration (minutes)", "timezone": "Timezone"]
            return keys.map { key in
                let label = labels[key] ?? key.replacingOccurrences(of: "_", with: " ").capitalized
                return "\(label): \(fields[key]?.displayText ?? "Unavailable")"
            }.joined(separator: "\n")
        }
        return fields[field]?.displayText ?? (useApple ? apple?.title : source.title) ?? "Unavailable"
    }
}
public extension DueValue {
    var displayText: String { [date, time, timezone].compactMap { $0 }.joined(separator: " · ") }
}
public extension AppleConflictChoice {
    var label: String {
        switch self {
        case .keepKitchenOS: return "Keep KitchenOS value"
        case .keepApple: return "Keep Apple value"
        case .keepManual: return "Keep Apple item separate"
        case .restore: return "Restore KitchenOS item"
        }
    }
}

/// Evidence can contain unsupported Apple values; display them without treating them as valid writes.
public indirect enum AppleDetailValue: Decodable, Sendable {
    case string(String), number(Double), bool(Bool), object([String: AppleDetailValue]), array([AppleDetailValue]), null
    public init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .null }
        else if let value = try? c.decode(Bool.self) { self = .bool(value) }
        else if let value = try? c.decode(String.self) { self = .string(value) }
        else if let value = try? c.decode(Double.self) { self = .number(value) }
        else if let value = try? c.decode([String: AppleDetailValue].self) { self = .object(value) }
        else { self = .array(try c.decode([AppleDetailValue].self)) }
    }
    public var displayText: String {
        switch self {
        case let .string(value): return value
        case let .number(value): return value.formatted()
        case let .bool(value): return value ? "Completed" : "Incomplete"
        case .null: return "None"
        case let .object(value): return value.keys.sorted().map { "\($0): \(value[$0]!.displayText)" }.joined(separator: " · ")
        case let .array(value): return value.map(\.displayText).joined(separator: ", ")
        }
    }
}
