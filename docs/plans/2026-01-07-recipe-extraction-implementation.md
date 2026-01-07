# YouTube Recipe Extraction Pipeline - Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a pipeline that captures YouTube cooking videos, extracts structured recipe data using AI, and writes formatted markdown files to an Obsidian vault.

**Architecture:** n8n orchestrates two entry points (webhook for iOS Share Sheet, daily schedule for Apple Reminders). Python script fetches transcript/description as JSON. Ollama extracts recipe structure (Claude API fallback). Markdown file written directly to Obsidian vault.

**Tech Stack:** Python 3.9, n8n, Ollama (llama3.1:8b), Claude API, Apple Reminders (via AppleScript), iOS Shortcuts, Obsidian

**Design Document:** `docs/plans/2026-01-07-youtube-recipe-extraction-design.md`

---

## Phase 1: Python Script JSON Mode

### Task 1.1: Add JSON Output Argument

**Files:**
- Modify: `main.py:164-167` (argument parser section)

**Step 1: Add the --json argument to the parser**

In `main.py`, locate the argument parser and add the new flag:

```python
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch YouTube video transcript and description.")
    parser.add_argument('video_id_in', type=str, help='The ID or URL of the YouTube video')
    parser.add_argument('--json', action='store_true', help='Output JSON instead of formatted text')
    args = parser.parse_args()
```

**Step 2: Test argument parsing**

Run: `.venv/bin/python main.py --help`

Expected output includes:
```
--json                Output JSON instead of formatted text
```

**Step 3: Commit**

```bash
git add main.py
git commit -m "feat: add --json argument to main.py"
```

---

### Task 1.2: Fetch Video Title and Channel

**Files:**
- Modify: `main.py:40-61` (get_video_description function)

**Step 1: Expand get_video_description to return title and channel**

Replace the function with one that returns a dict:

```python
def get_video_metadata(video_id):
    """Fetch video title, channel, and description from YouTube API"""
    try:
        youtube = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)
        request = youtube.videos().list(
            part='snippet',
            id=video_id
        )
        response = request.execute()

        if 'items' in response and len(response['items']) > 0:
            snippet = response['items'][0]['snippet']
            return {
                'title': snippet.get('title', ''),
                'channel': snippet.get('channelTitle', ''),
                'description': snippet.get('description', '')
            }
        else:
            return None
    except Exception as e:
        print(f"Error fetching video metadata: {e}", file=sys.stderr)
        return None
```

**Step 2: Test the function manually**

Run: `.venv/bin/python -c "from main import get_video_metadata; print(get_video_metadata('dQw4w9WgXcQ'))"`

Expected: Dict with title, channel, description keys (or connection error if no API key)

**Step 3: Commit**

```bash
git add main.py
git commit -m "feat: expand get_video_description to return title and channel"
```

---

### Task 1.3: Collect Transcript as String

**Files:**
- Modify: `main.py:63-95` (print_transcript function)

**Step 1: Create get_transcript function that returns string**

Add a new function that returns transcript text instead of printing:

```python
def get_transcript(video_id):
    """Fetch transcript and return as string with source indicator"""
    try:
        api = YouTubeTranscriptApi()

        # Try English first
        try:
            transcript_data = api.fetch(video_id, languages=['en'])
            text = '\n'.join(segment.text for segment in transcript_data)
            return {'text': text, 'source': 'youtube', 'error': None}
        except:
            pass

        # Try any available transcript
        try:
            transcript_data = api.fetch(video_id)
            text = '\n'.join(segment.text for segment in transcript_data)
            return {'text': text, 'source': 'youtube', 'error': None}
        except:
            pass

        return {'text': None, 'source': None, 'error': 'No transcript available'}

    except Exception as e:
        return {'text': None, 'source': None, 'error': str(e)}
```

**Step 2: Test the function**

Run: `.venv/bin/python -c "from main import get_transcript; r = get_transcript('dQw4w9WgXcQ'); print(r['source'], len(r['text']) if r['text'] else 'None')"`

Expected: Shows source and length, or error message

**Step 3: Commit**

