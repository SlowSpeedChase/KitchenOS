# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## Project Overview

**KitchenOS** is a YouTube-to-Obsidian recipe extraction pipeline. It captures cooking videos, extracts structured recipe data using AI (Ollama local, Claude API fallback), and saves formatted markdown files to an Obsidian vault for browsing with Dataview.

### Key Paths

- **Project**: `/Users/chaseeasterling/Documents/Documents - Chase's MacBook Air - 1/GitHub/KitchenOS/`
- **Obsidian Vault**: `/Users/chaseeasterling/Library/Mobile Documents/iCloud~md~obsidian/Documents/KitchenOS/`
- **Recipes Folder**: `{vault}/Recipes/`

## Development Environment

- **Python Version**: 3.9
- **Virtual Environment**: `.venv/` (required for all Python operations)
- **API Keys**: In `.env` file (YOUTUBE_API_KEY, OPENAI_API_KEY)

## Key Dependencies

- `youtube-transcript-api` - Fetches video transcripts
- `google-api-python-client` - YouTube Data API integration
- `yt-dlp` - Downloads audio for Whisper transcription fallback
- `openai` - Whisper API for audio transcription
- `python-dotenv` - Environment variable management

## Running Commands

### Activate Virtual Environment
```bash
source .venv/bin/activate
```

### Run Script
```bash
# Text output
.venv/bin/python main.py "VIDEO_ID_OR_URL"

# JSON output (for n8n automation)
.venv/bin/python main.py --json "VIDEO_ID_OR_URL"
```

## Architecture

### Core Components

- `main.py` - Main application script:
  - `youtube_parser()` - Parses YouTube URLs/IDs
  - `get_video_metadata()` - Fetches title, channel, description
  - `get_transcript()` - Gets transcript (YouTube or Whisper fallback)
  - `--json` flag outputs structured JSON for n8n

- `prompts/recipe_extraction.py` - AI prompt templates for recipe extraction
- `templates/recipe_template.py` - Markdown template formatter

### Automation Pipeline

```
YouTube URL → n8n → Python (--json) → AI (Ollama/Claude) → Obsidian markdown
```

Entry points:
- iOS Share Sheet → n8n webhook
- Apple Reminders list → n8n daily poll

### Supported Input Formats

- Full YouTube URLs: `https://www.youtube.com/watch?v=VIDEO_ID`
- Short URLs: `https://youtu.be/VIDEO_ID`
- Video IDs: `VIDEO_ID`

## Documentation

- **Session Summary**: `docs/SESSION_SUMMARY.md` ← **Read this first if continuing work**
- **Design**: `docs/plans/2026-01-07-youtube-recipe-extraction-design.md`
- **Implementation**: `docs/plans/2026-01-07-recipe-extraction-implementation.md`

## n8n Workflows

Import these into n8n (http://localhost:5678):
- `n8n-workflows/youtube-recipe-webhook.json` - iOS Share Sheet trigger
- `n8n-workflows/youtube-recipe-reminders.json` - Daily Apple Reminders poll

## Worktree Convention

Use `.worktrees/` directory for feature branches:
```bash
git worktree add .worktrees/feature-name -b feature/feature-name
```

## Testing

Test with any cooking video that has captions:
```bash
.venv/bin/python main.py --json "https://www.youtube.com/watch?v=VIDEO_ID"
```
