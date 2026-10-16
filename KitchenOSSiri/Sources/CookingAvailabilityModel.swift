import SwiftUI
import KitchenOSKit

@MainActor
final class CookingAvailabilityModel: ObservableObject {
    @Published var days: [String: CookingOpportunity] = [:]

    func follow(week: String) async {
        days = [:]
        while !Task.isCancelled {
            let result = try? await KitchenOSClient(config: .resolved()).cookingAvailability(week: week)
            guard !Task.isCancelled else { return }
            days = result?.days ?? [:]
            do { try await Task.sleep(for: .seconds(60)) } catch { return }
        }
    }
}
