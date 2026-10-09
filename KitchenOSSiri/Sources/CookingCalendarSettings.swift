import SwiftUI
import KitchenOSKit

#if os(macOS)

@MainActor
final class CookingCalendarSync: ObservableObject {
    static let shared = CookingCalendarSync()
    @Published var calendars: [AppleDestination] = []
    @Published var message = "Connect Calendar to find days that suit cooking."
    @Published var working = false
    private let defaults = UserDefaults.standard
    private var refreshAgain = false
    private var pendingExclusions: Set<UUID>?
    private var connected: Bool { defaults.bool(forKey: "cookingCalendar.connected") }
    private var coordinator: AppleIntegrationCoordinator { .shared }
    private var store: any AppleItemStore { coordinator.store }

    func connect() async {
        guard coordinator.isLocalServer else {
            message = "Connect Calendar on the Mac running your KitchenOS server, using its localhost connection."
            return
        }
        do {
            guard try await coordinator.requestAccess(for: .cooking) == .authorized else {
                message = "Allow Calendar access in System Settings, then connect again."
                return
            }
            await loadCalendars()
            message = "Choose your commitments calendar and Time Blocking, then save."
        } catch { message = "Couldn’t connect Calendar. Check Calendar permission and try again." }
    }
    func loadCalendars() async {
        guard coordinator.isLocalServer, store.authorization(for: .cooking) == .authorized else { calendars = []; return }
        calendars = (try? await store.availabilityCalendars()) ?? []
    }
    func save(firmID: String, flexibleID: String) async {
        guard !working, !firmID.isEmpty, !flexibleID.isEmpty, firmID != flexibleID else {
            message = "Choose two different calendars."; return
        }
        if firmID != defaults.string(forKey: "cookingCalendar.firm") || flexibleID != defaults.string(forKey: "cookingCalendar.flexible") {
            defaults.set(true, forKey: "cookingCalendar.clearPending")
        }
        defaults.set(firmID, forKey: "cookingCalendar.firm")
        defaults.set(flexibleID, forKey: "cookingCalendar.flexible")
        defaults.set(true, forKey: "cookingCalendar.connected")
        // Sync the already active bridge scopes first, then calculate
        // availability using its fresh set of linked cooking tokens.
        await coordinator.refresh(trigger: .foreground)
    }
    func disconnect() async {
        guard !working else { return }
        defaults.set(false, forKey: "cookingCalendar.connected")
        defaults.set(true, forKey: "cookingCalendar.clearPending")
        await refresh()
    }
    private func clear(_ client: KitchenOSClient) async throws {
        // Keep this set until BOTH representations are cleared, including on retry.
        defaults.set(true, forKey: "cookingCalendar.clearPending")
        try await client.syncCookingAvailability(days: [:])
        try await client.clearPlanningCalendar()
        defaults.set(false, forKey: "cookingCalendar.clearPending")
    }
    func refresh(excludingOwnedTokens: Set<UUID> = []) async {
        guard coordinator.isLocalServer else {
            message = "Calendar sync runs on the server Mac using a localhost connection."; return
        }
        guard !working else {
            refreshAgain = true
            pendingExclusions = excludingOwnedTokens
            return
        }
        guard connected || defaults.bool(forKey: "cookingCalendar.clearPending") else { return }
        working = true
        defer {
            working = false
            if refreshAgain {
                refreshAgain = false
                let next = pendingExclusions ?? excludingOwnedTokens
                pendingExclusions = nil
                Task { await self.refresh(excludingOwnedTokens: next) }
            }
        }
        let config = KitchenOSConfig.resolved()
        let client = KitchenOSClient(config: config)
        do {
            if defaults.bool(forKey: "cookingCalendar.clearPending") { try await clear(client) }
            guard connected else { message = "Calendar disconnected. Calendar details cleared."; return }
            await loadCalendars()
            let firmID = defaults.string(forKey: "cookingCalendar.firm") ?? ""
            let flexibleID = defaults.string(forKey: "cookingCalendar.flexible") ?? ""
            guard store.authorization(for: .cooking) == .authorized, firmID != flexibleID,
                  calendars.contains(where: { $0.id == firmID }), calendars.contains(where: { $0.id == flexibleID }) else {
                try await clear(client)
                message = "Choose two different calendars. If they’re missing, reconnect Calendar."; return
            }
            let snapshot: PlanningCalendarSnapshot
            do { snapshot = try await store.availabilitySnapshot(firmID: firmID, flexibleID: flexibleID, excludingOwnedTokens: excludingOwnedTokens) }
            catch { try await clear(client); throw error }
            guard coordinator.isLocalServer, KitchenOSConfig.resolved().baseURL == config.baseURL,
                  connected, firmID == defaults.string(forKey: "cookingCalendar.firm"), flexibleID == defaults.string(forKey: "cookingCalendar.flexible") else {
                refreshAgain = true; return
            }
            guard store.authorization(for: .cooking) == .authorized else { try await clear(client); return }
            try await client.syncCookingAvailability(days: snapshot.cookingAvailability())
            guard coordinator.isLocalServer, KitchenOSConfig.resolved().baseURL == config.baseURL else {
                defaults.set(true, forKey: "cookingCalendar.clearPending"); return
            }
            try await client.syncPlanningCalendar(snapshot)
            guard coordinator.isLocalServer, KitchenOSConfig.resolved().baseURL == config.baseURL else {
                defaults.set(true, forKey: "cookingCalendar.clearPending"); return
            }
            // Permission may have changed while either request was suspended.
            guard store.authorization(for: .cooking) == .authorized else { try await clear(client); return }
            message = "Availability updated at \(Date().formatted(date: .omitted, time: .shortened))."
        } catch KitchenOSError.http(404) {
            message = "Update the KitchenOS server to enable the detailed calendar view."
        } catch { message = "Couldn’t update availability. Check the KitchenOS connection and refresh." }
    }
}

