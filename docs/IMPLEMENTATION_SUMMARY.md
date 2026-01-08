# KitchenOS Implementation Summary

**Date:** 2026-01-07
**Status:** Complete - Core functionality working

## What Was Built

A standalone Python-based recipe extraction pipeline that:
1. Takes a YouTube URL as input
2. Fetches video metadata and transcript
3. Sends to Ollama (mistral:7b) for AI extraction
4. Formats as Obsidian-compatible markdown
5. Saves to the Obsidian vault

## Original Plan vs. Actual Implementation

### Original Plan (n8n-based)

The original design in `2026-01-07-youtube-recipe-extraction-design.md` proposed:

```
YouTube URL → n8n → Python → Ollama → n8n → Obsidian
```

With entry points:
- iOS Share Sheet → n8n webhook
- Apple Reminders → n8n daily poll

### Actual Implementation (Standalone Python)

Due to persistent issues with n8n's Execute Command node and path handling, we simplified to:

```
YouTube URL → extract_recipe.py → Ollama → Obsidian
```

**Advantages of the simpler approach:**
- No external dependencies (n8n not required)
- Easier to debug and maintain
- Works directly from command line
- Can still be wrapped by automation tools later

## Components Built

### Phase 1: Python Script JSON Mode ✅

| Task | Status | File |
|------|--------|------|
| Add --json argument | Complete | `main.py` |
| Fetch title/channel | Complete | `main.py:get_video_metadata()` |
| Collect transcript as string | Complete | `main.py:get_transcript()` |
| Whisper fallback | Complete | `main.py:transcribe_with_whisper_text()` |
| JSON output mode | Complete | `main.py` |
| Backwards compatibility | Complete | `main.py:get_video_description()` |

### Phase 2: AI Prompt Templates ✅

| Task | Status | File |
|------|--------|------|
| Create prompt templates | Complete | `prompts/recipe_extraction.py` |
| Create markdown template | Complete | `templates/recipe_template.py` |

### Phase 3: All-in-One Script ✅

| Task | Status | File |
|------|--------|------|
| Create extraction script | Complete | `extract_recipe.py` |
| Ollama integration | Complete | `extract_recipe.py:extract_recipe_with_ollama()` |
| Obsidian file writing | Complete | `extract_recipe.py:save_recipe_to_obsidian()` |
| Dry-run mode | Complete | `extract_recipe.py --dry-run` |

### Phase 4: n8n Workflows ❌ (Abandoned)

The n8n workflows were created but had persistent issues with:
- Path escaping for directories with spaces
- Execute Command node reliability
- Webhook activation and restart requirements

**Decision:** Abandoned n8n in favor of standalone script.

### Phase 5: iOS Shortcut 🔜 (Future)

Not implemented. Can be added later to call the Python script via SSH or a simple API wrapper.

## Files Created/Modified

### New Files

| File | Purpose |
|------|---------|
| `extract_recipe.py` | Main entry point - all-in-one extraction |
| `prompts/__init__.py` | Package init |
| `prompts/recipe_extraction.py` | AI prompt templates |
| `templates/__init__.py` | Package init |
| `templates/recipe_template.py` | Markdown formatter |

### Modified Files

| File | Changes |
|------|---------|
| `main.py` | Added `--json` mode, `get_video_metadata()`, `get_transcript()` |
| `CLAUDE.md` | Updated with current architecture |
| `README.md` | Comprehensive documentation |

### Deprecated Files

| File | Status |
|------|--------|
| `n8n-workflows/*.json` | Created but not in use |
| `run-recipe.sh` | Wrapper script, no longer needed |

## Configuration

### Paths

```python
# extract_recipe.py
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "mistral:7b"
OBSIDIAN_RECIPES_PATH = Path("/Users/chaseeasterling/Library/Mobile Documents/iCloud~md~obsidian/Documents/KitchenOS/Recipes")
```

### API Keys (.env)

```bash
YOUTUBE_API_KEY="..."
OPENAI_API_KEY="..."  # For Whisper fallback
```

## Usage

### Extract a Recipe

```bash
cd /Users/chaseeasterling/KitchenOS
.venv/bin/python extract_recipe.py "https://www.youtube.com/watch?v=VIDEO_ID"
```

### Preview Without Saving

```bash
.venv/bin/python extract_recipe.py --dry-run "URL"
```

### Fetch Video Data Only

```bash
.venv/bin/python main.py --json "VIDEO_ID"
```

## Test Results

### Successful Extraction

**Video:** "Binging with Babish: Pasta Aglio e Olio from 'Chef'"
**URL:** https://www.youtube.com/watch?v=bJUiWdM__Qw

**Output file:** `2026-01-07-pasta-aglio-e-olio-from-chef.md`

**Extracted data:**
- Recipe name: Pasta Aglio e Olio
- Cuisine: Italian
- Difficulty: Easy
- 6 ingredients (4 inferred)
- 9 instruction steps
- 6 equipment items

## Known Issues

### Python 3.9 Compatibility

Backslashes are not allowed in f-string expressions. Fixed by using:

```python
quote = '"'
f"[{', '.join(quote + e + quote for e in items)}]"
```

### Library Warnings

urllib3 and google-api-core produce warnings about Python 3.9 compatibility. These are cosmetic and don't affect functionality.

### Transcript Availability

Some videos don't have transcripts. The script:
1. Tries YouTube's auto-generated captions
2. Falls back to Whisper (requires OpenAI API key)
3. Proceeds with description only if both fail

## Future Enhancements

### Priority

1. **Recipe Link Detection** - Before AI extraction, check description for existing recipe URLs and scrape those instead
2. **iOS Shortcut** - Create shortcut that calls script via SSH or local API
3. **Batch Processing** - Process multiple URLs from a file

### Nice to Have

- Image extraction from video thumbnails
- Ingredient linking with `[[wikilinks]]`
- Shopping list generation
- Meal planning integration

## Lessons Learned

1. **Start simple** - The standalone script works better than the complex n8n orchestration
2. **Path with spaces cause problems** - Moved project to `/Users/chaseeasterling/KitchenOS/`
3. **Python 3.9 has f-string limitations** - Can't use backslashes in expressions
4. **Ollama JSON mode is reliable** - Format enforcement works well with mistral:7b

## Git History

Key commits for this implementation:

```
d084b89 Rename project to KitchenOS
f3e463c Merge branch 'feature/recipe-extraction'
c42bc6c feat: add standalone recipe extraction script
```

The `feature/recipe-extraction` branch contained all Phase 1-2 work before being merged to main.
