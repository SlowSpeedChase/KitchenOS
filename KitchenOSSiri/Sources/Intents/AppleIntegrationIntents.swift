#if os(macOS)
import AppIntents
import Foundation
import KitchenOSKit

// These app-target actions are discoverable in the Mac action library. They do
// not add automatic phrases or another EventKit writer to the iOS app.
struct SendShoppingListToRemindersIntent: AppIntent {
    static var title: LocalizedStringResource = "Send Shopping List to Reminders"
    static var description = IntentDescription("Send the saved shopping list for a selected week to the Reminders list chosen in KitchenOS.")
    static var supportedModes: IntentModes { [.background, .foreground(.dynamic)] }
    @Parameter(title: "Date in week") var week: Date
    init() { week = Date() }
    static var parameterSummary: some ParameterSummary { Summary("Send shopping list for the week of \(\.$week)") }
    @MainActor func perform() async throws -> some IntentResult & ProvidesDialog {
        let message = try await sendAppleWeek(.shopping, date: week)
        return .result(dialog: "\(message)")
    }
}

struct SendPrepTasksToRemindersIntent: AppIntent {
    static var title: LocalizedStringResource = "Send Prep Tasks to Reminders"
    static var description = IntentDescription("Send saved prep tasks for a selected week to the Reminders list chosen in KitchenOS.")
    static var supportedModes: IntentModes { [.background, .foreground(.dynamic)] }
    @Parameter(title: "Date in week") var week: Date
    init() { week = Date() }
    static var parameterSummary: some ParameterSummary { Summary("Send prep tasks for the week of \(\.$week)") }
    @MainActor func perform() async throws -> some IntentResult & ProvidesDialog {
        let message = try await sendAppleWeek(.prep, date: week)
        return .result(dialog: "\(message)")
    }
}

struct SyncCookingCalendarIntent: AppIntent {
    static var title: LocalizedStringResource = "Sync Cooking Calendar"
    static var description = IntentDescription("Activate cooking calendar sync for a selected week using the calendar chosen in KitchenOS.")
    static var supportedModes: IntentModes { [.background, .foreground(.dynamic)] }
    @Parameter(title: "Date in week") var week: Date
    init() { week = Date() }
    static var parameterSummary: some ParameterSummary { Summary("Sync cooking calendar for the week of \(\.$week)") }
    @MainActor func perform() async throws -> some IntentResult & ProvidesDialog {
        let message = try await sendAppleWeek(.cooking, date: week)
        return .result(dialog: "\(message)")
    }
}

struct PlannedCookOptions: DynamicOptionsProvider {
    @IntentParameterDependency<ScheduleCookingIntent>(\.$week) var intent
    func results() async throws -> [PlannedCookEntity] {
        let week = CookingIntentParameters.weekID(for: intent?.week ?? Date())
        return try await KitchenOSClient(config: .resolved()).plannedCooks(week: week).map(PlannedCookEntity.init)
    }
}

struct ScheduleCookingIntent: AppIntent {
    static var title: LocalizedStringResource = "Schedule Cooking"
    static var description = IntentDescription("Schedule an existing uncooked single recipe. Use a start and duration in 15-minute steps. First placement requires servings to eat. Existing portions stay unchanged. Sync Cooking Calendar activates Apple delivery for the week.")
    static var supportedModes: IntentModes { [.background, .foreground(.dynamic)] }
    @Parameter(title: "Date in week") var week: Date
    @Parameter(title: "Planned cook", optionsProvider: PlannedCookOptions()) var cook: PlannedCookEntity
    @Parameter(title: "Start date and time") var start: Date
    @Parameter(title: "Duration in minutes", default: 60) var duration: Int
    @Parameter(title: "Meal", default: .dinner) var meal: MealSlot
    @Parameter(title: "Servings to eat", description: "Required for a cook being placed for the first time.") var servings: Double?
    init() { week = Date() }
    static var parameterSummary: some ParameterSummary {
        Summary("Schedule \(\.$cook) at \(\.$start)") {
            \.$week; \.$duration; \.$meal; \.$servings
        }
    }
    @MainActor func perform() async throws -> some IntentResult & ProvidesDialog {
        let weekID = CookingIntentParameters.weekID(for: week)
        let coordinator = AppleIntegrationCoordinator.shared
        guard coordinator.isLocalServer else {
            return .result(dialog: "Run this action on the server Mac with KitchenOS connected to its local server.")
        }
        let status: IntegrationStatus
        do { status = try await coordinator.readStatus() }
        catch { return .result(dialog: "Couldn’t read Apple integration status. Check the KitchenOS connection and try again.") }
        guard status.connected else {
            let message = try await openAppleSetup(.cooking, week: weekID)
            return .result(dialog: "\(message)")
        }
        let scope = status.scopes.first { $0.domain == .cooking && $0.week == weekID && $0.status == .active }
        if let scope, status.permissions[AppleDomain.cooking.rawValue] != .authorized ||
            status.destinations[AppleDomain.cooking.rawValue]?.contains(where: { $0.id == scope.destinationID }) != true {
            let message = try await openAppleSetup(.cooking, week: weekID)
            return .result(dialog: "\(message)")
        }
        do {
            try await KitchenOSClient(config: .resolved()).scheduleCooking(cookID: cook.id, week: weekID,
                start: start, durationMinutes: duration, meal: meal, servingsToEat: servings)
        } catch let error as CookingIntentParameterError {
            return .result(dialog: "\(error.localizedDescription)")
        } catch KitchenOSError.http(404) {
            return .result(dialog: "That cook no longer exists. Choose another planned cook.")
        } catch {
            return .result(dialog: "The schedule wasn’t confirmed. Check the cook in KitchenOS before trying again.")
        }
        guard let scope else {
            return .result(dialog: "Cooking was scheduled in KitchenOS. Run Sync Cooking Calendar for this week to send it to Apple Calendar.")
        }
        do {
            let report = try await coordinator.perform(.sync)
            let latest = try await coordinator.readStatus()
            let stillActive = latest.scopes.contains {
                $0.domain == .cooking && $0.week == weekID && $0.status == .active &&
                    $0.destinationID == scope.destinationID && $0.revision == scope.revision
            }
            let result = AppleIntentResult(report: report, latest: latest, scopeActive: stillActive)
            return .result(dialog: "Cooking was scheduled in KitchenOS. Overall sync across active weeks: \(result.message)")
        } catch {
            return .result(dialog: "Cooking was scheduled in KitchenOS, but Apple delivery wasn’t confirmed. Check integration status before syncing again.")
        }
    }
}

