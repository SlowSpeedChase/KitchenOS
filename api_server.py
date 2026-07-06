#!/usr/bin/env python3
"""Simple API server for iOS Shortcuts integration."""

from flask import Flask, request, jsonify, send_file, redirect
from markupsafe import escape
from urllib.parse import quote
from youtube_transcript_api import YouTubeTranscriptApi
from googleapiclient.discovery import build
import functools
import os
import re
import sqlite3
import subprocess
import sys
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
from templates.meal_plan_template import generate_meal_plan_markdown, format_week_range
from lib.meal_plan_index import regenerate_index
from lib.ingredient_validator import validate_ingredients
from lib.ingredient_cleaner import clean_ingredient_list
from lib.seasonality import match_ingredients_to_seasonal, get_peak_months
from lib.nutrition_engine import calculate_recipe_nutrition
from lib import meal_loader, pantry as pantry_module, paths, task_extractor
from recipe_sources import parse_recipe_from_text

load_dotenv()
warnings.filterwarnings('ignore', message='urllib3 v2 only supports OpenSSL 1.1.1+')

YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY')
OBSIDIAN_RECIPES_PATH = paths.recipes_dir()
_RECIPES_ENV_AT_IMPORT = os.environ.get("KITCHENOS_VAULT")
MEAL_PLANS_PATH = paths.meal_plans_dir()
VAULT_NAME = paths.vault_root().name

app = Flask(__name__)


def require_token(view):
    """Require a bearer token for non-localhost callers when KITCHENOS_API_TOKEN is set.

    No-op when the env var is unset. Localhost (Mac app, local browser UI) is always
    exempt; remote callers (iPad over Tailscale) must send Authorization: Bearer <token>.
    """
    @functools.wraps(view)
    def wrapper(*args, **kwargs):
        token = os.environ.get("KITCHENOS_API_TOKEN")
        if not token:
            return view(*args, **kwargs)
        if request.remote_addr in ("127.0.0.1", "::1"):
            return view(*args, **kwargs)
        if request.headers.get("Authorization", "") == f"Bearer {token}":
            return view(*args, **kwargs)
        return jsonify({"error": "Unauthorized"}), 401
    return wrapper


_recipe_cache = {"data": None, "timestamp": 0}
_recipe_ingredient_cache = {"data": None, "timestamp": 0}
RECIPE_CACHE_TTL = 300  # 5 minutes


def error_page(message: str) -> str:
    """Generate simple HTML error page.

    The message is escaped here (call sites pass raw text, often str(e));
    escaping already-escaped Markup is a no-op.
    """
    return f'''<!DOCTYPE html>
<html><head><meta name="viewport" content="width=device-width, initial-scale=1"><title>KitchenOS</title></head>
<body style="font-family: system-ui; padding: 2rem; max-width: 600px; margin: 0 auto;">
<div style="background: #fee; border: 1px solid #c00; padding: 1rem; border-radius: 8px;">
<strong style="color: #c00;">Error</strong><br>{escape(message)}
</div>
<p><a href="obsidian://open?vault={VAULT_NAME}" style="display: inline-block; padding: 12px 20px; border: 1px solid #ccc; border-radius: 8px; text-decoration: none;">Return to Obsidian</a></p>
</body></html>'''


