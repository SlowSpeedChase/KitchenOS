#if os(macOS)
import AppKit
import EventKit
import SwiftUI
import KitchenOSKit

/// The application (including Siri actions), not a window, owns the single writer.
@MainActor final class AppleIntegrationCoordinator: ObservableObject {
    static let shared = AppleIntegrationCoordinator(store: EventKitAppleItemStore())
    static let domainChangedNotification = Notification.Name("KitchenOSAppleDomainChanged")
    let store: any AppleItemStore
    @Published private(set) var status: IntegrationStatus?
    @Published private(set) var report: SyncReport?
    @Published private(set) var message = "Apple integration is ready to connect."
    private let defaults: UserDefaults
    private var service: AppleIntegrationService?
    private var serviceURL: URL?
    private var observers: [(NotificationCenter, NSObjectProtocol)] = []
    private var started = false
    private lazy var lifecycle = AppleIntegrationLifecycle { [weak self] trigger in
        await self?.refresh(trigger: trigger)
    }

    init(store: any AppleItemStore, defaults: UserDefaults = .standard) {
        self.store = store; self.defaults = defaults
    }
    var isLocalServer: Bool {
        let url = KitchenOSConfig.resolved(defaults: defaults).baseURL
        return ["http", "https"].contains(url.scheme?.lowercased() ?? "") &&
            ["localhost", "127.0.0.1", "::1", "[::1]"].contains(url.host?.lowercased() ?? "")
    }
    private var ownerID: UUID {
        if let value = defaults.string(forKey: "appleIntegration.ownerID"), let id = UUID(uuidString: value) { return id }
        let id = UUID(); defaults.set(id.uuidString.lowercased(), forKey: "appleIntegration.ownerID"); return id
    }
    private func currentService() async throws -> AppleIntegrationService {
        guard isLocalServer else { throw AppleIntegrationError.unavailable }
        let config = KitchenOSConfig.resolved(defaults: defaults)
        if let serviceURL, serviceURL != config.baseURL {
            message = "Restart KitchenOS after changing the server address."
            throw AppleIntegrationError.unavailable
        }
        if service == nil {
            let address = config.baseURL
            service = AppleIntegrationService(api: AppleIntegrationClient(client: KitchenOSClient(config: config)), store: store, ownerID: ownerID,
                isCurrentServer: { [weak self] in
                    guard let self else { return false }
                    return await MainActor.run {
                        return self.isLocalServer && KitchenOSConfig.resolved(defaults: self.defaults).baseURL == address
                    }
                })
            serviceURL = config.baseURL
        }
        return service!
    }
    func start() {
        guard !started else { return }; started = true
        observe(NSWorkspace.shared.notificationCenter, NSWorkspace.didWakeNotification, trigger: .wake)
        observe(.default, NSApplication.didBecomeActiveNotification, trigger: .foreground)
        observe(.default, .EKEventStoreChanged, trigger: .eventStoreChanged)
        observe(.default, Self.domainChangedNotification, trigger: .domainChanged)
        lifecycle.start()
    }
    private func observe(_ center: NotificationCenter, _ name: Notification.Name, trigger: AppleIntegrationTrigger) {
        let observer = center.addObserver(forName: name, object: nil, queue: .main) { [weak self] _ in
            Task { @MainActor in self?.lifecycle.notify(trigger) }
        }
        observers.append((center, observer))
    }
    func stop() {
        started = false; lifecycle.stop()
        for (center, observer) in observers { center.removeObserver(observer) }; observers.removeAll()
        let previous = service; service = nil; serviceURL = nil
        Task { await previous?.shutdown() }
    }
    func domainChanged() { lifecycle.notify(.domainChanged) }
    func perform(_ command: AppleIntegrationCommand) async throws -> SyncReport {
        guard isLocalServer else {
            message = "Apple sync runs on the server Mac using a localhost connection."
            throw AppleIntegrationError.unavailable
        }
        let service = try await currentService()
        do {
            let value = try await service.perform(command)
            report = value; await refreshStatus()
            await CookingCalendarSync.shared.refresh(excludingOwnedTokens: await service.ownedCookingTokens())
            return value
        } catch {
            await refreshStatus()
            message = "Apple sync needs attention. Check the connection and integration status."
            throw error
        }
    }
    func refresh(trigger: AppleIntegrationTrigger = .foreground) async {
        guard isLocalServer else {
            message = "Apple sync runs on the server Mac using a localhost connection."
            return
        }
        do {
            let service = try await currentService()
            report = try await service.reconcile(trigger: trigger)
            await refreshStatus()
        } catch is CancellationError { return }
        catch { message = "Apple sync needs attention. Check the connection and integration status." }
        await CookingCalendarSync.shared.refresh(excludingOwnedTokens: await service?.ownedCookingTokens() ?? [])
    }
    func refreshStatus() async {
        do {
            status = try await AppleIntegrationClient(client: KitchenOSClient(config: .resolved(defaults: defaults))).status()
            if let report {
                message = report.unavailable > 0 ? "Some Apple items are unavailable. Check permissions and try again." :
                    report.conflicts > 0 ? "Apple sync has changes to review." :
                    report.queued > 0 ? "Apple changes are queued." : "Apple sync is up to date."
            }
        } catch { message = "Couldn’t read Apple integration status. Check the KitchenOS connection." }
    }
    /// Foreground setup alone requests permission. Background refresh never prompts.
    func requestAccess(for domain: AppleDomain) async throws -> AppleAuthorization {
        guard isLocalServer else { throw AppleIntegrationError.unavailable }
        return try await store.requestAccess(for: domain)
    }
    func destinations(for domain: AppleDomain) async throws -> [AppleDestination] { try await store.destinations(for: domain) }
    func createDestination(name: String, domain: AppleDomain) async throws -> AppleDestination {
        guard isLocalServer else { throw AppleIntegrationError.unavailable }
        return try await store.createDestination(name: name, domain: domain)
    }
}
#endif