struct CookingCalendarSettings: View {
    @ObservedObject private var sync = CookingCalendarSync.shared
    @State private var firmID = UserDefaults.standard.string(forKey: "cookingCalendar.firm") ?? ""
    @State private var flexibleID = UserDefaults.standard.string(forKey: "cookingCalendar.flexible") ?? ""

    var body: some View {
        Section("Cooking opportunities") {
            Text("From noon onward: commitments mean keep food easy; Time Blocking means cooking may still fit.")
                .font(.caption)
            Button("Connect Calendar") { Task { await sync.connect() } }
            if !sync.calendars.isEmpty {
                Picker("Commitments (iCloud)", selection: $firmID) {
                    Text("Choose a calendar").tag("")
                    ForEach(sync.calendars, id: \.id) { c in
                        Text(c.title).tag(c.id)
                    }
                }
                Picker("Flexible (Time Blocking)", selection: $flexibleID) {
                    Text("Choose a calendar").tag("")
                    ForEach(sync.calendars, id: \.id) { c in
                        Text(c.title).tag(c.id)
                    }
                }
                Button("Save calendars and refresh") { Task { await sync.save(firmID: firmID, flexibleID: flexibleID) } }
                Button("Refresh availability") { Task { await AppleIntegrationCoordinator.shared.refresh(trigger: .foreground) } }
            }
            Button("Disconnect Calendar") { Task { await sync.disconnect() } }
            Text(sync.message).font(.caption).accessibilityAddTraits(.updatesFrequently)
            Text("Event names and times from these calendars are shared with your local KitchenOS server. Keep this app open for updates every five minutes. After six hours without an update, availability shows as unknown.")
                .font(.caption).foregroundStyle(.secondary)
        }
        .disabled(sync.working)
        .task { await sync.loadCalendars() }
    }
}

#endif
