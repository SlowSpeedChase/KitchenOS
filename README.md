# KitchenOS

A YouTube-to-Obsidian recipe extraction pipeline. Captures cooking videos, extracts structured recipe data using AI, and saves formatted markdown to your Obsidian vault.

## Features

- Extracts video transcripts (YouTube captions or Whisper fallback)
- AI-powered recipe extraction (Ollama local, Claude API fallback)
- Structured markdown output with Dataview-compatible frontmatter
- Multiple input paths: Share Sheet, Apple Reminders, CLI
- n8n workflow automation

## Setup

1. **Virtual Environment**:
   ```bash
   source .venv/bin/activate
   ```

2. **API Keys** (in `.env` file):
   ```bash
   YOUTUBE_API_KEY="your_youtube_api_key"
   OPENAI_API_KEY="your_openai_api_key"  # For Whisper fallback
   ```

## Usage

### CLI Mode

```bash
# Text output (original)
.venv/bin/python main.py "VIDEO_ID_OR_URL"

# JSON output (for automation)
.venv/bin/python main.py --json "VIDEO_ID_OR_URL"
```

### Automation (n8n)

See `docs/plans/2026-01-07-youtube-recipe-extraction-design.md` for full pipeline design.

## Dependencies

- `youtube-transcript-api` - Fetches video transcripts
- `google-api-python-client` - YouTube Data API
- `yt-dlp` - Audio download for Whisper
- `openai` - Whisper transcription
- `python-dotenv` - Environment variables

## Documentation

- Design: `docs/plans/2026-01-07-youtube-recipe-extraction-design.md`
- Implementation: `docs/plans/2026-01-07-recipe-extraction-implementation.md`