def success_page(message: str, filename: str) -> str:
    """Generate simple HTML success page."""
    from urllib.parse import quote
    encoded_filename = quote(filename, safe='')
    return f'''<!DOCTYPE html>
<html><head><meta name="viewport" content="width=device-width, initial-scale=1"><title>KitchenOS</title></head>
<body style="font-family: system-ui; padding: 2rem; max-width: 600px; margin: 0 auto;">
<div style="background: #efe; border: 1px solid #0a0; padding: 1rem; border-radius: 8px;">
<strong style="color: #0a0;">Success</strong><br>{message}
</div>
<p><a href="obsidian://open?vault={VAULT_NAME}&file=Recipes/{encoded_filename}" style="display: inline-block; padding: 12px 20px; border: 1px solid #ccc; border-radius: 8px; text-decoration: none;">Return to {filename}</a></p>
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
@require_token
def api_recipes():
    """Return recipe metadata for meal planner sidebar.

    Optional query param:
        ingredient: case-insensitive substring. When provided, only recipes
            whose ingredient list contains a match are returned.
    """
    ingredient = request.args.get("ingredient", "").strip()
    now = time.time()

    if ingredient:
        cache = _recipe_ingredient_cache
        if cache["data"] is None or (now - cache["timestamp"]) > RECIPE_CACHE_TTL:
            cache["data"] = get_recipe_index(OBSIDIAN_RECIPES_PATH, include_ingredients=True)
            cache["timestamp"] = now
        term = ingredient.lower()
        matches = [
            r for r in cache["data"]
            if any(term in item.lower() for item in r.get("ingredient_items", []))
        ]
        return jsonify(matches)

    if _recipe_cache["data"] is None or (now - _recipe_cache["timestamp"]) > RECIPE_CACHE_TTL:
        _recipe_cache["data"] = get_recipe_index(OBSIDIAN_RECIPES_PATH)
        _recipe_cache["timestamp"] = now
    return jsonify(_recipe_cache["data"])


@app.route('/api/recipes/by-ingredients', methods=['POST'])
@require_token
def api_recipes_by_ingredients():
    """Rank recipes by how many of the given ingredients they share.

    Body JSON: {"ingredients": [str, ...], "limit": int (optional, default 15)}.
    Reuses the meal-suggester overlap scoring. Returns matches sorted by score desc,
    excluding zero-overlap recipes.
    """
    from lib.meal_suggester import normalize_ingredient, rank_candidates, load_pantry_staples

    data = request.get_json(force=True, silent=True) or {}
    ingredients = data.get("ingredients") or []
    if not ingredients:
        return jsonify({"error": "ingredients (a non-empty list) is required"}), 400

    target = {normalize_ingredient(i) for i in ingredients if str(i).strip()}
    pantry = load_pantry_staples()
    candidates = get_recipe_index(OBSIDIAN_RECIPES_PATH, include_ingredients=True)
    ranked = rank_candidates(candidates, target, pantry, limit=int(data.get("limit", 15)))
    matches = [
        {"name": r["name"], "score": r["score"], "shared_ingredients": r["shared_ingredients"]}
        for r in ranked if r["score"] > 0
    ]
    return jsonify({"matches": matches})


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
            data['ingredients'] = clean_ingredient_list(validate_ingredients(
                data['ingredients'], verbose=False
            ))

        # Match seasonal ingredients
        seasonal_matches = match_ingredients_to_seasonal(
            data.get('ingredients', [])
        )
        data['seasonal_ingredients'] = seasonal_matches
        data['peak_months'] = get_peak_months(seasonal_matches)

        # Calculate nutrition (servings raw → engine flags null instead of hiding it)
        ingredients = data.get('ingredients', [])
        nutrition_result = calculate_recipe_nutrition(ingredients, data.get('servings'))
        if nutrition_result:
            data['nutrition_calories'] = nutrition_result.nutrition.calories
            data['nutrition_protein'] = nutrition_result.nutrition.protein
            data['nutrition_carbs'] = nutrition_result.nutrition.carbs
            data['nutrition_fat'] = nutrition_result.nutrition.fat
            data['nutrition_source'] = nutrition_result.source
            data['nutrition_confidence'] = nutrition_result.confidence
            if nutrition_result.needs_review:
                data['needs_review'] = True

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


@app.route('/api/recipes/import-text', methods=['POST'])
def api_recipe_import_text():
    """Parse a free-text recipe (e.g. pasted from a chat assistant) and save it.

    Body JSON: {"text": str (required), "title": str (optional), "source": str (optional)}.
    The raw text is parsed by Ollama (un-gated) into the recipe schema, enriched,
    and saved through the same conventions as /api/recipes/save. The original text
    is preserved in a collapsible "Import Source" block so a bad parse can be
    corrected later. Backs Selene's /webhook/api/recipe forward.
    """
    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({"error": "Request body required"}), 400

    text = (data.get('text') or '').strip()
    if not text:
        return jsonify({"error": "text is required"}), 400

    title = (data.get('title') or '').strip()
    source = (data.get('source') or 'selene').strip()

    try:
        recipe = parse_recipe_from_text(text, title=title)
        if not recipe or not recipe.get('recipe_name'):
            return jsonify({
                "error": "Could not parse a recipe from the provided text"
            }), 422

        recipe['source'] = source
        recipe.setdefault('needs_review', False)
        recipe_name = recipe['recipe_name']

        # Validate ingredients
        if recipe.get('ingredients'):
            recipe['ingredients'] = clean_ingredient_list(validate_ingredients(
                recipe['ingredients'], verbose=False
            ))

        # Match seasonal ingredients
        seasonal_matches = match_ingredients_to_seasonal(recipe.get('ingredients', []))
        recipe['seasonal_ingredients'] = seasonal_matches
        recipe['peak_months'] = get_peak_months(seasonal_matches)

        # Calculate nutrition (servings raw → engine flags null instead of hiding it)
        ingredients = recipe.get('ingredients', [])
        nutrition_result = calculate_recipe_nutrition(ingredients, recipe.get('servings'))
        if nutrition_result:
            recipe['nutrition_calories'] = nutrition_result.nutrition.calories
            recipe['nutrition_protein'] = nutrition_result.nutrition.protein
            recipe['nutrition_carbs'] = nutrition_result.nutrition.carbs
            recipe['nutrition_fat'] = nutrition_result.nutrition.fat
            recipe['nutrition_source'] = nutrition_result.source
            recipe['nutrition_confidence'] = nutrition_result.confidence
            if nutrition_result.needs_review:
                recipe['needs_review'] = True

        # Generate markdown, then preserve the original pasted text for later correction.
        markdown = format_recipe_markdown(
            recipe,
            video_url='',
            video_title='',
            channel=data.get('source_channel', ''),
        )
        import_section = (
            "## Import Source\n\n"
            "<details>\n"
            "<summary>Original text imported via Selene</summary>\n\n"
            "```\n"
            f"{text}\n"
            "```\n\n"
            "</details>"
        )
        markdown = markdown.rstrip() + "\n\n" + import_section + "\n"

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


def _resolve_recipes_dir() -> Path:
    """Resolve the recipes directory for the current request.

    Older tests patch ``api_server.OBSIDIAN_RECIPES_PATH`` directly via
    ``unittest.mock.patch`` (env var untouched). Newer tests use the
    ``tmp_vault`` fixture, which monkeypatches the ``KITCHENOS_VAULT`` env
    var instead — the module-level ``OBSIDIAN_RECIPES_PATH`` constant was
    already captured at import time (from the repo's real .env-configured
    vault) and won't see that change.

    Compare the current env var against the value captured at import
    (``_RECIPES_ENV_AT_IMPORT``): if it changed, a test has monkeypatched
    ``KITCHENOS_VAULT``, so recompute fresh via ``paths.recipes_dir()`` to
    pick it up. If unchanged, fall back to the module constant, which
    respects a direct ``unittest.mock.patch`` of it. This differs from
    ``lib.week_view.recipe_base_servings``, which always calls
    ``paths.recipes_dir()`` fresh regardless of env state.
    """
    if os.environ.get("KITCHENOS_VAULT") != _RECIPES_ENV_AT_IMPORT:
        return paths.recipes_dir()
    return OBSIDIAN_RECIPES_PATH


@app.route('/api/recipes/<name>', methods=['GET'])
@require_token
def api_recipe_detail(name):
    """Return full recipe details as JSON."""
    recipes_dir = _resolve_recipes_dir()
    filepath = (recipes_dir / f"{name}.md").resolve()
    if not filepath.is_relative_to(recipes_dir.resolve()):
        return jsonify({"error": "Invalid recipe name"}), 400

    if not filepath.exists():
        return jsonify({"error": f"Recipe not found: {name}"}), 404

    try:
        content = filepath.read_text(encoding='utf-8')
        parsed = parse_recipe_file(content)
        fm = parsed['frontmatter']
        body_data = parse_recipe_body(parsed['body'])

        nutrition = None
        if fm.get('nutrition_calories') is not None:
            nutrition = {
                "calories": fm.get('nutrition_calories'),
                "protein": fm.get('nutrition_protein'),
                "carbs": fm.get('nutrition_carbs'),
                "fat": fm.get('nutrition_fat'),
                "coverage": fm.get('nutrition_coverage'),
                "confidence": fm.get('nutrition_confidence'),
                "source": fm.get('nutrition_source'),
            }

        image_file = recipes_dir / "Images" / f"{name}.jpg"
        image = f"{name}.jpg" if image_file.exists() else None

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
            "nutrition": nutrition,
            "image": image,
            "seasonal_ingredients": fm.get('seasonal_ingredients', []),
            "peak_months": fm.get('peak_months', []),
            "source_url": fm.get('source_url'),
            "needs_review": fm.get('needs_review', False),
            "description": body_data.get('description', ''),
            "ingredients": body_data.get('ingredients', []),
            "instructions": body_data.get('instructions', []),
            "video_tips": body_data.get('video_tips', []),
            "body_markdown": parsed['body'],
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/recipe/<name>', methods=['GET'])
def recipe_detail_page(name):
    """Serve the interactive recipe detail page with live ingredient scaling."""
    recipes_dir = _resolve_recipes_dir()
    filepath = (recipes_dir / f"{name}.md").resolve()
    if not filepath.is_relative_to(recipes_dir.resolve()) or not filepath.exists():
        # error_page() escapes the reflected name itself now; escaping here
        # too would double-escape (the f-string demotes Markup to plain str,
        # so the outer escape would re-escape the entities).
        return error_page(f"Recipe not found: {name}"), 404

    html = open('templates/recipe_detail.html').read()
    html = html.replace('vault=KitchenOS', f'vault={VAULT_NAME}')
    return html, 200, {'Content-Type': 'text/html'}


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
            cwd=str(Path(__file__).resolve().parent),
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
<p><a href="obsidian://open?vault={VAULT_NAME}&file=Nutrition%20Dashboard">View Dashboard</a></p>
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
@require_token
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
        # New week file → refresh the human-readable Meal Plans Index
        try:
            regenerate_index()
        except Exception as e:
            print(f"Warning: could not refresh meal plan index: {e}", file=sys.stderr)
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
                # servings is a float (fractional multipliers, e.g. 1.5); JSON numbers are JS-native
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
@require_token
def api_meal_plan_put(week):
    """Save meal plan from structured JSON."""
    match = re.match(r'^(\d{4})-W(\d{2})$', week)
    if not match:
        return jsonify({"error": "Invalid week format. Expected YYYY-WNN"}), 400

    # Fail closed at the legacy/board boundary: this payload carries no
    # scale/placement info and would clobber ledger-authored Markdown.
    from lib import serving_ledger
    if serving_ledger.cooks_for_week(week):
        return jsonify({"error": "week is ledger-managed"}), 409

    data = request.get_json(force=True, silent=True)
    if not data or "days" not in data:
        return jsonify({"error": "Request body must include 'days' array"}), 400

    content = rebuild_meal_plan_markdown(week, data["days"])

    MEAL_PLANS_PATH.mkdir(parents=True, exist_ok=True)
    plan_file = MEAL_PLANS_PATH / f"{week}.md"
    plan_file.write_text(content, encoding="utf-8")

    _recipe_cache["data"] = None

    return jsonify({"status": "saved", "week": week})


# --- Serving ledger -----------------------------------------------------------

def _ledger_error(fn):
    """Map ledger exceptions to HTTP codes; regenerate affected week views."""
    from functools import wraps
    from lib.serving_ledger import OverplacementError

    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except OverplacementError as e:
            return jsonify({"error": str(e)}), 409
        except sqlite3.OperationalError:
            return jsonify({"error": "ledger busy, retry"}), 503
        except (ValueError, TypeError) as e:
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            # Residual failures surface as JSON 500s, not HTML tracebacks —
            # board-mode JS reads resp.json() on every path.
            print(f"Error in {fn.__name__}: {e}", file=sys.stderr)
            return jsonify({"error": f"internal error: {e}"}), 500
    return wrapper


def _iso_week_of(date_str):
    from datetime import date as _date
    y, w, _ = _date.fromisoformat(date_str).isocalendar()
    return f"{y}-W{w:02d}"


def _regen_weeks(*weeks):
    from lib import week_view
    for wk in {w for w in weeks if w}:
        try:
            week_view.write_week_markdown(wk)
        except Exception as e:
            print(f"Warning: week view regen failed for {wk}: {e}", file=sys.stderr)


@app.route('/api/week-board/<week>', methods=['GET'])
@require_token
@_ledger_error
def api_week_board(week):
    from lib import serving_ledger
    if not re.match(r'^\d{4}-W\d{2}$', week):
        return jsonify({"error": "Invalid week format. Expected YYYY-WNN"}), 400
    return jsonify(serving_ledger.week_board(week, _resolve_recipes_dir()))


def _import_legacy_if_first_write(*weeks):
    """Pre-mutation hook: before the FIRST ledger cook lands in a week,
    convert a hand-edited plan file's [[links]] into ledger cooks — backing
    the file up first — so the post-mutation ``_regen_weeks`` renders the
    converted week instead of clobbering it.

    The backup is unconditional whenever the plan file exists, even a
    linkless/notes-only file: any first ledger write into an existing plan
    file is about to overwrite hand-authored content, whether or not that
    content happens to contain a [[link]] worth importing.

    Placements-only weeks (a foreign placement already dragged in from
    another week's cook, but no cook of this week's own yet) now import
    too — safe because ``lib.week_view.import_legacy_week`` strips
    ``(leftover`` lines before parsing, so it can't double-count a
    placement that's already backed by a cook elsewhere. The import guard
    is therefore keyed on cooks only, not placements.

    Must run BEFORE the mutation: afterwards the week has a cook row and
    the no-cooks guard can never fire again.
    """
    from lib import serving_ledger, week_view, paths
    for wk in {w for w in weeks if w}:
        if not re.match(r'^\d{4}-W\d{2}$', wk):
            continue
        plan_file = paths.meal_plans_dir() / f"{wk}.md"
        if not plan_file.exists():
            continue
        try:
            create_backup(plan_file)
        except Exception as e:
            print(f"Warning: legacy backup failed for {wk}: {e}", file=sys.stderr)
            continue
        if "[[" not in plan_file.read_text(encoding="utf-8"):
            continue
        if serving_ledger.cooks_for_week(wk):
            continue
        try:
            week_view.import_legacy_week(wk)
        except Exception as e:
            # The backup (taken first) preserves the hand-edited content
            # even if conversion fails and the regen rewrites the file.
            print(f"Warning: legacy import failed for {wk}: {e}", file=sys.stderr)


@app.route('/api/week-board/<week>/import-legacy', methods=['POST'])
@require_token
@_ledger_error
def api_week_board_import_legacy(week):
    """One-time conversion of a hand-edited week to the serving ledger.

    Thin wrapper over ``lib.week_view.import_legacy_week`` (the mutation
    routes run the same conversion server-side before the first ledger
    write into a legacy week). Guarded against re-import: 409 if the week
    already has ledger rows (cooks or placements).
    """
    from lib import serving_ledger, week_view
    if not re.match(r'^\d{4}-W\d{2}$', week):
        return jsonify({"error": "Invalid week format. Expected YYYY-WNN"}), 400
    if serving_ledger.cooks_for_week(week) or serving_ledger.placements_for_week(week):
        return jsonify({"error": "week already has ledger rows"}), 409

    imported = week_view.import_legacy_week(week)
    _regen_weeks(week)
    return jsonify({"imported": imported})


@app.route('/api/cooks', methods=['POST'])
@require_token
@_ledger_error
def api_cook_create():
    from lib import serving_ledger
    data = request.get_json(force=True, silent=True) or {}
    # C1: a hand-edited legacy week must be converted (import + backup)
    # BEFORE its first ledger row lands, or the regen below clobbers it.
    _import_legacy_if_first_write(
        data.get('week'),
        _iso_week_of(data["date"]) if data.get("date") else None)
    cook = serving_ledger.create_cook(
        recipe=data.get('recipe'), week=data.get('week'),
        scale=float(data.get('scale', 1.0)),
        servings_produced=data.get('servings_produced'),
        date=data.get('date'), meal=data.get('meal'),
        initial_placement_count=float(data.get('initial_placement_count', 1.0)),
        notes=data.get('notes'))
    _regen_weeks(cook["week"], _iso_week_of(data["date"]) if data.get("date") else None)
    return jsonify(cook), 201


@app.route('/api/cooks/<int:cook_id>', methods=['PATCH'])
@require_token
@_ledger_error
def api_cook_update(cook_id):
    from lib import serving_ledger
    data = request.get_json(force=True, silent=True) or {}
    before = serving_ledger.get_cook(cook_id)
    if before is None:
        return jsonify({"error": "cook not found"}), 404
    cook = serving_ledger.update_cook(cook_id, **data)
    _regen_weeks(before["week"], cook["week"])
    return jsonify(cook)


@app.route('/api/cooks/<int:cook_id>', methods=['DELETE'])
@require_token
@_ledger_error
def api_cook_delete(cook_id):
    from lib import serving_ledger
    cook = serving_ledger.get_cook(cook_id)
    if cook is None:
        return jsonify({"error": "cook not found"}), 404
    affected = [cook["week"]] + [_iso_week_of(p["date"])
                                 for p in cook["placements"] if p.get("date")]
    serving_ledger.delete_cook(cook_id)
    _regen_weeks(*affected)
    return jsonify({"status": "deleted"})


@app.route('/api/placements', methods=['POST'])
@require_token
@_ledger_error
def api_placement_create():
    from lib import serving_ledger
    data = request.get_json(force=True, silent=True) or {}
    cook_id = int(data.get('cook_id', 0))
    if serving_ledger.get_cook(cook_id) is None:
        return jsonify({"error": "cook not found"}), 404
    # C1: dropping a serving into a hand-edited legacy week converts it first.
    if data.get('date'):
        _import_legacy_if_first_write(_iso_week_of(data['date']))
    p = serving_ledger.add_placement(
        cook_id=cook_id,
        destination=data.get('destination'),
        count=float(data.get('count', 0)),
        date=data.get('date'), meal=data.get('meal'))
    cook = serving_ledger.get_cook(p["cook_id"])
    _regen_weeks(cook["week"], _iso_week_of(p["date"]) if p.get("date") else None)
    return jsonify(p), 201


@app.route('/api/placements/<int:pid>', methods=['PATCH'])
@require_token
@_ledger_error
def api_placement_update(pid):
    from lib import serving_ledger, inventory_db
    data = request.get_json(force=True, silent=True) or {}
    conn = inventory_db.connect()
    try:
        before = conn.execute("SELECT * FROM placements WHERE id = ?", (pid,)).fetchone()
    finally:
        conn.close()
    if before is None:
        return jsonify({"error": "placement not found"}), 404
    # C1: patching a serving's date into a hand-edited legacy week converts
    # it first (same wiring as create/move — this was the one mutating
    # ledger route missing it).
    if data.get('date'):
        _import_legacy_if_first_write(_iso_week_of(data['date']))
    p = serving_ledger.update_placement(pid, **data)
    cook = serving_ledger.get_cook(p["cook_id"])
    _regen_weeks(cook["week"],
                 _iso_week_of(before["date"]) if before["date"] else None,
                 _iso_week_of(p["date"]) if p.get("date") else None)
    return jsonify(p)


@app.route('/api/placements/<int:pid>', methods=['DELETE'])
@require_token
@_ledger_error
def api_placement_delete(pid):
    from lib import serving_ledger, inventory_db
    conn = inventory_db.connect()
    try:
        row = conn.execute("SELECT * FROM placements WHERE id = ?", (pid,)).fetchone()
    finally:
        conn.close()
    if row is None:
        return jsonify({"error": "placement not found"}), 404
    cook = serving_ledger.get_cook(row["cook_id"])
    serving_ledger.delete_placement(pid)
    _regen_weeks(cook["week"],
                 _iso_week_of(row["date"]) if row["date"] else None)
    return jsonify({"status": "deleted"})


@app.route('/api/placements/<int:pid>/move', methods=['POST'])
@require_token
@_ledger_error
def api_placement_move(pid):
    from lib import serving_ledger, inventory_db
    data = request.get_json(force=True, silent=True) or {}
    conn = inventory_db.connect()
    try:
        before = conn.execute("SELECT * FROM placements WHERE id = ?", (pid,)).fetchone()
    finally:
        conn.close()
    if before is None:
        return jsonify({"error": "placement not found"}), 404
    # C1: moving a serving into a hand-edited legacy week converts it first.
    if data.get('date'):
        _import_legacy_if_first_write(_iso_week_of(data['date']))
    result = serving_ledger.move_servings(
        pid, count=float(data.get('count', 0)),
        destination=data.get('destination'),
        date=data.get('date'), meal=data.get('meal'))
    cook = serving_ledger.get_cook(result["to"]["cook_id"])
    weeks = [cook["week"]]
    for part in (result.get("from"), result.get("to")):
        if part and part.get("date"):
            weeks.append(_iso_week_of(part["date"]))
    _regen_weeks(*weeks)
    return jsonify(result)


@app.route('/api/suggest-meal', methods=['POST'])
@require_token
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


def _week_option_label(week_id: str) -> str:
    """Dropdown label leading with the date range, e.g. 'Jun 22 - Jun 28 (2026-W26)'."""
    try:
        return f"{format_week_range(week_id, with_year=False)} ({week_id})"
    except ValueError:
        return week_id


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

    week_options = ''.join(f'<option value="{w}">{_week_option_label(w)}</option>' for w in weeks)
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
<p><a href="obsidian://open?vault={VAULT_NAME}&file={encoded_file}">View Meal Plan</a></p>
<p><a href="obsidian://open?vault={VAULT_NAME}">Back to Obsidian</a></p>
</body></html>'''


