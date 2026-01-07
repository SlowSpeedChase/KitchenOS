# YouTube to Obsidian Recipe Extraction Pipeline

**Date:** 2026-01-07
**Status:** Design Complete - Ready for Implementation

## Overview

A pipeline that captures YouTube cooking videos, extracts structured recipe data using AI, and writes formatted markdown files to an Obsidian vault for browsing with Dataview.

### Core Flow

```
YouTube URL → n8n → Python transcript fetcher → AI extraction → Obsidian markdown file
```

### Problem Solved

Cooking videos often lack written recipes. This system:
- Extracts recipes from videos where someone is just cooking and talking (no recipe card)
- Cleans up recipes buried in video descriptions with sponsor noise
- Creates a searchable, structured recipe database in Obsidian

## Architecture

### Components

| Component | Purpose | Status |
|-----------|---------|--------|
| Python script (`main.py`) | Fetches transcript + description from YouTube | Exists - needs `--json` mode |
| n8n | Orchestrates pipeline, handles triggers | Running locally |
| Ollama | Local LLM for recipe extraction | Installed |
| Claude API | Fallback if local LLM quality insufficient | Optional |
| Obsidian | Recipe storage and browsing | Vault to be created |
| iOS Shortcut | Share Sheet trigger | To be created |
| Apple Reminders | Batch processing queue | List to be created |

### System Diagram

```
┌─────────────────┐     ┌─────────────────┐
│  Share Sheet    │     │ Apple Reminders │
│  (iOS Shortcut) │     │ "Recipes to     │
│                 │     │  Process" List  │
└────────┬────────┘     └────────┬────────┘
         │                       │
         ▼                       ▼
┌─────────────────┐     ┌─────────────────┐
│ Webhook Trigger │     │ Schedule Trigger│
│ (immediate)     │     │ (daily)         │
└────────┬────────┘     └────────┬────────┘
         │                       │
         └───────────┬───────────┘
                     ▼
         ┌─────────────────────┐
         │ Extract Video ID    │
         │ (regex parse URL)   │
         └──────────┬──────────┘
                    ▼
         ┌─────────────────────┐
         │ Call Python Script  │
         │ (Execute Command)   │
         │ main.py --json URL  │
         └──────────┬──────────┘
                    ▼
         ┌─────────────────────┐
         │ AI: Extract Recipe  │
         │ (Ollama → Claude)   │
         └──────────┬──────────┘
                    ▼
         ┌─────────────────────┐
         │ Write Markdown File │
         │ (to Obsidian vault) │
         └──────────┬──────────┘
                    ▼
         ┌─────────────────────┐
         │ Mark Reminder Done  │
         │ (if from Reminders) │
         └─────────────────────┘
```

## Recipe Markdown Template

### Frontmatter Schema

```yaml
---
title: "{{recipe_name}}"
source_url: "{{youtube_url}}"
source_channel: "{{channel_name}}"
date_added: {{YYYY-MM-DD}}
video_title: "{{original_video_title}}"

prep_time: "{{X min}}"
cook_time: "{{X min}}"
total_time: "{{X min}}"
servings: {{number}}
difficulty: "{{easy|medium|hard}}"

cuisine: "{{type}}"
protein: "{{main protein or 'none'}}"
dish_type: "{{breakfast|lunch|dinner|snack|dessert|side}}"
dietary: [{{vegetarian, gluten-free, dairy-free, etc.}}]

equipment: [{{list of tools/appliances needed}}]

tags:
  - {{ingredient-tag}}
  - {{cuisine-tag}}
  - {{other-tags}}

needs_review: {{true|false}}
confidence_notes: "{{what was inferred vs explicit}}"
---
```

### Full Template

