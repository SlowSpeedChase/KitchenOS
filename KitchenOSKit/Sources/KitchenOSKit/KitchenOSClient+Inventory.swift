import Foundation

public extension KitchenOSClient {
    // MARK: Inventory

    func inventory(category: String? = nil, location: String? = nil) async throws -> [InventoryItem] {
        var comps = URLComponents(url: baseURL.appendingPathComponent("/api/inventory"),
                                  resolvingAgainstBaseURL: false)!
        var q: [URLQueryItem] = []
        if let category { q.append(URLQueryItem(name: "category", value: category)) }
        if let location { q.append(URLQueryItem(name: "location", value: location)) }
        comps.queryItems = q.isEmpty ? nil : q
        return try await getJSON(comps.url!)
    }

    func addInventory(_ items: [InventoryItem]) async throws {
        try await postJSON(path: "/api/inventory/add", body: ["items": items])
    }

    func removeInventory(name: String, location: String? = nil) async throws {
        var body: [String: String] = ["name": name]
        if let location { body["location"] = location }
        try await postJSON(path: "/api/inventory/remove", body: body)
    }

    func updateInventory(name: String, quantity: Double, location: String? = nil) async throws {
        var body: [String: Any] = ["name": name, "quantity": quantity]
        if let location { body["location"] = location }
        try await postRawJSON(path: "/api/inventory/update", object: body)
    }

    // MARK: Pantry

    func pantry() async throws -> [PantryItem] {
        struct Wrapper: Decodable { let items: [PantryItem] }
        let url = baseURL.appendingPathComponent("/api/pantry")
        let wrapped: Wrapper = try await getJSON(url)
        return wrapped.items
    }

    // MARK: Shopping list

    func previewShoppingList(week: String, usePantry: Bool = true) async throws -> ShoppingPreview {
        try await postDecoding(path: "/api/shopping-list/preview",
                               object: ["week": week, "use_pantry": usePantry])
    }

    @discardableResult
    func confirmShoppingList(week: String, itemsToBuy: [String],
                             decisions: [[String: Any]] = []) async throws -> Bool {
        try await postRawJSON(path: "/api/shopping-list/confirm",
                              object: ["week": week, "items_to_buy": itemsToBuy, "decisions": decisions])
        return true
    }
}