def _render_schedule_prompt(recipe: str, meal_name: str, action: str, info: str | None = None) -> str:
    """Screen 2 — hybrid optional schedule prompt after meal save."""
    from urllib.parse import quote
    weeks = _generate_week_options()
    days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    meals = ['Breakfast', 'Lunch', 'Snack', 'Dinner']
    week_options = ''.join(f'<option value="{w}">{_week_option_label(w)}</option>' for w in weeks)
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
<a class="skip" href="obsidian://open?vault={VAULT_NAME}&file={encoded_meal}">Skip &mdash; open in Obsidian</a>
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
    html = open('templates/meal_planner.html').read()
    html = html.replace('vault=KitchenOS', f'vault={VAULT_NAME}')
    return html, 200, {'Content-Type': 'text/html'}


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
    from lib.expiry import expiry_status

    items = read_inventory()
    category = (request.args.get('category') or '').lower().strip()
    location = (request.args.get('location') or '').lower().strip()
    if category:
        items = [i for i in items if i.category == category]
    if location:
        items = [i for i in items if i.location == location]

    payload = []
    for i in items:
        d = i.to_dict()
        d["expiry_status"] = expiry_status(d.get("expires"))
        payload.append(d)
    return jsonify(payload)


@app.route('/api/use-it-up', methods=['GET'])
def api_use_it_up():
    """Recipes that use up at-risk (expiring) inventory, so nothing is wasted.

    Returns {at_risk: [...], suggestions: [...]} — see lib/use_it_up.suggest.
    Staples are excluded; only the actionable expiry window is surfaced.
    """
    from lib import use_it_up

    limit = request.args.get('limit', type=int) or 10
    return jsonify(use_it_up.generate(limit=limit))


