import Foundation
import UserNotifications

enum ExtractionStatus: Equatable {
    case idle
    case extracting
    case success(String)
    case error(String)
}

@MainActor
class ExtractionManager: ObservableObject {
    @Published var status: ExtractionStatus = .idle
    @Published var history: [HistoryItem] = []

    private let pythonPath = "/Users/chaseeasterling/KitchenOS/.venv/bin/python"
    private let scriptPath = "/Users/chaseeasterling/KitchenOS/extract_recipe.py"
    private let workingDir = "/Users/chaseeasterling/KitchenOS"

    private var currentProcess: Process?

    func extract(url: String) {
        guard case .idle = status else { return }
        guard !url.isEmpty else {
            status = .error("Please enter a URL")
            return
        }

        status = .extracting

        Task {
            await runExtraction(url: url)
        }
    }

    private func runExtraction(url: String) async {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: pythonPath)
        process.arguments = [scriptPath, url]
        process.currentDirectoryURL = URL(fileURLWithPath: workingDir)

        let stdoutPipe = Pipe()
        let stderrPipe = Pipe()
        process.standardOutput = stdoutPipe
        process.standardError = stderrPipe

        currentProcess = process

        // Run blocking work off MainActor
        let result: (status: Int32, stdout: String, stderr: String) = await Task.detached {
            do {
                try process.run()

                // Timeout handling
                let timeoutTask = Task {
                    try await Task.sleep(for: .seconds(300))
                    if process.isRunning {
                        process.terminate()
                    }
                }

                process.waitUntilExit()
                timeoutTask.cancel()

                let stdoutData = stdoutPipe.fileHandleForReading.readDataToEndOfFile()
                let stderrData = stderrPipe.fileHandleForReading.readDataToEndOfFile()
                let stdout = String(data: stdoutData, encoding: .utf8) ?? ""
                let stderr = String(data: stderrData, encoding: .utf8) ?? ""

                return (process.terminationStatus, stdout, stderr)
            } catch {
                return (-1, "", "Failed to start: \(error.localizedDescription)")
            }
        }.value

        currentProcess = nil

        // Now back on MainActor, update UI safely
        if result.status == 0, let savedLine = result.stdout.components(separatedBy: "\n").first(where: { $0.hasPrefix("SAVED:") }) {
            let filePath = String(savedLine.dropFirst(6))
            let recipeName = extractRecipeName(from: filePath)

            let item = HistoryItem(recipeName: recipeName, filePath: filePath, extractedAt: Date())
            history.insert(item, at: 0)
            if history.count > 10 {
                history.removeLast()
            }

            status = .success(recipeName)
            sendNotification(title: "Recipe Saved", body: recipeName)

            Task {
                try? await Task.sleep(for: .seconds(3))
                if case .success = self.status {
                    self.status = .idle
                }
            }
        } else {
            let errorMessage = result.stderr.isEmpty ? "Extraction failed" : result.stderr.components(separatedBy: "\n").first ?? "Extraction failed"
            status = .error(errorMessage)
        }
    }

    private func extractRecipeName(from filePath: String) -> String {
        let filename = URL(fileURLWithPath: filePath).deletingPathExtension().lastPathComponent
        // Remove date prefix (YYYY-MM-DD-)
        if filename.count > 11 && filename.prefix(4).allSatisfy({ $0.isNumber }) {
            return String(filename.dropFirst(11)).replacingOccurrences(of: "-", with: " ").capitalized
        }
        return filename.replacingOccurrences(of: "-", with: " ").capitalized
    }

    private func sendNotification(title: String, body: String) {
        let content = UNMutableNotificationContent()
        content.title = title
        content.body = body
        content.sound = .default

        let request = UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil)
        UNUserNotificationCenter.current().add(request)
    }

    func openInObsidian(item: HistoryItem) {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/open")
        process.arguments = [item.filePath]
        try? process.run()
    }

    func resetError() {
        if case .error = status {
            status = .idle
        }
    }
}
