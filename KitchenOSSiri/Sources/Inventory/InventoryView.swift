import SwiftUI
import KitchenOSKit

/// Current inventory, grouped by category. Add / adjust quantity / remove.
struct InventoryView: View {
    @State private var items: [InventoryItem] = []
    @State private var status = ""
    @State private var isLoading = false
    @State private var showingAdd = false

    private var client: KitchenOSClient { KitchenOSClient(config: .resolved()) }

    private var grouped: [(category: String, items: [InventoryItem])] {
        Dictionary(grouping: items, by: \.category)
            .map { (category: $0.key,
                    items: $0.value.sorted {
                        ($0.expiryRank, $0.name) < ($1.expiryRank, $1.name)
                    }) }
            .sorted { $0.category < $1.category }
    }

    var body: some View {
        List {
            if items.isEmpty, !isLoading {
                Text(status.isEmpty ? "Inventory is empty." : status).foregroundStyle(.secondary)
            }
            ForEach(grouped, id: \.category) { group in
                Section(group.category.capitalized) {
                    ForEach(group.items) { item in
                        row(item)
                    }
                }
            }
        }
        .navigationTitle("Inventory")
        .overlay { if isLoading { ProgressView() } }
        .toolbar {
            ToolbarItem {
                Button { showingAdd = true } label: { Image(systemName: "plus") }
            }
        }
        .sheet(isPresented: $showingAdd) {
            InventoryAddSheet { newItem in
                Task { await add(newItem) }
            }
        }
        .task { await load() }
        .refreshable { await load() }
    }

    private func row(_ item: InventoryItem) -> some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text(item.name)
                Text(item.inventorySecondaryLine)
                    .font(.caption).foregroundStyle(.secondary)
                Text(item.location)
                    .font(.caption2).foregroundStyle(.tertiary)
            }
            Spacer()
            Stepper(value: Binding(
                get: { item.quantity },
                set: { newQty in
                    Task {
                        if newQty <= 0 {
                            await remove(item)
                        } else {
                            await update(item, quantity: newQty)
                        }
                    }
                }
            ), in: 0...999, step: 1) {
                Text("\(formatQty(item.quantity)) \(item.unit)")
                    .font(.callout).monospacedDigit()
            }
            .labelsHidden()
            Text("\(formatQty(item.quantity)) \(item.unit)")
                .font(.callout).foregroundStyle(.secondary)
            Button(role: .destructive) {
                Task { await remove(item) }
            } label: {
                Image(systemName: "trash")
            }
            .buttonStyle(.borderless)
            .tint(.red)
            .help("Remove from inventory")
        }
        .swipeActions {
            Button(role: .destructive) {
                Task { await remove(item) }
            } label: { Label("Remove", systemImage: "trash") }
        }
    }

    private func formatQty(_ q: Double) -> String {
        q == q.rounded() ? String(Int(q)) : String(format: "%.2g", q)
    }

    // MARK: - Network

    private func load() async {
        isLoading = true
        defer { isLoading = false }
        do { items = try await client.inventory() }
        catch { status = "Error: \(error)" }
    }

    private func add(_ item: NewInventoryItem) async {
        do { try await client.addInventory([item]); await load() }
        catch { status = "Add failed: \(error)" }
    }

    private func update(_ item: InventoryItem, quantity: Double) async {
        do {
            try await client.updateInventory(name: item.name, quantity: quantity, location: item.location)
            await load()
        } catch { status = "Update failed: \(error)" }
    }

    private func remove(_ item: InventoryItem) async {
        do { try await client.removeInventory(name: item.name, location: item.location); await load() }
        catch { status = "Remove failed: \(error)" }
    }
}

/// Sheet to add a new inventory item.
private struct InventoryAddSheet: View {
    let onAdd: (NewInventoryItem) -> Void
    @Environment(\.dismiss) private var dismiss

    @State private var name = ""
    @State private var quantity = 1.0
    @State private var unit = "ct"
    @State private var category = "other"
    // nil = Auto. This MUST default to nil: a pre-selected shelf the user never
    // touched used to be sent as an explicit location, which the server records as
    // a placement you confirmed — so app-added rows could never show the unsure
    // marker that /review and Inventory.md show. Only a deliberate pick is explicit.
    @State private var location: String? = nil

    private let categories = ["produce", "dairy", "meat", "seafood", "pantry",
                              "frozen", "bakery", "beverages", "household", "other"]
    private let locations = ["fridge", "freezer", "pantry", "counter", "other"]

    var body: some View {
        NavigationStack {
            Form {
                TextField("Name", text: $name)
                HStack {
                    Text("Quantity")
                    Spacer()
                    TextField("Qty", value: $quantity, format: .number).frame(width: 60)
                    TextField("Unit", text: $unit).frame(width: 60)
                }
                Picker("Category", selection: $category) {
                    ForEach(categories, id: \.self) { Text($0.capitalized).tag($0) }
                }
                Picker("Location", selection: $location) {
                    Text("Auto").tag(String?.none)
                    ForEach(locations, id: \.self) { Text($0.capitalized).tag(String?.some($0)) }
                }
                if location == nil {
                    Text("Auto files it from your storage rules, and marks it unsure if there's no rule yet — so you get asked instead of it guessing silently.")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
            }
            .navigationTitle("Add Item")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Add") {
                        onAdd(NewInventoryItem(name: name, quantity: quantity, unit: unit,
                                               category: category, location: location,
                                               source: "manual"))
                        dismiss()
                    }
                    .disabled(name.trimmingCharacters(in: .whitespaces).isEmpty)
                }
            }
        }
        .frame(minWidth: 360, minHeight: 320)
    }
}
