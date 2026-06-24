import SwiftUI
import KitchenOSKit

/// Cents → "$x.xx".
func dollars(_ cents: Int?) -> String {
    String(format: "$%.2f", Double(cents ?? 0) / 100)
}

/// Receipts: shopping trips (drill into purchases) and price trends.
struct ReceiptsView: View {
    enum Tab: String, CaseIterable, Identifiable { case trips = "Trips", prices = "Prices"; var id: String { rawValue } }

    @State private var tab: Tab = .trips
    @State private var trips: [Trip] = []
    @State private var price: PriceData?
    @State private var status = ""
    @State private var isLoading = false

    private var client: KitchenOSClient { KitchenOSClient(config: .resolved()) }

    var body: some View {
        List {
            Picker("View", selection: $tab) {
                ForEach(Tab.allCases) { Text($0.rawValue).tag($0) }
            }
            .pickerStyle(.segmented)

            switch tab {
            case .trips: tripsContent
            case .prices: pricesContent
            }
        }
        .navigationTitle("Receipts")
        .navigationDestination(for: Trip.self) { TripDetailView(trip: $0) }
        .overlay { if isLoading { ProgressView() } }
        .task { await load() }
        .refreshable { await load() }
    }

    @ViewBuilder private var tripsContent: some View {
        if trips.isEmpty, !isLoading {
            Text(status.isEmpty ? "No trips recorded." : status).foregroundStyle(.secondary)
        }
        ForEach(trips) { trip in
            NavigationLink(value: trip) {
                HStack {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(trip.store ?? "Trip").font(.body)
                        Text(trip.date).font(.caption).foregroundStyle(.secondary)
                    }
                    Spacer()
                    Text(dollars(trip.totalCents)).monospacedDigit()
                    if trip.needsReview {
                        Image(systemName: "exclamationmark.triangle").foregroundStyle(.orange)
                    }
                }
            }
        }
    }

    @ViewBuilder private var pricesContent: some View {
        if let p = price {
            if let weeks = p.weeks, !weeks.isEmpty {
                Section("Spending (last 4 weeks)") {
                    ForEach(weeks, id: \.week) { w in
                        HStack { Text(w.week).monospaced(); Spacer(); Text(dollars(w.spendCents)).monospacedDigit() }
                    }
                }
            }
            Section("Average trip") {
                Text("\(dollars(p.averageTripCents)) across \(p.tripCount ?? 0) trips")
            }
            if let cats = p.byCategory, !cats.isEmpty {
                Section("By category (12 mo)") {
                    ForEach(cats, id: \.category) { c in
                        HStack { Text(c.category.capitalized); Spacer(); Text(dollars(c.spendCents)).monospacedDigit() }
                    }
                }
            }
            if let trends = p.trends, !trends.isEmpty {
                Section("Price trends (vs 90-day avg)") {
                    ForEach(trends) { t in
                        HStack {
                            Image(systemName: arrow(t.direction)).foregroundStyle(color(t.direction))
                            Text(t.item).lineLimit(1)
                            Spacer()
                            Text("\(dollars(t.currentCents))/\(t.unit ?? "")").monospacedDigit()
                            Text("avg \(dollars(t.avg90Cents))").font(.caption).foregroundStyle(.secondary)
                        }
                    }
                }
            }
        } else if !isLoading {
            Text(status.isEmpty ? "No price data." : status).foregroundStyle(.secondary)
        }
    }

    private func arrow(_ d: String) -> String {
        d == "up" ? "arrow.up" : (d == "down" ? "arrow.down" : "minus")
    }
    private func color(_ d: String) -> Color {
        d == "up" ? .orange : (d == "down" ? .green : .secondary)
    }

    private func load() async {
        isLoading = true
        defer { isLoading = false }
        do {
            async let t = client.trips()
            async let p = client.priceTrends()
            trips = try await t
            price = try await p
        } catch { status = "Error: \(error)" }
    }
}

/// Purchases for a single trip.
struct TripDetailView: View {
    let trip: Trip
    @State private var detail: TripDetail?
    @State private var status = ""

    private var client: KitchenOSClient { KitchenOSClient(config: .resolved()) }

    var body: some View {
        List {
            Section {
                HStack { Text(trip.store ?? "Trip"); Spacer(); Text(dollars(trip.totalCents)).monospacedDigit() }
                Text(trip.date).font(.caption).foregroundStyle(.secondary)
            }
            if let purchases = detail?.purchases {
                Section("Items (\(purchases.count))") {
                    ForEach(purchases) { p in
                        HStack {
                            VStack(alignment: .leading, spacing: 2) {
                                Text(p.canonicalName.capitalized)
                                if let raw = p.rawName, raw.lowercased() != p.canonicalName.lowercased() {
                                    Text(raw).font(.caption2).foregroundStyle(.secondary)
                                }
                            }
                            Spacer()
                            Text(dollars(p.totalCents)).monospacedDigit()
                        }
                    }
                }
            } else if !status.isEmpty {
                Text(status).foregroundStyle(.secondary)
            }
        }
        .navigationTitle(trip.store ?? "Trip")
        .task { await load() }
    }

    private func load() async {
        do { detail = try await client.trip(id: trip.id) }
        catch { status = "Error: \(error)" }
    }
}