```bash
git add main.py
git commit -m "feat: add get_transcript function returning string"
```

---

### Task 1.4: Add Whisper Fallback to get_transcript

**Files:**
- Modify: `main.py` (get_transcript function)

**Step 1: Integrate Whisper fallback into get_transcript**

Update get_transcript to try Whisper when YouTube fails:

```python
def get_transcript(video_id):
    """Fetch transcript and return as string with source indicator"""
    try:
        api = YouTubeTranscriptApi()

        # Try English first
        try:
            transcript_data = api.fetch(video_id, languages=['en'])
            text = '\n'.join(segment.text for segment in transcript_data)
            return {'text': text, 'source': 'youtube', 'error': None}
        except:
            pass

        # Try any available transcript
        try:
            transcript_data = api.fetch(video_id)
            text = '\n'.join(segment.text for segment in transcript_data)
            return {'text': text, 'source': 'youtube', 'error': None}
        except:
            pass

        # Fallback to Whisper
        if OPENAI_API_KEY:
            audio_file = download_audio(video_id)
            if audio_file:
                whisper_result = transcribe_with_whisper_text(audio_file)
                if whisper_result:
                    return {'text': whisper_result, 'source': 'whisper', 'error': None}

        return {'text': None, 'source': None, 'error': 'No transcript available'}

    except Exception as e:
        return {'text': None, 'source': None, 'error': str(e)}


def transcribe_with_whisper_text(audio_file_path):
    """Transcribe audio file using OpenAI Whisper API, return text only"""
    if not OPENAI_API_KEY:
        return None

    try:
        client = openai.OpenAI(api_key=OPENAI_API_KEY)

        with open(audio_file_path, "rb") as audio_file:
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                response_format="text"
            )

        return transcript

    except Exception as e:
        print(f"Whisper error: {e}", file=sys.stderr)
        return None
    finally:
        try:
            os.remove(audio_file_path)
            temp_dir = os.path.dirname(audio_file_path)
            if os.path.exists(temp_dir) and not os.listdir(temp_dir):
                os.rmdir(temp_dir)
        except:
            pass
```

**Step 2: Commit**

```bash
git add main.py
git commit -m "feat: add Whisper fallback to get_transcript"
```

---

### Task 1.5: Implement JSON Output Mode

**Files:**
- Modify: `main.py` (main block)

**Step 1: Add JSON output logic**

Replace the main block with conditional JSON/text output:

```python
import json

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch YouTube video transcript and description.")
    parser.add_argument('video_id_in', type=str, help='The ID or URL of the YouTube video')
    parser.add_argument('--json', action='store_true', help='Output JSON instead of formatted text')
    args = parser.parse_args()

    video_id = youtube_parser(args.video_id_in)

    if args.json:
        # JSON output mode for n8n integration
        output = {
            'success': False,
            'video_id': video_id,
            'title': None,
            'channel': None,
            'transcript': None,
            'description': None,
            'transcript_source': None,
            'error': None
        }

        # Get metadata
        metadata = get_video_metadata(video_id)
        if metadata:
            output['title'] = metadata['title']
            output['channel'] = metadata['channel']
            output['description'] = metadata['description']

        # Get transcript
        transcript_result = get_transcript(video_id)
        output['transcript'] = transcript_result['text']
        output['transcript_source'] = transcript_result['source']

        if transcript_result['error'] and not metadata:
            output['error'] = transcript_result['error']
        else:
            output['success'] = True

        print(json.dumps(output, ensure_ascii=False))
    else:
        # Original text output mode
        print(f"Processing video ID: {video_id}")

        print("\n" + "="*50)
        print("TRANSCRIPT:")
        print("="*50)
        transcript_success = print_transcript(video_id)

        if not transcript_success:
            print("\nNo YouTube transcript available. Trying Whisper transcription...")
            audio_file = download_audio(video_id)
            if audio_file:
                whisper_success = transcribe_with_whisper(audio_file)
                if not whisper_success:
                    print("Whisper transcription also failed.")
            else:
                print("Could not download audio for Whisper transcription.")

        print("\n" + "="*50)
        print("VIDEO DESCRIPTION:")
        print("="*50)
        description = get_video_description(video_id)
        if description:
            print(description)
        else:
            print("No description found for the video.")
```

