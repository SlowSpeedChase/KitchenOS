#!/usr/bin/env python3
"""Simple API server for iOS Shortcuts integration."""

from flask import Flask, request, jsonify, send_file
from youtube_transcript_api import YouTubeTranscriptApi
from googleapiclient.discovery import build
import os
import re
import subprocess
import time
import warnings
from datetime import timedelta
from pathlib import Path
from dotenv import load_dotenv

from lib.shopping_list_generator import (
    generate_shopping_list,
    parse_shopping_list_file,
    extract_manual_items,
    SHOPPING_LISTS_PATH,
)
from lib.backup import create_backup
from lib.recipe_index import get_recipe_index
from lib.meal_plan_parser import insert_recipe_into_meal_plan, parse_meal_plan, rebuild_meal_plan_markdown
from lib.recipe_parser import parse_recipe_file, extract_my_notes, parse_recipe_body
from templates.shopping_list_template import generate_shopping_list_markdown, generate_filename as shopping_list_filename
from templates.recipe_template import format_recipe_markdown
from templates.meal_plan_template import generate_meal_plan_markdown

load_dotenv()
warnings.filterwarnings('ignore', message='urllib3 v2 only supports OpenSSL 1.1.1+')

YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY')
OBSIDIAN_RECIPES_PATH = Path("/Users/chaseeasterling/Library/Mobile Documents/iCloud~md~obsidian/Documents/KitchenOS/Recipes")
MEAL_PLANS_PATH = Path("/Users/chaseeasterling/Library/Mobile Documents/iCloud~md~obsidian/Documents/KitchenOS/Meal Plans")

app = Flask(__name__)

_recipe_cache = {"data": None, "timestamp": 0}
RECIPE_CACHE_TTL = 300  # 5 minutes


def error_page(message: str) -> str:
    """Generate simple HTML error page."""
    return f'''<!DOCTYPE html>
<html><head><title>KitchenOS</title></head>
<body style="font-family: system-ui; padding: 2rem; max-width: 600px; margin: 0 auto;">
<div style="background: #fee; border: 1px solid #c00; padding: 1rem; border-radius: 8px;">
<strong style="color: #c00;">Error</strong><br>{message}
</div>
<p><a href="obsidian://open?vault=KitchenOS">Return to Obsidian</a></p>
</body></html>'''


def success_page(message: str, filename: str) -> str:
    """Generate simple HTML success page."""
    from urllib.parse import quote
    encoded_filename = quote(filename, safe='')
    return f'''<!DOCTYPE html>
<html><head><title>KitchenOS</title></head>
<body style="font-family: system-ui; padding: 2rem; max-width: 600px; margin: 0 auto;">
<div style="background: #efe; border: 1px solid #0a0; padding: 1rem; border-radius: 8px;">
<strong style="color: #0a0;">Success</strong><br>{message}
</div>
<p><a href="obsidian://open?vault=KitchenOS&file=Recipes/{encoded_filename}">Return to {filename}</a></p>
</body></html>'''


def inject_my_notes(content: str, notes: str) -> str:
    """Replace the My Notes placeholder with preserved notes."""
    placeholder = "<!-- Your personal notes, ratings, and modifications go here -->"
    return content.replace(placeholder, notes)


def youtube_parser(input_str):
    """Extract video ID from URL and detect Shorts.

    Returns:
        dict with keys:
            - video_id: str
            - is_short: bool (True if /shorts/ URL)
    """
    # Handle Shorts URLs
    match = re.search(r'youtube\.com/shorts/([^?&/]+)', input_str)
    if match:
        return {'video_id': match.group(1), 'is_short': True}
    # Handle youtu.be short URLs
    match = re.search(r'youtu\.be/([^?&]+)', input_str)
    if match:
        return {'video_id': match.group(1), 'is_short': False}
    # Handle standard YouTube URLs
    match = re.search(r'v=([^&]+)', input_str)
    if match:
        return {'video_id': match.group(1), 'is_short': False}
    return {'video_id': input_str, 'is_short': False}


