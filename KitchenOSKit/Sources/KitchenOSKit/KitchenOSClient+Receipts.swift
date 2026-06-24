import Foundation

public extension KitchenOSClient {
    /// Recent shopping trips (newest first).
    func trips() async throws -> [Trip] {
        try await getJSON(baseURL.appendingPathComponent("/api/receipts/trips"))
    }

    /// One trip plus its purchase lines.
    func trip(id: Int) async throws -> TripDetail {
        try await getJSON(baseURL.appendingPathComponent("/api/receipts/trips/\(id)"))
    }

    /// Structured price-tracker data (spending, by-category, trends).
    func priceTrends() async throws -> PriceData {
        try await getJSON(baseURL.appendingPathComponent("/api/price/trends"))
    }
}
