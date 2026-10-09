import SwiftUI
import Combine
import KitchenOSKit

@MainActor final class AppRouter: ObservableObject {
    static let shared = AppRouter()
    enum Presentation { case item, settings }
    @Published var presentation: Presentation?
    @Published var settingsDomain: AppleDomain = .shopping
    @Published var settingsWeek: String?
    let items = KitchenOSItemRouter(clientProvider: { AppleIntegrationClient(client: KitchenOSClient(config: .resolved())) })
    private var subscription: AnyCancellable?
    init() {
        subscription = items.objectWillChange.sink { [weak self] _ in self?.objectWillChange.send() }
    }
    func open(_ link: KitchenOSDeepLink) async {
        presentation = .item
        await items.open(link)
    }
    /// Foreground setup destination shared by buttons and Mac intents.
    func openIntegrationSettings(domain: AppleDomain = .shopping, week: String? = nil) {
        settingsDomain = domain; settingsWeek = week
        presentation = .settings
    }
}

struct NativeItemDestinationView: View {
    @ObservedObject var router: KitchenOSItemRouter
    var body: some View {
        Group {
            switch router.destination {
            case let .shopping(week, id): ShoppingListView(routedWeek: week, focusedRowID: id)
            case let .prep(week, id): TasksView(routedWeek: week, focusedTaskID: id)
            case let .cooking(week, id): PlanningCalendarWebView(week: week, focusCookID: id)
            case nil: ContentUnavailableView("Linked item", systemImage: "link", description: Text(router.message))
            }
        }
    }
}

struct NativeNavigationHost<Content: View>: View {
    @ObservedObject var router = AppRouter.shared
    @ViewBuilder var content: () -> Content
    var body: some View {
        content()
            .onOpenURL { url in
                guard let link = KitchenOSDeepLink(url: url) else { return }
                Task { await router.open(link) }
            }
            .sheet(isPresented: Binding(get: { router.presentation != nil }, set: { if !$0 { router.presentation = nil } })) {
                NavigationStack {
                    Group {
                        if router.presentation == .settings {
                            Form { AppleIntegrationSettingsView(initialDomain: router.settingsDomain, initialWeek: router.settingsWeek) }
                                .id(router.settingsDomain.rawValue + (router.settingsWeek ?? ""))
                                .padding().navigationTitle("Apple integration")
                        } else { NativeItemDestinationView(router: router.items) }
                    }
                    .toolbar { Button("Close") { router.presentation = nil } }
                }
                #if os(macOS)
                .frame(minWidth: 850, minHeight: 650)
                #endif
            }
    }
}
