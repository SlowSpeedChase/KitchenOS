#!/usr/bin/env python3
"""Simple API server for iOS Shortcuts integration."""

from flask import Flask, request, jsonify, send_file, redirect
from urllib.parse import quote
from youtube_transcript_api import YouTubeTranscriptApi
from googleapiclient.discovery import build
import os
import re
import subprocess
import time
import warnings
from datetime import date, timedelta
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
from lib.ingredient_validator import validate_ingredients
from lib.seasonality import match_ingredients_to_seasonal, get_peak_months
from lib.nutrition_lookup import calculate_recipe_nutrition
from lib import meal_loader, pantry as pantry_module, paths, task_extractor

load_dotenv()
warnings.filterwarnings('ignore', message='urllib3 v2 only supports OpenSSL 1.1.1+')

YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY')
OBSIDIAN_RECIPES_PATH = paths.recipes_dir()
MEAL_PLANS_PATH = paths.meal_plans_dir()

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
    except Exception:
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


@app.route('/api/recipes/save', methods=['POST'])
def api_recipe_save():
    """Save a recipe from structured JSON data (e.g., from Claude conversation)."""
    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({"error": "Request body required"}), 400

    recipe_name = data.get('recipe_name')
    if not recipe_name:
        return jsonify({"error": "recipe_name is required"}), 400

    try:
        # Validate ingredients
        if data.get('ingredients'):
            data['ingredients'] = validate_ingredients(
                data['ingredients'], verbose=False
            )

        # Match seasonal ingredients
        seasonal_matches = match_ingredients_to_seasonal(
            data.get('ingredients', [])
        )
        data['seasonal_ingredients'] = seasonal_matches
        data['peak_months'] = get_peak_months(seasonal_matches)

        # Calculate nutrition
        ingredients = data.get('ingredients', [])
        try:
            servings = int(data.get('servings', 1) or 1)
        except (ValueError, TypeError):
            servings = 1

        nutrition_result = calculate_recipe_nutrition(ingredients, servings)
        if nutrition_result:
            data['nutrition_calories'] = nutrition_result.nutrition.calories
            data['nutrition_protein'] = nutrition_result.nutrition.protein
            data['nutrition_carbs'] = nutrition_result.nutrition.carbs
            data['nutrition_fat'] = nutrition_result.nutrition.fat
            data['nutrition_source'] = nutrition_result.source

        # Set source metadata
        data.setdefault('source', 'claude')
        data.setdefault('needs_review', False)

        # Generate markdown
        markdown = format_recipe_markdown(
            data,
            video_url=data.get('source_url', ''),
            video_title='',
            channel=data.get('source_channel', ''),
        )

        # Save to Obsidian
        OBSIDIAN_RECIPES_PATH.mkdir(parents=True, exist_ok=True)
        safe_name = re.sub(r'[<>:"/\\|?*/]', '', recipe_name)
        safe_name = ' '.join(safe_name.split()).title()
        filepath = (OBSIDIAN_RECIPES_PATH / f"{safe_name}.md").resolve()
        if not filepath.is_relative_to(OBSIDIAN_RECIPES_PATH.resolve()):
            return jsonify({"error": "Invalid recipe name"}), 400

        if filepath.exists():
            create_backup(filepath)

        filepath.write_text(markdown, encoding='utf-8')

        # Invalidate recipe cache
        _recipe_cache["data"] = None

        return jsonify({
            "status": "success",
            "recipe_name": recipe_name,
            "file": safe_name + ".md",
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/recipes/<name>', methods=['GET'])
def api_recipe_detail(name):
    """Return full recipe details as JSON."""
    filepath = (OBSIDIAN_RECIPES_PATH / f"{name}.md").resolve()
    if not filepath.is_relative_to(OBSIDIAN_RECIPES_PATH.resolve()):
        return jsonify({"error": "Invalid recipe name"}), 400

    if not filepath.exists():
        return jsonify({"error": f"Recipe not found: {name}"}), 404

    try:
        content = filepath.read_text(encoding='utf-8')
        parsed = parse_recipe_file(content)
        fm = parsed['frontmatter']
        body_data = parse_recipe_body(parsed['body'])

        return jsonify({
            "title": fm.get('title', name),
            "cuisine": fm.get('cuisine'),
            "protein": fm.get('protein'),
            "dish_type": fm.get('dish_type'),
            "difficulty": fm.get('difficulty'),
            "servings": fm.get('servings'),
            "prep_time": fm.get('prep_time'),
            "cook_time": fm.get('cook_time'),
            "total_time": fm.get('total_time'),
            "dietary": fm.get('dietary', []),
            "equipment": fm.get('equipment', []),
            "meal_occasion": fm.get('meal_occasion', []),
            "nutrition_calories": fm.get('nutrition_calories'),
            "nutrition_protein": fm.get('nutrition_protein'),
            "nutrition_carbs": fm.get('nutrition_carbs'),
            "nutrition_fat": fm.get('nutrition_fat'),
            "seasonal_ingredients": fm.get('seasonal_ingredients', []),
            "peak_months": fm.get('peak_months', []),
            "source_url": fm.get('source_url'),
            "needs_review": fm.get('needs_review', False),
            "description": body_data.get('description', ''),
            "ingredients": body_data.get('ingredients', []),
            "instructions": body_data.get('instructions', []),
            "video_tips": body_data.get('video_tips', []),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/images/<path:filename>', methods=['GET'])
def serve_recipe_image(filename):
    """Serve recipe images from Obsidian vault."""
    # Block path traversal
    if '..' in filename or '/' in filename:
        return '', 404

    image_path = OBSIDIAN_RECIPES_PATH / "Images" / filename
    if not image_path.exists():
        return '', 404

    return send_file(image_path, mimetype='image/jpeg')


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
            cwd='/Users/chaseeasterling/GitHub/KitchenOS',
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
    ics_path = paths.calendar_ics_path()

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

    vault_path = paths.vault_root()

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
            cwd='/Users/chaseeasterling/GitHub/KitchenOS',
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
            "breakfast": None, "lunch": None, "snack": None, "dinner": None,
        }
        for meal in ("breakfast", "lunch", "snack", "dinner"):
            entry = day_data[meal]
            if entry is not None:
                slot_json = {"name": entry.name, "servings": entry.servings, "kind": entry.kind}
                if entry.kind == "meal":
                    meal_def = meal_loader.load_meal(entry.name)
                    if meal_def is not None:
                        slot_json["sub_recipes"] = [
                            {"recipe": s.recipe, "servings": s.servings}
                            for s in meal_def.sub_recipes
                        ]
                day_json[meal] = slot_json
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


@app.route('/api/suggest-meal', methods=['POST'])
def api_suggest_meal():
    """Suggest a recipe for an empty meal slot based on ingredient overlap."""
    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({"error": "Request body required"}), 400

    week = data.get("week")
    day = data.get("day")
    meal = data.get("meal")
    skip_index = data.get("skip_index", 0)

    if not week or not day or not meal:
        return jsonify({"error": "Required fields: week, day, meal"}), 400

    if not re.match(r'^\d{4}-W\d{2}$', week):
        return jsonify({"error": "Invalid week format. Expected YYYY-WNN"}), 400

    # Load current meal plan to get planned meals with ingredients
    plan_file = MEAL_PLANS_PATH / f"{week}.md"
    planned_meals = []

    if plan_file.exists():
        content = plan_file.read_text(encoding="utf-8")
        year_num, week_num = int(week[:4]), int(week.split("W")[1])
        parsed = parse_meal_plan(content, year_num, week_num)

        for day_data in parsed:
            for meal_type in ("breakfast", "lunch", "snack", "dinner"):
                entry = day_data.get(meal_type)
                if entry is not None and entry.name:
                    # Load ingredient items for this recipe
                    recipe_file = OBSIDIAN_RECIPES_PATH / f"{entry.name}.md"
                    ingredients = []
                    if recipe_file.exists():
                        try:
                            rc = recipe_file.read_text(encoding="utf-8")
                            rp = parse_recipe_file(rc)
                            body_data = parse_recipe_body(rp["body"])
                            ingredients = [
                                ing["item"] for ing in body_data.get("ingredients", [])
                                if ing.get("item")
                            ]
                        except Exception:
                            pass

                    planned_meals.append({
                        "day": day_data["day"],
                        "meal": meal_type,
                        "name": entry.name,
                        "ingredients": ingredients,
                    })

    from lib.meal_suggester import suggest_meal

    result = suggest_meal(
        recipes_dir=OBSIDIAN_RECIPES_PATH,
        planned_meals=planned_meals,
        day=day,
        meal=meal,
        skip_index=skip_index,
    )

    if result is None:
        return jsonify({"suggestion": None, "message": "No suggestions available"})

    return jsonify({"suggestion": result})


# ----- Add to Meal Plan (recipe button) -----

def _list_meal_names() -> list[str]:
    """Sorted meal names from vault/Meals/, used by the form."""
    return [m.name for m in meal_loader.list_meals()]


def _generate_week_options(weeks_ahead: int = 4) -> list[str]:
    today = date.today()
    weeks: list[str] = []
    for i in range(weeks_ahead):
        d = today + timedelta(days=7 * i)
        iso = d.isocalendar()
        weeks.append(f"{iso[0]}-W{iso[1]:02d}")
    return weeks


_INVALID_MEAL_NAME_CHARS = ('/', ':', '\\')


def _validate_meal_name(name: str) -> str | None:
    """Return an error message if the name is invalid, else None."""
    name = name.strip()
    if not name:
        return "Meal name is required."
    if name.startswith('.'):
        return "Meal name can't start with a dot."
    for ch in _INVALID_MEAL_NAME_CHARS:
        if ch in name:
            return "Meal name can't contain / : or \\."
    return None


def _render_add_form(recipe_display: str, error: str | None = None) -> str:
    """Screen 1: branch picker + conditional fields."""
    weeks = _generate_week_options()
    days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    meals = ['Breakfast', 'Lunch', 'Snack', 'Dinner']
    meal_names = _list_meal_names()

    week_options = ''.join(f'<option value="{w}">{w}</option>' for w in weeks)
    day_options = ''.join(f'<option value="{d}">{d}</option>' for d in days)
    meal_options = ''.join(f'<option value="{m}">{m}</option>' for m in meals)
    meal_name_options = ''.join(f'<option value="{n}">{n}</option>' for n in meal_names)

    has_meals = bool(meal_names)
    existing_disabled = '' if has_meals else 'disabled'
    existing_label = 'Add to an existing meal' if has_meals else 'Add to an existing meal (none yet)'

    error_html = (
        f'<div class="error">{error}</div>' if error else ''
    )

    return f'''<!DOCTYPE html>
<html><head>
<title>Add to Meal Plan</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
    body {{ font-family: system-ui; padding: 1.5rem; max-width: 480px; margin: 0 auto; background: #fafafa; }}
    h2 {{ margin-top: 0; }}
    .recipe-name {{ background: #f0f0f0; padding: 0.75rem; border-radius: 8px; margin-bottom: 1.5rem; font-weight: 600; }}
    .error {{ background: #fee; border: 1px solid #c00; color: #c00; padding: 0.75rem; border-radius: 8px; margin-bottom: 1rem; }}
    .branch {{ display: block; padding: 0.75rem; margin-bottom: 0.5rem; border: 1px solid #ddd; border-radius: 8px; cursor: pointer; background: white; }}
    .branch input[type="radio"] {{ margin-right: 0.5rem; }}
    .branch.disabled {{ opacity: 0.5; cursor: not-allowed; }}
    .fields {{ display: none; margin-top: 1rem; }}
    .fields.active {{ display: block; }}
    label {{ display: block; font-weight: 600; margin-bottom: 0.25rem; margin-top: 1rem; }}
    select, input[type="text"] {{ width: 100%; padding: 0.75rem; font-size: 16px; border: 1px solid #ccc; border-radius: 8px; background: white; -webkit-appearance: none; box-sizing: border-box; }}
    button {{ width: 100%; padding: 1rem; font-size: 18px; font-weight: 600; background: #2563eb; color: white; border: none; border-radius: 8px; margin-top: 1.5rem; cursor: pointer; }}
    button:active {{ background: #1d4ed8; }}
</style>
</head>
<body>
<h2>Add to Meal Plan</h2>
<div class="recipe-name">{recipe_display}</div>
{error_html}
<form method="POST" action="/add-to-meal-plan">
    <input type="hidden" name="recipe" value="{recipe_display}">

    <label class="branch"><input type="radio" name="mode" value="direct" checked onchange="toggleFields(this.value)">Schedule directly</label>
    <label class="branch {('disabled' if not has_meals else '')}"><input type="radio" name="mode" value="existing" {existing_disabled} onchange="toggleFields(this.value)">{existing_label}</label>
    <label class="branch"><input type="radio" name="mode" value="new" onchange="toggleFields(this.value)">Start a new meal</label>

    <div id="fields-direct" class="fields active">
        <label for="week">Week</label>
        <select name="week" id="week">{week_options}</select>
        <label for="day">Day</label>
        <select name="day" id="day">{day_options}</select>
        <label for="meal">Meal</label>
        <select name="meal" id="meal">{meal_options}</select>
    </div>

    <div id="fields-existing" class="fields">
        <label for="meal_name_existing">Meal</label>
        <select name="meal_name" id="meal_name_existing" form="ignored">{meal_name_options}</select>
    </div>

    <div id="fields-new" class="fields">
        <label for="meal_name_new">New meal name</label>
        <input type="text" name="meal_name" id="meal_name_new" placeholder="e.g. Salmon Dinner" form="ignored">
    </div>

    <button type="submit">Submit</button>
</form>

<script>
    function toggleFields(mode) {{
        ['direct', 'existing', 'new'].forEach(function(m) {{
            var el = document.getElementById('fields-' + m);
            if (!el) return;
            el.classList.toggle('active', m === mode);
            // Re-attach the active panel's name=meal_name input to the form,
            // and detach the inactive ones (so only one meal_name is posted).
            el.querySelectorAll('[form]').forEach(function(input) {{
                if (m === mode) input.removeAttribute('form');
                else input.setAttribute('form', 'ignored');
            }});
        }});
    }}
    // Sync on initial load (covers back-button restoration).
    document.addEventListener('DOMContentLoaded', function() {{
        var checked = document.querySelector('input[name="mode"]:checked');
        if (checked) toggleFields(checked.value);
    }});
</script>
</body></html>'''


def _success_page_for_wikilink(wikilink_target: str, day: str, meal: str, week: str) -> str:
    """Green confirmation card after a slot insert. Works for [[Recipe]] or [[Meal: X]]."""
    from urllib.parse import quote
    encoded_file = quote(f"Meal Plans/{week}", safe='')
    return f'''<!DOCTYPE html>
<html><head><title>KitchenOS</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
</head>
<body style="font-family: system-ui; padding: 2rem; max-width: 600px; margin: 0 auto;">
<div style="background: #efe; border: 1px solid #0a0; padding: 1rem; border-radius: 8px;">
<strong style="color: #0a0;">Added!</strong><br>
[[{wikilink_target}]] &rarr; {day} {meal} ({week})
</div>
<p><a href="obsidian://open?vault=KitchenOS&file={encoded_file}">View Meal Plan</a></p>
<p><a href="obsidian://open?vault=KitchenOS">Back to Obsidian</a></p>
</body></html>'''


def _render_schedule_prompt(recipe: str, meal_name: str, action: str, info: str | None = None) -> str:
    """Screen 2 — hybrid optional schedule prompt after meal save."""
    from urllib.parse import quote
    weeks = _generate_week_options()
    days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    meals = ['Breakfast', 'Lunch', 'Snack', 'Dinner']
    week_options = ''.join(f'<option value="{w}">{w}</option>' for w in weeks)
    day_options = ''.join(f'<option value="{d}">{d}</option>' for d in days)
    meal_options = ''.join(f'<option value="{m}">{m}</option>' for m in meals)
    encoded_meal = quote(f"Meals/{meal_name}", safe='')

    if action == 'created':
        banner = f'Created meal &ldquo;{meal_name}&rdquo; with {recipe}.'
    elif action == 'added':
        banner = f'Added {recipe} to &ldquo;{meal_name}&rdquo;.'
    else:
        banner = f'Saved &ldquo;{meal_name}&rdquo;.'

    info_html = f'<div class="info">{info}</div>' if info else ''

    return f'''<!DOCTYPE html>
<html><head>
<title>Schedule Meal</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
    body {{ font-family: system-ui; padding: 1.5rem; max-width: 480px; margin: 0 auto; background: #fafafa; }}
    .ok {{ background: #efe; border: 1px solid #0a0; color: #060; padding: 0.75rem; border-radius: 8px; margin-bottom: 1rem; }}
    .info {{ background: #eef; border: 1px solid #66c; color: #336; padding: 0.5rem 0.75rem; border-radius: 8px; margin-bottom: 1rem; font-size: 14px; }}
    h3 {{ margin-top: 0.5rem; }}
    label {{ display: block; font-weight: 600; margin-bottom: 0.25rem; margin-top: 1rem; }}
    select {{ width: 100%; padding: 0.75rem; font-size: 16px; border: 1px solid #ccc; border-radius: 8px; background: white; -webkit-appearance: none; }}
    button {{ width: 100%; padding: 1rem; font-size: 18px; font-weight: 600; background: #2563eb; color: white; border: none; border-radius: 8px; margin-top: 1.5rem; cursor: pointer; }}
    .skip {{ display: block; text-align: center; margin-top: 1rem; color: #666; }}
</style>
</head>
<body>
<div class="ok"><strong>&#10003;</strong> {banner}</div>
{info_html}
<h3>Schedule it now? <span style="font-weight: 400; color: #888;">(optional)</span></h3>
<form method="POST" action="/add-to-meal-plan">
    <input type="hidden" name="recipe" value="{recipe}">
    <input type="hidden" name="mode" value="schedule_meal">
    <input type="hidden" name="meal_name" value="{meal_name}">
    <label for="week">Week</label>
    <select name="week" id="week">{week_options}</select>
    <label for="day">Day</label>
    <select name="day" id="day">{day_options}</select>
    <label for="meal">Slot</label>
    <select name="meal" id="meal">{meal_options}</select>
    <button type="submit">Schedule meal</button>
</form>
<a class="skip" href="obsidian://open?vault=KitchenOS&file={encoded_meal}">Skip &mdash; open in Obsidian</a>
</body></html>'''


def _schedule_meal_token(meal_name: str, week: str, day: str, meal: str):
    """Insert ``[[Meal: <meal_name>]]`` into the plan slot. Mirrors _schedule_recipe_directly."""
    try:
        parts = week.split('-W')
        year = int(parts[0])
        week_num = int(parts[1])
    except (ValueError, IndexError):
        return error_page(f"Error: Invalid week format: {week}"), 400

    MEAL_PLANS_PATH.mkdir(parents=True, exist_ok=True)
    plan_file = MEAL_PLANS_PATH / f"{week}.md"
    if not plan_file.exists():
        content = generate_meal_plan_markdown(year, week_num)
        plan_file.write_text(content, encoding='utf-8')

    content = plan_file.read_text(encoding='utf-8')
    token = f"Meal: {meal_name}"
    try:
        new_content = insert_recipe_into_meal_plan(content, day, meal, token)
    except ValueError as e:
        return error_page(f"Error: {str(e)}"), 400

    plan_file.write_text(new_content, encoding='utf-8')
    return _success_page_for_wikilink(token, day, meal, week)


def _schedule_recipe_directly(recipe: str, week: str, day: str, meal: str):
    """The original direct flow, extracted unchanged."""
    try:
        parts = week.split('-W')
        year = int(parts[0])
        week_num = int(parts[1])
    except (ValueError, IndexError):
        return error_page(f"Error: Invalid week format: {week}"), 400

    MEAL_PLANS_PATH.mkdir(parents=True, exist_ok=True)
    plan_file = MEAL_PLANS_PATH / f"{week}.md"

    if not plan_file.exists():
        content = generate_meal_plan_markdown(year, week_num)
        plan_file.write_text(content, encoding='utf-8')

    content = plan_file.read_text(encoding='utf-8')
    try:
        new_content = insert_recipe_into_meal_plan(content, day, meal, recipe)
    except ValueError as e:
        return error_page(f"Error: {str(e)}"), 400

    plan_file.write_text(new_content, encoding='utf-8')
    return _success_page_for_wikilink(recipe, day, meal, week)


@app.route('/add-to-meal-plan', methods=['GET'])
def add_to_meal_plan_form():
    """Screen 1 — branch picker."""
    from urllib.parse import unquote
    recipe = request.args.get('recipe')
    if not recipe:
        return error_page("Error: recipe parameter required"), 400
    recipe_display = unquote(recipe).replace('.md', '')
    return _render_add_form(recipe_display)


@app.route('/add-to-meal-plan', methods=['POST'])
def add_to_meal_plan():
    """Branches on `mode`. Modes: direct, existing, new, schedule_meal."""
    recipe = request.form.get('recipe')
    mode = request.form.get('mode', 'direct')

    if not recipe:
        return error_page("Error: recipe parameter required"), 400

    if mode == 'direct':
        week = request.form.get('week')
        day = request.form.get('day')
        meal = request.form.get('meal')
        if not all([week, day, meal]):
            return error_page("Error: recipe, week, day, and meal are all required"), 400
        return _schedule_recipe_directly(recipe, week, day, meal)

    if mode == 'existing':
        meal_name = (request.form.get('meal_name') or '').strip()
        if not meal_name:
            recipe_display = recipe.replace('.md', '')
            return _render_add_form(recipe_display, error="Pick a meal."), 400
        meal = meal_loader.load_meal(meal_name)
        if meal is None:
            recipe_display = recipe.replace('.md', '')
            return _render_add_form(recipe_display, error=f'Meal not found: "{meal_name}".'), 404
        already_present = any(s.recipe == recipe for s in meal.sub_recipes)
        meal_loader.append_sub_recipe(meal, recipe_name=recipe)
        meal_loader.save_meal(meal)
        info = f'{recipe} is already in this meal.' if already_present else None
        return _render_schedule_prompt(recipe, meal_name, action='added', info=info)

    if mode == 'new':
        meal_name = (request.form.get('meal_name') or '').strip()
        recipe_display = recipe.replace('.md', '')
        err = _validate_meal_name(meal_name)
        if err:
            return _render_add_form(recipe_display, error=err), 400
        if meal_loader.load_meal(meal_name) is not None:
            return _render_add_form(
                recipe_display,
                error=f'A meal called "{meal_name}" already exists.'
            ), 409
        meal = meal_loader.Meal(
            name=meal_name,
            sub_recipes=[meal_loader.SubRecipe(recipe=recipe, servings=1)],
        )
        meal_loader.save_meal(meal)
        return _render_schedule_prompt(recipe, meal_name, action='created')

    if mode == 'schedule_meal':
        meal_name = (request.form.get('meal_name') or '').strip()
        week = request.form.get('week')
        day = request.form.get('day')
        meal = request.form.get('meal')
        if not all([meal_name, week, day, meal]):
            return error_page("Error: meal_name, week, day, and meal are all required"), 400
        return _schedule_meal_token(meal_name, week, day, meal)

    return error_page(f"Unknown mode: {mode}"), 400


@app.route('/meal-planner', methods=['GET'])
def meal_planner():
    """Serve the interactive meal planner board."""
    return send_file('templates/meal_planner.html', mimetype='text/html')


@app.route('/current/meal-plan', methods=['GET'])
def current_meal_plan_redirect():
    """Redirect to the current week's meal plan in Obsidian."""
    today = date.today()
    iso = today.isocalendar()
    week = f"{iso[0]}-W{iso[1]:02d}"
    encoded = quote(f"Meal Plans/{week}", safe='')
    return redirect(f"obsidian://open?vault={paths.vault_root().name}&file={encoded}")


@app.route('/current/shopping-list', methods=['GET'])
def current_shopping_list_redirect():
    """Redirect to the current week's shopping list in Obsidian."""
    today = date.today()
    iso = today.isocalendar()
    week = f"{iso[0]}-W{iso[1]:02d}"
    encoded = quote(f"Shopping Lists/{week}", safe='')
    return redirect(f"obsidian://open?vault={paths.vault_root().name}&file={encoded}")


# ----- Meals (composite recipe bundles) -----

def _meal_to_json(meal):
    return {
        "name": meal.name,
        "description": meal.description,
        "tags": list(meal.tags),
        "sub_recipes": [
            {"recipe": s.recipe, "servings": s.servings} for s in meal.sub_recipes
        ],
    }


@app.route('/api/meals', methods=['GET'])
def api_meals_list():
    return jsonify({"meals": [_meal_to_json(m) for m in meal_loader.list_meals()]})


@app.route('/api/meals', methods=['POST'])
def api_meals_create():
    data = request.get_json(force=True, silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    if meal_loader.load_meal(name) is not None:
        return jsonify({"error": f"meal '{name}' already exists"}), 409
    sub_recipes = data.get("sub_recipes") or []
    if not isinstance(sub_recipes, list) or not sub_recipes:
        return jsonify({"error": "sub_recipes must be a non-empty list"}), 400
    parsed_subs = [
        meal_loader.SubRecipe(
            recipe=str(s.get("recipe", "")),
            servings=int(s.get("servings", 1) or 1),
        )
        for s in sub_recipes
        if isinstance(s, dict) and s.get("recipe")
    ]
    if not parsed_subs:
        return jsonify({"error": "every sub_recipes entry must include a 'recipe' key"}), 400
    meal = meal_loader.Meal(
        name=name,
        description=data.get("description", ""),
        tags=list(data.get("tags") or []),
        sub_recipes=parsed_subs,
        body=data.get("body", ""),
    )
    meal_loader.save_meal(meal)
    return jsonify(_meal_to_json(meal)), 201


@app.route('/api/meals/<name>', methods=['GET'])
def api_meals_get(name):
    meal = meal_loader.load_meal(name)
    if meal is None:
        return jsonify({"error": f"meal '{name}' not found"}), 404
    return jsonify(_meal_to_json(meal))


@app.route('/api/meals/<name>', methods=['PUT'])
def api_meals_update(name):
    existing = meal_loader.load_meal(name)
    if existing is None:
        return jsonify({"error": f"meal '{name}' not found"}), 404
    data = request.get_json(force=True, silent=True) or {}
    new_name = (data.get("name") or name).strip()
    if new_name != name:
        # rename: write new file, delete old
        meal_loader.delete_meal(name)
    sub_recipes = data.get("sub_recipes")
    if sub_recipes is None:
        sub_records = existing.sub_recipes
    elif isinstance(sub_recipes, list) and sub_recipes:
        sub_records = [
            meal_loader.SubRecipe(
                recipe=str(s.get("recipe", "")),
                servings=int(s.get("servings", 1) or 1),
            )
            for s in sub_recipes
            if s.get("recipe")
        ]
    else:
        return jsonify({"error": "sub_recipes must be a non-empty list"}), 400
    meal = meal_loader.Meal(
        name=new_name,
        description=data.get("description", existing.description),
        tags=list(data.get("tags") if data.get("tags") is not None else existing.tags),
        sub_recipes=sub_records,
        body=data.get("body", existing.body),
    )
    meal_loader.save_meal(meal)
    return jsonify(_meal_to_json(meal))


@app.route('/api/meals/<name>', methods=['DELETE'])
def api_meals_delete(name):
    if not meal_loader.delete_meal(name):
        return jsonify({"error": f"meal '{name}' not found"}), 404
    return jsonify({"status": "deleted", "name": name})


# ----- Pantry inventory -----

@app.route('/api/pantry', methods=['GET'])
def api_pantry_get():
    return jsonify({"items": pantry_module.load_pantry()})


@app.route('/api/pantry', methods=['PUT'])
def api_pantry_put():
    data = request.get_json(force=True, silent=True) or {}
    items = data.get("items")
    if not isinstance(items, list):
        return jsonify({"error": "items must be a list"}), 400
    pantry_module.save_pantry(items)
    return jsonify({"status": "saved", "count": len(items)})


# ----- Pantry-aware shopping list flow -----

@app.route('/api/shopping-list/preview', methods=['POST'])
def api_shopping_list_preview():
    data = request.get_json(force=True, silent=True) or {}
    week = data.get("week")
    if not week or not re.match(r'^\d{4}-W\d{2}$', week):
        return jsonify({"error": "week required (YYYY-WNN)"}), 400
    pantry = pantry_module.load_pantry()
    result = generate_shopping_list(week, pantry=pantry if data.get("use_pantry", True) else None)
    return jsonify(result)


@app.route('/api/shopping-list/confirm', methods=['POST'])
def api_shopping_list_confirm():
    data = request.get_json(force=True, silent=True) or {}
    week = data.get("week")
    items = data.get("items_to_buy")
    decisions = data.get("decisions") or []
    if not week or not isinstance(items, list):
        return jsonify({"error": "week and items_to_buy required"}), 400

    SHOPPING_LISTS_PATH.mkdir(parents=True, exist_ok=True)
    markdown = generate_shopping_list_markdown(week, items)
    filename = shopping_list_filename(week)
    out_path = SHOPPING_LISTS_PATH / filename
    out_path.write_text(markdown, encoding="utf-8")

    if decisions:
        pantry = pantry_module.load_pantry()
        updated = pantry_module.apply_decisions(decisions, pantry)
        pantry_module.save_pantry(updated)

    return jsonify({"status": "saved", "filename": filename, "items": len(items)})


# ----- Cross-recipe prep tasks -----

@app.route('/api/tasks/<week>', methods=['GET'])
def api_tasks_get(week):
    if not re.match(r'^\d{4}-W\d{2}$', week):
        return jsonify({"error": "Invalid week format. Expected YYYY-WNN"}), 400
    force = request.args.get("force") in ("1", "true", "yes")
    payload = task_extractor.extract_tasks(week, force=force)
    return jsonify(payload)


@app.route('/api/tasks/<week>/<task_id>/done', methods=['POST'])
def api_task_mark_done(week, task_id):
    if not re.match(r'^\d{4}-W\d{2}$', week):
        return jsonify({"error": "Invalid week format. Expected YYYY-WNN"}), 400
    data = request.get_json(force=True, silent=True) or {}
    done = bool(data.get("done", True))
    result = task_extractor.mark_task_done(week, task_id, done)
    status = 200 if result.get("success") else 404
    return jsonify(result), status


# ----- Inventory (receipt-to-pantry; same DB table the pantry API adapts) -----

@app.route('/api/inventory', methods=['GET'])
def api_inventory_list():
    """List inventory items, with optional category/location filters."""
    from lib.inventory import read_inventory

    items = read_inventory()
    category = (request.args.get('category') or '').lower().strip()
    location = (request.args.get('location') or '').lower().strip()
    if category:
        items = [i for i in items if i.category == category]
    if location:
        items = [i for i in items if i.location == location]
    return jsonify([i.to_dict() for i in items])


@app.route('/api/inventory/add', methods=['POST'])
def api_inventory_add():
    """Add items to inventory. Body: {items: [{name, quantity, unit, ...}]}."""
    from lib.inventory import (
        InventoryItem, add_items,
        normalize_category, normalize_location, normalize_source,
    )

    data = request.get_json(force=True, silent=True)
    if not data or 'items' not in data:
        return jsonify({"error": "Request body must include 'items' array"}), 400

    raw_items = data['items']
    if not isinstance(raw_items, list) or not raw_items:
        return jsonify({"error": "'items' must be a non-empty array"}), 400

    parsed: list[InventoryItem] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        name = (raw.get('name') or '').strip()
        if not name:
            continue
        try:
            quantity = float(raw.get('quantity', 1) or 1)
        except (ValueError, TypeError):
            quantity = 1.0
        parsed.append(InventoryItem(
            name=name,
            quantity=quantity,
            unit=(raw.get('unit') or 'ct').strip(),
            category=normalize_category(raw.get('category')),
            location=normalize_location(raw.get('location')),
            purchased=(raw.get('purchased') or None),
            source=normalize_source(raw.get('source') or 'claude'),
            notes=(raw.get('notes') or '').strip(),
        ))

    if not parsed:
        return jsonify({"error": "No valid items provided"}), 400

    result = add_items(parsed)
    return jsonify({"status": "ok", **result})


@app.route('/api/inventory/remove', methods=['POST'])
def api_inventory_remove():
    """Remove an item. Body: {name, location?}."""
    from lib.inventory import remove_item

    data = request.get_json(force=True, silent=True)
    if not data or not data.get('name'):
        return jsonify({"error": "'name' is required"}), 400

    removed = remove_item(data['name'], data.get('location'))
    if not removed:
        return jsonify({"status": "not_found"}), 404
    return jsonify({"status": "removed"})


@app.route('/api/inventory/update', methods=['POST'])
def api_inventory_update():
    """Update an item's quantity. Body: {name, quantity, location?}."""
    from lib.inventory import update_quantity

    data = request.get_json(force=True, silent=True)
    if not data or not data.get('name') or 'quantity' not in data:
        return jsonify({"error": "'name' and 'quantity' are required"}), 400
    try:
        quantity = float(data['quantity'])
    except (ValueError, TypeError):
        return jsonify({"error": "'quantity' must be a number"}), 400

    updated = update_quantity(data['name'], quantity, data.get('location'))
    if not updated:
        return jsonify({"status": "not_found"}), 404
    return jsonify({"status": "updated"})


if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