@app.route('/api/cook', methods=['POST'])
def api_cook():
    """Mark a recipe cooked: decrement its non-staple ingredients from inventory.

    Body: {recipe: str, servings?: float}. Optional/additive — surfaces true
    partial-package leftovers. Returns the consume summary (see lib/cook).
    """
    from lib.cook import consume_recipe

    data = request.get_json(force=True, silent=True) or {}
    recipe = data.get('recipe')
    if not recipe:
        return jsonify({"error": "'recipe' is required"}), 400
    servings = data.get('servings')
    try:
        servings = float(servings) if servings is not None else 1.0
    except (TypeError, ValueError):
        servings = 1.0
    result = consume_recipe(recipe, servings=servings)
    if result.get("error") == "recipe not found":
        return jsonify(result), 404
    return jsonify(result)


@app.route('/api/inventory/add', methods=['POST'])
def api_inventory_add():
    """Add items to inventory. Body: {items: [{name, quantity, unit, ...}]}."""
    from lib.inventory import (
        InventoryItem, add_items,
        normalize_category, normalize_location, normalize_source,
    )
    from lib.storage_locations import resolve_location

    data = request.get_json(force=True, silent=True)
    if not data or 'items' not in data:
        return jsonify({"error": "Request body must include 'items' array"}), 400

    raw_items = data['items']
    if not isinstance(raw_items, list) or not raw_items:
        return jsonify({"error": "'items' must be a non-empty array"}), 400

    # Default on: tag items with the meal-plan recipe they were bought for.
    # Set {"match_plan": false} to skip (e.g. a pure restock).
    match_plan = data.get('match_plan', True)

    parsed: list[InventoryItem] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        name = (raw.get('name') or '').strip()
        if not name:
            continue
        # Fee lines (sales tax, totes, tips) belong in the price ledger only —
        # they must never become inventory rows.
        if (raw.get('category') or '').lower().strip() == 'fee':
            continue
        try:
            quantity = float(raw.get('quantity', 1) or 1)
        except (ValueError, TypeError):
            quantity = 1.0
        category = normalize_category(raw.get('category'))
        # Explicit location wins; otherwise resolve from the storage table.
        location = (normalize_location(raw['location'])
                    if raw.get('location')
                    else resolve_location(name, category))
        parsed.append(InventoryItem(
            name=name,
            quantity=quantity,
            unit=(raw.get('unit') or 'ct').strip(),
            category=category,
            location=location,
            purchased=(raw.get('purchased') or None),
            source=normalize_source(raw.get('source') or 'claude'),
            notes=(raw.get('notes') or '').strip(),
            for_recipe=(raw.get('for_recipe') or None),
            expires=(raw.get('expires') or None),  # else auto-filled in add_items
        ))

    # Fill for_recipe for any item that didn't carry an explicit assignment.
    if match_plan and any(it.for_recipe is None for it in parsed):
        from lib.recipe_matcher import build_plan_index
        index = build_plan_index()
        for it in parsed:
            if it.for_recipe is None:
                matches = index.match(it.name)
                it.for_recipe = ", ".join(matches) if matches else None

    trip_payload = data.get('trip')
    # An all-fee items list is valid when a trip rides along (the ledger still
    # wants the rows) — only 400 when there's nothing to do at all.
    if not parsed and not trip_payload:
        return jsonify({"error": "No valid items provided"}), 400

    result = add_items(parsed) if parsed else {"added": 0, "merged": 0, "total": 0}

    # Optional price ledger: a "trip" object turns this add into a recorded
    # shopping trip (photo receipts from the Claude flow). Uses the RAW
    # request dicts so unit_price/line_total survive InventoryItem parsing.
    if trip_payload:
        from lib.inventory_db import record_trip
        from lib.receipt_parser import to_cents

        # for_recipe assignments were computed on InventoryItem (by name);
        # map them back onto the ledger rows so the trip records them too.
        recipe_by_name = {
            it.name.lower().strip(): it.for_recipe for it in parsed
        }
        purchases = [
            {
                "raw_name": it.get('notes') or it.get('name', ''),
                "canonical_name": (it.get('name') or '').lower().strip(),
                "quantity": it.get('quantity', 1),
                "unit": it.get('unit', 'ct'),
                "unit_price_cents": to_cents(it.get('unit_price')),
                "total_cents": to_cents(it.get('line_total')),
                "category": it.get('category', 'other'),
                "for_recipe": (
                    it.get('for_recipe')
                    or recipe_by_name.get((it.get('name') or '').lower().strip())
                ),
            }
            for it in raw_items
            if isinstance(it, dict)
        ]
        # record_trip returns None on a duplicate source_id (same receipt
        # shared twice) — that's fine, the inventory add still succeeded.
        record_trip(
            {
                "date": trip_payload.get('date', ''),
                "store": trip_payload.get('store', 'HEB'),
                "source": trip_payload.get('source', 'photo'),
                "source_id": trip_payload.get('source_id'),
                "total_cents": to_cents(trip_payload.get('total')),
            },
            purchases,
        )

    return jsonify({"status": "ok", **result})


