# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## Project Overview

**KitchenOS** is a YouTube-to-Obsidian recipe extraction pipeline. It captures cooking videos, extracts structured recipe data using AI (Ollama), and saves formatted markdown files to an Obsidian vault for browsing with Dataview.

### Key Paths

- **Project**: `/Users/chaseeasterling/KitchenOS/`
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
- `requests` - HTTP requests for Ollama API

## Running Commands

### Extract a Recipe (All-in-One)
```bash
cd /Users/chaseeasterling/KitchenOS
.venv/bin/python extract_recipe.py "https://www.youtube.com/watch?v=VIDEO_ID"
```

### Fetch Video Data Only (JSON)
```bash
.venv/bin/python main.py --json "VIDEO_ID_OR_URL"
```

## Architecture

### Core Components

- `extract_recipe.py` - **Main entry point**: Fetches video, extracts recipe via Ollama, writes to Obsidian
- `main.py` - Video data fetcher (transcript, metadata)
- `prompts/recipe_extraction.py` - AI prompt templates
- `templates/recipe_template.py` - Markdown template formatter

### Pipeline Flow

```
YouTube URL → Python → Ollama (mistral:7b) → Markdown → Obsidian Vault
```

### Supported Input Formats

- Full YouTube URLs: `https://www.youtube.com/watch?v=VIDEO_ID`
- Short URLs: `https://youtu.be/VIDEO_ID`
- Video IDs: `VIDEO_ID`

## Documentation

- **Design**: `docs/plans/2026-01-07-youtube-recipe-extraction-design.md`
- **Implementation**: `docs/plans/2026-01-07-recipe-extraction-implementation.md`

## Testing

```bash
cd /Users/chaseeasterling/KitchenOS
.venv/bin/python extract_recipe.py "https://www.youtube.com/watch?v=bJUiWdM__Qw"
```