def get_video_description(video_id, is_short=False):
    """Fetch video description. Uses yt-dlp for Shorts, YouTube API for regular videos."""
    if is_short:
        return get_video_description_ytdlp(video_id, is_short=True)

    try:
        youtube = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)
        request = youtube.videos().list(part='snippet', id=video_id)
        response = request.execute()

        if 'items' in response and len(response['items']) > 0:
            return response['items'][0]['snippet']['description']
        return None
    except Exception as e:
        return f"[Error fetching description: {e}]"


def get_video_description_ytdlp(video_id, is_short=False):
    """Fetch video description using yt-dlp (for Shorts)."""
    import yt_dlp

    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'extract_flat': False,
    }

    if is_short:
        url = f"https://www.youtube.com/shorts/{video_id}"
    else:
        url = f"https://www.youtube.com/watch?v={video_id}"

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info.get('description', '')
    except Exception as e:
        return f"[Error fetching description: {e}]"


def get_transcript(video_id):
    """Fetch transcript from YouTube."""
    try:
        api = YouTubeTranscriptApi()
        try:
            transcript_data = api.fetch(video_id, languages=['en'])
        except:
            transcript_data = api.fetch(video_id)

        return ' '.join([segment.text for segment in transcript_data])
    except Exception as e:
        return None


