# KitchenOS Menu Bar App Design

## Overview

A lightweight SwiftUI menu bar app for triggering recipe extraction from YouTube videos. Lives in the macOS menu bar, provides a simple interface to paste URLs, shows extraction status, and maintains a session history of extracted recipes.

## Requirements

- Menu bar app with popover UI (not a full window)
- Paste YouTube URL and trigger extraction
- Background processing with spinner, macOS notification when done
- Session-only history (clears on quit)
- Click history items to open recipes in Obsidian
- Launch at Login enabled by default

## Architecture

### Components

1. **Menu Bar Icon + Popover** - SF Symbol icon (`fork.knife` or similar), clicking opens popover
2. **SwiftUI Views** - URL input, extract button, status area, history list
3. **Python Bridge** - Calls existing `extract_recipe.py` via `Process()`

### Project Structure

```
KitchenOS/
├── extract_recipe.py      ← add SAVED: output line
├── main.py                ← unchanged
├── prompts/               ← unchanged
├── templates/             ← unchanged
├── .venv/                 ← unchanged
│
└── KitchenOSApp/          ← new Swift project
    ├── KitchenOSApp.xcodeproj
    └── KitchenOSApp/
        ├── KitchenOSApp.swift       ← @main entry, menu bar setup
        ├── ContentView.swift        ← popover UI
        ├── ExtractionManager.swift  ← runs Python, manages state
        ├── HistoryItem.swift        ← model for history list
        └── Assets.xcassets          ← app icon
```

## User Interface

Popover is ~300px wide, height adjusts to content.

```
┌─────────────────────────────┐
│  [YouTube URL field     ]   │
│  [    Extract Recipe    ]   │
├─────────────────────────────┤
│  Status: Ready              │  ← or spinner + "Extracting..."
├─────────────────────────────┤
│  Recent:                    │
│  • Pasta Aglio e Olio  2m   │  ← click opens in Obsidian
│  • Thai Green Curry   15m   │
├─────────────────────────────┤
│  [x] Launch at Login        │
└─────────────────────────────┘
```

### Behavior

- Paste URL, press Enter or click button to start
- Button disables during extraction, spinner appears
- When done: macOS notification, status shows success, item added to history
- On error: status shows error in red, no history entry
- Click history item: opens markdown file in Obsidian
- History shows last ~10 items, newest at top

## Python Integration

### Launching the Script

```swift
let process = Process()
process.executableURL = URL(fileURLWithPath: "/Users/chaseeasterling/KitchenOS/.venv/bin/python")
process.arguments = ["extract_recipe.py", youtubeURL]
process.currentDirectoryURL = URL(fileURLWithPath: "/Users/chaseeasterling/KitchenOS")
```

### Output Parsing

Script change needed - add final print when saving succeeds:
```python
print(f"SAVED: {filepath}")
```

Swift parses stdout for `SAVED: /path/to/file.md` line to determine success and extract filename for history.

### Success/Failure

- Exit code 0 + "SAVED:" line = success
- Non-zero exit or missing "SAVED:" = failure, show stderr

## Launch at Login

- Uses `SMAppService` API
- Toggle in settings row at bottom of popover
- Default: enabled
- Persists via `UserDefaults`

## Error Handling

| Scenario | Response |
|----------|----------|
| Ollama not running | Status: "Error: Ollama not running" |
| Invalid YouTube URL | Status: "Error: Invalid YouTube URL" |
| No transcript | Script handles fallback, app waits |
| Script timeout (5 min) | Status: "Error: Extraction timed out", kill process |
| Extract while running | Button disabled, one at a time |
| Popover closed during extraction | Continues in background, notification fires |

## Build & Run

1. Open `KitchenOSApp.xcodeproj` in Xcode
2. Build: Cmd+B
3. Run: Cmd+R
4. Or archive for standalone `.app`
