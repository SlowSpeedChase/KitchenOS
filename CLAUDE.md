# CLAUDE.md

Development guide for Claude Code when working with this repository.

## Project Overview

**KitchenOS** is a YouTube-to-Obsidian recipe extraction pipeline. It captures cooking videos, extracts structured recipe data using AI (Ollama local), and saves formatted markdown files to an Obsidian vault for browsing with Dataview.

## Key Paths

| Path | Purpose |
|------|---------|
| `/Users/chaseeasterling/KitchenOS/` | Project root |
| `.venv/` | Python virtual environment |
| `Recipes/` in Obsidian vault | Output folder for recipe markdown |

**Obsidian Vault**: `/Users/chaseeasterling/Library/Mobile Documents/iCloud~md~obsidian/Documents/KitchenOS/`

## Running Commands

### Extract a Recipe (Primary Use)

```bash
cd /Users/chaseeasterling/KitchenOS
.venv/bin/python extract_recipe.py "https://www.youtube.com/watch?v=VIDEO_ID"

# Dry run (preview without saving)
.venv/bin/python extract_recipe.py --dry-run "VIDEO_URL"
```

### Fetch Video Data Only

```bash
.venv/bin/python main.py --json "VIDEO_ID_OR_URL"
```

## Architecture

### Pipeline Flow

```
YouTube URL → extract_recipe.py → main.py (fetch data) → Ollama (extract) → template → Obsidian
```

### Core Components

| File | Purpose |
|------|---------|
| `extract_recipe.py` | **Main entry point** - orchestrates entire pipeline |
| `main.py` | Video data fetcher (transcript, metadata, `--json` mode) |
| `prompts/recipe_extraction.py` | AI prompt templates for structured extraction |
| `templates/recipe_template.py` | Markdown formatter with YAML frontmatter |

### Key Functions

**extract_recipe.py:**
- `extract_recipe_with_ollama()` - Sends data to Ollama, returns parsed JSON
- `save_recipe_to_obsidian()` - Formats and writes markdown file
- `main()` - CLI entry point with `--dry-run` support

**main.py:**
- `youtube_parser(url)` - Extracts video ID from various URL formats
- `get_video_metadata(video_id)` - Fetches title, channel, description
- `get_transcript(video_id)` - Gets transcript (YouTube or Whisper fallback)

**templates/recipe_template.py:**
- `format_recipe_markdown()` - Converts recipe JSON to Obsidian markdown
- `generate_filename()` - Creates `YYYY-MM-DD-recipe-slug.md` filename

## AI Configuration

### Ollama Settings

```python
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "mistral:7b"
```

### Recipe JSON Schema

The AI extracts this structure:

```json
{
  "recipe_name": "string",
  "description": "string",
  "prep_time": "string or null",
  "cook_time": "string or null",
  "servings": "number or null",
  "difficulty": "easy|medium|hard",
  "cuisine": "string",
  "protein": "string or null",
  "dish_type": "string",
  "dietary": ["array"],
  "equipment": ["array"],
  "ingredients": [{"quantity": "string", "item": "string", "inferred": boolean}],
  "instructions": [{"step": number, "text": "string", "time": "string or null"}],
  "storage": "string or null",
  "variations": ["array"],
  "needs_review": boolean,
  "confidence_notes": "string"
}
```

## Development Environment

- **Python Version**: 3.9
- **Virtual Environment**: `.venv/` (required for all Python operations)
- **API Keys**: In `.env` file
  - `YOUTUBE_API_KEY` - YouTube Data API
  - `OPENAI_API_KEY` - Whisper fallback

## Dependencies

```
youtube-transcript-api    # Fetch video transcripts
google-api-python-client  # YouTube Data API
yt-dlp                    # Audio download for Whisper
openai                    # Whisper API transcription
python-dotenv             # Environment variables
requests                  # HTTP requests to Ollama
```

## Testing

Test with a cooking video that has captions:

```bash
# Dry run first
.venv/bin/python extract_recipe.py --dry-run "https://www.youtube.com/watch?v=bJUiWdM__Qw"

# Then full extraction
.venv/bin/python extract_recipe.py "https://www.youtube.com/watch?v=bJUiWdM__Qw"
```

## Common Issues

### Ollama not running
```bash
ollama serve  # Start in background
curl http://localhost:11434/api/tags  # Verify running
```

### Python 3.9 f-string limitations
Backslashes are not allowed in f-string expressions. Use:
```python
quote = '"'
result = f"[{', '.join(quote + x + quote for x in items)}]"
```

### Transcript unavailable
Falls back to Whisper (requires OpenAI key) or proceeds with description only.

## File Naming Convention

Output files use: `{YYYY-MM-DD}-{recipe-name-slugified}.md`

Example: `2026-01-07-pasta-aglio-e-olio.md`

## Documentation

- **User Guide**: `README.md`
- **Design Doc**: `docs/plans/2026-01-07-youtube-recipe-extraction-design.md`
- **Implementation Plan**: `docs/plans/2026-01-07-recipe-extraction-implementation.md`