**Step 2: Test JSON output**

Run: `.venv/bin/python main.py --json "dQw4w9WgXcQ" | python -m json.tool`

Expected: Valid JSON with video_id, title, channel, transcript, description fields

**Step 3: Test text output still works**

Run: `.venv/bin/python main.py "dQw4w9WgXcQ" | head -5`

Expected: Original formatted output

**Step 4: Commit**

```bash
git add main.py
git commit -m "feat: implement --json output mode for n8n integration"
```

---

### Task 1.6: Keep Backwards Compatibility

**Files:**
- Modify: `main.py` (ensure get_video_description still exists)

**Step 1: Add wrapper for backwards compatibility**

Keep the old function name as a wrapper:

```python
def get_video_description(video_id):
    """Backwards compatible wrapper - returns description string only"""
    metadata = get_video_metadata(video_id)
    if metadata:
        return metadata['description']
    return None
```

**Step 2: Test backwards compatibility**

Run: `.venv/bin/python main.py "dQw4w9WgXcQ"`

Expected: Original output format unchanged

**Step 3: Commit**

```bash
git add main.py
git commit -m "refactor: maintain backwards compatibility for get_video_description"
```

---

## Phase 2: AI Prompt Templates

### Task 2.1: Create Prompt Templates File

**Files:**
- Create: `prompts/recipe_extraction.py`

**Step 1: Create prompts directory**

```bash
mkdir -p prompts
```

**Step 2: Create the prompt templates file**

```python
"""Prompt templates for AI recipe extraction"""

SYSTEM_PROMPT = """You are a recipe extraction assistant. Given a YouTube video transcript
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
}"""

USER_PROMPT_TEMPLATE = """Extract a recipe from this cooking video.

VIDEO TITLE: {title}
CHANNEL: {channel}

DESCRIPTION:
{description}

TRANSCRIPT:
{transcript}"""


def build_user_prompt(title, channel, description, transcript):
    """Build the user prompt with video data"""
    return USER_PROMPT_TEMPLATE.format(
        title=title or "Unknown",
        channel=channel or "Unknown",
        description=description or "No description",
        transcript=transcript or "No transcript"
    )
```

**Step 3: Create __init__.py**

```python
# prompts/__init__.py
from .recipe_extraction import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE, build_user_prompt
```

**Step 4: Commit**

```bash
git add prompts/
git commit -m "feat: add AI prompt templates for recipe extraction"
```

---

### Task 2.2: Create Recipe Markdown Template

**Files:**
- Create: `templates/recipe_template.py`

**Step 1: Create the template file**