@app.route('/transcript', methods=['GET', 'POST'])
def get_video_info():
    """Main endpoint - accepts URL via GET param or POST body."""
    if request.method == 'POST':
        data = request.get_json(force=True, silent=True) or {}
        url = data.get('url') or request.form.get('url')
    else:
        url = request.args.get('url')

    if not url:
        return jsonify({'error': 'No URL provided'}), 400

    parsed = youtube_parser(url)
    video_id = parsed['video_id']
    is_short = parsed['is_short']

    # Build the output blob
    output_parts = []

    # Get transcript
    transcript = get_transcript(video_id)
    if transcript:
        output_parts.append("TRANSCRIPT:")
        output_parts.append(transcript)
    else:
        output_parts.append("TRANSCRIPT: No transcript available")

    output_parts.append("")  # blank line

    # Get description (uses yt-dlp for Shorts)
    description = get_video_description(video_id, is_short=is_short)
    if description:
        output_parts.append("DESCRIPTION:")
        output_parts.append(description)
    else:
        output_parts.append("DESCRIPTION: No description available")

    combined_text = '\n'.join(output_parts)

    return jsonify({
        'text': combined_text,
        'video_id': video_id,
        'is_short': is_short
    })


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint."""
    return jsonify({'status': 'ok'})


@app.route('/api/recipes', methods=['GET'])
def api_recipes():
    """Return recipe metadata for meal planner sidebar."""
    now = time.time()
    if _recipe_cache["data"] is None or (now - _recipe_cache["timestamp"]) > RECIPE_CACHE_TTL:
        _recipe_cache["data"] = get_recipe_index(OBSIDIAN_RECIPES_PATH)
        _recipe_cache["timestamp"] = now
    return jsonify(_recipe_cache["data"])


@app.route('/extract', methods=['POST'])
def extract_recipe():
    """Run full recipe extraction and save to Obsidian."""
    data = request.get_json(force=True, silent=True) or {}
    url = data.get('url')

    if not url:
        return jsonify({'error': 'No URL provided'}), 400

    try:
        result = subprocess.run(
            ['.venv/bin/python', 'extract_recipe.py', url],
            capture_output=True,
            text=True,
            cwd='/Users/chaseeasterling/KitchenOS',
            timeout=300  # 5 min timeout
        )

        # Parse output for "SAVED: /path/to/file.md"
        if result.returncode == 0 and 'SAVED:' in result.stdout:
            saved_line = [l for l in result.stdout.split('\n') if 'SAVED:' in l][0]
            filepath = saved_line.split('SAVED:')[1].strip()
            recipe_name = Path(filepath).stem
            return jsonify({'status': 'success', 'recipe': recipe_name})
        else:
            error_msg = result.stderr.strip() if result.stderr else 'Extraction failed'
            return jsonify({'status': 'error', 'message': error_msg}), 500

    except subprocess.TimeoutExpired:
        return jsonify({'status': 'error', 'message': 'Extraction timed out (5 min)'}), 504
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/generate-shopping-list', methods=['POST'])
def generate_shopping_list_endpoint():
    """Generate shopping list markdown from meal plan."""
    data = request.get_json(force=True, silent=True) or {}
    week = data.get('week')

    if not week:
        return jsonify({'success': False, 'error': 'No week provided'}), 400

    # Generate the shopping list
    result = generate_shopping_list(week)

    if not result['success']:
        return jsonify(result), 400

    # Check for existing manual items before overwriting
    manual_items = []
    filename = shopping_list_filename(week)
    filepath = SHOPPING_LISTS_PATH / filename
    if filepath.exists():
        existing_result = parse_shopping_list_file(week)
        if existing_result['success']:
            manual_items = extract_manual_items(
                existing_result['items'],
                result['items']
            )

    # Combine generated items with manual items
    all_items = result['items'] + manual_items

    # Create markdown content
    markdown = generate_shopping_list_markdown(week, all_items)

    # Ensure Shopping Lists folder exists
    SHOPPING_LISTS_PATH.mkdir(parents=True, exist_ok=True)

    # Write file
    filepath.write_text(markdown, encoding='utf-8')

    return jsonify({
        'success': True,
        'file': f"Shopping Lists/{filename}",
        'item_count': len(all_items),
        'generated_count': len(result['items']),
        'manual_count': len(manual_items),
        'recipes': result['recipes'],
        'warnings': result.get('warnings', [])
    })


@app.route('/send-to-reminders', methods=['POST'])
def send_to_reminders_endpoint():
    """Send shopping list items to Apple Reminders."""
    from lib.reminders import add_to_reminders, create_reminders_list

    data = request.get_json(force=True, silent=True) or {}
    week = data.get('week')

    if not week:
        return jsonify({'success': False, 'error': 'No week provided'}), 400

    # Parse shopping list
    result = parse_shopping_list_file(week)

    if not result['success']:
        return jsonify(result), 400

    if not result['items']:
        return jsonify({
            'success': True,
            'items_sent': 0,
            'items_skipped': result['skipped'],
            'message': 'No unchecked items to send'
        })

    # Send to Reminders
    try:
        create_reminders_list("Shopping")
        add_to_reminders(result['items'], "Shopping")

        return jsonify({
            'success': True,
            'items_sent': len(result['items']),
            'items_skipped': result['skipped']
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Failed to add to Reminders: {e}'
        }), 500


@app.route('/calendar.ics', methods=['GET'])
def serve_calendar():
    """Serve the meal plan calendar ICS file."""
    ics_path = Path("/Users/chaseeasterling/Library/Mobile Documents/iCloud~md~obsidian/Documents/KitchenOS/meal_calendar.ics")

    if not ics_path.exists():
        return "Calendar not generated. Run sync_calendar.py first.", 404

    return send_file(
        ics_path,
        mimetype='text/calendar',
        as_attachment=False,
        download_name='meal_calendar.ics'
    )


@app.route('/refresh-nutrition', methods=['GET'])
def refresh_nutrition():
    """Regenerate nutrition dashboard for a given week."""
    from lib.nutrition_dashboard import save_dashboard

    week = request.args.get('week')

    if not week:
        return error_page("Error: week parameter required (e.g., 2026-W03)"), 400

    vault_path = Path("/Users/chaseeasterling/Library/Mobile Documents/iCloud~md~obsidian/Documents/KitchenOS")

    try:
        output_path, warnings = save_dashboard(week, vault_path)

        # Generate success page with link to dashboard
        warnings_html = ""
        if warnings:
            warnings_list = "".join(f"<li>{w}</li>" for w in warnings)
            warnings_html = f'<div style="background: #ffc; border: 1px solid #cc0; padding: 1rem; border-radius: 8px; margin-top: 1rem;"><strong>Warnings:</strong><ul>{warnings_list}</ul></div>'

        return f'''<!DOCTYPE html>
<html><head><title>KitchenOS</title></head>
<body style="font-family: system-ui; padding: 2rem; max-width: 600px; margin: 0 auto;">
<div style="background: #efe; border: 1px solid #0a0; padding: 1rem; border-radius: 8px;">
<strong style="color: #0a0;">Success</strong><br>Dashboard updated for {week}
</div>
{warnings_html}
<p><a href="obsidian://open?vault=KitchenOS&file=Nutrition%20Dashboard">View Dashboard</a></p>
</body></html>'''

    except FileNotFoundError as e:
        return error_page(f"Error: {str(e)}"), 404
    except ValueError as e:
        return error_page(f"Error: {str(e)}"), 400
    except Exception as e:
        return error_page(f"Error generating dashboard: {str(e)}"), 500


@app.route('/refresh', methods=['GET'])
def refresh_template():
    """Regenerate recipe file with current template, preserving data and notes."""
    from urllib.parse import unquote

    filename = request.args.get('file')

    if not filename:
        return error_page("Error: file parameter required"), 400

    # URL-decode the filename
    filename = unquote(filename)
    filepath = OBSIDIAN_RECIPES_PATH / filename

    if not filepath.exists():
        return error_page(f"Error: Recipe not found: {filename}"), 404

    try:
        # Read and parse existing file
        content = filepath.read_text(encoding='utf-8')
        parsed = parse_recipe_file(content)
        frontmatter = parsed['frontmatter']
        body = parsed['body']

        # Extract notes to preserve
        my_notes = extract_my_notes(content)

        # Parse body for recipe data
        body_data = parse_recipe_body(body)

        # Build recipe_data from frontmatter + body
        recipe_data = {
            'recipe_name': frontmatter.get('title', 'Untitled'),
            'description': body_data.get('description', ''),
            'prep_time': frontmatter.get('prep_time'),
            'cook_time': frontmatter.get('cook_time'),
            'total_time': frontmatter.get('total_time'),
            'servings': frontmatter.get('servings'),
            'difficulty': frontmatter.get('difficulty'),
            'cuisine': frontmatter.get('cuisine'),
            'protein': frontmatter.get('protein'),
            'dish_type': frontmatter.get('dish_type'),
            'dietary': frontmatter.get('dietary', []),
            'equipment': frontmatter.get('equipment', []),
            'ingredients': body_data.get('ingredients', []),
            'instructions': body_data.get('instructions', []),
            'video_tips': body_data.get('video_tips', []),
            'needs_review': frontmatter.get('needs_review', False),
            'confidence_notes': frontmatter.get('confidence_notes', ''),
            'source': frontmatter.get('recipe_source', 'unknown'),
        }

        # Create backup
        create_backup(filepath)

        # Regenerate markdown (preserve original date_added)
        new_content = format_recipe_markdown(
            recipe_data,
            video_url=frontmatter.get('source_url', ''),
            video_title=frontmatter.get('video_title', ''),
            channel=frontmatter.get('source_channel', ''),
            date_added=frontmatter.get('date_added')
        )

        # Inject preserved notes
        if my_notes and my_notes != "<!-- Your personal notes, ratings, and modifications go here -->":
            new_content = inject_my_notes(new_content, my_notes)

        # Write file
        filepath.write_text(new_content, encoding='utf-8')

        return success_page("Template refreshed successfully", filename)

    except Exception as e:
        return error_page(f"Error refreshing template: {str(e)}"), 500


@app.route('/reprocess', methods=['GET'])
def reprocess_recipe():
    """Full re-extraction: fetch from YouTube, run through Ollama, regenerate."""
    from urllib.parse import unquote

    filename = request.args.get('file')

    if not filename:
        return error_page("Error: file parameter required"), 400

    # URL-decode the filename
    filename = unquote(filename)
    filepath = OBSIDIAN_RECIPES_PATH / filename

    if not filepath.exists():
        return error_page(f"Error: Recipe not found: {filename}"), 404

    try:
        # Read existing file to get source_url and notes
        content = filepath.read_text(encoding='utf-8')
        parsed = parse_recipe_file(content)
        frontmatter = parsed['frontmatter']

        source_url = frontmatter.get('source_url')
        if not source_url:
            return error_page("Error: Cannot reprocess - no source URL in recipe"), 400

        # Extract notes to preserve
        my_notes = extract_my_notes(content)

        # Create backup before re-extraction
        create_backup(filepath)

        # Run full extraction
        result = subprocess.run(
            ['.venv/bin/python', 'extract_recipe.py', source_url],
            capture_output=True,
            text=True,
            cwd='/Users/chaseeasterling/KitchenOS',
            timeout=300
        )

        if result.returncode != 0:
            error_msg = result.stderr.strip() if result.stderr else 'Extraction failed'
            return error_page(f"Error: {error_msg}"), 500

        # Inject preserved notes into the newly created file
        if my_notes and my_notes != "<!-- Your personal notes, ratings, and modifications go here -->":
            # Re-read the file (extract_recipe.py may have written to different filename)
            if filepath.exists():
                new_content = filepath.read_text(encoding='utf-8')
                new_content = inject_my_notes(new_content, my_notes)
                filepath.write_text(new_content, encoding='utf-8')

        return success_page("Recipe re-extracted successfully", filename)

    except subprocess.TimeoutExpired:
        return error_page("Error: Extraction timed out (5 min)"), 504
    except Exception as e:
        return error_page(f"Error: {str(e)}"), 500


@app.route('/api/meal-plan/<week>', methods=['GET'])
def api_meal_plan_get(week):
    """Return meal plan as structured JSON."""
    match = re.match(r'^(\d{4})-W(\d{2})$', week)
    if not match:
        return jsonify({"error": "Invalid week format. Expected YYYY-WNN"}), 400

    year = int(match.group(1))
    week_num = int(match.group(2))

    MEAL_PLANS_PATH.mkdir(parents=True, exist_ok=True)
    plan_file = MEAL_PLANS_PATH / f"{week}.md"

    if not plan_file.exists():
        content = generate_meal_plan_markdown(year, week_num)
        plan_file.write_text(content, encoding="utf-8")
    else:
        content = plan_file.read_text(encoding="utf-8")

    parsed = parse_meal_plan(content, year, week_num)

    days = []
    for day_data in parsed:
        day_json = {
            "day": day_data["day"],
            "date": day_data["date"].isoformat(),
            "breakfast": None, "lunch": None, "dinner": None,
        }
        for meal in ("breakfast", "lunch", "dinner"):
            entry = day_data[meal]
            if entry is not None:
                day_json[meal] = {"name": entry.name, "servings": entry.servings}
        days.append(day_json)

    return jsonify({"week": week, "days": days})


@app.route('/api/meal-plan/<week>', methods=['PUT'])
def api_meal_plan_put(week):
    """Save meal plan from structured JSON."""
    match = re.match(r'^(\d{4})-W(\d{2})$', week)
    if not match:
        return jsonify({"error": "Invalid week format. Expected YYYY-WNN"}), 400

    data = request.get_json(force=True, silent=True)
    if not data or "days" not in data:
        return jsonify({"error": "Request body must include 'days' array"}), 400

    content = rebuild_meal_plan_markdown(week, data["days"])

    MEAL_PLANS_PATH.mkdir(parents=True, exist_ok=True)
    plan_file = MEAL_PLANS_PATH / f"{week}.md"
    plan_file.write_text(content, encoding="utf-8")

    _recipe_cache["data"] = None

    return jsonify({"status": "saved", "week": week})


@app.route('/add-to-meal-plan', methods=['GET'])
def add_to_meal_plan_form():
    """Serve HTML form for picking meal plan slot."""
    from urllib.parse import unquote
    from datetime import date

    recipe = request.args.get('recipe')
    if not recipe:
        return error_page("Error: recipe parameter required"), 400

    recipe = unquote(recipe)
    # Strip .md extension for display
    recipe_display = recipe.replace('.md', '')

    # Generate week options: current week + next 3
    today = date.today()
    weeks = []
    for i in range(4):
        d = today + timedelta(days=7 * i)
        iso = d.isocalendar()
        week_id = f"{iso[0]}-W{iso[1]:02d}"
        weeks.append(week_id)

    days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    meals = ['Breakfast', 'Lunch', 'Dinner']

    week_options = ''.join(f'<option value="{w}">{w}</option>' for w in weeks)
    day_options = ''.join(f'<option value="{d}">{d}</option>' for d in days)
    meal_options = ''.join(f'<option value="{m}">{m}</option>' for m in meals)

    return f'''<!DOCTYPE html>
<html><head>
<title>Add to Meal Plan</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
    body {{ font-family: system-ui; padding: 1.5rem; max-width: 480px; margin: 0 auto; background: #fafafa; }}
    h2 {{ margin-top: 0; }}
    .recipe-name {{ background: #f0f0f0; padding: 0.75rem; border-radius: 8px; margin-bottom: 1.5rem; font-weight: 600; }}
    label {{ display: block; font-weight: 600; margin-bottom: 0.25rem; margin-top: 1rem; }}
    select {{ width: 100%; padding: 0.75rem; font-size: 16px; border: 1px solid #ccc; border-radius: 8px; background: white; -webkit-appearance: none; }}
    button {{ width: 100%; padding: 1rem; font-size: 18px; font-weight: 600; background: #2563eb; color: white; border: none; border-radius: 8px; margin-top: 1.5rem; cursor: pointer; }}
    button:active {{ background: #1d4ed8; }}
</style>
</head>
<body>
<h2>Add to Meal Plan</h2>
<div class="recipe-name">{recipe_display}</div>
<form method="POST" action="/add-to-meal-plan">
    <input type="hidden" name="recipe" value="{recipe_display}">
    <label for="week">Week</label>
    <select name="week" id="week">{week_options}</select>
    <label for="day">Day</label>
    <select name="day" id="day">{day_options}</select>
    <label for="meal">Meal</label>
    <select name="meal" id="meal">{meal_options}</select>
    <button type="submit">Add to Meal Plan</button>
</form>
</body></html>'''


@app.route('/add-to-meal-plan', methods=['POST'])
def add_to_meal_plan():
    """Add recipe to a meal plan slot."""
    recipe = request.form.get('recipe')
    week = request.form.get('week')
    day = request.form.get('day')
    meal = request.form.get('meal')

    if not all([recipe, week, day, meal]):
        return error_page("Error: recipe, week, day, and meal are all required"), 400

    # Parse week string (e.g. "2026-W07")
    try:
        parts = week.split('-W')
        year = int(parts[0])
        week_num = int(parts[1])
    except (ValueError, IndexError):
        return error_page(f"Error: Invalid week format: {week}"), 400

    # Find or create meal plan file
    MEAL_PLANS_PATH.mkdir(parents=True, exist_ok=True)
    plan_file = MEAL_PLANS_PATH / f"{week}.md"

    if not plan_file.exists():
        content = generate_meal_plan_markdown(year, week_num)
        plan_file.write_text(content, encoding='utf-8')

    # Read current content and insert recipe
    content = plan_file.read_text(encoding='utf-8')
    try:
        new_content = insert_recipe_into_meal_plan(content, day, meal, recipe)
    except ValueError as e:
        return error_page(f"Error: {str(e)}"), 400

    plan_file.write_text(new_content, encoding='utf-8')

    # Success page with link to meal plan in Obsidian
    from urllib.parse import quote
    encoded_file = quote(f"Meal Plans/{week}", safe='')
    return f'''<!DOCTYPE html>
<html><head><title>KitchenOS</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
</head>
<body style="font-family: system-ui; padding: 2rem; max-width: 600px; margin: 0 auto;">
<div style="background: #efe; border: 1px solid #0a0; padding: 1rem; border-radius: 8px;">
<strong style="color: #0a0;">Added!</strong><br>
[[{recipe}]] &rarr; {day} {meal} ({week})
</div>
<p><a href="obsidian://open?vault=KitchenOS&file={encoded_file}">View Meal Plan</a></p>
<p><a href="obsidian://open?vault=KitchenOS">Back to Obsidian</a></p>
</body></html>'''


@app.route('/meal-planner', methods=['GET'])
def meal_planner():
    """Serve the interactive meal planner board."""
    return send_file('templates/meal_planner.html', mimetype='text/html')


if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
