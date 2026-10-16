import SwiftUI
import EventKit
import KitchenOSKit

#if os(macOS)

@MainActor
final class CookingCalendarSync: ObservableObject {
    static let shared = CookingCalendarSync()
    @Published var calendars: [EKCalendar] = []
    @Published var message = "Connect Calendar to find days that suit cooking."
    @Published var working = false
    private let store = EKEventStore()
    private let defaults = UserDefaults.standard
    private var connected: Bool { defaults.bool(forKey: "cookingCalendar.connected") }

    private var isLocalServer: Bool {
        ["localhost", "127.0.0.1", "::1", "[::1]"].contains(KitchenOSConfig.resolved().baseURL.host ?? "")
    }

    func connect() async {
        guard isLocalServer else {
            message = "Connect Calendar on the Mac running your KitchenOS server, using its localhost connection."
            return
        }
        do {
            guard try await store.requestFullAccessToEvents() else {
                message = "Allow Calendar access in System Settings, then connect again."
                return
            }
            calendars = store.calendars(for: .event)
            message = "Choose your commitments calendar and Time Blocking, then save."
        } catch {
            message = "Couldn’t connect Calendar. Check Calendar permission and try again."
        }
    }

    func loadCalendars() {
        if EKEventStore.authorizationStatus(for: .event) == .fullAccess {
            calendars = store.calendars(for: .event)
        }
    }

    func save(firmID: String, flexibleID: String) async {
        guard !working, !firmID.isEmpty, !flexibleID.isEmpty, firmID != flexibleID else {
            message = "Choose two different calendars."
            return
        }
        if firmID != defaults.string(forKey: "cookingCalendar.firm") || flexibleID != defaults.string(forKey: "cookingCalendar.flexible") {
            defaults.set(true, forKey: "cookingCalendar.clearPending")
        }
        defaults.set(firmID, forKey: "cookingCalendar.firm")
        defaults.set(flexibleID, forKey: "cookingCalendar.flexible")
        defaults.set(true, forKey: "cookingCalendar.connected")
        await refresh()
    }

    func disconnect() async {
        guard !working else { return }
        defaults.set(false, forKey: "cookingCalendar.connected")
        // Retry clearing on the next refresh if the server is temporarily offline.
        defaults.set(true, forKey: "cookingCalendar.clearPending")
        await refresh()
    }

    func run() async {
        while !Task.isCancelled {
            await refresh()
            do { try await Task.sleep(for: .seconds(300)) } catch { return }
        }
    }