```python
"""Markdown template for recipe output"""

from datetime import date

RECIPE_TEMPLATE = """---
title: "{title}"
source_url: "{source_url}"
source_channel: "{source_channel}"
date_added: {date_added}
video_title: "{video_title}"

prep_time: {prep_time}
cook_time: {cook_time}
total_time: {total_time}
servings: {servings}
difficulty: {difficulty}

cuisine: {cuisine}
protein: {protein}
dish_type: {dish_type}
dietary: {dietary}

equipment: {equipment}

tags:
{tags}

needs_review: {needs_review}
confidence_notes: "{confidence_notes}"
---

# {title}

> {description}

## Ingredients

{ingredients}

## Instructions

{instructions}

## Equipment

{equipment_list}
{notes_section}
---
*Extracted from [{video_title}]({source_url}) on {date_added}*
"""


def format_recipe_markdown(recipe_data, video_url, video_title, channel):
    """Format recipe data into markdown string"""

    # Format ingredients
    ingredients_lines = []
    for ing in recipe_data.get('ingredients', []):
        inferred = " *(inferred)*" if ing.get('inferred') else ""
        ingredients_lines.append(f"- {ing.get('quantity', '')} {ing.get('item', '')}{inferred}")

    # Format instructions
    instructions_lines = []
    for inst in recipe_data.get('instructions', []):
        time_note = f" ({inst['time']})" if inst.get('time') else ""
        instructions_lines.append(f"{inst.get('step', '')}. {inst.get('text', '')}{time_note}")

    # Format equipment list
    equipment_list = '\n'.join(f"- {e}" for e in recipe_data.get('equipment', []))

    # Format dietary as YAML list
    dietary = recipe_data.get('dietary', [])
    dietary_yaml = f"[{', '.join(dietary)}]" if dietary else "[]"

    # Format equipment as YAML list
    equipment = recipe_data.get('equipment', [])
    equipment_yaml = f"[{', '.join(f'\"{e}\"' for e in equipment)}]" if equipment else "[]"

    # Format tags
    tags = []
    if recipe_data.get('cuisine'):
        tags.append(f"  - {recipe_data['cuisine'].lower().replace(' ', '-')}")
    if recipe_data.get('protein'):
        tags.append(f"  - {recipe_data['protein'].lower().replace(' ', '-')}")
    if recipe_data.get('dish_type'):
        tags.append(f"  - {recipe_data['dish_type'].lower().replace(' ', '-')}")
    tags_yaml = '\n'.join(tags) if tags else "  - recipe"

    # Build notes section
    notes_parts = []
    if recipe_data.get('storage'):
        notes_parts.append(f"### Storage\n{recipe_data['storage']}")
    if recipe_data.get('variations'):
        variations = '\n'.join(f"- {v}" for v in recipe_data['variations'])
        notes_parts.append(f"### Variations\n{variations}")
    if recipe_data.get('nutritional_info'):
        notes_parts.append(f"### Nutritional Info\n{recipe_data['nutritional_info']}")

    notes_section = "\n\n## Notes\n\n" + "\n\n".join(notes_parts) + "\n" if notes_parts else ""

    # Calculate total time
    prep = recipe_data.get('prep_time')
    cook = recipe_data.get('cook_time')
    total = recipe_data.get('total_time')

    # Format nullable fields
    def quote_or_null(val):
        return f'"{val}"' if val else "null"

    def num_or_null(val):
        return val if val is not None else "null"

    return RECIPE_TEMPLATE.format(
        title=recipe_data.get('recipe_name', 'Untitled Recipe'),
        source_url=video_url,
        source_channel=channel or "Unknown",
        date_added=date.today().isoformat(),
        video_title=video_title or "Unknown Video",
        prep_time=quote_or_null(prep),
        cook_time=quote_or_null(cook),
        total_time=quote_or_null(total or prep or cook),
        servings=num_or_null(recipe_data.get('servings')),
        difficulty=quote_or_null(recipe_data.get('difficulty')),
        cuisine=quote_or_null(recipe_data.get('cuisine')),
        protein=quote_or_null(recipe_data.get('protein')),
        dish_type=quote_or_null(recipe_data.get('dish_type')),
        dietary=dietary_yaml,
        equipment=equipment_yaml,
        tags=tags_yaml,
        needs_review=str(recipe_data.get('needs_review', True)).lower(),
        confidence_notes=recipe_data.get('confidence_notes', ''),
        description=recipe_data.get('description', ''),
        ingredients='\n'.join(ingredients_lines),
        instructions='\n'.join(instructions_lines),
        equipment_list=equipment_list,
        notes_section=notes_section
    )


def generate_filename(recipe_name):
    """Generate filename from recipe name"""
    import re
    slug = re.sub(r'[^a-z0-9]+', '-', recipe_name.lower()).strip('-')
    return f"{date.today().isoformat()}-{slug}.md"
```

**Step 2: Update templates/__init__.py if it exists, or create it**

```python
# templates/__init__.py (create or update)
from .recipe_template import format_recipe_markdown, generate_filename
```

**Step 3: Commit**

```bash
git add templates/
git commit -m "feat: add recipe markdown template formatter"
```

---

## Phase 3: Setup Tasks

### Task 3.1: Create Apple Reminders List

**Manual step - no code**

1. Open Apple Reminders app
2. Create new list named "Recipes to Process"
3. Note: This list will hold YouTube URLs to process

