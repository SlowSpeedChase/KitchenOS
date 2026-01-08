# CLAUDE.md

Development guide for Claude Code when working with this repository.

## Project Overview

**KitchenOS** is a YouTube-to-Obsidian recipe extraction pipeline. It captures cooking videos, extracts structured recipe data using AI (Ollama local), and saves formatted markdown files to an Obsidian vault for browsing with Dataview.

### User Context

- **Primary user**: Home cook who watches YouTube cooking videos
- **Use case**: Save recipes from videos that don't have written recipes
- **Workflow**: Watch video → run command → recipe appears in Obsidian
- **Browsing**: Uses Obsidian + Dataview to search/filter recipes

### Design Principles

| Principle | Rationale |
|-----------|-----------|
| **Local-first** | Privacy, no cloud dependency, works offline (except YouTube fetch) |
| **Simple over complex** | Standalone script beats n8n orchestration |
| **Obsidian-native** | YAML frontmatter for Dataview, flat folder structure |
| **Honest about inference** | Mark uncertain data, set `needs_review` flag |
| **Graceful degradation** | Missing transcript → try Whisper → use description only |

### Constraints

- **Python 3.9** - No backslashes in f-string expressions
- **Ollama local** - Must be running for extraction to work
- **YouTube API key required** - For metadata fetching
- **iCloud path** - Obsidian vault is in iCloud, path has spaces (escaped)

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
YouTube URL → extract_recipe.py
    ↓
main.py (fetch metadata + transcript)
    ↓
recipe_sources.py:
  1. find_recipe_link() → scrape_recipe_from_url()
  2. parse_recipe_from_description()
  3. extract_recipe_with_ollama() (fallback)
    ↓
extract_cooking_tips() (if webpage/description source)
    ↓
template → Obsidian
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

**recipe_sources.py:**
- `find_recipe_link()` - Detects recipe URLs in video descriptions
- `scrape_recipe_from_url()` - Fetches and parses JSON-LD from recipe websites
- `parse_recipe_from_description()` - Extracts inline recipes from descriptions
- `extract_cooking_tips()` - Pulls practical tips from transcripts

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

## Completing Work

When finishing a feature or fix, follow this checklist:

### 1. Verify
- [ ] Run `extract_recipe.py --dry-run` with a test video
- [ ] Check for Python errors or warnings
- [ ] Verify Ollama is responding correctly

### 2. Test End-to-End (if applicable)
- [ ] Run full extraction: `.venv/bin/python extract_recipe.py "VIDEO_URL"`
- [ ] Check recipe file was created in Obsidian vault
- [ ] Open in Obsidian - verify frontmatter and content look correct

### 3. Update Documentation

**Which doc to update:**

| Change Type | Update This |
|-------------|-------------|
| New feature/function | CLAUDE.md → "Key Functions" |
| Architecture change | CLAUDE.md → "Architecture" |
| New config option | CLAUDE.md → "AI Configuration" |
| New constraint/gotcha | CLAUDE.md → "Constraints" or "Common Issues" |
| New design principle | CLAUDE.md → "Design Principles" |
| User-facing change | README.md → relevant section |
| Major feature complete | Future Enhancements → mark done or remove |
| Lessons learned | docs/IMPLEMENTATION_SUMMARY.md → "Lessons Learned" |

**Documentation standards:**
- Keep CLAUDE.md concise - it's loaded every session
- Use tables for structured data
- Include code examples for commands
- Update the JSON schema if recipe structure changes

### 4. Commit
```bash
git add -A
git commit -m "feat/fix/docs: description

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

### 5. Update Future Enhancements
- [ ] Mark completed features as done (move to "Completed" or remove)
- [ ] Add any new ideas discovered during implementation

## Future Enhancements

These features are planned but not yet implemented:

| Feature | Priority | Notes |
|---------|----------|-------|
| ~~Recipe link detection~~ | ~~High~~ | **Completed** - Priority chain: webpage → description → AI |
| iOS Shortcut | Medium | Call script via SSH or local API wrapper |
| Batch processing | Medium | Process multiple URLs from a file |
| Claude API fallback | Low | Use Claude when Ollama fails |
| Image extraction | Low | Get video thumbnails for recipes |

## Documentation

| Document | Purpose |
|----------|---------|
| `README.md` | User guide - installation, usage, configuration |
| `docs/IMPLEMENTATION_SUMMARY.md` | What was built vs planned, lessons learned |
| `docs/plans/2026-01-07-youtube-recipe-extraction-design.md` | Original design (n8n-based, **superseded** by standalone script) |

**Note:** The original design proposed n8n orchestration, but we built a simpler standalone Python solution. See `IMPLEMENTATION_SUMMARY.md` for details on this decision.
