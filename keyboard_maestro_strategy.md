# Keyboard Maestro Integration Strategy

## Overview
This strategy will capture the YouTube video info output and automatically paste it into another application using Keyboard Maestro macros.

## Workflow Options

### Option 1: Direct AppleScript to App Integration
1. **YouTube Script** → **Clipboard** → **Keyboard Maestro Trigger** → **Target App**

### Option 2: File-Based Integration  
1. **YouTube Script** → **Temp File** → **Keyboard Maestro File Watch** → **Target App**

### Option 3: URL Scheme Integration
1. **YouTube Script** → **Custom URL** → **Keyboard Maestro URL Trigger** → **Target App**

## Detailed Implementation

### Strategy 1: Clipboard + Hotkey Trigger (Recommended)

#### Step 1: Modified AppleScript
- Script copies output to clipboard
- Script triggers a specific Keyboard Maestro macro via URL scheme
- Keyboard Maestro handles the app switching and pasting

#### Step 2: Keyboard Maestro Macro Setup
1. **Trigger**: URL trigger or hotkey
2. **Actions**:
   - Activate target application
   - Navigate to text input field
   - Paste clipboard content
   - Format if needed

### Strategy 2: Named Clipboard Integration

#### Benefits:
- Multiple clipboard support
- More reliable than system clipboard
- Can store metadata

#### Implementation:
- AppleScript stores output in named Keyboard Maestro clipboard
- Keyboard Maestro macro retrieves from named clipboard
- More control over data flow

## Target Applications Examples

### For ChatGPT/Claude (Web)
1. Open browser
2. Navigate to chat interface
3. Click in text area
4. Paste content
5. Optionally submit

### For Native Apps
1. Activate application
2. Use keyboard shortcuts to open new document/prompt
3. Paste content
4. Format as needed

### For Note-Taking Apps
1. Open app (Notes, Obsidian, Notion)
2. Create new note
3. Add title with video ID/URL
4. Paste content
5. Save/organize

## Implementation Files Created:
- `youtube_to_km.applescript` - Enhanced script with KM integration
- `km_macro_templates.md` - Keyboard Maestro macro templates
- `app_specific_workflows.md` - Specific workflows for popular apps
