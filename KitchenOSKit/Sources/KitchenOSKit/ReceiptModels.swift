import Foundation

/// A shopping trip (receipt). Money is in integer cents.
public struct Trip: Codable, Sendable, Hashable, Identifiable {
    public let id: Int
    public let date: String
    public let store: String?
    public let source: String?
    public let totalCents: Int?
    public let needsReviewRaw: Int?

    public var needsReview: Bool { (needsReviewRaw ?? 0) != 0 }

    enum CodingKeys: String, CodingKey {
        case id, date, store, source
        case totalCents = "total_cents"
        case needsReviewRaw = "needs_review"
    }
}

public struct Purchase: Codable, Sendable, Hashable, Identifiable {
    public let rawName: String?
    public let canonicalName: String
    public let quantity: Double?
    public let unit: String?
    public let unitPriceCents: Int?
    public let totalCents: Int?
    public let category: String?

    public var id: String { "\(canonicalName)|\(unit ?? "")|\(totalCents ?? 0)" }

    enum CodingKeys: String, CodingKey {
        case quantity, unit, category
        case rawName = "raw_name"
        case canonicalName = "canonical_name"
        case unitPriceCents = "unit_price_cents"
        case totalCents = "total_cents"
    }
}

public struct TripDetail: Codable, Sendable {
    public let trip: Trip
    public let purchases: [Purchase]
}

public struct WeekSpend: Codable, Sendable, Hashable {
    public let week: String
    public let spendCents: Int

    enum CodingKeys: String, CodingKey {
        case week
        case spendCents = "spend_cents"
    }
}

public struct CategorySpend: Codable, Sendable, Hashable {
    public let category: String
    public let spendCents: Int

    enum CodingKeys: String, CodingKey {
        case category
        case spendCents = "spend_cents"
    }
}

public struct PriceTrend: Codable, Sendable, Hashable, Identifiable {
    public let item: String
    public let currentCents: Int?
    public let avg90Cents: Int?
    public let unit: String?
    public let direction: String   // "up" | "down" | "flat"

    public var id: String { item }

    enum CodingKeys: String, CodingKey {
        case item, unit, direction
        case currentCents = "current_cents"
        case avg90Cents = "avg90_cents"
    }
}

public struct PriceData: Codable, Sendable {
    public let weeks: [WeekSpend]?
    public let byCategory: [CategorySpend]?
    public let averageTripCents: Int?
    public let tripCount: Int?
    public let trends: [PriceTrend]?

    enum CodingKeys: String, CodingKey {
        case weeks, trends
        case byCategory = "by_category"
        case averageTripCents = "average_trip_cents"
        case tripCount = "trip_count"
    }
}