@app.route('/api/inventory/paste', methods=['POST'])
def api_inventory_paste():
    """Bulk-add from a pasted markdown table (preview-then-commit).

    Body: {markdown: str, commit?: bool}. With commit=false (default) returns
    the parsed + routed rows for confirmation without writing; with commit=true
    persists them via inventory.add_items.
    """
    from lib import receipt_paster

    data = request.get_json(force=True, silent=True) or {}
    markdown = data.get('markdown')
    if not markdown or not markdown.strip():
        return jsonify({"error": "'markdown' is required"}), 400

    if data.get('commit'):
        return jsonify({"status": "committed", **receipt_paster.commit(markdown)})
    return jsonify({"status": "preview", **receipt_paster.preview(markdown)})


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


@app.route('/api/receipts/trips', methods=['GET'])
@require_token
def api_receipt_trips():
    """Recent shopping trips (newest first)."""
    from lib.inventory_db import fetch_trips
    return jsonify(fetch_trips())


@app.route('/api/receipts/trips/<int:trip_id>', methods=['GET'])
@require_token
def api_receipt_trip(trip_id):
    """One trip plus its purchase lines."""
    from lib.inventory_db import fetch_trip
    result = fetch_trip(trip_id)
    if result is None:
        return jsonify({"error": f"Trip not found: {trip_id}"}), 404
    return jsonify(result)