```markdown
---
title: "{{recipe_name}}"
source_url: "{{youtube_url}}"
source_channel: "{{channel_name}}"
date_added: {{YYYY-MM-DD}}
video_title: "{{original_video_title}}"

prep_time: "{{X min}}"
cook_time: "{{X min}}"
total_time: "{{X min}}"
servings: {{number}}
difficulty: "{{easy|medium|hard}}"

cuisine: "{{type}}"
protein: "{{main protein or 'none'}}"
dish_type: "{{breakfast|lunch|dinner|snack|dessert|side}}"
dietary: [{{vegetarian, gluten-free, dairy-free, etc.}}]

equipment: [{{list of tools/appliances needed}}]

tags:
  - {{ingredient-tag}}
  - {{cuisine-tag}}
  - {{other-tags}}

needs_review: {{true|false}}
confidence_notes: "{{what was inferred vs explicit}}"
---

# {{Recipe Name}}

> {{Brief 1-2 sentence description of the dish}}

## Ingredients

- {{quantity}} {{ingredient}}
- {{quantity}} {{ingredient}} *(inferred)*

## Instructions

1. {{Step with clear action}}
2. {{Step with timing if mentioned}}

## Equipment

- {{Tool or appliance}}

## Notes

### Storage
{{How to store leftovers, if mentioned}}

### Variations
{{Any variations mentioned in the video}}

### Nutritional Info
{{If mentioned in video, otherwise omit section}}

---
*Extracted from [{{video_title}}]({{youtube_url}}) on {{date}}*
```

### File Naming

```
{{YYYY-MM-DD}}-{{recipe-name-slugified}}.md
```

Example: `2026-01-07-honey-garlic-chicken.md`

### Folder Structure

Flat structure in `Recipes/` folder. Dataview handles organization.

```
Vault/
└── Recipes/
    ├── 2026-01-07-honey-garlic-chicken.md
    ├── 2026-01-08-beef-stew.md
    └── ...
```

## AI Extraction

### System Prompt

```
You are a recipe extraction assistant. Given a YouTube video transcript
and description about cooking, extract a structured recipe.

Rules:
- Extract ONLY what is shown/said in the video
- When inferring (timing, quantities, temperatures), mark with "(estimated)"
- If a field cannot be determined, use null
- Set needs_review: true if significant inference was required
- List confidence_notes explaining what was inferred vs explicit

Output valid JSON matching this schema:
{
  "recipe_name": "string",
  "description": "string (1-2 sentences)",
  "prep_time": "string or null",
  "cook_time": "string or null",
  "servings": "number or null",
  "difficulty": "easy|medium|hard or null",
  "cuisine": "string or null",
  "protein": "string or null",
  "dish_type": "string or null",
  "dietary": ["array of tags"],
  "equipment": ["array of items"],
  "ingredients": [
    {"quantity": "string", "item": "string", "inferred": boolean}
  ],
  "instructions": [
    {"step": number, "text": "string", "time": "string or null"}
  ],
  "storage": "string or null",
  "variations": ["array of strings"],
  "nutritional_info": "string or null",
  "needs_review": boolean,
  "confidence_notes": "string"
}
```

### User Prompt Template

```
Extract a recipe from this cooking video.

VIDEO TITLE: {{title}}
CHANNEL: {{channel}}

DESCRIPTION:
{{description}}

TRANSCRIPT:
{{transcript}}
```

### Quality Validation

Before accepting AI output, verify:
- JSON parses successfully
- `recipe_name` is not null
- `ingredients` array has at least 2 items
- `instructions` array has at least 2 steps

If validation fails: retry once, then fall back to Claude API.

### Model Configuration

**Ollama (Primary):**
- Model: `llama3.1:8b`
- Endpoint: `http://localhost:11434/api/generate`
- Format: JSON mode enabled

**Claude API (Fallback):**
- Model: `claude-sonnet-4-20250514`
- Same prompt structure

## Python Script Modifications

### New Argument

```python
parser.add_argument('--json', action='store_true',
                    help='Output JSON instead of formatted text')
```

### JSON Output Schema

```json
{
  "success": true,
  "video_id": "dQw4w9WgXcQ",
  "title": "Video Title Here",
  "channel": "Channel Name",
  "transcript": "Full transcript text...",
  "description": "Video description...",
  "transcript_source": "youtube|whisper",
  "error": null
}
```

### Changes Required

1. Fetch video title and channel name from YouTube API (expand `snippet` parsing)
2. Collect transcript into single string instead of printing
3. Add JSON output mode controlled by `--json` flag
4. Maintain backwards compatibility (no flag = current behavior)

## n8n Workflow Details

### Webhook Node

- Path: `/webhook/recipe`
- Method: POST
- Expected body: `{"url": "https://youtube.com/watch?v=..."}`

