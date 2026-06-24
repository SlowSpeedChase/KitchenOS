import SwiftUI
import KitchenOSKit

struct AssistantView: View {
    struct Message: Identifiable {
        let id = UUID()
        let role: String   // "user" | "assistant"
        let text: String
    }

    @State private var messages: [Message] = []
    @State private var input = ""
    @State private var isThinking = false
    @State private var assistant: MealPlanAssistant?
    @State private var pending: PendingMealAddition?

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                if case let .unavailable(reason) = RecipeAI.availability {
                    Label(reason, systemImage: "exclamationmark.triangle")
                        .font(.caption).foregroundStyle(.secondary)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(8)
                }

                ScrollViewReader { proxy in
                    ScrollView {
                        LazyVStack(alignment: .leading, spacing: 8) {
                            ForEach(messages) { m in
                                MessageRow(message: m).id(m.id)
                            }
                            if isThinking {
                                Text("Thinking…").font(.caption).foregroundStyle(.secondary)
                            }
                        }
                        .padding()
                    }
                    .onChange(of: messages.count) {
                        if let last = messages.last {
                            withAnimation { proxy.scrollTo(last.id, anchor: .bottom) }
                        }
                    }
                }

                if let p = pending {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Add **\(p.recipe)** to \(p.day) \(p.meal)?")
                            .font(.callout)
                        HStack {
                            Button("Confirm") { confirmAdd(p) }
                                .buttonStyle(.borderedProminent)
                            Button("Dismiss") {
                                pending = nil
                                assistant?.clearProposal()
                            }
                            .buttonStyle(.bordered)
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding()
                    .background(Color.yellow.opacity(0.15))
                }

                HStack {
                    TextField("Ask about recipes or your plan…", text: $input)
                        .textFieldStyle(.roundedBorder)
                        .onSubmit(send)
                    Button("Send", action: send)
                        .disabled(input.isEmpty || isThinking || !MealPlanAssistant.isAvailable)
                }
                .padding()
            }
            .navigationTitle("Assistant")
        }
    }

    private func send() {
        let text = input.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        messages.append(Message(role: "user", text: text))
        input = ""

        // Deterministic add-intent: surface the Confirm card without relying on the model.
        if let proposal = AddRequestParser.parse(text) {
            pending = proposal
            messages.append(Message(role: "assistant",
                                    text: "Add \(proposal.recipe) to \(proposal.day) \(proposal.meal)? Tap Confirm below."))
            return
        }

        isThinking = true
        Task { @MainActor in
            do {
                if assistant == nil { assistant = MealPlanAssistant() }
                let reply = try await assistant!.reply(to: text)
                messages.append(Message(role: "assistant", text: reply))
                pending = assistant!.pendingProposal()
            } catch {
                messages.append(Message(role: "assistant", text: "Sorry — \(error.localizedDescription)"))
            }
            isThinking = false
        }
    }

    private func confirmAdd(_ p: PendingMealAddition) {
        pending = nil
        isThinking = true
        Task { @MainActor in
            do {
                if assistant == nil { assistant = MealPlanAssistant() }
                let result = try await assistant!.confirm(p)
                messages.append(Message(role: "assistant", text: result))
            } catch {
                messages.append(Message(role: "assistant", text: "Couldn't add it — \(error.localizedDescription)"))
            }
            isThinking = false
        }
    }
}

private struct MessageRow: View {
    let message: AssistantView.Message

    var body: some View {
        HStack {
            if message.role == "user" { Spacer(minLength: 32) }
            Text(message.text)
                .padding(8)
                .background(
                    message.role == "user"
                        ? Color.accentColor.opacity(0.2)
                        : Color.gray.opacity(0.15)
                )
                .clipShape(RoundedRectangle(cornerRadius: 10))
            if message.role == "assistant" { Spacer(minLength: 32) }
        }
    }
}
