# 🚀 Complete Keyboard Maestro Integration Setup

## 📋 Overview

This setup will allow you to:
1. **Fetch YouTube video info** with your Python script
2. **Automatically pass the output** to Keyboard Maestro
3. **Have KM click through any app's UI** to paste the content
4. **Support multiple target applications** (ChatGPT, Notes, Obsidian, etc.)

## 🛠️ Step-by-Step Setup

### Phase 1: Test Basic Integration

#### 1.1 Verify Keyboard Maestro is Running
```bash
# Run this test script
osascript test_km_integration.applescript
```

#### 1.2 Create Your First Test Macro
1. **Open Keyboard Maestro Editor**
2. **Create new macro** with these settings:
   - **Name:** `KM-Test-Basic`
   - **Trigger:** Script trigger with script name: `KM-Test-Basic`
   - **Action:** Display Text in Window
   - **Text:** `Success! Integration working!`

#### 1.3 Test the Connection
```bash
# This should trigger your test macro
osascript -e 'tell application "Keyboard Maestro Engine" to do script "KM-Test-Basic"'
```

### Phase 2: Create Production Macros

#### 2.1 ChatGPT Integration Macro

**Macro Name:** `YouTube-to-ChatGPT`

**Actions Sequence:**
```
1. Get Variable "YouTubeVideoInfo" → Store in clipboard
2. Activate Application "Google Chrome" (or your browser)
3. Press Key ⌘T (new tab)
4. Type Text "https://chat.openai.com"
5. Press Key Return
6. Pause 3 seconds (wait for load)
7. Click at Found Image [ChatGPT input area screenshot]
8. Type Text "Please analyze this YouTube video information:\n\n"
9. Paste from Clipboard
10. Optional: Press Key Return (auto-submit)
```

**📸 Image Setup:**
- Screenshot the ChatGPT text input area
- Save as "ChatGPT-Input-Area.png"
- Use in "Click at Found Image" action

#### 2.2 Notes App Integration Macro

**Macro Name:** `YouTube-to-Notes`

**Actions Sequence:**
```
1. Get Variable "YouTubeVideoInfo" → Store in clipboard  
2. Get Variable "YouTubeVideoID" → Store in variable "VideoID"
3. Activate Application "Notes"
4. Press Key ⌘N (new note)
5. Type Text "YouTube Analysis - %Variable%VideoID%"
6. Press Key Return (move to body)
7. Paste from Clipboard
8. Press Key ⌘S (save)
```

#### 2.3 Generic Text App Macro

**Macro Name:** `YouTube-to-TextEdit`

**Actions Sequence:**
```
1. Get Variable "YouTubeVideoInfo" → Store in clipboard
2. Activate Application "TextEdit"  
3. Press Key ⌘N (new document)
4. Paste from Clipboard
5. Press Key ⌘S (save)
6. Type Text "YouTube_Info_%ICUDateTime%yyyyMMdd_HHmmss%.txt"
7. Press Key Return
```

### Phase 3: Advanced App-Specific Macros

#### 3.1 Obsidian with Templating

**Template Creation:**
```markdown
# 🎥 YouTube Analysis

**Video ID:** %Variable%YouTubeVideoID%
**Source:** %Variable%YouTubeSourceURL%  
**Date:** %ICUDateTime%yyyy-MM-dd HH:mm%
**Tags:** #youtube #video-analysis

---

%Variable%YouTubeVideoInfo%

---

## 💭 My Analysis
<!-- Add your thoughts here -->
```

#### 3.2 Discord Team Sharing

**For sharing video analysis with team:**
```
1. Activate Application "Discord"
2. Press Key ⌘K (quick switcher)
3. Type Text "video-research" (your channel name)
4. Press Key Return
5. Type Text "🎥 **YouTube Analysis**\nVideo: %Variable%YouTubeVideoID%\n```"
6. Paste from Clipboard  
7. Type Text "```"
8. Press Key Return
```

### Phase 4: Test Your Complete Workflow

#### 4.1 Run the Integration Script
```bash
osascript youtube_to_km.applescript
```

#### 4.2 Full Workflow Test:
1. **Copy a YouTube URL** to clipboard
2. **Run the script** - URL should auto-populate
3. **Choose target app** from dialog
4. **Watch the magic happen** ✨

## 📱 App-Specific UI Navigation

### ChatGPT Web Interface
- **Input Area Detection:** Look for "Message ChatGPT..." placeholder
- **Alternative:** Click at coordinates (50% width, 85% height)
- **Submit Options:** 
  - Return key (immediate send)
  - Shift+Return (new line, manual send)

### Claude Web Interface
- **URL:** `https://claude.ai`
- **Input Detection:** "Talk to Claude..." placeholder
- **Usually more reliable** than ChatGPT for automation

### Notion
- **New Page:** ⌘N
- **Database Entry:** Navigate to specific database first
- **Template Usage:** Set up page templates for consistency

### Obsidian
- **New Note:** ⌘N
- **Template Insertion:** Use community plugins for templating
- **Vault Navigation:** Use ⌘O (quick switcher)

## 🔧 Troubleshooting Guide

### Common Issues:

#### "Macro doesn't trigger"
- ✅ Check Keyboard Maestro Engine is running
- ✅ Verify exact macro name spelling
- ✅ Ensure macro is enabled
- ✅ Test manual trigger first

#### "Variables not passing"
- ✅ Check variable names match exactly
- ✅ Verify AppleScript syntax
- ✅ Test with simple text first

#### "App doesn't respond correctly"
- ✅ Add longer pause times
- ✅ Use image detection instead of coordinates
- ✅ Check app-specific shortcuts
- ✅ Test UI navigation manually first

#### "Image detection fails"
- ✅ Re-screenshot UI elements
- ✅ Adjust match tolerance
- ✅ Use multiple similar images
- ✅ Fall back to coordinate clicking

## 🎯 Optimization Tips

### Performance:
- **Cache common apps** in dock for faster activation
- **Use keyboard shortcuts** instead of mouse clicks when possible
- **Group related actions** in sub-macros
- **Add progress indicators** for long operations

### Reliability:
- **Always add pauses** after app activation
- **Use conditional logic** for different app states
- **Create fallback actions** for failed image detection
- **Test across different screen resolutions**

### User Experience:
- **Add progress dialogs** for multi-step operations
- **Provide clear error messages** when things fail
- **Create keyboard shortcuts** for frequent workflows
- **Log successful operations** for debugging

## 🚀 Next Steps

1. **Start with basic test macro**
2. **Add your most-used app** (probably ChatGPT)
3. **Test thoroughly** with different videos
4. **Gradually add more apps**
5. **Create shortcuts** for frequent workflows
6. **Share templates** with others!

## 📚 Files Reference

- `youtube_to_km.applescript` - Main integration script
- `test_km_integration.applescript` - Test connection
- `km_macro_templates.md` - Detailed macro templates
- `app_specific_workflows.md` - App-specific configurations
- `km_basic_test_macro.txt` - Simple macro to get started

**You're now ready to automate your YouTube video analysis workflow! 🎉**
