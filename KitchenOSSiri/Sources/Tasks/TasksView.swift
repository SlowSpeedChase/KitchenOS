import SwiftUI
import KitchenOSKit

/// Weekly prep tasks, grouped by day. Toggle done; "get-ahead" items flagged.
struct TasksView: View {
    var routedWeek: String? = nil
    var focusedTaskID: String? = nil
    @State private var details: [AppleItemDetail] = []
    @State private var weekAnchor = Date()
    @State private var loadedWeek: String?
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
        ScrollViewReader { reader in
        List {
            if !status.isEmpty { Text(status) }
            if routedWeek == nil {
            Button("Refresh tasks from the plan") {
                Task {
                    do { _ = try await client.tasks(week: weekID, force: true); await load() }
                    catch { status = "Couldn’t refresh tasks. Check the connection and try again." }
                }
            }.disabled(isLoading)
            }
            #if os(macOS)
            Button("Send prep tasks to Reminders…") { AppRouter.shared.openIntegrationSettings(domain: .prep, week: weekID) }
            #endif
            if tasks.isEmpty, !isLoading {
                Text(status.isEmpty ? "No prep tasks for this week." : status)
                    .foregroundStyle(.secondary)
            }
            ForEach(byDay, id: \.day) { group in
                Section(group.day) {
                    ForEach(group.tasks) { task in
                        row(task).id(task.id)
                    }
                }
            }
        }
        .navigationTitle("Tasks")
        .overlay { if isLoading { ProgressView() } }
        .toolbar {
            ToolbarItemGroup {
                Button { shiftWeek(-1) } label: { Image(systemName: "chevron.left") }.accessibilityLabel("Previous week")
                Text(WeekDate.weekRangeLabel(for: weekAnchor))
                Button { shiftWeek(1) } label: { Image(systemName: "chevron.right") }.accessibilityLabel("Next week")
            }
        }
        .task(id: weekID) { await load() }
        .task(id: (routedWeek ?? "") + (focusedTaskID ?? "")) {
            if let week = routedWeek, let date = WeekDate.date(forWeekID: week) { weekAnchor = date }
            await load()
            if let id = focusedTaskID { reader.scrollTo(id, anchor: .center) }
        }
        }

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
                    if focusedTaskID == task.id { Label("Linked task", systemImage: "link").font(.caption) }
                    if let detail = details.first(where: { $0.item.logicalID == task.id }), detail.hasDueOverride {
                        Text("Reminder due: \(detail.dueOverride?.displayText ?? "No due date")").font(.caption)
                    }
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
        .frame(minHeight: 44)
        .buttonStyle(.plain)
        .disabled(isLoading || loadedWeek != weekID)
        .accessibilityLabel(task.text)
        .accessibilityValue(task.done ? "Completed" : "Incomplete")
    }

    private func shiftWeek(_ delta: Int) {
        weekAnchor = Calendar.current.date(byAdding: .day, value: delta * 7, to: weekAnchor) ?? weekAnchor
    }

    private func load() async {
        isLoading = true
        defer { isLoading = false }
        let requestedWeek = weekID
        do {
            let payload = try await client.savedTasks(week: requestedWeek)
            guard weekID == requestedWeek else { return }
            tasks = payload.tasks; loadedWeek = requestedWeek; status = ""
            if let id = focusedTaskID, routedWeek == requestedWeek, !tasks.contains(where: { $0.id == id }) {
                status = "The linked task is no longer available. No task was recreated."
            }
            let values = try? await AppleIntegrationClient(client: client).items(domain: .prep, week: requestedWeek)
            if weekID == requestedWeek { details = (values ?? []).sorted { $0.item.generation > $1.item.generation } }
        } catch { guard weekID == requestedWeek else { return }; tasks = []; details = []; status = routedWeek == nil ? "Saved tasks are unavailable. Refresh tasks explicitly to use the current plan." : "The saved task for this link is unavailable. Open Tasks from the main screen to review the current plan." }
    }

    private func toggle(_ task: PrepTask) async {
        guard loadedWeek == weekID else { return }
        let requestedWeek = weekID
        let newDone = !task.done
        // Optimistic update.
        if let idx = tasks.firstIndex(where: { $0.id == task.id }) {
            tasks[idx].done = newDone
        }
        do {
            try await client.markTask(week: requestedWeek, taskId: task.id, done: newDone)
            #if os(macOS)
            AppleIntegrationCoordinator.shared.domainChanged()
            #endif
        }
        catch {
            guard weekID == requestedWeek else { return }
            if let idx = tasks.firstIndex(where: { $0.id == task.id }) { tasks[idx].done = !newDone }
            status = "Update failed: \(error)"
        }
    }
}