@app.route('/api/price/trends', methods=['GET'])
@require_token
def api_price_trends():
    """Structured price-tracker data (spending, by-category, trends)."""
    from lib.price_dashboard import compute_price_data
    return jsonify(compute_price_data())


@app.route('/api/nutrition/<week>', methods=['GET'])
@require_token
def api_nutrition(week):
    """Structured nutrition dashboard for a week (JSON projection of the
    same data that backs Nutrition Dashboard.md)."""
    if not re.match(r'^\d{4}-W\d{2}$', week):
        return jsonify({"error": "Invalid week format. Expected YYYY-WNN"}), 400

    from lib.nutrition_dashboard import compute_dashboard
    try:
        return jsonify(compute_dashboard(week, paths.vault_root()))
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _nutrition_review_norm(item: str) -> str:
    """Normalize an ingredient item exactly like ``nutrition_engine._resolve_food``
    so resolutions/cache entries pinned here line up with what the engine looks
    up during recompute."""
    from lib.nutrition_engine import normalize_ingredient_key
    return normalize_ingredient_key(item)


def _result_summary(result) -> dict:
    """Shared JSON-able summary of a ``RecipeNutritionResult`` for the
    nutrition-review ``/resolve`` and ``/recompute`` responses."""
    return {
        "per_serving": result.per_serving.to_dict(),
        "coverage": result.coverage,
        "confidence": result.confidence,
        "unmatched": result.unmatched,
        "needs_review": result.needs_review,
        "sanity_flags": result.sanity_flags,
    }