### Reminders Integration

**Fetch uncompleted items (AppleScript):**

```applescript
tell application "Reminders"
    set recipeList to list "Recipes to Process"
    set output to ""
    repeat with r in (reminders in recipeList whose completed is false)
        set output to output & name of r & linefeed
    end repeat
    return output
end tell
```

**Mark item complete (AppleScript):**

```applescript
tell application "Reminders"
    set recipeList to list "Recipes to Process"
    repeat with r in (reminders in recipeList whose completed is false)
        if name of r is "{{URL}}" then
            set completed of r to true
        end if
    end repeat
end tell
```

### Ollama HTTP Request

```
URL: http://localhost:11434/api/generate
Method: POST
Body:
{
  "model": "llama3.1:8b",
  "prompt": "{{system_prompt}}\n\n{{user_prompt}}",
  "stream": false,
  "format": "json"
}
```

## iOS Shortcut

### Configuration

- Name: "Save Recipe"
- Accepts: URLs from Share Sheet

### Steps

1. Receive [Shortcut Input]
2. Get URLs from [Shortcut Input]
3. Get Contents of URL:
   - URL: `http://{{MAC_IP}}:5678/webhook/recipe`
   - Method: POST
   - Headers: `Content-Type: application/json`
   - Body: `{"url": "[URLs]"}`
4. Show Notification: "Recipe queued for processing"

### Network Requirements

- Mac must have static local IP or hostname
- iPhone must be on same network (or use Tailscale for remote access)

## Implementation Checklist

### Setup Tasks

- [ ] Create Obsidian vault with `Recipes/` folder
- [ ] Create Apple Reminders list "Recipes to Process"
- [ ] Pull Ollama model: `ollama pull llama3.1:8b`
- [ ] Grant Terminal/n8n Automation permission for Reminders
- [ ] Note Mac's local IP address for iOS Shortcut

### Development Tasks

- [ ] Modify `main.py` to add `--json` output mode
- [ ] Create n8n webhook workflow
- [ ] Create n8n Reminders polling workflow
- [ ] Build iOS Shortcut
- [ ] Add Claude API credentials to n8n (optional)

### Testing

- [ ] Test Python script JSON output
- [ ] Test n8n → Python → Ollama → file write
- [ ] Test iOS Shortcut → webhook trigger
- [ ] Test Reminders → daily poll → processing
- [ ] Test Claude fallback when Ollama fails

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Automation framework | n8n (local) | Already running, familiar |
| Primary LLM | Ollama (local) | Free, private, good enough for structured extraction |
| Fallback LLM | Claude API | Higher quality when local fails |
| Recipe format | Markdown + YAML frontmatter | Dataview compatibility |
| Folder structure | Flat | Dataview handles organization better than folders |
| Inference handling | Flag with "(estimated)" | User knows what to verify |
| Reminders polling | Daily | Batch processing, not time-sensitive |
| File naming | Date prefix + slugified name | Chronological, no conflicts |

## Future Enhancements (Out of Scope)

### Recipe Link Detection (Priority)

Before running AI extraction, parse the video description for existing recipe links:

1. **Detect recipe URLs** - Look for links to common recipe sites (allrecipes, food network, bonappetit, etc.) or creator's own site
2. **Fetch the linked page** - Use web scraping to get the recipe content
3. **Convert to template** - Parse the fetched recipe into the standard markdown format
4. **Skip AI extraction** - If a valid recipe is found, no need to process transcript

This optimization:
- Produces higher quality recipes (written by humans, not inferred)
- Reduces API/compute costs
- Faster processing

**Flow modification:**
```
Get transcript + description
        ↓
Parse description for recipe URLs
        ↓
    ┌───┴───┐
    │ Found │
    └───┬───┘
   Yes  │  No
    ↓   │   ↓
Fetch   │  AI extraction
recipe  │  (current flow)
    ↓   │
Convert │
to MD   │
    ↓   │
    └───┴───┐
            ↓
    Write to Obsidian
```

### Other Future Enhancements

- Push notification when recipe is saved
- Image extraction from video thumbnails
- Ingredient linking with `[[wikilinks]]`
- Shopping list generation from selected recipes
- Meal planning integration
