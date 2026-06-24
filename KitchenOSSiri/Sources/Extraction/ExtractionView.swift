#if os(macOS)
import SwiftUI

/// Native macOS recipe-extraction screen (folded in from the retired menu-bar app).
struct ExtractionView: View {
    @StateObject private var manager = ExtractionManager()
    @State private var urlInput: String = ""

    var body: some View {
        Form {
            Section("Extract from YouTube") {
                TextField("YouTube URL", text: $urlInput)
                    .textFieldStyle(.roundedBorder)
                    .onSubmit(extract)
                    .disabled(manager.isAnyExtracting)

                Button(action: extract) {
                    HStack {
                        if manager.isExtracting {
                            ProgressView().controlSize(.small)
                        }
                        Text(manager.isExtracting ? "Extracting..." : "Extract Recipe")
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(manager.isAnyExtracting || urlInput.isEmpty)

                Button(action: { manager.batchExtract() }) {
                    HStack {
                        if manager.isBatchExtracting {
                            ProgressView().controlSize(.small)
                        }
                        Text(batchButtonText)
                    }
                }
                .disabled(manager.isAnyExtracting)
            }

            Section("Status") {
                Text(manager.status)
                    .foregroundColor(manager.statusIsError ? .red : .primary)
            }

            if !manager.history.isEmpty {
                Section("Recent") {
                    ForEach(manager.history) { item in
                        Button(action: { item.openInObsidian() }) {
                            HStack {
                                Image(systemName: "doc.text").foregroundColor(.secondary)
                                Text(item.recipeName).lineLimit(1)
                                Spacer()
                                Text(item.timeAgo).font(.caption2).foregroundColor(.secondary)
                            }
                        }
                        .buttonStyle(.plain)
                    }
                }
            }
        }
        .formStyle(.grouped)
        .navigationTitle("Extraction")
    }

    private var batchButtonText: String {
        if manager.isBatchExtracting {
            return manager.batchTotal > 0
                ? "Processing \(manager.batchCurrent)/\(manager.batchTotal)..."
                : "Starting..."
        }
        return "Process Queue"
    }

    private func extract() {
        guard !urlInput.isEmpty else { return }
        let url = urlInput
        urlInput = ""
        manager.extract(url: url)
    }
}
#endif