@app.route('/api/nutrition-review/recipes', methods=['GET'])
@require_token
def api_nutrition_review_list():
    """Ranked queue of recipes needing nutrition review, worst (lowest
    coverage, then lowest confidence) first. Reads frontmatter only — fast,
    no live recomputation."""
    recipes_dir = paths.recipes_dir()
    rows = []
    for filepath in sorted(recipes_dir.glob("*.md")):
        if filepath.name.startswith("."):
            continue
        try:
            content = filepath.read_text(encoding="utf-8")
            fm = parse_recipe_file(content)["frontmatter"]
        except Exception:
            continue
        if fm.get("nutrition_calories") is None:
            continue

        coverage = fm.get("nutrition_coverage")
        coverage = float(coverage) if isinstance(coverage, (int, float)) else 0.0
        confidence = fm.get("nutrition_confidence")
        confidence = float(confidence) if isinstance(confidence, (int, float)) else 0.0
        unmatched_raw = fm.get("nutrition_unmatched") or ""
        unmatched = [u.strip() for u in str(unmatched_raw).split(";") if u.strip()]

        # Scoped nutrition verdict is the source of truth; fall back to the
        # shared (escalate-only) flag for recipes backfilled before that key
        # existed.
        scoped_review = fm.get("nutrition_needs_review")
        needs_review = scoped_review if scoped_review is not None else fm.get("needs_review", False)

        rows.append({
            "name": filepath.stem,
            "coverage": coverage,
            "confidence": confidence,
            "calories": fm.get("nutrition_calories"),
            "needs_review": bool(needs_review),
            "unmatched": unmatched,
            "flags": [],  # sanity_flags aren't persisted to frontmatter (Task 8)
        })

    rows.sort(key=lambda r: (r["coverage"], r["confidence"]))
    return jsonify(rows)


@app.route('/api/nutrition-review/recipe/<name>', methods=['GET'])
@require_token
def api_nutrition_review_detail(name):
    """Recompute one recipe's nutrition live (deterministic — no LLM) and
    return an audit-trail view with USDA candidates for any weak/unresolved
    line, for the human review UI."""
    import backfill_nutrition
    from lib import food_db, inventory_db

    recipes_dir = paths.recipes_dir()
    filepath = (recipes_dir / f"{name}.md").resolve()
    if not filepath.is_relative_to(recipes_dir.resolve()) or not filepath.exists():
        return jsonify({"error": f"Recipe not found: {name}"}), 404

    query = request.args.get("q")
    if query:
        # Free-text re-query: the human typed a better search term for a
        # weak line's "Search…" box. Not tied to any particular ingredient
        # line, so return candidates at the top level instead of per-line.
        try:
            candidates = [
                {"source_id": c.source_id, "description": c.description}
                for c in (food_db.usda_search(query) or [])[:10]
            ]
        except Exception:
            candidates = []
        return jsonify({"name": name, "query": query, "candidates": candidates})

    content = filepath.read_text(encoding="utf-8")
    parsed = parse_recipe_file(content)
    ingredients = backfill_nutrition.extract_ingredients(parsed["body"])
    result = calculate_recipe_nutrition(
        ingredients, parsed["frontmatter"].get("servings"),
        resolution_provider="none", portion_provider="none",
    )
    if result is None:
        return jsonify({"error": "No ingredients could be resolved"}), 404

    lines = []
    for li in result.line_items:
        weak = li.needs_review or li.confidence < 0.8
        norm = _nutrition_review_norm(li.item)
        candidates = []
        if weak:
            try:
                candidates = [
                    {"source_id": c.source_id, "description": c.description}
                    for c in (food_db.usda_search(norm) or [])[:5]
                ]
            except Exception:
                candidates = []
        description = ""
        if li.food_source:
            cached = inventory_db.get_food_cache(norm, li.food_source)
            if cached:
                description = cached.get("description", "")
        lines.append({
            "item": li.item,
            "amount": li.amount,
            "unit": li.unit,
            "grams": li.grams,
            "grams_method": li.grams_method,
            "food_source": li.food_source,
            "food_description": description,
            "confidence": li.confidence,
            "needs_review": li.needs_review,
            "candidates": candidates,
        })

    return jsonify({
        "name": name,
        "servings": result.servings_used,
        "result": {
            "per_serving": result.per_serving.to_dict(),
            "coverage": result.coverage,
            "confidence": result.confidence,
            "unmatched": result.unmatched,
            "sanity_flags": result.sanity_flags,
        },
        "lines": lines,
    })