**Verification:** Open Reminders, confirm list exists

---

### Task 3.2: Verify Ollama Model

**Step 1: Check if model is installed**

Run: `ollama list | grep llama3.1`

**Step 2: If not present, pull the model**

Run: `ollama pull llama3.1:8b`

Expected: Model downloads (4.7GB)

**Step 3: Test model responds**

Run: `curl http://localhost:11434/api/generate -d '{"model": "llama3.1:8b", "prompt": "Say hello", "stream": false}' | python -m json.tool`

Expected: JSON response with "response" field containing greeting

---

### Task 3.3: Create Obsidian Vault

**Manual step**

1. Open Obsidian
2. Create new vault (or use existing)
3. Create folder: `Recipes/`
4. Note the full path to the Recipes folder

**Path format:** `/Users/chaseeasterling/path/to/vault/Recipes/`

---

## Phase 4: n8n Workflows

### Task 4.1: Create Webhook Workflow

**This task is done in n8n UI**

**Step 1: Create new workflow named "YouTube Recipe - Webhook"**

**Step 2: Add Webhook node**
- HTTP Method: POST
- Path: `recipe`
- Response Mode: Last Node

**Step 3: Add Execute Command node (Extract Video ID)**
- Command: `echo '{{ $json.url }}' | grep -oP 'v=\K[^&]+' || echo '{{ $json.url }}' | grep -oP 'youtu.be/\K[^?]+'`

**Step 4: Add Execute Command node (Fetch Transcript)**
- Command: `/path/to/.venv/bin/python /path/to/main.py --json "{{ $json.stdout.trim() }}"`
- Note: Replace paths with actual paths

**Step 5: Add HTTP Request node (Ollama)**
- Method: POST
- URL: `http://localhost:11434/api/generate`
- Body (JSON):
```json
{
  "model": "llama3.1:8b",
  "prompt": "SYSTEM: [paste system prompt]\n\nUSER: Extract a recipe from this cooking video.\n\nVIDEO TITLE: {{ $json.title }}\nCHANNEL: {{ $json.channel }}\n\nDESCRIPTION:\n{{ $json.description }}\n\nTRANSCRIPT:\n{{ $json.transcript }}",
  "stream": false,
  "format": "json"
}
```

**Step 6: Add IF node (Validate Response)**
- Condition: Check if response contains valid JSON with recipe_name

**Step 7: Add Write File node**
- File Path: `/path/to/vault/Recipes/{{ $now.format('yyyy-MM-dd') }}-{{ $json.response.recipe_name | slug }}.md`
- File Content: [Use template from design doc]

**Step 8: Save and activate workflow**

**Step 9: Test with curl**

Run:
```bash
curl -X POST http://localhost:5678/webhook/recipe \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.youtube.com/watch?v=VIDEO_ID"}'
```

---

### Task 4.2: Create Reminders Polling Workflow

**This task is done in n8n UI**

**Step 1: Create new workflow named "YouTube Recipe - Reminders"**

**Step 2: Add Schedule Trigger node**
- Interval: 1 day
- Time: Choose preferred time (e.g., 6:00 AM)

**Step 3: Add Execute Command node (Get Reminders)**
- Command:
```bash
osascript -e 'tell application "Reminders"
    set recipeList to list "Recipes to Process"
    set output to ""
    repeat with r in (reminders in recipeList whose completed is false)
        set output to output & name of r & linefeed
    end repeat
    return output
end tell'
```

**Step 4: Add Split In Batches node**
- Split by: newline
- Batch Size: 1

**Step 5: Connect to same processing nodes as webhook workflow**
- Execute Command (Fetch Transcript)
- HTTP Request (Ollama)
- IF (Validate)
- Write File

**Step 6: Add Execute Command node (Mark Complete)**
- Command:
```bash
osascript -e 'tell application "Reminders"
    set recipeList to list "Recipes to Process"
    repeat with r in (reminders in recipeList whose completed is false)
        if name of r is "{{ $json.url }}" then
            set completed of r to true
        end if
    end repeat
end tell'
```

**Step 7: Save and activate workflow**

