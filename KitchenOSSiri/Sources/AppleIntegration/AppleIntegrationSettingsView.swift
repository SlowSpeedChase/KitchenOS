import SwiftUI
import KitchenOSKit

/// All Apple mutations remain behind the single Mac coordinator.
struct AppleIntegrationSettingsView: View {
    #if os(macOS)
    @StateObject private var controls = AppleIntegrationControls(coordinator: AppleIntegrationCoordinator.shared)
    @State private var domain: AppleDomain = .shopping
    @State private var weekAnchor = Date()
    @State private var destination = ""
    @State private var destinationName = ""
    @State private var details: [AppleItemDetail] = []
    @State private var conflicts: [AppleConflictDetail] = []
    @State private var detailError = ""
    @State private var pendingRemoval: AppleItemDetail?
    init(initialDomain: AppleDomain = .shopping, initialWeek: String? = nil) {
        _domain = State(initialValue: initialDomain)
        _weekAnchor = State(initialValue: initialWeek.flatMap { WeekDate.date(forWeekID: $0) } ?? Date())
    }
    private var week: String { WeekDate.weekID(for: weekAnchor) }
    private var api: AppleIntegrationClient { AppleIntegrationClient(client: KitchenOSClient(config: .resolved())) }
    var body: some View {
        Section("Apple integration") {
            Text(controls.message).textSelection(.enabled)
            if let status = controls.status {
                Text(status.report.lastSuccess.map { "Last successful sync: \($0)" } ?? "No successful sync yet")
                    .font(.caption).foregroundStyle(.secondary)
                HStack {
                    Button(status.connected ? "Refresh connection" : "Connect Apple integration") { run(.connect) }
                    Button("Sync now") { run(.sync) }.disabled(!status.connected || status.paused)
                    if status.connected {
                        Button(status.paused ? "Resume sync" : "Pause sync") { run(.setPaused(!status.paused, revision: status.settingsRevision)) }
                        Button("Disconnect") { run(.disconnect) }
                    }
                }
                Text("Connecting publishes nothing. Sending a week starts ongoing sync for that week. Archive a week to preserve its Apple items and stop syncing it.")
                    .font(.caption).foregroundStyle(.secondary)
            } else { Button("Read integration status") { Task { await controls.load() } } }
        }
        .disabled(controls.busy)
        Section("Send a week") {
            Picker("Items", selection: $domain) {
                Text("Shopping reminders").tag(AppleDomain.shopping)
                Text("Prep reminders").tag(AppleDomain.prep)
                Text("Cooking calendar").tag(AppleDomain.cooking)
            }
            Text("Full access: \((controls.permissions[domain] ?? .unknown).rawValue.replacingOccurrences(of: "_", with: " "))")
            Button(domain == .cooking ? "Allow Calendar access" : "Allow Reminders access") {
                Task { await controls.requestPermission(domain) }
            }
            Picker("Destination", selection: Binding(get: { destination }, set: { id in
                destination = id; AppleIntegrationCoordinator.shared.selectDestination(id, for: domain)
            })) {
                Text("Choose a destination").tag("")
                ForEach(controls.destinations[domain] ?? [], id: \.id) { value in Text(value.title).tag(value.id) }
            }
            Button("Refresh destinations") { Task { await controls.reloadDestinations(domain) } }
            TextField("New destination name", text: $destinationName)
            Button("Create destination") {
                Task { if let id = await controls.createDestination(destinationName, domain: domain) { destination = id; AppleIntegrationCoordinator.shared.selectDestination(id, for: domain); destinationName = "" } }
            }
            .disabled(destinationName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            DatePicker("Week containing", selection: $weekAnchor, displayedComponents: .date)
            Text(WeekDate.weekRangeLabel(for: weekAnchor))
            Button(domain == .cooking ? "Sync cooking calendar for this week" : domain == .shopping ? "Send shopping list for this week" : "Send prep tasks for this week") {
                run(.activate(domain, week: week, destination: destination))
            }
            .disabled(destination.isEmpty || !(controls.destinations[domain] ?? []).contains(where: { $0.id == destination }) || controls.permissions[domain] != .authorized || controls.status?.paused == true)
            if controls.status?.scopes.contains(where: { $0.domain == domain && $0.week == week && $0.status != .archived }) == true {
                Button("Archive this week’s sync") { run(.archive(domain, week: week)) }
            }
        }
        .disabled(controls.busy || !AppleIntegrationCoordinator.shared.isLocalServer)
        .onChange(of: domain) { _, value in destination = AppleIntegrationCoordinator.shared.preferredDestination(for: value) ?? "" }
        Section("Review Apple changes") {
            if !detailError.isEmpty { Text(detailError) }
            ForEach(conflicts) { conflict in
                VStack(alignment: .leading, spacing: 6) {
                    Text(conflict.label).font(.headline)
                    Text(conflict.source.title)
                    Button("Open linked item") { Task { await AppRouter.shared.open(.item(token: conflict.token)) } }
                    Text("KitchenOS: \(conflict.value(apple: false))")
                    Text("Apple: \(conflict.value(apple: true))")
                    if let explanation = conflict.shoppingExplanation {
                        Text(explanation).font(.caption)
                    }
                    if let explanation = conflict.retiredUnavailableExplanation {
                        Text(explanation).font(.caption)
                    }
                    ForEach(conflict.choices, id: \.rawValue) { choice in
                        Button(conflict.choiceLabel(choice)) {
                            Task { await controls.resolve(conflict, choice: choice); await loadDetails() }
                        }
                    }
                }.padding(.vertical, 4)
            }
            if conflicts.isEmpty { Text("No conflicts to review.").foregroundStyle(.secondary) }
        }.disabled(controls.busy || controls.status?.connected != true || controls.status?.paused == true)
        Section("Exported items for this week") {
            Text("Remove deletes only the selected owned Apple item after checking its identity. Restore creates a replacement export for a suppressed item.").font(.caption)
            ForEach(details) { detail in
                VStack(alignment: .leading) {
                    Text(detail.item.title)
                    Text("\(detail.item.state.rawValue.capitalized) · Export \(detail.item.generation)").font(.caption)
                    HStack {
                        if detail.item.state == .suppressed {
                            Button("Restore Apple item") { run(.restore(detail.id, revision: detail.item.revision)) }
                        }
                        if detail.item.locator != nil {
                            Button("Remove owned Apple item", role: .destructive) { pendingRemoval = detail }
                        } else {
                            Text("Apple item location is unavailable. Sync and review its identity before removing it.").font(.caption)
                        }
                    }
                }
            }
        }
        .disabled(controls.busy || controls.status?.connected != true || controls.status?.paused == true)
        .confirmationDialog("Remove this owned Apple item?", isPresented: Binding(get: { pendingRemoval != nil }, set: { if !$0 { pendingRemoval = nil } }), titleVisibility: .visible) {
            if let detail = pendingRemoval {
                Button("Remove \(detail.item.title)", role: .destructive) {
                    pendingRemoval = nil
                    run(.removeOwned([AppleOwnedSelection(token: detail.id, revision: detail.item.revision)]))
                }
            }
            Button("Cancel", role: .cancel) { pendingRemoval = nil }
        }
        .task { destination = AppleIntegrationCoordinator.shared.preferredDestination(for: domain) ?? ""; await controls.load() }
        .task(id: domain.rawValue + week) { await loadDetails() }
    }
    private func run(_ command: AppleIntegrationCommand) {
        Task { await controls.run(command); await loadDetails() }
    }
    private func loadDetails() async {
        let selectedDomain = domain; let selectedWeek = week
        do {
            let result = try await api.items(domain: selectedDomain, week: selectedWeek)
            var loaded: [AppleConflictDetail] = []
            let status = try await api.status()
            for summary in status.conflicts { loaded.append(try await api.conflict(summary.conflictID)) }
            guard domain == selectedDomain, week == selectedWeek else { return }
            details = result; conflicts = loaded; detailError = ""
        } catch { detailError = "Couldn’t read item details. Refresh the connection and try again."; details = []; conflicts = [] }
    }
    #else
    init(initialDomain: AppleDomain = .shopping, initialWeek: String? = nil) {}
    @State private var status: IntegrationStatus?
    @State private var message = "Read Apple integration status from your server Mac."
    var body: some View {
        Section("Apple integration") {
            Text(message)
            if let status {
                Text(AppleIntegrationControls.summary(status.report, connected: status.connected, paused: status.paused))
                Text(status.report.lastSuccess.map { "Last successful sync: \($0)" } ?? "No successful sync yet")
                ForEach(status.conflicts, id: \.conflictID) { conflict in Text("Review \(conflict.field.replacingOccurrences(of: "_", with: " ")) on your Mac.") }
            }
            Text("Use KitchenOS on the server Mac to grant access, choose destinations, send a week, or resolve changes.").font(.caption)
            Button("Refresh Apple status") { Task { await load() } }
        }.task { await load() }
    }
    private func load() async {
        do { status = try await AppleIntegrationClient(client: KitchenOSClient(config: .resolved())).status(); message = "Apple sync runs on your server Mac." }
        catch { status = nil; message = "Couldn’t read Apple status. Check your connection and try again." }
    }
    #endif
}