def _recompute_and_write(recipe_name: str):
    """Recompute one recipe file's nutrition and persist it.

    Returns ``(result, error)`` — exactly one is set. ``error`` distinguishes
    the two cheap-to-tell-apart failure modes: the recipe file doesn't exist,
    or it exists but no ingredient line could be resolved at all.
    """
    import backfill_nutrition

    recipes_dir = paths.recipes_dir()
    filepath = (recipes_dir / f"{recipe_name}.md").resolve()
    if not filepath.is_relative_to(recipes_dir.resolve()) or not filepath.exists():
        return None, f"recipe not found: {recipe_name}"

    content = filepath.read_text(encoding="utf-8")
    parsed = parse_recipe_file(content)
    ingredients = backfill_nutrition.extract_ingredients(parsed["body"])
    result = calculate_recipe_nutrition(ingredients, parsed["frontmatter"].get("servings"))
    if result is None:
        return None, "no ingredients could be resolved"

    create_backup(filepath)
    backfill_nutrition.write_nutrition_to_file(filepath, result)
    return result, None


@app.route('/api/nutrition-review/resolve', methods=['POST'])
@require_token
def api_nutrition_review_resolve():
    """Pin a human food match (or mark an item resolved-as-zero) so the
    nutrition engine's cache picks it up on the next recompute. When
    ``recipe`` is given, also recompute + persist that recipe's nutrition."""
    from lib import food_db, inventory_db

    data = request.get_json(force=True, silent=True) or {}
    item = data.get("item")
    if not item:
        return jsonify({"error": "'item' is required"}), 400
    norm = _nutrition_review_norm(item)
    if not norm:
        return jsonify({"error": f"'{item}' normalizes to empty"}), 400

    if data.get("negligible"):
        inventory_db.put_food_resolution(norm, "none", "0", 1.0, "human-negligible")
    else:
        source_id = data.get("source_id")
        if not source_id:
            return jsonify({"error": "'source_id' is required unless negligible"}), 400
        detail = food_db.usda_food_detail(source_id)
        if detail is None:
            return jsonify({"error": f"USDA detail not found for {source_id}"}), 404
        # A human just confirmed this is the right food. Real USDA detail
        # lookups usually carry a usable density/portions; when the source
        # doesn't (e.g. an item outside our curated staples), default to a
        # water-like density rather than leaving a confirmed match stuck
        # "unresolved" for grams forever.
        density = detail.density_g_per_ml if detail.density_g_per_ml is not None else 1.0
        record = {
            "query_norm": norm,
            "source": "usda",
            "source_id": detail.source_id,
            "description": detail.description,
            "per_100g": detail.per_100g.to_dict(),
            "portions": detail.portions,
            "density_g_per_ml": density,
        }
        inventory_db.put_food_cache(record)
        inventory_db.put_food_resolution(norm, "usda", source_id, 1.0, "human")

    response = {"status": "ok"}
    recipe = data.get("recipe")
    if recipe:
        result, error = _recompute_and_write(recipe)
        if result is not None:
            response["recipe_result"] = _result_summary(result)
        else:
            # The pin above still succeeded — surface the recompute failure
            # separately so the UI can tell "pinned but couldn't recompute"
            # from "everything worked".
            response["recipe_error"] = error
    return jsonify(response)


@app.route('/api/nutrition-review/recompute', methods=['POST'])
@require_token
def api_nutrition_review_recompute():
    """Rerun the nutrition engine for one recipe file and persist + return
    the new summary."""
    data = request.get_json(force=True, silent=True) or {}
    recipe = data.get("recipe")
    if not recipe:
        return jsonify({"error": "'recipe' is required"}), 400

    result, error = _recompute_and_write(recipe)
    if result is None:
        return jsonify({"error": error or f"Recipe not found or unresolvable: {recipe}"}), 404

    return jsonify({"name": recipe, **_result_summary(result)})


@app.route('/api/system-health', methods=['GET'])
def api_system_health():
    """System health JSON: Ollama, vault, recent recipes, run/failure logs, Reminders queue."""
    from lib import health
    return jsonify(health.get_system_health())


@app.route('/system-health', methods=['GET'])
def system_health_dashboard():
    """Interactive system health dashboard."""
    html = open('templates/system_health.html').read()
    return html


@app.route('/nutrition-review', methods=['GET'])
def nutrition_review_page():
    """Human review UI for weak/unresolved nutrition matches."""
    html = open('templates/nutrition_review.html').read()
    return html


if __name__ == '__main__':
    try:
        import setproctitle
        setproctitle.setproctitle('kitchenos-api')
    except ImportError:
        pass
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
