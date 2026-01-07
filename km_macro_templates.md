# Keyboard Maestro Macro Templates

## Required Macros to Create

### 1. YouTube-to-ChatGPT Macro

**Trigger:** Script trigger (name: "YouTube-to-ChatGPT")

**Actions:**
1. **Get Variable** → `YouTubeVideoInfo` → Store in clipboard
2. **Activate Application** → "Google Chrome" (or your browser)
3. **Pause** → 0.5 seconds
4. **Press Key** → ⌘T (new tab)
5. **Type Text** → `https://chat.openai.com` (or Claude URL)
6. **Press Key** → Return
7. **Pause** → 3 seconds (wait for page load)
8. **Click at Found Image** → [Screenshot of text input area]
   - Or use **Click at Coordinates** if consistent
9. **Paste from Clipboard**
10. **Optional: Press Key** → Return (to submit)

### 2. YouTube-to-Notes Macro

**Trigger:** Script trigger (name: "YouTube-to-Notes")

**Actions:**
1. **Get Variable** → `YouTubeVideoInfo` → Store in clipboard
2. **Get Variable** → `YouTubeVideoID` → Store in variable "VideoID"
3. **Activate Application** → "Notes"
4. **Pause** → 0.5 seconds
5. **Press Key** → ⌘N (new note)
6. **Type Text** → `YouTube Analysis - %Variable%VideoID%`
7. **Press Key** → Return (move to body)
8. **Paste from Clipboard**
9. **Press Key** → ⌘S (save)

### 3. YouTube-to-Obsidian Macro

**Trigger:** Script trigger (name: "YouTube-to-Obsidian")

**Actions:**
1. **Get Variable** → `YouTubeVideoInfo` → Store in clipboard
2. **Get Variable** → `YouTubeVideoID` → Store in variable "VideoID"
3. **Get Variable** → `YouTubeSourceURL` → Store in variable "SourceURL"
4. **Activate Application** → "Obsidian"
5. **Pause** → 0.5 seconds
6. **Press Key** → ⌘N (new note)
7. **Type Text** → `# YouTube: %Variable%VideoID%

Source: %Variable%SourceURL%
Date: %ICUDateTime%yyyy-MM-dd HH:mm%

---

`
8. **Paste from Clipboard**
9. **Press Key** → ⌘S (save)

### 4. YouTube-to-TextEdit Macro

**Trigger:** Script trigger (name: "YouTube-to-TextEdit")

**Actions:**
1. **Get Variable** → `YouTubeVideoInfo` → Store in clipboard  
2. **Activate Application** → "TextEdit"
3. **Press Key** → ⌘N (new document)
4. **Paste from Clipboard**
5. **Press Key** → ⌘S (save)
6. **Type Text** → `YouTube_Info_%ICUDateTime%yyyyMMdd_HHmmss%.txt`
7. **Press Key** → Return

## Advanced Template: Multi-App Chooser

### YouTube-to-MultiApp Macro

**Trigger:** Script trigger (name: "YouTube-to-Custom")

**Actions:**
1. **Prompt for User Input** → 
   - Title: "Choose Destination"
   - Options: "ChatGPT|Notes|Obsidian|TextEdit|Notion"
   - Store in variable "TargetApp"
2. **Switch/Case based on TargetApp variable:**
   - **If Text** `%Variable%TargetApp%` **contains** "ChatGPT" → Execute Macro "YouTube-to-ChatGPT"
   - **If Text** `%Variable%TargetApp%` **contains** "Notes" → Execute Macro "YouTube-to-Notes"  
   - **If Text** `%Variable%TargetApp%` **contains** "Obsidian" → Execute Macro "YouTube-to-Obsidian"
   - **If Text** `%Variable%TargetApp%` **contains** "TextEdit" → Execute Macro "YouTube-to-TextEdit"

## App-Specific Coordinate/Image Templates

### ChatGPT Web Interface
- **Text Input Area**: Look for the text "Message ChatGPT..." 
- **Alternative**: Click at coordinates (usually bottom center of window)
- **Submit Button**: Look for "Send" button or use Shift+Return

### Claude Web Interface  
- **Text Input Area**: Look for placeholder text
- **Submit**: Usually Enter key

### Notion
- **New Page**: ⌘N
- **Title Area**: Usually auto-focused on new page
- **Body**: Tab or click in content area

### Discord (if using for notes)
- **Message Input**: Click at bottom text area
- **Send**: Just Enter

## Macro Creation Steps

1. **Open Keyboard Maestro Editor**
2. **Create New Macro Group** (optional): "YouTube Integration"
3. **For each template above:**
   - Click "New Macro"
   - Set name (e.g., "YouTube-to-ChatGPT")
   - Add "Script" trigger
   - Add actions as listed
   - Test with manual trigger first

## Testing Strategy

1. **Create a simple test macro first:**
   ```
   Trigger: Script trigger "test-km"
   Action: Display Text "Keyboard Maestro is working!"
   ```

2. **Test from AppleScript:**
   ```applescript
   do shell script "osascript -e 'tell application \"Keyboard Maestro Engine\" to do script \"test-km\"'"
   ```

3. **Gradually add complexity**

## Variables Available from AppleScript

- `YouTubeVideoInfo` - Full formatted output
- `YouTubeVideoID` - Just the video ID
- `YouTubeSourceURL` - Original URL/ID input

Use these in your macros with `%Variable%YouTubeVideoInfo%` syntax.
