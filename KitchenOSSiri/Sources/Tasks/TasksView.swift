import SwiftUI
import KitchenOSKit

/// Weekly prep tasks, grouped by day. Toggle done; "get-ahead" items flagged.
struct TasksView: View {
    @State private var weekAnchor = Date()
    @State private var tasks: [PrepTask] = []
    @State private var status = ""
    @State private var isLoading = false

    private var client: KitchenOSClient { KitchenOSClient(config: .resolved()) }
    private var weekID: String { WeekDate.weekID(for: weekAnchor) }

    private let dayOrder = ["Monday", "Tuesday", "Wednesday", "Thursday",
                            "Friday", "Saturday", "Sunday"]

    private var byDay: [(day: String, tasks: [PrepTask])] {
        Dictionary(grouping: tasks, by: \.day)
            .map { (day: $0.key, tasks: $0.value.sorted { ($0.step ?? 0) < ($1.step ?? 0) }) }
            .sorted { (dayOrder.firstIndex(of: $0.day) ?? 99) < (dayOrder.firstIndex(of: $1.day) ?? 99) }
    }

    var body: some View {
        List {
            if tasks.isEmpty, !isLoading {
                Text(status.isEmpty ? "No prep tasks for this week." : status)
                    .foregroundStyle(.secondary)
            }
            ForEach(byDay, id: \.day) { group in
                Section(group.day) {
                    ForEach(group.tasks) { task in
                        row(task)
                    }
                }
            }
        }
        .navigationTitle("Tasks")
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

    private func row(_ task: PrepTask) -> some View {
        Button {
            Task { await toggle(task) }
        } label: {
            HStack(alignment: .top) {
                Image(systemName: task.done ? "checkmark.circle.fill" : "circle")
                    .foregroundStyle(task.done ? .green : .secondary)
                VStack(alignment: .leading, spacing: 2) {
                    Text(task.text)
                        .strikethrough(task.done)
                        .foregroundStyle(task.done ? .secondary : .primary)
                    HStack(spacing: 6) {
                        Text(task.recipe).font(.caption).foregroundStyle(.secondary)
                        if task.canDoAhead {
                            Text("get ahead").font(.caption2)
                                .padding(.horizontal, 5).padding(.vertical, 1)
                                .background(.blue.opacity(0.15), in: Capsule())
                        }
                        if let m = task.timeMinutes, m > 0 {
                            Text("\(m)m").font(.caption2).foregroundStyle(.secondary)
                        }
                    }
                }
            }
        }
        .buttonStyle(.plain)
    }

    private func shiftWeek(_ delta: Int) {
        weekAnchor = Calendar.current.date(byAdding: .day, value: delta * 7, to: weekAnchor) ?? weekAnchor
    }

    private func load() async {
        isLoading = true
        defer { isLoading = false }
        do { tasks = try await client.tasks(week: weekID).tasks }
        catch { tasks = []; status = "Error: \(error)" }
    }

    private func toggle(_ task: PrepTask) async {
        let newDone = !task.done
        // Optimistic update.
        if let idx = tasks.firstIndex(where: { $0.id == task.id }) {
            tasks[idx].done = newDone
        }
        do { try await client.markTask(week: weekID, taskId: task.id, done: newDone) }
        catch {
            if let idx = tasks.firstIndex(where: { $0.id == task.id }) { tasks[idx].done = !newDone }
            status = "Update failed: \(error)"
        }
    }
}