    func refresh() async {
        guard isLocalServer else {
            message = "Calendar sync runs on the server Mac using a localhost connection."
            return
        }
        guard !working else { return }
        guard connected || defaults.bool(forKey: "cookingCalendar.clearPending") else { return }
        working = true
        defer { working = false }
        let client = KitchenOSClient(config: .resolved())
        do {
            if defaults.bool(forKey: "cookingCalendar.clearPending") {
                try await client.syncCookingAvailability(days: [:])
                try await client.clearPlanningCalendar()
                defaults.set(false, forKey: "cookingCalendar.clearPending")
            }
            if !connected {
                message = "Calendar disconnected. Calendar details cleared."
                return
            }
            loadCalendars()
            let firmID = defaults.string(forKey: "cookingCalendar.firm") ?? ""
            let flexibleID = defaults.string(forKey: "cookingCalendar.flexible") ?? ""
            guard EKEventStore.authorizationStatus(for: .event) == .fullAccess,
                  firmID != flexibleID,
                  let firm = calendars.first(where: { $0.calendarIdentifier == firmID }),
                  let flexible = calendars.first(where: { $0.calendarIdentifier == flexibleID }) else {
                defaults.set(true, forKey: "cookingCalendar.clearPending")
                try await client.syncCookingAvailability(days: [:])
                try await client.clearPlanningCalendar()
                defaults.set(false, forKey: "cookingCalendar.clearPending")
                message = "Choose two different calendars. If they’re missing, reconnect Calendar."
                return
            }
            var calendar = Calendar(identifier: .gregorian)
            calendar.timeZone = .current
            let start = calendar.startOfDay(for: Date())
            guard let end = calendar.date(byAdding: .day, value: 35, to: start) else { return }
            let predicate = store.predicateForEvents(withStart: start, end: end, calendars: [firm, flexible])
            let generatedAt = Date()
            let sourceEvents = store.events(matching: predicate).filter {
                $0.status != .canceled && $0.availability != .free &&
                !($0.attendees?.contains(where: { $0.isCurrentUser && $0.participantStatus == .declined }) ?? false)
            }
            let events = sourceEvents.map { CookingCalendarEvent(start: $0.startDate, end: $0.endDate,
                                         flexible: $0.calendar.calendarIdentifier == flexibleID) }
            let detailedEvents = try sourceEvents.map { event in
                try PlanningCalendarEvent(calendarID: event.calendar.calendarIdentifier,
                    eventID: event.calendarItemExternalIdentifier ?? event.calendarItemIdentifier,
                    title: event.title ?? "Untitled event", start: event.startDate, end: event.endDate,
                    allDay: event.isAllDay, flexible: event.calendar.calendarIdentifier == flexibleID, timezone: calendar.timeZone)
            }
            let formatter = DateFormatter()
            formatter.calendar = calendar
            formatter.locale = Locale(identifier: "en_US_POSIX")
            formatter.timeZone = calendar.timeZone
            formatter.dateFormat = "yyyy-MM-dd"
            var days: [String: CookingOpportunity] = [:]
            for offset in 0..<35 {
                guard let day = calendar.date(byAdding: .day, value: offset, to: start) else { continue }
                days[formatter.string(from: day)] = CookingOpportunity.classify(day: day, events: events, calendar: calendar)
            }
            let detailed = try PlanningCalendarSnapshot(firmID: firmID, flexibleID: flexibleID,
                generatedAt: generatedAt, timezone: calendar.timeZone.identifier,
                coverageStart: formatter.string(from: start), coverageEnd: formatter.string(from: end), events: detailedEvents)
            guard connected, firmID == defaults.string(forKey: "cookingCalendar.firm"),
                  flexibleID == defaults.string(forKey: "cookingCalendar.flexible") else { return }
            try await client.syncCookingAvailability(days: days)
            try await client.syncPlanningCalendar(detailed)
            message = "Availability updated at \(Date().formatted(date: .omitted, time: .shortened))."
        } catch KitchenOSError.http(404) {
            message = "Update the KitchenOS server to enable the detailed calendar view."
        } catch {
            message = "Couldn’t update availability. Check the KitchenOS connection and refresh."
        }
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
                    ForEach(sync.calendars, id: \.calendarIdentifier) { c in
                        Text("\(c.title) — \(c.source.title)").tag(c.calendarIdentifier)
                    }
                }
                Picker("Flexible (Time Blocking)", selection: $flexibleID) {
                    Text("Choose a calendar").tag("")
                    ForEach(sync.calendars, id: \.calendarIdentifier) { c in
                        Text("\(c.title) — \(c.source.title)").tag(c.calendarIdentifier)
                    }
                }
                Button("Save calendars and refresh") { Task { await sync.save(firmID: firmID, flexibleID: flexibleID) } }
                Button("Refresh availability") { Task { await sync.refresh() } }
            }
            Button("Disconnect Calendar") { Task { await sync.disconnect() } }
            Text(sync.message).font(.caption).accessibilityAddTraits(.updatesFrequently)
            Text("Event names and times from these calendars are shared with your local KitchenOS server. Keep this app open for updates every five minutes. After six hours without an update, availability shows as unknown.")
                .font(.caption).foregroundStyle(.secondary)
        }
        .disabled(sync.working)
        .onAppear { sync.loadCalendars() }
    }
}

#endif
