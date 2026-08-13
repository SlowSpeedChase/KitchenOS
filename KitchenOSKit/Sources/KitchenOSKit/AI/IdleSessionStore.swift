import Foundation

/// Keeps one live instance across Siri intent invocations so follow-up questions share
/// the model session's transcript. iOS 27 exposes no public conversation identity to
/// third-party intents (SDK introspection, 2026-08-12 — the `_ModelDelegationIntent`
/// machinery is Apple-internal), so continuity is time-based: reuse within `idleTimeout`
/// of the last touch, fresh after. Single user, single device — one slot is enough.
@MainActor
public final class IdleSessionStore<T: AnyObject> {
    private var value: T?
    private var lastUsed: Date = .distantPast
    private let idleTimeout: TimeInterval

    public init(idleTimeout: TimeInterval = 300) {
        self.idleTimeout = idleTimeout
    }

    public func current(now: Date = Date(), make: @MainActor () -> T) -> T {
        if let v = value, now.timeIntervalSince(lastUsed) < idleTimeout {
            lastUsed = now
            return v
        }
        let v = make()
        value = v
        lastUsed = now
        return v
    }

    public func reset() {
        value = nil
    }
}
