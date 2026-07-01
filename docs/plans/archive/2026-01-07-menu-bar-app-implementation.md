# Menu Bar App Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a SwiftUI menu bar app that triggers YouTube recipe extraction via the existing Python script.

**Architecture:** Menu bar icon opens a popover with URL input, extract button, status display, and history list. Calls `extract_recipe.py` as subprocess, parses output to track success/failure.

**Tech Stack:** SwiftUI, macOS 13+, SMAppService for login item, Process for Python bridge.

---

## Task 1: Modify Python Script for Machine-Readable Output

**Files:**
- Modify: `extract_recipe.py:146-151`

**Step 1: Add SAVED: output line**

In `extract_recipe.py`, change the save block (around line 146-149) to output a machine-readable line:

```python
    else:
        # Save to Obsidian
        filepath = save_recipe_to_obsidian(recipe_data, video_url, title, channel)
        print(f"\nSaved to: {filepath}")
        print(f"SAVED:{filepath}")
```

**Step 2: Verify the change works**

Run:
```bash
cd /Users/chaseeasterling/KitchenOS
.venv/bin/python extract_recipe.py --dry-run "https://www.youtube.com/watch?v=bJUiWdM__Qw" 2>&1 | head -5
```

Expected: Script runs without syntax errors (dry-run won't print SAVED: line, but verifies no breakage).

**Step 3: Commit**

```bash
git add extract_recipe.py
git commit -m "feat: add SAVED: output line for Swift app parsing"
```

---

## Task 2: Create Xcode Project Structure

**Files:**
- Create: `KitchenOSApp/` directory structure

**Step 1: Create project directory**

```bash
cd /Users/chaseeasterling/KitchenOS/.worktrees/menu-bar-app
mkdir -p KitchenOSApp/KitchenOSApp
```

**Step 2: Create Swift Package manifest (simpler than .xcodeproj)**

Create `KitchenOSApp/Package.swift`:

```swift
// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "KitchenOSApp",
    platforms: [.macOS(.v13)],
    targets: [
        .executableTarget(
            name: "KitchenOSApp",
            path: "KitchenOSApp"
        )
    ]
)
```

**Step 3: Commit**

```bash
git add KitchenOSApp/
git commit -m "chore: create Swift package structure"
```

---

## Task 3: Create HistoryItem Model

**Files:**
- Create: `KitchenOSApp/KitchenOSApp/HistoryItem.swift`

**Step 1: Write the model**

```swift
import Foundation

struct HistoryItem: Identifiable {
    let id = UUID()
    let recipeName: String
    let filePath: String
    let extractedAt: Date

    var timeAgo: String {
        let interval = Date().timeIntervalSince(extractedAt)
        if interval < 60 {
            return "just now"
        } else if interval < 3600 {
            let minutes = Int(interval / 60)
            return "\(minutes)m"
        } else {
            let hours = Int(interval / 3600)
            return "\(hours)h"
        }
    }
}
```

**Step 2: Verify it compiles**

```bash
cd /Users/chaseeasterling/KitchenOS/.worktrees/menu-bar-app/KitchenOSApp
swift build 2>&1 | tail -5
```

Expected: Build will fail (no main entry point yet) but HistoryItem.swift should have no syntax errors.

**Step 3: Commit**

```bash
git add KitchenOSApp/KitchenOSApp/HistoryItem.swift
git commit -m "feat: add HistoryItem model"
```

---

## Task 4: Create ExtractionManager

**Files:**
- Create: `KitchenOSApp/KitchenOSApp/ExtractionManager.swift`

**Step 1: Write the manager class**

```swift
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

        do {
            try process.run()

            // Wait with timeout
            let timeoutTask = Task {
                try await Task.sleep(for: .seconds(300)) // 5 minutes
                process.terminate()
            }

            process.waitUntilExit()
            timeoutTask.cancel()

            let stdoutData = stdoutPipe.fileHandleForReading.readDataToEndOfFile()
            let stderrData = stderrPipe.fileHandleForReading.readDataToEndOfFile()
            let stdout = String(data: stdoutData, encoding: .utf8) ?? ""
            let stderr = String(data: stderrData, encoding: .utf8) ?? ""

            if process.terminationStatus == 0, let savedLine = stdout.components(separatedBy: "\n").first(where: { $0.hasPrefix("SAVED:") }) {
                let filePath = String(savedLine.dropFirst(6))
                let recipeName = extractRecipeName(from: filePath)

                let item = HistoryItem(recipeName: recipeName, filePath: filePath, extractedAt: Date())
                history.insert(item, at: 0)
                if history.count > 10 {
                    history.removeLast()
                }

                status = .success(recipeName)
                sendNotification(title: "Recipe Saved", body: recipeName)

                // Reset to idle after 3 seconds
                Task {
                    try? await Task.sleep(for: .seconds(3))
                    if case .success = self.status {
                        self.status = .idle
                    }
                }
            } else {
                let errorMessage = stderr.isEmpty ? "Extraction failed" : stderr.components(separatedBy: "\n").first ?? "Extraction failed"
                status = .error(errorMessage)
            }
        } catch {
            status = .error("Failed to start extraction: \(error.localizedDescription)")
        }

        currentProcess = nil
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
```

**Step 2: Verify no syntax errors**

```bash
cd /Users/chaseeasterling/KitchenOS/.worktrees/menu-bar-app/KitchenOSApp
swift build 2>&1 | grep -i error | head -5
```

Expected: May fail due to missing main, but no errors in ExtractionManager.swift itself.

**Step 3: Commit**

```bash
git add KitchenOSApp/KitchenOSApp/ExtractionManager.swift
git commit -m "feat: add ExtractionManager for Python bridge"
```

---

## Task 5: Create ContentView

**Files:**
- Create: `KitchenOSApp/KitchenOSApp/ContentView.swift`

**Step 1: Write the view**

```swift
import SwiftUI
import ServiceManagement

struct ContentView: View {
    @StateObject private var manager = ExtractionManager()
    @State private var urlInput = ""
    @AppStorage("launchAtLogin") private var launchAtLogin = true

    var body: some View {
        VStack(spacing: 12) {
            // URL Input
            HStack {
                TextField("YouTube URL", text: $urlInput)
                    .textFieldStyle(.roundedBorder)
                    .onSubmit(extract)
            }

            // Extract Button
            Button(action: extract) {
                HStack {
                    if case .extracting = manager.status {
                        ProgressView()
                            .scaleEffect(0.7)
                            .frame(width: 16, height: 16)
                    }
                    Text("Extract Recipe")
                }
                .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            .disabled(isExtracting)

            Divider()

            // Status
            HStack {
                Text("Status:")
                    .foregroundColor(.secondary)
                Spacer()
                statusText
            }
            .font(.caption)

            // History
            if !manager.history.isEmpty {
                Divider()

                VStack(alignment: .leading, spacing: 4) {
                    Text("Recent:")
                        .font(.caption)
                        .foregroundColor(.secondary)

                    ForEach(manager.history) { item in
                        Button(action: { manager.openInObsidian(item: item) }) {
                            HStack {
                                Text(item.recipeName)
                                    .lineLimit(1)
                                Spacer()
                                Text(item.timeAgo)
                                    .foregroundColor(.secondary)
                            }
                        }
                        .buttonStyle(.plain)
                        .font(.caption)
                    }
                }
            }

            Divider()

            // Settings
            Toggle("Launch at Login", isOn: $launchAtLogin)
                .font(.caption)
                .onChange(of: launchAtLogin) { _, newValue in
                    updateLoginItem(enabled: newValue)
                }
        }
        .padding()
        .frame(width: 280)
        .onAppear {
            requestNotificationPermission()
        }
    }

    private var isExtracting: Bool {
        if case .extracting = manager.status { return true }
        return false
    }

    @ViewBuilder
    private var statusText: some View {
        switch manager.status {
        case .idle:
            Text("Ready")
                .foregroundColor(.secondary)
        case .extracting:
            Text("Extracting...")
                .foregroundColor(.orange)
        case .success(let name):
            Text("Saved: \(name)")
                .foregroundColor(.green)
                .lineLimit(1)
        case .error(let message):
            Text(message)
                .foregroundColor(.red)
                .lineLimit(1)
                .onTapGesture {
                    manager.resetError()
                }
        }
    }

    private func extract() {
        manager.extract(url: urlInput)
        urlInput = ""
    }

    private func updateLoginItem(enabled: Bool) {
        do {
            if enabled {
                try SMAppService.mainApp.register()
            } else {
                try SMAppService.mainApp.unregister()
            }
        } catch {
            print("Failed to update login item: \(error)")
        }
    }

    private func requestNotificationPermission() {
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound]) { _, _ in }
    }
}
```

**Step 2: Commit**

```bash
git add KitchenOSApp/KitchenOSApp/ContentView.swift
git commit -m "feat: add ContentView with URL input, status, and history"
```

---

## Task 6: Create App Entry Point

**Files:**
- Create: `KitchenOSApp/KitchenOSApp/KitchenOSApp.swift`

**Step 1: Write the app main**

```swift
import SwiftUI

@main
struct KitchenOSApp: App {
    var body: some Scene {
        MenuBarExtra("KitchenOS", systemImage: "fork.knife") {
            ContentView()
        }
        .menuBarExtraStyle(.window)
    }
}
```

**Step 2: Build the app**

```bash
cd /Users/chaseeasterling/KitchenOS/.worktrees/menu-bar-app/KitchenOSApp
swift build
```

Expected: Build succeeds.

**Step 3: Commit**

```bash
git add KitchenOSApp/KitchenOSApp/KitchenOSApp.swift
git commit -m "feat: add menu bar app entry point"
```

---

## Task 7: Test the App

**Step 1: Run the app**

```bash
cd /Users/chaseeasterling/KitchenOS/.worktrees/menu-bar-app/KitchenOSApp
swift run
```

Expected: Fork and knife icon appears in menu bar. Click it to open popover.

**Step 2: Manual verification checklist**

- [ ] Menu bar icon appears
- [ ] Popover opens on click
- [ ] URL field accepts input
- [ ] Button says "Extract Recipe"
- [ ] "Launch at Login" toggle exists
- [ ] Status shows "Ready"

**Step 3: Test extraction (requires Ollama running)**

1. Paste a YouTube cooking video URL
2. Click "Extract Recipe"
3. Verify spinner appears
4. Wait for completion
5. Check notification appears
6. Check history list shows the recipe
7. Click history item, verify file opens

---

## Task 8: Build Release Binary

**Step 1: Build release version**

```bash
cd /Users/chaseeasterling/KitchenOS/.worktrees/menu-bar-app/KitchenOSApp
swift build -c release
```

**Step 2: Locate binary**

```bash
ls -la .build/release/KitchenOSApp
```

**Step 3: Copy to Applications (optional)**

```bash
cp .build/release/KitchenOSApp /Applications/KitchenOSApp
```

**Step 4: Final commit**

```bash
git add -A
git commit -m "feat: complete menu bar app implementation"
```

---

## Task 9: Merge to Main

**Step 1: Switch to main and merge**

```bash
cd /Users/chaseeasterling/KitchenOS
git checkout main
git merge feature/menu-bar-app
```

**Step 2: Clean up worktree**

```bash
git worktree remove .worktrees/menu-bar-app
git branch -d feature/menu-bar-app
```

**Step 3: Final verification**

```bash
cd KitchenOSApp
swift build
swift run
```

---

## Summary

| Task | Description | Key Files |
|------|-------------|-----------|
| 1 | Add SAVED: output to Python | extract_recipe.py |
| 2 | Create Swift package structure | Package.swift |
| 3 | HistoryItem model | HistoryItem.swift |
| 4 | ExtractionManager (Python bridge) | ExtractionManager.swift |
| 5 | ContentView (UI) | ContentView.swift |
| 6 | App entry point | KitchenOSApp.swift |
| 7 | Manual testing | - |
| 8 | Release build | - |
| 9 | Merge to main | - |
