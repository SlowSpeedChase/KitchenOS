import Foundation
import UserNotifications

/// Manages the Python script execution for recipe extraction
@MainActor
class ExtractionManager: ObservableObject {
    @Published var isExtracting = false
    @Published var isBatchExtracting = false
    @Published var status: String = "Ready"
    @Published var statusIsError = false
    @Published var history: [HistoryItem] = []

    // Batch processing state
    @Published var batchCurrent = 0
    @Published var batchTotal = 0
    private var batchSucceeded = 0
    private var batchSkipped = 0
    private var batchFailed = 0

    private var currentProcess: Process?
    private let maxHistoryItems = 10
    private let timeoutSeconds: TimeInterval = 300 // 5 minutes
    private let batchTimeoutSeconds: TimeInterval = 1800 // 30 minutes for batch

    private let pythonPath = "/Users/chaseeasterling/KitchenOS/.venv/bin/python"
    private let scriptPath = "/Users/chaseeasterling/KitchenOS/extract_recipe.py"
    private let batchScriptPath = "/Users/chaseeasterling/KitchenOS/batch_extract.py"
    private let workingDirectory = "/Users/chaseeasterling/KitchenOS"

    init() {
        // Request notification permission (may fail if not in app bundle)
        if Bundle.main.bundleIdentifier != nil {
            UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound]) { _, _ in }
        }
    }

    func extract(url: String) {
        guard !isExtracting else { return }
        guard isValidYouTubeURL(url) else {
            status = "Error: Invalid YouTube URL"
            statusIsError = true
            return
        }

        isExtracting = true
        status = "Extracting..."
        statusIsError = false

        Task {
            await runExtraction(url: url)
        }
    }

    private func runExtraction(url: String) async {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: pythonPath)
        process.arguments = [scriptPath, url]
        process.currentDirectoryURL = URL(fileURLWithPath: workingDirectory)

        let stdout = Pipe()
        let stderr = Pipe()
        process.standardOutput = stdout
        process.standardError = stderr

        currentProcess = process

        // Set up timeout
        let timeoutTask = Task {
            try await Task.sleep(nanoseconds: UInt64(timeoutSeconds * 1_000_000_000))
            if process.isRunning {
                process.terminate()
            }
        }

        do {
            try process.run()
            process.waitUntilExit()
            timeoutTask.cancel()

            let outputData = stdout.fileHandleForReading.readDataToEndOfFile()
            let errorData = stderr.fileHandleForReading.readDataToEndOfFile()
            let output = String(data: outputData, encoding: .utf8) ?? ""
            let errorOutput = String(data: errorData, encoding: .utf8) ?? ""

            handleResult(exitCode: process.terminationStatus, output: output, error: errorOutput)
        } catch {
            status = "Error: \(error.localizedDescription)"
            statusIsError = true
            isExtracting = false
        }

        currentProcess = nil
    }

    private func handleResult(exitCode: Int32, output: String, error: String) {
        isExtracting = false

        if exitCode == 0, let savedPath = parseSavedPath(from: output) {
            let recipeName = extractRecipeName(from: output, path: savedPath)

            let item = HistoryItem(
                recipeName: recipeName,
                filePath: savedPath,
                extractedAt: Date()
            )

            history.insert(item, at: 0)
            if history.count > maxHistoryItems {
                history.removeLast()
            }

            status = "Extracted: \(recipeName)"
            statusIsError = false

            sendNotification(title: "Recipe Extracted", body: recipeName)
        } else {
            // Check for specific error messages
            if error.contains("Ollama") || output.contains("Ollama") {
                status = "Error: Ollama not running"
            } else if error.isEmpty {
                status = "Error: Extraction failed"
            } else {
                // Extract first line of error
                let firstLine = error.components(separatedBy: .newlines).first ?? "Unknown error"
                status = "Error: \(firstLine)"
            }
            statusIsError = true
        }
    }

    private func parseSavedPath(from output: String) -> String? {
        let lines = output.components(separatedBy: .newlines)
        for line in lines {
            if line.hasPrefix("SAVED: ") {
                return String(line.dropFirst(7))
            }
        }
        return nil
    }

    private func extractRecipeName(from output: String, path: String) -> String {
        // Try to get recipe name from "Extracted: Name" line
        let lines = output.components(separatedBy: .newlines)
        for line in lines {
            if line.hasPrefix("Extracted: ") {
                let rest = String(line.dropFirst(11))
                // Remove "(source: xxx)" suffix if present
                if let parenIndex = rest.firstIndex(of: "(") {
                    return String(rest[..<parenIndex]).trimmingCharacters(in: .whitespaces)
                }
                return rest
            }
        }

        // Fallback: use filename
        return URL(fileURLWithPath: path).deletingPathExtension().lastPathComponent
            .replacingOccurrences(of: "-", with: " ")
            .capitalized
    }

    private func isValidYouTubeURL(_ url: String) -> Bool {
        let patterns = [
            "youtube.com/watch",
            "youtu.be/",
            "youtube.com/shorts/"
        ]
        return patterns.contains { url.contains($0) }
    }

    private func sendNotification(title: String, body: String) {
        // Skip if not in app bundle
        guard Bundle.main.bundleIdentifier != nil else { return }

        let content = UNMutableNotificationContent()
        content.title = title
        content.body = body
        content.sound = .default

        let request = UNNotificationRequest(
            identifier: UUID().uuidString,
            content: content,
            trigger: nil
        )

        UNUserNotificationCenter.current().add(request)
    }

    func cancelExtraction() {
        currentProcess?.terminate()
        currentProcess = nil
        isExtracting = false
        isBatchExtracting = false
        status = "Cancelled"
        statusIsError = false
    }

    // MARK: - Batch Extraction

    var isAnyExtracting: Bool {
        isExtracting || isBatchExtracting
    }

    func batchExtract() {
        guard !isAnyExtracting else { return }

        isBatchExtracting = true
        batchCurrent = 0
        batchTotal = 0
        batchSucceeded = 0
        batchSkipped = 0
        batchFailed = 0
        status = "Starting batch..."
        statusIsError = false

        Task {
            await runBatchExtraction()
        }
    }

    private func runBatchExtraction() async {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: pythonPath)
        process.arguments = [batchScriptPath]
        process.currentDirectoryURL = URL(fileURLWithPath: workingDirectory)

        let stdout = Pipe()
        let stderr = Pipe()
        process.standardOutput = stdout
        process.standardError = stderr

        currentProcess = process

        // Set up timeout
        let timeoutTask = Task {
            try await Task.sleep(nanoseconds: UInt64(batchTimeoutSeconds * 1_000_000_000))
            if process.isRunning {
                process.terminate()
            }
        }

        do {
            try process.run()

            // Read stdout line by line for progress
            let handle = stdout.fileHandleForReading
            handle.readabilityHandler = { [weak self] fileHandle in
                let data = fileHandle.availableData
                guard !data.isEmpty,
                      let line = String(data: data, encoding: .utf8) else { return }

                Task { @MainActor in
                    self?.parseBatchLine(line)
                }
            }

            process.waitUntilExit()
            timeoutTask.cancel()

            // Clean up handler
            handle.readabilityHandler = nil

            // Final status
            handleBatchResult()
        } catch {
            status = "Error: \(error.localizedDescription)"
            statusIsError = true
            isBatchExtracting = false
        }

        currentProcess = nil
    }

    private func parseBatchLine(_ line: String) {
        // Parse progress: [3/10]
        if let openBracket = line.firstIndex(of: "["),
           let slash = line.firstIndex(of: "/"),
           let closeBracket = line.firstIndex(of: "]"),
           openBracket < slash, slash < closeBracket {
            let currentStr = line[line.index(after: openBracket)..<slash]
            let totalStr = line[line.index(after: slash)..<closeBracket]
            if let current = Int(currentStr), let total = Int(totalStr) {
                batchCurrent = current
                batchTotal = total
                status = "Processing \(batchCurrent)/\(batchTotal)..."
            }
        }

        // Track results
        if line.contains("→ Saved:") && !line.contains("Already exists") {
            batchSucceeded += 1
        }
        if line.contains("Already exists") || line.contains("Not a YouTube URL") {
            batchSkipped += 1
        }
        if line.contains("→ Error:") {
            batchFailed += 1
        }
    }

    private func handleBatchResult() {
        isBatchExtracting = false

        let total = batchSucceeded + batchSkipped + batchFailed
        if total == 0 {
            status = "No items to process"
            statusIsError = false
        } else if batchFailed == 0 {
            status = "Done: \(batchSucceeded) extracted, \(batchSkipped) skipped"
            statusIsError = false
            if batchSucceeded > 0 {
                sendNotification(title: "Batch Complete", body: "\(batchSucceeded) recipes extracted")
            }
        } else {
            status = "Done: \(batchSucceeded) ok, \(batchSkipped) skipped, \(batchFailed) failed"
            statusIsError = true
            sendNotification(title: "Batch Complete", body: "\(batchSucceeded) extracted, \(batchFailed) failed")
        }

        batchCurrent = 0
        batchTotal = 0
    }
}
