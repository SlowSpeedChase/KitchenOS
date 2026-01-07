# App-Specific Workflow Configurations

## 🤖 AI Chat Applications

### ChatGPT (Web - chat.openai.com)

**Macro Name:** `YouTube-to-ChatGPT`

**Detailed Steps:**
1. **Get Variable** `YouTubeVideoInfo` → Clipboard
2. **Activate Application** "Google Chrome" (or preferred browser)
3. **New Tab** → ⌘T
4. **Navigate** → Type `https://chat.openai.com` + Return
5. **Wait for Load** → Pause 3 seconds
6. **Find Input** → One of these methods:
   - **Image Search**: Screenshot the text input area
   - **UI Element**: Look for textarea with placeholder "Message ChatGPT"
   - **Coordinates**: Click at relative position (50% width, 90% height)
7. **Click** → On found input area
8. **Paste** → ⌘V
9. **Optional Submit** → Return or click Send button

**Pro Tips:**
- Add a prefix prompt: "Please analyze this YouTube video information: " before pasting
- Use Found Image condition to wait for page load
- Store ChatGPT URL as a variable for easy changes

### Claude (Web - claude.ai)

**Macro Name:** `YouTube-to-Claude`

**Similar to ChatGPT but:**
- URL: `https://claude.ai`
- Look for "Talk to Claude..." placeholder
- May need different wait times

### Perplexity AI

**Macro Name:** `YouTube-to-Perplexity`

- URL: `https://perplexity.ai`
- Input area is usually center-page
- Great for follow-up research on video topics

## 📝 Note-Taking Applications

### Apple Notes

**Macro Name:** `YouTube-to-Notes`

**Steps:**
1. **Activate** "Notes"
2. **New Note** → ⌘N
3. **Title** → Type `YouTube: %Variable%YouTubeVideoID%`
4. **Move to Body** → Tab or Return
5. **Paste Content** → ⌘V
6. **Save** → ⌘S (auto-saves but good practice)

### Obsidian

**Macro Name:** `YouTube-to-Obsidian`

**Advanced Template:**
```markdown
# 🎥 {{title}}

**Video ID:** {{videoId}}
**Source:** {{sourceUrl}}  
**Processed:** {{date}}
**Tags:** #youtube #video-analysis

---

## 📋 Content

{{content}}

---

## 💭 My Notes

<!-- Add your analysis here -->

## 🔗 Related
<!-- Link to other notes -->
```

**Steps:**
1. **Activate** "Obsidian"
2. **New Note** → ⌘N
3. **Insert Template** → Use above markdown template
4. **Replace Variables** → Use KM text replacement
5. **Position Cursor** → In "My Notes" section for immediate use

### Notion

**Macro Name:** `YouTube-to-Notion`

**Database Template Approach:**
1. **Open Notion**
2. **Navigate to Database** → Use bookmarked page
3. **New Entry** → Click "New" or use shortcut
4. **Fill Properties:**
   - Title: Video ID
   - URL: Source URL
   - Content: Full output
   - Date: Current date
   - Status: "To Review"

### Roam Research / LogSeq

**Similar markdown approach with different shortcuts**

## 💬 Communication Apps

### Discord (for team sharing)

**Macro Name:** `YouTube-to-Discord`

**Use Case:** Share video analysis with team

**Steps:**
1. **Activate** Discord
2. **Navigate to Channel** → Use ⌘K quick switcher
3. **Type Channel Name** → e.g., "#video-research"
4. **Click in Message Area**
5. **Format Message:**
   ```
   🎥 **New YouTube Analysis**
   Video: %Variable%YouTubeVideoID%
   ```
6. **Code Block** → Type ``` and paste content
7. **Send** → Return

### Slack

**Similar to Discord but with threading:**
- Post initial message
- Use "Reply in thread" for full content
- Tag relevant team members

## 🔄 Automation Workflows

### Multi-App Distribution

**Macro Name:** `YouTube-to-MultipleApps`

**Concept:** Send the same content to multiple destinations

**Implementation:**
1. **Choice Dialog** → Checkboxes for multiple apps
2. **For Each Selected App** → Run corresponding macro
3. **Progress Indicator** → Show which app is being processed

### Content Processing Pipeline

**Macro Name:** `YouTube-ProcessingPipeline`

**Advanced Workflow:**
1. **Get Video Info** → Run YouTube script
2. **AI Summary** → Send to ChatGPT for summary
3. **Store Original** → Save to Notes
4. **Create Tasks** → Add action items to task manager
5. **Share Summary** → Post to team chat

## 🎯 Specialized Use Cases

### Research Workflow

**For Academic/Professional Research:**

1. **YouTube Script** → Get video info
2. **Research Database** → Store in Airtable/Notion database
3. **Citation Format** → Generate proper citation
4. **Bibliography** → Add to Zotero/EndNote
5. **Summary** → Create executive summary

### Content Creation Workflow

**For Content Creators:**

1. **Analyze Competitor Video**
2. **Extract Key Points** → Send to idea collection
3. **Content Calendar** → Schedule follow-up content
4. **Script Outline** → Generate response video outline

### Learning Workflow

**For Educational Content:**

1. **Get Transcript**
2. **Flashcard Generation** → Send to Anki
3. **Mind Map** → Create in MindMeister
4. **Quiz Creation** → Generate comprehension questions

## 🛠️ Implementation Priority

**Start with these macros first:**
1. `YouTube-to-ChatGPT` (most versatile)
2. `YouTube-to-Notes` (simplest, always works)
3. `YouTube-to-TextEdit` (fallback option)

**Then add based on your workflow:**
4. Your preferred note-taking app
5. Team communication app
6. Specialized workflows

## 🧪 Testing Approach

1. **Manual Test First** → Run each step manually
2. **Simple Automation** → Start with basic click/type
3. **Add Intelligence** → Image recognition, error handling
4. **Polish UI** → Better feedback, progress indicators
5. **Create Shortcuts** → Hotkeys for frequent use