---

### Task 4.3: Add Claude API Fallback

**This task is done in n8n UI**

**Step 1: Add Claude API credentials in n8n**
- Go to Settings > Credentials
- Add new: HTTP Header Auth
- Name: Claude API
- Header Name: x-api-key
- Header Value: [your API key]
- Also add header: anthropic-version = 2023-06-01

**Step 2: In webhook workflow, after IF node (false branch)**

Add HTTP Request node (Claude):
- Method: POST
- URL: `https://api.anthropic.com/v1/messages`
- Authentication: Claude API (created above)
- Headers: `Content-Type: application/json`
- Body:
```json
{
  "model": "claude-sonnet-4-20250514",
  "max_tokens": 4096,
  "messages": [
    {
      "role": "user",
      "content": "[same prompt as Ollama]"
    }
  ],
  "system": "[system prompt]"
}
```

**Step 3: Connect Claude node to Write File node**

**Step 4: Repeat for Reminders workflow**

---

## Phase 5: iOS Shortcut

### Task 5.1: Create iOS Shortcut

**This task is done on iPhone**

**Step 1: Open Shortcuts app**

**Step 2: Create new shortcut named "Save Recipe"**

**Step 3: Configure to accept URLs from Share Sheet**
- Tap the (i) icon
- Enable "Show in Share Sheet"
- Share Sheet Types: URLs

**Step 4: Add actions:**

1. **Get URLs from Input**
   - Input: Shortcut Input

2. **Get Contents of URL**
   - URL: `http://YOUR_MAC_IP:5678/webhook/recipe`
   - Method: POST
   - Headers: `Content-Type: application/json`
   - Request Body: JSON
   - Body: `{"url": "[URLs]"}`

3. **Show Notification**
   - Title: "Recipe Saved"
   - Body: "Processing recipe from YouTube..."

**Step 5: Test**
- Open YouTube app
- Find a cooking video
- Tap Share
- Select "Save Recipe" shortcut
- Verify notification appears

---

### Task 5.2: Note Mac's Local IP

**Step 1: Get IP address**

Run: `ipconfig getifaddr en0`

Expected: IP like `192.168.1.XXX`

**Step 2: Update iOS Shortcut with this IP**

**Optional: Set static IP in router settings for reliability**

---

## Phase 6: Integration Testing

### Task 6.1: End-to-End Test - Webhook Path

**Step 1: Find a cooking video with transcript**

Example: Search YouTube for "easy pasta recipe" and pick one

**Step 2: Send to webhook**

```bash
curl -X POST http://localhost:5678/webhook/recipe \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.youtube.com/watch?v=VIDEO_ID"}'
```

**Step 3: Check Obsidian vault**

Run: `ls -la /path/to/vault/Recipes/`

Expected: New .md file with today's date

**Step 4: Open in Obsidian and verify**
- Frontmatter is valid YAML
- Recipe content is reasonable
- Tags and metadata populated

---

### Task 6.2: End-to-End Test - Reminders Path

**Step 1: Add a YouTube URL to "Recipes to Process" list in Reminders**

**Step 2: Manually trigger the n8n workflow (or wait for schedule)**

**Step 3: Verify:**
- Recipe file created in Obsidian
- Reminder marked as complete

---

### Task 6.3: End-to-End Test - iOS Share Sheet

**Step 1: On iPhone, open YouTube app**

**Step 2: Find a cooking video**

**Step 3: Tap Share → Save Recipe**

**Step 4: Verify notification appears**

**Step 5: Check Mac - recipe file should appear in Obsidian vault**

---

## Completion Checklist

- [ ] Python script outputs valid JSON with --json flag
- [ ] Python script backwards compatible without flag
- [ ] Ollama model installed and responding
- [ ] Apple Reminders list "Recipes to Process" created
- [ ] Obsidian vault with Recipes/ folder exists
- [ ] n8n webhook workflow active and tested
- [ ] n8n Reminders workflow active and tested
- [ ] Claude API fallback configured (optional)
- [ ] iOS Shortcut created and tested
- [ ] End-to-end test passed for all three paths
