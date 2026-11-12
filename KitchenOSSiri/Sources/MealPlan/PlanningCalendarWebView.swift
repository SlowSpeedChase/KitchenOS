import SwiftUI
import WebKit
import KitchenOSKit

struct PlanningCalendarSheet: View {
    let week: String
    @Environment(\.dismiss) private var dismiss
    var body: some View {
        NavigationStack {
            PlanningCalendarWebView(week: week)
                .navigationTitle("Plan with calendar")
                .toolbar { Button("Done") { dismiss() } }
        }
        #if os(macOS)
        .frame(minWidth: 900, minHeight: 700)
        #endif
    }
}

struct PlanningCalendarWebView {
    let week: String
    var focusCookID: Int? = nil
    func makeCoordinator() -> Coordinator { Coordinator() }
    func makeWebView(_ coordinator: Coordinator) -> WKWebView {
        let config = KitchenOSConfig.resolved()
        let settings = WKWebViewConfiguration()
        settings.websiteDataStore = .nonPersistent()
        if let token = config.credentials.token(), let script = PlanningWebPolicy.authorizationScript(base: config.baseURL, token: token) {
            settings.userContentController.addUserScript(WKUserScript(source:script,injectionTime:.atDocumentStart,forMainFrameOnly:true))
        }
        let webView = WKWebView(frame:.zero,configuration:settings)
        coordinator.origin = config.baseURL
        webView.navigationDelegate = coordinator
        load(webView, coordinator: coordinator)
        return webView
    }
    func load(_ webView: WKWebView, coordinator: Coordinator) {
        let config = KitchenOSConfig.resolved()
        guard let origin = coordinator.origin, PlanningWebPolicy.sameOrigin(config.baseURL, origin) else { return }
        if let url = PlanningWebPolicy.plannerURL(base:config.baseURL,week:week, focusCookID: focusCookID), coordinator.loadedURL != url {
            coordinator.loadedURL = url
            var request=URLRequest(url:url)
            if let token=config.credentials.token() { request.setValue("Bearer \(token)",forHTTPHeaderField:"Authorization") }
            webView.load(request)
        }
    }
    static func clean(_ webView: WKWebView) {
        webView.stopLoading()
        webView.navigationDelegate=nil
        webView.configuration.userContentController.removeAllUserScripts()
        webView.configuration.userContentController.removeAllScriptMessageHandlers()
    }
    final class Coordinator: NSObject, WKNavigationDelegate {
        var origin: URL?
        var loadedURL: URL?
        func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
            guard let url=action.request.url, let origin else { decisionHandler(.cancel);return }
            if PlanningWebPolicy.sameOrigin(url,origin), action.targetFrame?.isMainFrame == true,
               url.path == "/meal-planner" { decisionHandler(.allow);return }
            if action.navigationType == .linkActivated, ["http","https"].contains(url.scheme?.lowercased() ?? "") {
                #if os(macOS)
                NSWorkspace.shared.open(url)
                #else
                UIApplication.shared.open(url)
                #endif
            }
            decisionHandler(.cancel)
        }
    }
}

#if os(macOS)
extension PlanningCalendarWebView: NSViewRepresentable {
    func makeNSView(context: Context) -> WKWebView { makeWebView(context.coordinator) }
    func updateNSView(_ view: WKWebView, context: Context) { load(view, coordinator: context.coordinator) }
    static func dismantleNSView(_ view: WKWebView, coordinator: Coordinator) { clean(view) }
}
#else
extension PlanningCalendarWebView: UIViewRepresentable {
    func makeUIView(context: Context) -> WKWebView { makeWebView(context.coordinator) }
    func updateUIView(_ view: WKWebView, context: Context) { load(view, coordinator: context.coordinator) }
    static func dismantleUIView(_ view: WKWebView, coordinator: Coordinator) { clean(view) }
}
#endif
