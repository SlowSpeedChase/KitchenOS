import SwiftUI
import KitchenOSKit

/// Weekly nutrition: per-day macros, week averages vs targets, warnings.
struct NutritionDashboardView: View {
    @State private var weekAnchor = Date()
    @State private var dashboard: NutritionDashboard?
    @State private var status = ""
    @State private var isLoading = false

    private var client: KitchenOSClient { KitchenOSClient(config: .resolved()) }
    private var weekID: String { WeekDate.weekID(for: weekAnchor) }

    var body: some View {
        List {
            if let d = dashboard {
                Section(d.weekLabel ?? d.week) {
                    ForEach(d.days) { day in
                        HStack {
                            Text(day.day).frame(width: 90, alignment: .leading)
                            Spacer()
                            if day.hasMeals {
                                Text(macroLine(day, targets: d.targets))
                                    .font(.callout).monospacedDigit()
                            } else {
                                Text("—").foregroundStyle(.secondary)
                            }
                        }
                    }
                }

                if let avg = d.averages, let t = d.targets {
                    Section("Week averages vs target") {
                        avgRow("Calories", avg.calories, t.calories, unit: "")
                        avgRow("Protein", avg.protein, t.protein, unit: "g")
                        avgRow("Carbs", avg.carbs, t.carbs, unit: "g")
                        avgRow("Fat", avg.fat, t.fat, unit: "g")
                    }
                }

                if let warnings = d.warnings, !warnings.isEmpty {
                    Section("Warnings") {
                        ForEach(warnings, id: \.self) { w in
                            Label(w, systemImage: "exclamationmark.triangle")
                                .font(.caption).foregroundStyle(.orange)
                        }
                    }
                }
            } else if !isLoading {
                Text(status.isEmpty ? "No data." : status).foregroundStyle(.secondary)
            }
        }
        .navigationTitle("Nutrition")
        .overlay { if isLoading { ProgressView() } }
        .toolbar {
            ToolbarItemGroup {
                Button { shiftWeek(-1) } label: { Image(systemName: "chevron.left") }
                Text(weekID).font(.callout.monospaced())
                Button { shiftWeek(1) } label: { Image(systemName: "chevron.right") }
            }
        }
        .task(id: weekID) { await load() }
    }

    private func macroLine(_ day: DayMacros, targets: Macros?) -> String {
        let cal = day.calories ?? 0
        let p = day.protein ?? 0
        let c = day.carbs ?? 0
        let f = day.fat ?? 0
        if let t = targets {
            return "\(cal)/\(t.calories) cal · \(p)/\(t.protein)p · \(c)/\(t.carbs)c · \(f)/\(t.fat)f"
        }
        return "\(cal) cal · \(p)p · \(c)c · \(f)f"
    }

    private func avgRow(_ label: String, _ value: Int, _ target: Int, unit: String) -> some View {
        let diff = value - target
        return HStack {
            Text(label)
            Spacer()
            Text("\(value)\(unit) / \(target)\(unit)").monospacedDigit()
            Text(diff == 0 ? "—" : "\(diff > 0 ? "+" : "")\(diff)\(unit)")
                .font(.caption).monospacedDigit()
                .foregroundStyle(diff == 0 ? Color.secondary : (diff > 0 ? Color.orange : Color.blue))
                .frame(width: 56, alignment: .trailing)
        }
    }

    private func shiftWeek(_ delta: Int) {
        weekAnchor = Calendar.current.date(byAdding: .day, value: delta * 7, to: weekAnchor) ?? weekAnchor
    }

    private func load() async {
        isLoading = true
        defer { isLoading = false }
        do { dashboard = try await client.nutrition(week: weekID) }
        catch { dashboard = nil; status = "Error: \(error)" }
    }
}
