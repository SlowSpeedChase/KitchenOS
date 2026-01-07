# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a YouTube video information fetcher that extracts transcripts and descriptions from YouTube videos using the YouTube API. The project includes automation workflows for integrating with Keyboard Maestro to send results to various applications (ChatGPT, Notes, Obsidian, etc.).

## Development Environment

- **Python Version**: 3.9
- **Virtual Environment**: `.venv/` (required for all Python operations)
- **API Key**: YouTube Data API key stored in `YOUTUBE_API_KEY` environment variable
- **Hardcoded API Key**: Available in `main.py:13` (not recommended for production)

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

### Set API Key
```bash
export YOUTUBE_API_KEY="your_api_key_here"
```

### Run Script (Multiple Options)

1. **Test Script (Recommended)**:
   ```bash
   ./test_script.sh "VIDEO_ID_OR_URL"
   ./test_script.sh  # Interactive mode
   ```

2. **Direct Python**:
   ```bash
   .venv/bin/python main.py "VIDEO_ID_OR_URL"
   ```

3. **AppleScript GUI**:
   ```bash
   osascript run_youtube_info.applescript
   osascript run_youtube_info_advanced.applescript
   ```

4. **Keyboard Maestro Integration**:
   ```bash
   osascript youtube_to_km.applescript
   ```

## Architecture

### Core Components

- `main.py` - Main application script that:
  - Parses YouTube URLs/IDs using regex (`youtube_parser()`)
  - Fetches video descriptions via YouTube Data API (`get_video_description()`)
  - Retrieves transcripts in multiple languages (`print_transcript()`)
  - Handles errors gracefully with user-friendly messages

- `test_script.sh` - Bash wrapper that:
  - Validates environment setup
  - Provides interactive and single-use modes
  - Uses hardcoded paths to virtual environment

### Automation Workflows

- `youtube_to_km.applescript` - Main Keyboard Maestro integration:
  - Auto-detects YouTube URLs from clipboard
  - Runs Python script and formats output
  - Sets Keyboard Maestro variables for macro consumption
  - Triggers target app-specific macros

- `run_youtube_info*.applescript` - Standalone GUI applications

### Supported Input Formats

- Full YouTube URLs: `https://www.youtube.com/watch?v=VIDEO_ID`
- Short URLs: `https://youtu.be/VIDEO_ID`
- Video IDs: `VIDEO_ID`

## Path Configuration

All scripts use hardcoded absolute paths pointing to this location:
- Script directory: `/Users/chaseeasterling/Documents/Documents - Chase's MacBook Air - 1/GitHub/YT-Vid-Recipie/`
- Python binary: `.venv/bin/python`
- Main script: `main.py`

## Keyboard Maestro Integration

The project includes extensive Keyboard Maestro automation:

- **Variables Set**: `YouTubeVideoInfo`, `YouTubeVideoID`, `YouTubeSourceURL`
- **Target Macros**: `YouTube-to-ChatGPT`, `YouTube-to-Notes`, custom macros
- **Workflow**: AppleScript → Python → Keyboard Maestro → Target Application

## Error Handling

The application handles common scenarios:
- Missing transcripts/captions
- Invalid API keys or quota exceeded
- Network connectivity issues
- Private/restricted videos
- Invalid video IDs

## Testing

Use these video IDs for testing:
- `dQw4w9WgXcQ` (Rick Astley - likely no transcripts)
- Any educational YouTube video (more likely to have transcripts)

---

# Development Process

## GitOps Workflow

Claude MUST follow these practices for all development work.

### Core Principles

1. **Visibility** - All work state visible in BRANCH-STATUS.md
2. **Isolation** - Each piece of work in its own worktree/branch
3. **Checkpoints** - Explicit stages with checklists
4. **Currency** - Frequent rebasing keeps branches healthy

### Session Start Ritual (MANDATORY)

Before doing ANY work in a worktree:

```bash
git fetch origin
BEHIND=$(git rev-list --count HEAD..origin/main)
```

If `BEHIND > 0`: "Main has [X] new commits. Rebase now before continuing?"

### Branch Naming

```
US-NNN/short-description
```

Examples: `US-001/api-server-setup`, `US-017/ios-shortcuts`

### Development Stages

| Stage | Purpose |
|-------|---------|
| **planning** | Design approved, plan written |
| **dev** | Tests first, implementation, no errors |
| **testing** | All tests pass, manual testing |
| **docs** | README updated if needed |
| **review** | Code reviewed, feedback addressed |
| **ready** | Rebased, final tests, ready to merge |

### Starting Work

```bash
git worktree add -b US-NNN/feature-name .worktrees/feature-name main
cd .worktrees/feature-name
cp ../../templates/BRANCH-STATUS.md ./BRANCH-STATUS.md
```

### Closure Ritual

After merge:
1. Create summary in `docs/completed/YYYY-MM-DD-US-NNN-feature.md`
2. Remove worktree: `git worktree remove .worktrees/feature-name`
3. Announce completion

### Commit Format

```
type(scope): description

Co-Authored-By: Claude <noreply@anthropic.com>
```

Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`

---

## Story-Driven Development

### Quick Reference

```bash
./scripts/story.sh status              # Dashboard
./scripts/story.sh new <title>         # Create draft
./scripts/story.sh promote US-NNN      # Move to next state
./scripts/story.sh list [state]        # List stories
```

### Story Lifecycle

```
draft/ → ready/ → active/ → done/
  │        │         │        │
Ideas   Refined   Working   Merged
         with       on
       criteria   branch
```

| State | Requirements |
|-------|--------------|
| **draft/** | Has user story (As a... I want... So that...) |
| **ready/** | Has acceptance criteria |
| **active/** | Has git branch, max 5 concurrent |
| **done/** | PR merged, story archived |

### Story Template Location

`docs/stories/templates/STORY-TEMPLATE.md`

### Rules

- Max 5 active stories
- Must have acceptance criteria before `ready/`
- Moving to `active/` creates git branch
- Don't skip acceptance criteria
