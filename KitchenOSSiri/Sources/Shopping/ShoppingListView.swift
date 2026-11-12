import SwiftUI
import KitchenOSKit

struct ShoppingListView: View {
    var routedWeek: String? = nil
    var focusedRowID: String? = nil
    @State private var weekAnchor = Date()
    @State private var loadedWeek: String?
    @State private var saved: SavedShoppingList?
    @State private var preview: ShoppingPreview?
    @State private var status = ""
    @State private var isLoading = false
    @State private var isSaving = false
    @State private var details: [AppleItemDetail] = []
    private var client: KitchenOSClient { KitchenOSClient(config: .resolved()) }
    private var weekID: String { WeekDate.weekID(for: weekAnchor) }
    private var routeKey: String { (routedWeek ?? "") + ":" + (focusedRowID ?? "") }
    var body: some View {
        ScrollViewReader { reader in
            List {
                Section {
                    if !status.isEmpty { Text(status).foregroundStyle(.secondary) }
                    if routedWeek == nil {
                    Button("Preview shopping list") { Task { await runPreview() } }.disabled(isLoading || isSaving)
                    }
                    Button("Reload saved list") { Task { await loadSaved() } }.disabled(isLoading || isSaving)
                    #if os(macOS)
                    Button("Send shopping list to Reminders…") { AppRouter.shared.openIntegrationSettings(domain: .shopping, week: weekID) }
                    #endif
                }
                if let saved {
                    Section("Saved shopping list") {
                        ForEach(saved.rows.filter { !$0.id.isEmpty }) { row in
                            // Exact row IDs drive completion and focus; legacy rows have no identity and cannot be toggled.
                            VStack(alignment: .leading, spacing: 4) {
                                Button { Task { await toggle(row, document: saved) } } label: {
                                    Label(row.text, systemImage: row.completed ? "checkmark.circle.fill" : "circle")
                                        .strikethrough(row.completed)
                                        .frame(maxWidth: .infinity, minHeight: 44, alignment: .leading)
                                }
                                .buttonStyle(.plain)
                                .accessibilityLabel(row.text)
                                .accessibilityValue(row.completed ? "Completed" : "Incomplete")
                                .disabled(isSaving || loadedWeek != weekID || row.issue != nil || row.id.isEmpty)
                                if let issue = row.issue {
                                    Text(issue == "shopping_amount_changed" ? "Shopping amount changed — review this item in Apple integration on your Mac." : "This item needs identity review. Save the list explicitly before changing completion.")
                                        .font(.caption)
                                }
                                if let due = details.first(where: { $0.item.logicalID == row.id }), due.hasDueOverride {
                                    Text("Reminder due: \(due.dueOverride?.displayText ?? "No due date")").font(.caption)
                                }
                                if focusedRowID == row.id { Label("Linked item", systemImage: "link").font(.caption) }
                            }.id(row.id)
                        }
                        ForEach(Array(saved.rows.filter { $0.id.isEmpty }.enumerated()), id: \.offset) { _, row in
                            VStack(alignment: .leading) {
                                Text(row.text)
                                Text("Save this list to assign an identity before checking this item.").font(.caption)
                            }
                        }
                    }
                }
                if routedWeek == nil, let preview, preview.success {
                    Section("Preview — to buy") {
                        ForEach(Array((preview.lines ?? []).enumerated()), id: \.offset) { _, line in
                            if let amount = line.toBuy { HStack { Text(line.item); Spacer(); Text(amount.display) } }
                        }
                    }
                    Section("Preview — inventory matches") {
                        ForEach(Array((preview.lines ?? []).enumerated()), id: \.offset) { _, line in
                            if let amount = line.fromPantry { HStack { Text(line.item); Spacer(); Text(amount.display) } }
                        }
                    }
                    Button("Save preview as shopping list") { Task { await save(preview) } }.disabled(isSaving)
                }
            }
            .navigationTitle("Shopping list")
            .overlay { if isLoading { ProgressView() } }
            .toolbar {
                ToolbarItemGroup {
                    Button { shiftWeek(-1) } label: { Image(systemName: "chevron.left") }.accessibilityLabel("Previous week")
                    Text(WeekDate.weekRangeLabel(for: weekAnchor))
                    Button { shiftWeek(1) } label: { Image(systemName: "chevron.right") }.accessibilityLabel("Next week")
                }
            }
            .task(id: routeKey) {
                if let week = routedWeek, let date = WeekDate.date(forWeekID: week) { weekAnchor = date }
                await loadSaved()
                if let id = focusedRowID { reader.scrollTo(id, anchor: .center) }
            }
            .task(id: weekID) { await loadSaved() }
        }
    }
    private func shiftWeek(_ delta: Int) {
        weekAnchor = Calendar.current.date(byAdding: .day, value: delta * 7, to: weekAnchor) ?? weekAnchor
        preview = nil
    }
    private func loadSaved() async {
        let requestedWeek = weekID
        isLoading = true; defer { isLoading = false }
        do {
            let document = try await client.savedShoppingList(week: requestedWeek)
            guard weekID == requestedWeek else { return }
            saved = document; loadedWeek = requestedWeek; status = ""
            if let id = focusedRowID, routedWeek == requestedWeek, !document.rows.contains(where: { $0.id == id }) {
                status = "The linked item is no longer in this saved list. No item was recreated."
            }
            let values = try? await AppleIntegrationClient(client: client).items(domain: .shopping, week: requestedWeek)
            if weekID == requestedWeek { details = (values ?? []).sorted { $0.item.generation > $1.item.generation } }
        } catch {
            guard weekID == requestedWeek else { return }
            saved = nil; details = []; status = routedWeek == nil ? "No saved list is available. Preview this week, then save it when you’re ready." : "The saved list for this link is unavailable. Open Shopping list from the main screen to review the current week."
        }
    }
    private func toggle(_ row: SavedShoppingRow, document: SavedShoppingList) async {
        guard loadedWeek == weekID else { return }
        let requestedWeek = weekID
        isSaving = true; defer { isSaving = false }
        do {
            let result = try await client.completeShoppingRow(week: requestedWeek, rowID: row.id, completed: !row.completed, expectedHash: document.contentHash)
            if weekID == requestedWeek { saved = result; status = "" }
            #if os(macOS)
            AppleIntegrationCoordinator.shared.domainChanged()
            #endif
        } catch { status = "Completion wasn’t confirmed. Reload the saved list before trying again." }
    }
    private func runPreview() async {
        let requestedWeek = weekID
        isLoading = true; defer { isLoading = false }
        do {
            let value = try await client.previewShoppingList(week: requestedWeek)
            if weekID == requestedWeek { preview = value; status = value.success ? "Review the preview before saving." : value.error ?? "Couldn’t create preview." }
        } catch { status = "Couldn’t preview this week. Check your connection and try again." }
    }
    private func save(_ preview: ShoppingPreview) async {
        guard let items = preview.items else { return }
        let requestedWeek = weekID
        isSaving = true; defer { isSaving = false }
        do {
            try await client.confirmShoppingList(week: requestedWeek, itemsToBuy: items)
            if weekID == requestedWeek { self.preview = nil; await loadSaved() }
            #if os(macOS)
            AppleIntegrationCoordinator.shared.domainChanged()
            #endif
        } catch { status = "Couldn’t save the list. Check your connection and try again." }
    }
}
