import SwiftUI
import KitchenOSKit

/// Generate a pantry-aware shopping list for a week, then confirm (writes the
/// shopping-list markdown to the vault).
struct ShoppingListView: View {
    @State private var weekAnchor = Date()
    @State private var preview: ShoppingPreview?
    @State private var status = ""
    @State private var isLoading = false
    @State private var confirmNote = ""

    private var client: KitchenOSClient { KitchenOSClient(config: .resolved()) }
    private var weekID: String { WeekDate.weekID(for: weekAnchor) }

    private var toBuyLines: [ShoppingLine] {
        (preview?.lines ?? []).filter { $0.toBuy != nil }
    }
    private var fromPantryLines: [ShoppingLine] {
        (preview?.lines ?? []).filter { $0.fromPantry != nil }
    }

    var body: some View {
        List {
            Section {
                Button("Preview shopping list") { Task { await runPreview() } }
                    .disabled(isLoading)
                if !status.isEmpty { Text(status).font(.caption).foregroundStyle(.secondary) }
                if !confirmNote.isEmpty { Text(confirmNote).font(.caption).foregroundStyle(.green) }
            }

            if let p = preview, p.success {
                if !toBuyLines.isEmpty {
                    Section("To buy (\(toBuyLines.count))") {
                        ForEach(toBuyLines, id: \.item) { line in
                            lineRow(line, amount: line.toBuy)
                        }
                    }
                }
                if !fromPantryLines.isEmpty {
                    Section("Already in pantry (\(fromPantryLines.count))") {
                        ForEach(fromPantryLines, id: \.item) { line in
                            lineRow(line, amount: line.fromPantry).foregroundStyle(.secondary)
                        }
                    }
                }
                Section {
                    Button("Confirm & save list") { Task { await confirm(p) } }
                        .disabled(p.items?.isEmpty != false)
                }
            }
        }
        .navigationTitle("Shopping List")
        .overlay { if isLoading { ProgressView() } }
        .toolbar {
            ToolbarItemGroup {
                Button { shiftWeek(-1) } label: { Image(systemName: "chevron.left") }
                Text(weekID).font(.callout.monospaced())
                Button { shiftWeek(1) } label: { Image(systemName: "chevron.right") }
            }
        }
    }

    private func lineRow(_ line: ShoppingLine, amount: ShoppingAmount?) -> some View {
        HStack {
            Text(line.item)
            Spacer()
            if let a = amount, !a.display.isEmpty {
                Text(a.display).foregroundStyle(.secondary)
            }
            if line.warning != nil {
                Image(systemName: "exclamationmark.triangle").foregroundStyle(.orange)
            }
        }
    }

    private func shiftWeek(_ delta: Int) {
        weekAnchor = Calendar.current.date(byAdding: .day, value: delta * 7, to: weekAnchor) ?? weekAnchor
        preview = nil; confirmNote = ""
    }

    private func runPreview() async {
        isLoading = true; status = ""; confirmNote = ""
        defer { isLoading = false }
        do {
            let p = try await client.previewShoppingList(week: weekID)
            preview = p
            if !p.success { status = p.error ?? "Could not generate list." }
        } catch { status = "Error: \(error)" }
    }

    private func confirm(_ p: ShoppingPreview) async {
        guard let items = p.items else { return }
        do {
            try await client.confirmShoppingList(week: weekID, itemsToBuy: items)
            confirmNote = "Saved \(items.count) items to the shopping list."
        } catch { status = "Confirm failed: \(error)" }
    }
}