struct SyncKitchenOSIntent: AppIntent {
    static var title: LocalizedStringResource = "Sync KitchenOS"
    static var description = IntentDescription("Reconcile Apple changes for weeks already activated in KitchenOS.")
    static var supportedModes: IntentModes { [.background, .foreground(.dynamic)] }
    @MainActor func perform() async throws -> some IntentResult & ProvidesDialog {
        let coordinator = AppleIntegrationCoordinator.shared
        guard coordinator.isLocalServer else {
            return .result(dialog: "Run this action on the server Mac with KitchenOS connected to its local server.")
        }
        let status: IntegrationStatus
        do { status = try await coordinator.readStatus() }
        catch { return .result(dialog: "Couldn’t read Apple integration status. Check the KitchenOS connection and try again.") }
        guard status.connected, status.scopes.contains(where: { $0.status == .active }) else {
            let message = try await openAppleSetup(.shopping, week: WeekDate.currentWeekID())
            return .result(dialog: "\(message)")
        }
        do {
            let report = try await coordinator.perform(.sync)
            let latest = try await coordinator.readStatus()
            let result = AppleIntentResult(report: report, latest: latest)
            return .result(dialog: "\(result.message)")
        } catch {
            return .result(dialog: "Apple sync wasn’t confirmed. Review integration status in KitchenOS and try again.")
        }
    }
}

private extension AppIntent {
    @MainActor func openAppleSetup(_ domain: AppleDomain, week: String) async throws -> String {
        try await continueInForeground("Open KitchenOS to finish Apple integration setup.")
        AppRouter.shared.openIntegrationSettings(domain: domain, week: week)
        return AppleIntentResult.setup.message
    }
    @MainActor func sendAppleWeek(_ domain: AppleDomain, date: Date) async throws -> String {
        let coordinator = AppleIntegrationCoordinator.shared
        let week = CookingIntentParameters.weekID(for: date)
        guard coordinator.isLocalServer else {
            return "Run this action on the server Mac with KitchenOS connected to its local server."
        }
        let status: IntegrationStatus
        do { status = try await coordinator.readStatus() }
        catch { return "Couldn’t read Apple integration status. Check the KitchenOS connection and try again." }
        guard status.connected, status.permissions[domain.rawValue] == .authorized else {
            return try await openAppleSetup(domain, week: week)
        }
        let destination: String
        do { destination = try await coordinator.validatedPreferredDestination(for: domain) }
        catch { return try await openAppleSetup(domain, week: week) }
        do {
            let report = try await coordinator.perform(.activate(domain, week: week, destination: destination))
            let latest = try await coordinator.readStatus()
            let stillActive = latest.scopes.contains {
                $0.domain == domain && $0.week == week && $0.status == .active && $0.destinationID == destination
            }
            let result = AppleIntentResult(report: report, latest: latest, scopeActive: stillActive)
            return "Overall sync across active weeks: " + result.message
        } catch {
            return "Apple delivery wasn’t confirmed. Review integration status in KitchenOS and try again."
        }
    }
}
#endif
