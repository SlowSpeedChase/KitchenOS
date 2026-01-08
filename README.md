# KitchenOS

A YouTube-to-Obsidian recipe extraction pipeline. Captures cooking videos, extracts structured recipe data using AI, and saves formatted markdown to your Obsidian vault for browsing with Dataview.

## What It Does

Cooking videos often lack written recipes. This system:

- **Extracts recipes from videos** where someone is cooking and talking (no recipe card needed)
- **Cleans up recipes** buried in video descriptions with sponsor noise
- **Creates a searchable database** of structured recipes in Obsidian

## Quick Start

```bash
cd /Users/chaseeasterling/KitchenOS
.venv/bin/python extract_recipe.py "https://www.youtube.com/watch?v=VIDEO_ID"
```

The recipe will be saved to your Obsidian vault.

## Installation

### Prerequisites

- Python 3.9+
- [Ollama](https://ollama.ai/) with mistral:7b model
- YouTube API key
- OpenAI API key (for Whisper fallback)

### Setup

1. **Clone and enter directory:**
   ```bash
   cd /Users/chaseeasterling/KitchenOS
   ```

2. **Create virtual environment:**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

3. **Configure API keys** (create `.env` file):
   ```bash
   YOUTUBE_API_KEY="your_youtube_api_key"
   OPENAI_API_KEY="your_openai_api_key"
   ```

4. **Install Ollama model:**
   ```bash
   ollama pull mistral:7b
   ollama serve  # Run in background
   ```

5. **Create Obsidian vault folder:**
   ```bash
   mkdir -p "/Users/chaseeasterling/Library/Mobile Documents/iCloud~md~obsidian/Documents/KitchenOS/Recipes"
   ```

## Usage

### Extract a Recipe (Recommended)

```bash
# Full extraction - saves to Obsidian
.venv/bin/python extract_recipe.py "https://www.youtube.com/watch?v=bJUiWdM__Qw"

# Preview mode - prints markdown without saving
.venv/bin/python extract_recipe.py --dry-run "https://www.youtube.com/watch?v=bJUiWdM__Qw"
```

### Fetch Video Data Only

```bash
# Text output
.venv/bin/python main.py "VIDEO_ID_OR_URL"

# JSON output (for automation)
.venv/bin/python main.py --json "VIDEO_ID_OR_URL"
```

### Update Existing Recipes

Re-running extraction on a previously extracted video will update the existing file instead of creating a duplicate. Your personal notes in the "## My Notes" section are preserved.

```bash
# Re-extract (updates existing file, creates backup)
.venv/bin/python extract_recipe.py "https://www.youtube.com/watch?v=VIDEO_ID"
```

### Migrate Recipes to New Template

When the template changes (new fields added), update all existing recipes:

```bash
# Preview changes
.venv/bin/python migrate_recipes.py --dry-run

# Apply changes (creates backups first)
.venv/bin/python migrate_recipes.py
```

Backups are stored in `Recipes/.history/` and can be used to recover previous versions.

### Batch Processing

Process multiple YouTube URLs at once using iOS Reminders as your queue.

#### Setup

1. **Create Reminders list**: Open the Reminders app and create a list named exactly `Recipies to Process` (note: the typo is intentional for compatibility)

2. **Add URLs**: Save YouTube URLs as reminder titles in this list - you can share videos directly from YouTube to Reminders

3. **Grant permissions**: On first run, macOS will prompt for Reminders access - click "OK" to allow

#### Usage

```bash
# Process all uncompleted reminders
.venv/bin/python batch_extract.py

# Preview what would be processed (no changes)
.venv/bin/python batch_extract.py --dry-run
```

#### What Happens

- Each URL is extracted using the standard pipeline
- **Success**: Reminder is marked complete, recipe saved to Obsidian
- **Failure**: Reminder stays uncompleted, error logged to console
- Processing continues even if individual URLs fail

#### Tips

- Add URLs throughout the week, then run batch extraction when convenient
- Check console output for any failed extractions
- Failed reminders remain in the list for retry

### Supported URL Formats

- Full URL: `https://www.youtube.com/watch?v=VIDEO_ID`
- Short URL: `https://youtu.be/VIDEO_ID`
- Video ID only: `VIDEO_ID`

## Recipe Sources

KitchenOS extracts recipes using a priority chain:

1. **Webpage** - If description contains a recipe link, scrapes JSON-LD structured data
2. **Description** - If description has inline recipe (ingredients + method), parses it
3. **Transcript** - Falls back to AI extraction from video transcript

When using webpage or description sources, KitchenOS also extracts practical cooking tips from the video that aren't in the written recipe.

## Architecture

```
YouTube URL → Python → Ollama (mistral:7b) → Markdown → Obsidian Vault
```

### Components

| Component | File | Purpose |
|-----------|------|---------|
| Recipe Extractor | `extract_recipe.py` | All-in-one extraction script |
| Video Fetcher | `main.py` | Gets transcript and metadata |
| AI Prompts | `prompts/recipe_extraction.py` | System/user prompts for LLM |
| Markdown Template | `templates/recipe_template.py` | Formats recipe as Obsidian markdown |

### How It Works

1. **Fetch metadata** - Gets video title, channel, and description via YouTube API
2. **Get transcript** - Extracts captions (falls back to Whisper if unavailable)
3. **AI extraction** - Sends data to Ollama for structured recipe extraction
4. **Format output** - Converts JSON to markdown with YAML frontmatter
5. **Save file** - Writes to Obsidian vault with date-prefixed filename

## Output Format

### Recipe Markdown

Each recipe is saved as a markdown file with YAML frontmatter for Dataview queries:

```markdown
---
title: "Pasta Aglio e Olio"
source_url: "https://www.youtube.com/watch?v=..."
source_channel: "Binging with Babish"
date_added: 2026-01-07
prep_time: "10 min"
cook_time: "15 min"
servings: 2
difficulty: "easy"
cuisine: "Italian"
protein: null
dish_type: "Pasta dish"
dietary: []
equipment: ["Large pot", "Sauté pan"]
tags:
  - italian
  - pasta-dish
needs_review: false
---

# Pasta Aglio e Olio

> A simple Roman pasta with garlic and olive oil.

## Ingredients
- 1/2 lb dry linguine
- 1/2 head garlic, thinly sliced
...

## Instructions
1. Heavily salt a large pot of water and bring to a boil.
2. Cook pasta to al dente.
...
```

### File Naming

```
{YYYY-MM-DD}-{recipe-name-slugified}.md
```

Example: `2026-01-07-pasta-aglio-e-olio.md`

## Configuration

### Paths

Edit these in `extract_recipe.py`:

```python
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "mistral:7b"
OBSIDIAN_RECIPES_PATH = Path("/Users/chaseeasterling/Library/Mobile Documents/iCloud~md~obsidian/Documents/KitchenOS/Recipes")
```

### AI Model

The default is `mistral:7b` running locally via Ollama. To use a different model:

```bash
ollama pull llama3.1:8b
```

Then update `OLLAMA_MODEL` in `extract_recipe.py`.

## Dataview Queries

Once you have recipes in Obsidian, use Dataview to browse them:

### All Recipes Table

```dataview
TABLE source_channel, cuisine, difficulty, date_added
FROM "Recipes"
SORT date_added DESC
```

### By Cuisine

```dataview
LIST
FROM "Recipes"
WHERE cuisine = "Italian"
```

### Needs Review

```dataview
LIST
FROM "Recipes"
WHERE needs_review = true
```

## Troubleshooting

### "Cannot connect to Ollama"

Make sure Ollama is running:
```bash
ollama serve
```

### "No transcript available"

The video may not have captions. The script will:
1. Try YouTube's auto-generated captions
2. Fall back to Whisper transcription (requires OpenAI API key)
3. Proceed with description only if both fail

### "Failed to parse JSON"

Ollama may have returned malformed JSON. Try running again - LLM outputs can vary.

## Project Structure

```
KitchenOS/
├── extract_recipe.py      # Main entry point
├── main.py                # Video data fetcher
├── prompts/
│   └── recipe_extraction.py  # AI prompts
├── templates/
│   └── recipe_template.py    # Markdown formatter
├── docs/
│   └── plans/              # Design documents
├── .env                    # API keys (not in git)
├── .venv/                  # Python virtual environment
└── requirements.txt        # Dependencies
```

## Dependencies

| Package | Purpose |
|---------|---------|
| `youtube-transcript-api` | Fetch video transcripts |
| `google-api-python-client` | YouTube Data API |
| `yt-dlp` | Download audio for Whisper |
| `openai` | Whisper API transcription |
| `python-dotenv` | Environment variable management |
| `requests` | HTTP requests to Ollama |

## Documentation

- **iOS Shortcut Setup**: `iOS_SHORTCUT_SETUP.md`
- **Design**: `docs/plans/2026-01-07-youtube-recipe-extraction-design.md`
- **Implementation**: `docs/plans/2026-01-07-recipe-extraction-implementation.md`
- **Development Guide**: `CLAUDE.md`

## License

MIT License - see LICENSE file.
