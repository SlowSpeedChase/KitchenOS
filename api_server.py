#!/usr/bin/env python3
"""Simple API server for iOS Shortcuts integration."""

from flask import Flask, request, jsonify, send_file
from markupsafe import escape
from urllib.parse import quote
from youtube_transcript_api import YouTubeTranscriptApi
from googleapiclient.discovery import build
import functools
import math
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
import warnings
from datetime import date, timedelta
from pathlib import Path
from dotenv import load_dotenv

from lib.shopping_list_generator import (
    format_qty as shopping_list_format_qty,
    generate_shopping_list,
    on_hand_notes,
    parse_shopping_list_file,
    extract_manual_items,
    SHOPPING_LISTS_PATH,
)
from lib.backup import create_backup
from lib.recipe_index import get_recipe_index
from lib.meal_plan_parser import (
    flatten_to_recipes,
    insert_recipe_into_meal_plan,
    parse_meal_plan,
    rebuild_meal_plan_markdown,
)
from lib.meal_nutrition import meal_nutrition
from lib.recipe_parser import parse_recipe_file, extract_my_notes, parse_recipe_body
from lib import recipe_refresh, nutrition_quality
from templates.shopping_list_template import generate_shopping_list_markdown, generate_filename as shopping_list_filename
from templates.recipe_template import format_recipe_markdown
from templates.meal_plan_template import (
    format_week_heading,
    format_week_range,
    generate_meal_plan_markdown,
)
from lib.meal_plan_index import regenerate_index
from lib.ingredient_validator import validate_ingredients
from lib.ingredient_cleaner import clean_ingredient_list
from lib.seasonality import match_ingredients_to_seasonal, get_peak_months
from lib.nutrition_engine import calculate_recipe_nutrition
from lib import cook, meal_loader, pantry as pantry_module, paths, task_extractor
from lib.serving_ledger import MEALS as SLOT_VOCAB
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


def _html_page(title: str, body: str, extra_css: str = "") -> str:
    """The one <head> for every page api_server builds in Python.

    Six pages used to hand-roll their own, which is how they stayed
    light-only while the templates moved onto the design language. The
    guard in tests/test_theme_tokens.py asserts this is the only page
    with a doctype declaration in the file.
    """
    style = f"<style>{extra_css}</style>" if extra_css else ""
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#f4ede3" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#0f1116" media="(prefers-color-scheme: dark)">
<title>{title}</title>
<link rel="stylesheet" href="/static/tokens.css">
<link rel="stylesheet" href="/static/kitchenos.css">
<style>
  body {{ font-family: var(--font-body); background: var(--bg);
         background-image: var(--dots);
         background-size: var(--dot-size) var(--dot-size);
         color: var(--ink); padding: 2rem 1.5rem; max-width: 600px;
         margin: 0 auto; -webkit-text-size-adjust: 100%; }}
  .card {{ background: var(--surface); background-image: var(--grain);
          border: 1px solid var(--line); border-radius: var(--radius-box);
          padding: 1rem; }}
  .card.ok {{ background: var(--tint-done); border-color: var(--edge-done); }}
  .card.bad {{ background: var(--tint-alert); border-color: var(--edge-alert); }}
  .card.info {{ background: var(--tint-accent); border-color: var(--edge-accent); }}
  .card.warn {{ background: var(--tint-warning); border-color: var(--edge-warning); }}
  .card.ok strong {{ color: var(--done); }}
  .card.bad strong {{ color: var(--alert); }}
  a {{ color: var(--app-kitchenos); }}
  .btn {{ display: inline-block; padding: 12px 20px; border: 1px solid var(--line);
         border-radius: var(--radius-box); text-decoration: none; color: var(--ink); }}
</style>
{style}
</head>
<body>
{body}
</body>
</html>'''


def error_page(message: str) -> str:
    """Generate simple HTML error page.

    The message is escaped here (call sites pass raw text, often str(e));
    escaping already-escaped Markup is a no-op.
    """
    return _html_page("KitchenOS", f'''
<div class="card bad"><strong>Error</strong><br>{escape(message)}</div>
<p><a class="btn" href="obsidian://open?vault={VAULT_NAME}">Return to Obsidian</a></p>
''')


# ---- Claude launch bar (injected into every web page at serve time) ----

_CLAUDE_BAR_TEMPLATE = """
<div id="ko-claude-bar" style="position:sticky;top:0;left:0;right:0;z-index:2147483000;background:var(--raised);color:var(--ink);border-bottom:1px solid var(--line);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;font-size:14px;box-shadow:var(--shadow);">
  <div style="display:flex;align-items:center;gap:12px;padding:8px 14px;">
    <a id="ko-home-link" href="/" title="KitchenOS home" aria-label="KitchenOS home" style="color:var(--ink);text-decoration:none;padding:0 12px;border:1px solid var(--line);border-radius:8px;white-space:nowrap;display:inline-flex;align-items:center;justify-content:center;min-width:44px;min-height:44px;box-sizing:border-box;">&#127968;</a>
    <a id="ko-claude-launch" href="ssh://__SSH_TARGET__" style="background:var(--insight);color:var(--text-on-accent);text-decoration:none;padding:0 16px;border-radius:8px;font-weight:600;white-space:nowrap;display:inline-flex;align-items:center;min-height:44px;box-sizing:border-box;">&#129302; Launch Claude</a>
    <button id="ko-claude-toggle" type="button" style="background:transparent;color:var(--muted);border:1px solid var(--line);border-radius:8px;padding:0 14px;cursor:pointer;font-size:14px;display:inline-flex;align-items:center;min-height:44px;box-sizing:border-box;">&#128221; Notes</button>
    <span id="ko-claude-status" style="color:var(--muted);font-size:12px;margin-left:auto;"></span>
  </div>
  <div id="ko-claude-notes-wrap" style="display:none;padding:0 14px 12px;">
    <textarea id="ko-claude-notes" placeholder="Notes to yourself &amp; Claude — saved to Claude Notes.md, seeds the next Launch." style="width:100%;box-sizing:border-box;min-height:120px;background:var(--surface);color:var(--ink);border:1px solid var(--line);border-radius:8px;padding:10px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:13px;resize:vertical;"></textarea>
    <div style="display:flex;gap:10px;align-items:center;margin-top:8px;">
      <button id="ko-claude-send" type="button" style="background:var(--insight);color:var(--text-on-accent);border:none;border-radius:8px;padding:8px 16px;font-weight:700;cursor:pointer;min-height:44px;">&#9654;&#65039; Send to Claude</button>
      <button id="ko-claude-save" type="button" style="background:var(--done);color:var(--text-on-accent);border:none;border-radius:8px;padding:8px 16px;font-weight:700;cursor:pointer;min-height:44px;">Save</button>
      <span id="ko-claude-save-status" style="color:var(--muted);font-size:12px;"></span>
    </div>
  </div>
</div>
<script>
(function(){
  var toggle=document.getElementById('ko-claude-toggle');
  var wrap=document.getElementById('ko-claude-notes-wrap');
  var ta=document.getElementById('ko-claude-notes');
  var saveBtn=document.getElementById('ko-claude-save');
  var saveStatus=document.getElementById('ko-claude-save-status');
  var loaded=false;
  function loadNotes(){
    fetch('/api/claude-notes').then(function(r){return r.json();}).then(function(d){
      ta.value=(d&&d.notes)||''; loaded=true;
    }).catch(function(){ saveStatus.textContent='(offline)'; });
  }
  toggle.addEventListener('click',function(){
    var open=wrap.style.display==='none';
    wrap.style.display=open?'block':'none';
    if(open&&!loaded){loadNotes();}
  });
  saveBtn.addEventListener('click',function(){
    saveStatus.textContent='Saving…';
    fetch('/api/claude-notes',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({notes:ta.value})})
      .then(function(r){return r.json();}).then(function(d){
        if(d&&d.status==='saved'){ta.value=d.notes;saveStatus.textContent='Saved ✓';}
        else{saveStatus.textContent='Error';}
      }).catch(function(){saveStatus.textContent='Save failed';});
  });
  var sendBtn=document.getElementById('ko-claude-send');
  sendBtn.addEventListener('click',function(){
    var text=ta.value;
    if(!text.trim()){saveStatus.textContent='Nothing to send';return;}
    saveStatus.textContent='Sending…';
    // Carry the page, so "fix this" still has a "this" by the time Claude reads it.
    var payload={text:text,page:location.pathname+location.search,title:document.title};
    fetch('/api/claude-send',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)})
      .then(function(r){return r.json();}).then(function(d){
        if(d&&d.status==='sent'){
          // It landed in the live session, so the box has done its job — clearing
          // it prevents the same request being sent twice on a double tap.
          ta.value='';saveStatus.textContent='Sent to Claude ✓';
        } else if(d&&d.status==='queued'){
          // Cleared rather than refilled: the stored copy carries a context
          // header, and echoing that back would re-send it prefixed twice.
          ta.value='';saveStatus.textContent='No session — queued for next Launch ✓';
        } else {saveStatus.textContent=(d&&d.error)||'Error';}
      }).catch(function(){saveStatus.textContent='Send failed';});
  });
})();
</script>
"""


def _claude_bar_html() -> str:
    """The launch-bar widget with the current SSH target spliced in."""
    target = os.environ.get(
        'KITCHENOS_SSH_TARGET', 'chaseeasterling@chases-mac-mini.taila69703.ts.net'
    )
    return _CLAUDE_BAR_TEMPLATE.replace('__SSH_TARGET__', target)


def _inject_after_body(html: str, snippet: str) -> str:
    """Splice snippet in immediately after the opening <body ...> tag.

    String splice, not regex/replace — the snippet contains regex/format
    metacharacters. Falls back to prepending if there is no <body> tag.

    The search starts after ``</head>`` because a template may *write about*
    the tag before opening it: meal_planner.html explains the chrome bar in a
    CSS comment naming the literal ``<body>``, and matching that comment
    spliced the bar into the stylesheet, where the browser dropped it. The page
    then contained the markup and rendered no bar — so the planner, the one
    page you reach mid-task, was the only one with no way back home.
    """
    lower = html.lower()
    head_end = lower.find('</head>')
    search_from = head_end + len('</head>') if head_end != -1 else 0
    idx = lower.find('<body', search_from)
    if idx == -1:
        return snippet + html
    close = html.find('>', idx)
    if close == -1:
        return snippet + html
    return html[:close + 1] + snippet + html[close + 1:]


def _serve_page_with_claude_bar(template_filename: str, extra_replacements=None) -> str:
    """Read a template, apply page-specific replacements, inject the Claude bar."""
    html = open(f'templates/{template_filename}').read()
    for old, new in (extra_replacements or []):
        html = html.replace(old, new)
    return _inject_after_body(html, _claude_bar_html())


def success_page(message: str, filename: str) -> str:
    """Generate simple HTML success page."""
    from urllib.parse import quote
    encoded_filename = quote(filename, safe='')
    return _html_page("KitchenOS", f'''
<div class="card ok"><strong>Success</strong><br>{message}</div>
<p><a class="btn" href="obsidian://open?vault={VAULT_NAME}&file=Recipes/{encoded_filename}">Return to {filename}</a></p>
''')


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


def _annotate_stock(ingredients: list[dict]) -> list[dict]:
    """Copy of ``ingredients`` with each entry marked in-stock or not.

    Adds two keys per ingredient:
        ``in_stock``  True / False, or **None when there's nothing to check
                      against** — an empty inventory would otherwise render the
                      whole recipe as "you have none of this", which is a claim
                      about the kitchen rather than about the data.
        ``have``      the matched row as "3 lb", for a tooltip; None when unmatched.

    Presence, not sufficiency — see ``pantry.stock_for_ingredients``. Never
    raises: a DB that won't open leaves the page rendering an uncoloured
    ingredient list, which is what it did before this existed.
    """
    try:
        pantry = pantry_module.load_pantry()
    except Exception:
        pantry = []
    if not pantry:
        return [{**ing, "in_stock": None, "have": None} for ing in ingredients]

    matches = pantry_module.stock_for_ingredients(
        [ing.get("item", "") for ing in ingredients], pantry)
    annotated = []
    for ing, match in zip(ingredients, matches):
        have = None
        if match:
            have = shopping_list_format_qty(match.get("amount"), match.get("unit"))
        annotated.append({**ing, "in_stock": match is not None, "have": have})
    return annotated


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

        ingredients = _annotate_stock(body_data.get('ingredients', []))

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
            "ingredients": ingredients,
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

    html = _serve_page_with_claude_bar('recipe_detail.html', [('vault=KitchenOS', f'vault={VAULT_NAME}')])
    return html, 200, {'Content-Type': 'text/html'}


@app.route('/plan-week', methods=['GET'])
def plan_week_page():
    """The Sunday-planning command center: one page, three steps (fill →
    review → print). Defaults to next week; ?week= overrides.
    """
    from lib import plan_week, print_week

    week = request.args.get('week')
    if not week:
        week = plan_week.default_week()
    if not re.match(r'^\d{4}-W\d{2}$', week):
        return error_page(f"Invalid week format: {week} (expected YYYY-WNN)"), 400

    try:
        packet = print_week.build_week_packet(
            week, paths.vault_root(), _resolve_recipes_dir())
        targets = packet["targets"]
    except FileNotFoundError:
        packet = None
        from lib.print_week import _targets_dict
        targets, _ = _targets_dict(paths.vault_root())

    base = os.environ.get("KITCHENOS_API_BASE", "").rstrip("/")
    body = plan_week.render_plan_center_html(
        week, packet, targets, base,
        plan_week.shift_week(week, -1), plan_week.shift_week(week, 1))
    html = _serve_page_with_claude_bar('plan_week.html', [('<!--CENTER-->', body)])
    return html, 200, {'Content-Type': 'text/html'}


@app.route('/print/week', methods=['GET'])
def print_week_page():
    """Printable one-page 'week packet': plan grid + macros vs targets +
    shopping list + do-ahead prep. Defaults to the current ISO week; ?week=
    overrides, ?tasks=1 regenerates prep (an LLM call) instead of read-only cache.
    """
    from lib import print_week

    week = request.args.get('week')
    if not week:
        iso = date.today().isocalendar()
        week = f"{iso[0]}-W{iso[1]:02d}"
    if not re.match(r'^\d{4}-W\d{2}$', week):
        return error_page(f"Invalid week format: {week} (expected YYYY-WNN)"), 400

    include_tasks = request.args.get('tasks') in ('1', 'true', 'yes')
    try:
        packet = print_week.build_week_packet(
            week, paths.vault_root(), _resolve_recipes_dir(),
            include_tasks=include_tasks)
    except FileNotFoundError:
        return error_page(f"No meal plan for {week} yet — plan a week first."), 404

    base = os.environ.get("KITCHENOS_API_BASE", "").rstrip("/")
    body = print_week.render_packet_html(packet, base_url=base)
    html = _serve_page_with_claude_bar('print_week.html', [('<!--PACKET-->', body)])
    return html, 200, {'Content-Type': 'text/html'}


@app.route('/recipe-card/<name>', methods=['GET'])
def recipe_card_page(name):
    """Serve a printable 'grid' (Cooking-for-Engineers matrix) recipe card.

    The step grouping is AI-inferred (cached in a <recipe>.grid.json sidecar);
    ?force=1 recomputes it. The recipe's own extracted steps are never altered.
    """
    from html import escape as _escape
    from lib import recipe_grid, serving_ledger
    from lib.recipe_parser import parse_recipe_file, parse_recipe_body

    recipes_dir = _resolve_recipes_dir()
    filepath = (recipes_dir / f"{name}.md").resolve()
    if not filepath.is_relative_to(recipes_dir.resolve()) or not filepath.exists():
        return error_page(f"Recipe not found: {name}"), 404

    force = request.args.get('force') in ('1', 'true', 'yes')
    parsed = parse_recipe_file(filepath.read_text(encoding="utf-8"))
    fm = parsed["frontmatter"]
    ingredients = parse_recipe_body(parsed["body"]).get("ingredients", [])

    spec = recipe_grid.build_grid(name, recipes_dir, force=force)
    grid_html = recipe_grid.render_grid_html(spec, ingredients)

    title = _escape(str(fm.get("title") or name))
    meta_parts = []
    servings = fm.get("servings")
    if servings:
        meta_parts.append(f"Serves <strong>{_escape(str(servings))}</strong>")
    macros = serving_ledger.recipe_macros(name, recipes_dir)
    if macros:
        meta_parts.append(
            f"<strong>{macros['protein']} g</strong> protein · "
            f"<strong>{macros['calories']}</strong> kcal per serving")
    meta = " &nbsp;·&nbsp; ".join(meta_parts) or "—"

    review = ""
    if spec.get("needs_review"):
        src = _escape(str(spec.get("source", "AI")))
        review = ("<div class='review-note'>⚠️ The step grouping below is "
                  f"AI-suggested ({src}) — sanity-check it against the recipe. "
                  "Your recipe's own steps are unchanged.</div>")

    html = _serve_page_with_claude_bar('recipe_card.html', [
        ('__CARD_TITLE__', title),
        ('__CARD_META__', meta),
        ('__REVIEW_NOTE__', review),
        ('<!--GRID-->', grid_html),
    ])
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
    """Generate shopping list markdown from meal plan, crediting what's in stock.

    **Annotates, never decrements.** This is the one-shot trigger — the button on
    `/current/shopping-list`, the only one reachable from the phone you shop with
    — so there's no confirmation step to approve inventory writes against. It
    reads the pantry to keep what you already own off the buy list and records
    what it credited under "Already have"; the preview/confirm pair
    (`/api/shopping-list/preview` → `/confirm`) remains the only path that
    actually decrements stock.

    Until now this passed no pantry at all, so the list you generated from your
    phone told you to buy the garlic salt, eggs and brown sugar already in the
    kitchen. Pass `use_pantry: false` to get the old raw-demand behaviour.
    """
    data = request.get_json(force=True, silent=True) or {}
    week = data.get('week')

    if not week:
        return jsonify({'success': False, 'error': 'No week provided'}), 400

    use_pantry = data.get('use_pantry', True)
    pantry = pantry_module.load_pantry() if use_pantry else None
    result = generate_shopping_list(week, pantry=pantry)

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

    # Create markdown content. on_hand notes are informational only — they carry
    # no checkbox, so they never reach Reminders or come back as manual items.
    on_hand = on_hand_notes(result.get('lines') or []) if use_pantry else []
    markdown = generate_shopping_list_markdown(week, all_items, on_hand=on_hand)

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
    """Send this week's unchecked shopping-list items to Apple Reminders.

    Reachable from the phone since the shopping-list page's Send to Reminders
    button became plain HTTP; its Obsidian ``kitchenos://`` original is handled by
    a macOS helper app that no longer exists.
    """
    from lib.reminders import add_to_reminders

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

    # Send to Reminders. add_to_reminders creates the list if it's missing, so a
    # separate create call would just be another ~0.4s round-trip.
    try:
        sent = add_to_reminders(result['items'], "Shopping")

        return jsonify({
            'success': True,
            'items_sent': sent,
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
            warnings_html = (
                f'<div class="card warn" style="margin-top:1rem;">'
                f'<strong>Warnings:</strong><ul>{warnings_list}</ul></div>'
            )

        return _html_page("KitchenOS", f'''
<div class="card ok"><strong>Success</strong><br>Dashboard updated for {_week_label(week)}</div>
{warnings_html}
<p><a href="obsidian://open?vault={VAULT_NAME}&file=Nutrition%20Dashboard">View Dashboard</a></p>
''')

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

        # Build recipe_data from frontmatter + body.
        #
        # This dict used to be spelled out here and had fallen behind the
        # schema — 18 keys where the template renders 30 — so a "Refresh
        # template" press silently returned banner, all four macros,
        # serving_size, meal_occasion, seasonal_ingredients and peak_months as
        # null. lib/recipe_refresh owns the mapping now so it stays in one
        # place; see that module for why the merge below is schema-driven.
        recipe_data = recipe_refresh.template_payload(frontmatter, body_data)

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

        # The template has no slot for keys other producers write — short_title,
        # the fit_* family, nutrition_coverage, cook_count, last_cooked — so a
        # re-render drops them outright. Put back anything declared that the
        # render lost.
        new_content = recipe_refresh.preserve_unrendered(new_content, frontmatter)

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
            # Resolve from this file, never a literal. This was hardcoded to
            # ~/GitHub/KitchenOS, a path that stopped existing at the macOS 27
            # rebuild, so every press of the "Re-extract" button baked into all
            # 252 recipe notes raised FileNotFoundError into the generic
            # handler below and rendered an error page. /extract (above) had
            # already been fixed; these two drifted apart.
            cwd=str(Path(__file__).resolve().parent),
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

    plan_file = MEAL_PLANS_PATH / f"{week}.md"

    if plan_file.exists():
        content = plan_file.read_text(encoding="utf-8")
    else:
        # Reading a week must not create it. This used to write the file (and
        # regenerate the index) for any week it was asked about, and the
        # planner's prev/next nav calls it once per click with no bounds — so
        # idly paging through the calendar minted plan files. `2026-W52`,
        # `2027-W01` and `2030-W20` in the real vault are its output, not test
        # residue, and `sync_calendar.py` globs every plan file, so they shipped
        # to the subscribed calendar every morning at 06:05.
        #
        # The empty skeleton is still returned so the planner renders a usable
        # week; the file appears on the first actual write (a cook, or the
        # 06:00 agent), which is where `regenerate_index` now happens too.
        content = generate_meal_plan_markdown(year, week_num)

    parsed = parse_meal_plan(content, year, week_num)

    days = []
    macro_cache: dict = {}
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
                        # Shipped here, not left to the client's /api/meals fetch:
                        # the planner loads meals and the plan concurrently, so a
                        # card built from the plan can't count on the meal index
                        # being populated yet. `nutrition` is per 1x the bundle —
                        # the card scales it by its own servings multiplier.
                        slot_json["slot"] = meal_def.slot
                        slot_json["nutrition"] = meal_nutrition(
                            meal_def, OBSIDIAN_RECIPES_PATH, macro_cache=macro_cache)
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


#: Seconds within which an identical POST /api/cooks is treated as a repeat of
#: the same tap rather than a second cook. Deliberately short — see
#: serving_ledger.find_recent_duplicate.
COOK_DEDUPE_WINDOW_S = 10.0

#: Weeks with a prep-task precompute in flight, so a burst of chip drags
#: doesn't start one thread per drag. Guarded by _PRECOMPUTE_LOCK.
_PRECOMPUTING: set = set()
_PRECOMPUTE_LOCK = threading.Lock()


def _precompute_tasks_async(week: str):
    """Rebuild the week's prep-task sidecar off the request thread.

    This is the half of the /prep fix that `task_extractor` cannot do for
    itself. Inside a Flask request `llm_gate` caps inference at 8 s, but
    classifying a real week takes Haiku ~9.5 s — so a page render can never
    produce a real answer, and (correctly) refuses to cache the heuristic one
    it does produce. /prep therefore paid the full budget on every single load.

    A plain thread is enough: Flask's request context is thread-local, so this
    runs *outside* one, which is exactly what `llm_gate.budget_s` keys on — the
    caller's own 60 s applies here, nobody is waiting, and the result persists.
    Daemon so it can never hold up a shutdown; failures are swallowed because a
    missing sidecar is a slow page, not a broken one.
    """
    from lib import task_extractor

    with _PRECOMPUTE_LOCK:
        if week in _PRECOMPUTING:
            return
        _PRECOMPUTING.add(week)

    def run():
        try:
            task_extractor.extract_tasks(week, force=True)
        except Exception:
            app.logger.exception("prep-task precompute failed for %s", week)
        finally:
            with _PRECOMPUTE_LOCK:
                _PRECOMPUTING.discard(week)

    threading.Thread(target=run, name=f"precompute-tasks-{week}", daemon=True).start()


def _regen_weeks(*weeks):
    from lib import week_view
    for wk in {w for w in weeks if w}:
        try:
            week_view.write_week_markdown(wk)
        except Exception as e:
            print(f"Warning: week view regen failed for {wk}: {e}", file=sys.stderr)
        # The plan just changed, so the prep tasks are stale. Rebuild them now,
        # off-request, rather than making the next visitor of /prep wait.
        _precompute_tasks_async(wk)


def _sync_cook_history(*recipes):
    """Refresh cook stats on the affected recipe notes.

    Best-effort by design: this is bookkeeping that accrues over time, so a
    missing or unwritable note must never fail the ledger write that triggered
    it. The ledger is the source of truth; the frontmatter is a convenience
    view that the next cook will refresh anyway.
    """
    from lib import cook_history
    for recipe in {r for r in recipes if r}:
        try:
            cook_history.sync_recipe(recipe)
        except Exception as e:
            print(f"Warning: cook history sync failed for {recipe}: {e}", file=sys.stderr)

    # The On Track view reads from the ledger, so it goes stale the moment a
    # cook or verdict lands. Same best-effort contract as above.
    try:
        from lib import on_track
        on_track.write_note()
    except Exception as e:
        print(f"Warning: On Track regen failed: {e}", file=sys.stderr)


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
            # The import creates cooks in bulk, bypassing the per-cook hook in
            # api_cook_create — so without this the converted week's recipes
            # never learn their yield, and the notes look untouched even though
            # the ledger has rows. Reported as "I don't see this on the recipe
            # page anywhere".
            _sync_cook_history(*[c["recipe"]
                                 for c in serving_ledger.cooks_for_week(wk)])
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
    _sync_cook_history(*[c["recipe"] for c in serving_ledger.cooks_for_week(week)])
    return jsonify({"imported": imported})


@app.route('/api/cooks', methods=['POST'])
@require_token
@_ledger_error
def api_cook_create():
    from lib import serving_ledger
    data = request.get_json(force=True, silent=True) or {}

    # Absorb a double-tap. Returns 200 (not 201) so a caller can tell the
    # difference between creating and matching. See find_recent_duplicate for
    # why the window is seconds rather than a uniqueness constraint — cooking
    # the same dish twice in a week is legitimate; doing it twice in three
    # seconds is a button that didn't look like it worked.
    existing = serving_ledger.find_recent_duplicate(
        data.get('recipe'), data.get('week'), data.get('date'), data.get('meal'),
        COOK_DEDUPE_WINDOW_S)
    if existing is not None:
        return jsonify(existing), 200

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
    _sync_cook_history(cook["recipe"])
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
    updated = serving_ledger.update_cook(cook_id, **data)

    # Recording a cook is what closes the inventory loop, and it closes here —
    # server-side, on the NULL -> set transition of `cooked_at` — so that every
    # surface which can mark something cooked spends the pantry exactly once,
    # whether that's the board's 🍳, a phone, an intent, or the nightly sweep.
    # Before this, consumption lived in a client-side call the board made
    # alongside its PATCH, so only that one button closed it: inventory had 0 of
    # 239 rows ever use-stamped, and `POST /api/cook` had been called four times
    # in the system's life.
    #
    # Gated on the transition, not on the field being present, so re-PATCHing an
    # already-cooked row (or editing its note afterwards) cannot spend the
    # pantry twice.
    if before.get("cooked_at") is None and updated.get("cooked_at"):
        try:
            cook.consume_recipe(
                updated["recipe"],
                servings=float(updated.get("scale") or 1.0),
            )
        except Exception:
            # Never fail the PATCH over this. The cook record is the user's
            # memory of what happened; inventory is derived from it. Losing the
            # record because a decrement raised is the worse of the two
            # failures, and a missed depletion self-heals via the expiry prune.
            app.logger.exception(
                "consume_recipe failed for cook %s (%s); the cook was still recorded",
                cook_id, updated.get("recipe"),
            )

    _regen_weeks(before["week"], updated["week"])
    # Both names: a recipe rename must refresh the note it left as well.
    _sync_cook_history(before["recipe"], updated["recipe"])
    return jsonify(updated)


@app.route('/api/cooks/<int:cook_id>/move', methods=['POST'])
@require_token
@_ledger_error
def api_cook_move(cook_id):
    """Move a scheduled cook to another slot, home servings included.

    Distinct from PATCH /api/cooks/<id>, which is a field-setter: this rewrites
    placement rows as well, so it says so in its name rather than making
    {"date": ...} mean two different things depending on the caller.
    """
    from lib import serving_ledger
    data = request.get_json(force=True, silent=True) or {}
    cook = serving_ledger.get_cook(cook_id)
    if cook is None:
        return jsonify({"error": "cook not found"}), 404
    cook = serving_ledger.move_cook(cook_id, data.get('date'), data.get('meal'))
    # One week, not two: move_cook rejects a date outside the cook's week.
    _regen_weeks(cook["week"])
    _sync_cook_history(cook["recipe"])
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
    _sync_cook_history(cook["recipe"])
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
                if entry is None or not entry.name:
                    continue
                # Flatten meal bundles to their sub-recipes first. Everything
                # downstream — the ingredient overlap here, and day_macro_gap's
                # per-recipe frontmatter lookup — resolves a name against
                # Recipes/, where a `[[Meal: X]]` bundle has no file. Left
                # unflattened, a planned meal contributed zero ingredients and
                # zero calories, so the suggester believed the day was emptier
                # than it was and steered every macro-aware suggestion wrong by a
                # whole meal.
                for flat in flatten_to_recipes([entry]):
                    recipe_file = OBSIDIAN_RECIPES_PATH / f"{flat.name}.md"
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
                        "name": flat.name,
                        "ingredients": ingredients,
                        "servings": flat.servings or 1,
                    })

    from lib.meal_suggester import suggest_meal, day_macro_gap
    from lib.macro_targets import load_macro_targets

    # The target day's remaining macro gap steers the suggestion toward the
    # user's daily protein/calorie targets. None (no My Macros.md) => the
    # suggester falls back to its ingredient-overlap behaviour unchanged.
    targets = load_macro_targets(paths.vault_root())
    macro_gap = day_macro_gap(planned_meals, day, targets, OBSIDIAN_RECIPES_PATH)

    result = suggest_meal(
        recipes_dir=OBSIDIAN_RECIPES_PATH,
        planned_meals=planned_meals,
        day=day,
        meal=meal,
        skip_index=skip_index,
        macro_gap=(macro_gap or {}).get("remaining") if macro_gap else None,
    )

    if result is None:
        return jsonify({"suggestion": None, "message": "No suggestions available",
                        "macro_context": macro_gap})

    # macro_context describes the day's target/current/remaining plus what this
    # suggestion would add — additive, so pre-macro clients keep working.
    if macro_gap and result.get("nutrition"):
        projected = {
            k: macro_gap["current"][k] + result["nutrition"].get(k, 0)
            for k in ("protein", "calories", "carbs", "fat")
        }
        macro_gap = {**macro_gap, "projected_with_suggestion": projected}

    return jsonify({"suggestion": result, "macro_context": macro_gap})


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


def _week_label(week_id: str) -> str:
    """A week as a human reads it, e.g. 'This week · Jun 22 - Jun 28'.

    Never raises — falls back to the raw id, so a malformed week can't turn a
    success message into an error page. In a `<select>` the id is the option's
    *value*; it used to be appended in parentheses here too, which just put the
    unreadable form back in front of the user.
    """
    try:
        return format_week_heading(week_id, with_year=False)
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

    week_options = ''.join(f'<option value="{w}">{_week_label(w)}</option>' for w in weeks)
    day_options = ''.join(f'<option value="{d}">{d}</option>' for d in days)
    meal_options = ''.join(f'<option value="{m}">{m}</option>' for m in meals)
    meal_name_options = ''.join(f'<option value="{n}">{n}</option>' for n in meal_names)

    has_meals = bool(meal_names)
    existing_disabled = '' if has_meals else 'disabled'
    existing_label = 'Add to an existing meal' if has_meals else 'Add to an existing meal (none yet)'

    error_html = (
        f'<div class="error">{error}</div>' if error else ''
    )

    return _html_page("Add to Meal Plan", f'''
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
''', extra_css='''
    body { max-width: 480px; padding: 1.5rem; }
    h2 { margin-top: 0; }
    .recipe-name { background: var(--raised); padding: 0.75rem;
                   border-radius: var(--radius-box); margin-bottom: 1.5rem;
                   font-weight: 600; }
    .error { background: var(--tint-alert); border: 1px solid var(--edge-alert);
             color: var(--alert); padding: 0.75rem;
             border-radius: var(--radius-box); margin-bottom: 1rem; }
    .branch { display: block; padding: 0.75rem; margin-bottom: 0.5rem;
              border: 1px solid var(--line); border-radius: var(--radius-box);
              cursor: pointer; background: var(--surface); }
    .branch input[type="radio"] { margin-right: 0.5rem; }
    .branch.disabled { opacity: 0.5; cursor: not-allowed; }
    .fields { display: none; margin-top: 1rem; }
    .fields.active { display: block; }
    label { display: block; font-weight: 600; margin-bottom: 0.25rem;
            margin-top: 1rem; }
    select, input[type="text"] { width: 100%; padding: 0.75rem; font-size: 16px;
             border: 1px solid var(--line); border-radius: var(--radius-box);
             background: var(--surface); color: var(--ink);
             -webkit-appearance: none; box-sizing: border-box; }
    button { width: 100%; padding: 1rem; font-size: 18px; font-weight: 600;
             background: var(--app-kitchenos); color: var(--text-on-accent);
             border: none; border-radius: var(--radius-box);
             margin-top: 1.5rem; cursor: pointer; }
    button:active { opacity: 0.85; }
''')


def _success_page_for_wikilink(wikilink_target: str, day: str, meal: str, week: str) -> str:
    """Green confirmation card after a slot insert. Works for [[Recipe]] or [[Meal: X]]."""
    from urllib.parse import quote
    encoded_file = quote(f"Meal Plans/{week}", safe='')
    return _html_page("KitchenOS", f'''
<div class="card ok"><strong>Added!</strong><br>
[[{wikilink_target}]] &rarr; {day} {meal} ({week})</div>
<p><a href="obsidian://open?vault={VAULT_NAME}&file={encoded_file}">View Meal Plan</a></p>
<p><a href="obsidian://open?vault={VAULT_NAME}">Back to Obsidian</a></p>
''')


def _render_schedule_prompt(recipe: str, meal_name: str, action: str, info: str | None = None) -> str:
    """Screen 2 — hybrid optional schedule prompt after meal save."""
    from urllib.parse import quote
    weeks = _generate_week_options()
    days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    meals = ['Breakfast', 'Lunch', 'Snack', 'Dinner']
    week_options = ''.join(f'<option value="{w}">{_week_label(w)}</option>' for w in weeks)
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

    return _html_page("Schedule Meal", f'''
<div class="card ok"><strong>&#10003;</strong> {banner}</div>
{info_html}
<h3>Schedule it now? <span style="font-weight:400;color:var(--muted);">(optional)</span></h3>
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
''', extra_css='''
    body { max-width: 480px; padding: 1.5rem; }
    .info { background: var(--tint-accent); border: 1px solid var(--edge-accent);
            color: var(--app-kitchenos); padding: 0.5rem 0.75rem;
            border-radius: var(--radius-box); margin-bottom: 1rem;
            font-size: 14px; }
    h3 { margin-top: 0.5rem; }
    label { display: block; font-weight: 600; margin-bottom: 0.25rem;
            margin-top: 1rem; }
    select { width: 100%; padding: 0.75rem; font-size: 16px;
             border: 1px solid var(--line); border-radius: var(--radius-box);
             background: var(--surface); color: var(--ink);
             -webkit-appearance: none; }
    button { width: 100%; padding: 1rem; font-size: 18px; font-weight: 600;
             background: var(--app-kitchenos); color: var(--text-on-accent);
             border: none; border-radius: var(--radius-box);
             margin-top: 1.5rem; cursor: pointer; }
    .skip { display: block; text-align: center; margin-top: 1rem;
            color: var(--muted); }
''')


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
    html = _serve_page_with_claude_bar('meal_planner.html', [('vault=KitchenOS', f'vault={VAULT_NAME}')])
    return html, 200, {'Content-Type': 'text/html'}


def _current_week(explicit: str | None = None) -> str | None:
    """The requested week, or the current ISO week. None if malformed."""
    if explicit:
        return explicit if re.match(r'^\d{4}-W\d{2}$', explicit) else None
    iso = date.today().isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _render_note_page(subdir: str, week: str, title: str, empty_html: str) -> str:
    """Serve one generated vault note as a phone-readable page.

    These two routes used to 302 to ``obsidian://open?vault=…``, which from a
    phone browser dead-ends or ejects you into another app — so the week's plan
    and its shopping list, the output of the workflow this project is built
    around, could not be read on a phone at all. The Obsidian link is kept as a
    footer for desktop use rather than being the only way in.
    """
    from lib import note_view

    path = paths.vault_root() / subdir / f"{week}.md"
    body = (note_view.render(path.read_text(encoding='utf-8'), week=week)
            if path.exists() else empty_html)
    encoded = quote(f"{subdir}/{week}", safe='')
    obsidian = (f'<a href="obsidian://open?vault={paths.vault_root().name}'
                f'&file={encoded}">Open in Obsidian ›</a>')
    return _serve_page_with_claude_bar('note_view.html', [
        ('<!--TITLE-->', title),
        ('<!--SUB-->', format_week_heading(week)),
        ('<!--BODY-->', body),
        ('<!--OBSIDIAN-->', obsidian),
    ])


@app.route('/current/meal-plan', methods=['GET'])
def current_meal_plan_page():
    """This week's meal plan, rendered for a phone."""
    week = _current_week(request.args.get('week'))
    if not week:
        return error_page("Invalid week format (expected YYYY-WNN)"), 400
    empty = ('<p class="empty">No plan for this week yet.</p>'
             '<p><a class="gen" href="/plan-week?week=' + week + '">'
             'Plan this week ›</a></p>')
    return _render_note_page('Meal Plans', week, 'Meal plan', empty), 200, \
        {'Content-Type': 'text/html'}


@app.route('/current/shopping-list', methods=['GET'])
def current_shopping_list_page():
    """This week's shopping list, rendered for a phone — and generatable from it.

    The only trigger for generating a list was an Obsidian ``kitchenos://``
    button backed by a macOS helper app that no longer exists, so this gives the
    workflow its first trigger that works from the device you shop with.
    """
    week = _current_week(request.args.get('week'))
    if not week:
        return error_page("Invalid week format (expected YYYY-WNN)"), 400
    empty = ('<p class="empty">No shopping list for this week yet.</p>'
             f'<button class="gen" data-week="{week}">Generate shopping list</button>')
    return _render_note_page('Shopping Lists', week, 'Shopping list', empty), 200, \
        {'Content-Type': 'text/html'}


# ----- Meals (composite recipe bundles) -----

def _meal_to_json(meal, macro_cache=None):
    """Serialize a meal, with its macros rolled up from its sub-recipes.

    ``nutrition`` is derived on every read (see lib/meal_nutrition.py) — never
    stored, because per-recipe macros get re-derived by backfill_nutrition.py and
    a stored rollup would go stale invisibly. Pass ``macro_cache`` when
    serializing many meals so shared sub-recipes are read from disk once.
    """
    return {
        "name": meal.name,
        "description": meal.description,
        "tags": list(meal.tags),
        "slot": meal.slot,
        "sub_recipes": [
            {"recipe": s.recipe, "servings": s.servings} for s in meal.sub_recipes
        ],
        "nutrition": meal_nutrition(meal, OBSIDIAN_RECIPES_PATH, macro_cache=macro_cache),
    }


def _parse_sub_recipes(raw):
    """Coerce a client's sub_recipes payload to SubRecipes, or return an error string.

    Strict where ``meal_loader`` is forgiving: a file on disk with a garbage
    ``servings`` normalises quietly (a raise there would make the meal vanish),
    but a *client* sending one should hear about it.
    """
    parsed = []
    for entry in raw:
        if not isinstance(entry, dict) or not entry.get("recipe"):
            continue
        # `raw or 1.0` would be wrong here: 0 is falsy, and 0 is exactly the
        # value this is supposed to reject.
        raw = entry.get("servings")
        if raw is None:
            raw = 1.0
        try:
            servings = float(raw)
        except (TypeError, ValueError):
            return None, f"servings must be a number (got {raw!r})"
        if not math.isfinite(servings) or servings <= 0:
            return None, f"servings must be greater than 0 (got {raw!r})"
        parsed.append(meal_loader.SubRecipe(recipe=str(entry["recipe"]), servings=servings))
    return parsed, None


def _parse_slot(data, default=meal_loader.DEFAULT_SLOT):
    """Validate an optional ``slot`` from a client payload, or return an error string."""
    if "slot" not in data or data.get("slot") is None:
        return default, None
    slot = str(data["slot"]).strip().lower()
    if slot not in SLOT_VOCAB:
        return None, ("slot must be one of "
                      f"{', '.join(SLOT_VOCAB)} (got {data['slot']!r})")
    return slot, None


@app.route('/api/meals', methods=['GET'])
def api_meals_list():
    # One cache across the whole list: meals share sub-recipes, and each rollup
    # otherwise re-reads the same recipe frontmatter.
    macro_cache: dict = {}
    return jsonify({"meals": [
        _meal_to_json(m, macro_cache=macro_cache) for m in meal_loader.list_meals()
    ]})


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
    parsed_subs, err = _parse_sub_recipes(sub_recipes)
    if err:
        return jsonify({"error": err}), 400
    if not parsed_subs:
        return jsonify({"error": "every sub_recipes entry must include a 'recipe' key"}), 400
    slot, err = _parse_slot(data)
    if err:
        return jsonify({"error": err}), 400
    meal = meal_loader.Meal(
        name=name,
        description=data.get("description", ""),
        tags=list(data.get("tags") or []),
        sub_recipes=parsed_subs,
        body=data.get("body", ""),
        slot=slot,
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

    # Validate everything *before* the rename deletes the old file. A 400 raised
    # after the delete would take the meal with it — and there are more ways to
    # 400 now (non-positive servings, unknown slot) than when this was written.
    sub_recipes = data.get("sub_recipes")
    if sub_recipes is None:
        sub_records = existing.sub_recipes
    elif isinstance(sub_recipes, list) and sub_recipes:
        sub_records, err = _parse_sub_recipes(sub_recipes)
        if err:
            return jsonify({"error": err}), 400
        if not sub_records:
            return jsonify({"error": "every sub_recipes entry must include a 'recipe' key"}), 400
    else:
        return jsonify({"error": "sub_recipes must be a non-empty list"}), 400
    slot, err = _parse_slot(data, default=existing.slot)
    if err:
        return jsonify({"error": err}), 400

    if new_name != name:
        # rename: write new file, delete old
        meal_loader.delete_meal(name)
    meal = meal_loader.Meal(
        name=new_name,
        description=data.get("description", existing.description),
        tags=list(data.get("tags") if data.get("tags") is not None else existing.tags),
        sub_recipes=sub_records,
        body=data.get("body", existing.body),
        slot=slot,
    )
    meal_loader.save_meal(meal)
    return jsonify(_meal_to_json(meal))


@app.route('/api/meals/<name>', methods=['DELETE'])
def api_meals_delete(name):
    if not meal_loader.delete_meal(name):
        return jsonify({"error": f"meal '{name}' not found"}), 404
    return jsonify({"status": "deleted", "name": name})


@app.route('/api/macro-targets', methods=['GET'])
def api_macro_targets():
    """Daily macro targets plus how they split across the four meal slots.

    ``daily`` is null when there's no My Macros.md — clients should then show no
    reference line rather than inventing one. ``slot_shares_normalized`` is true
    when the file's own share numbers didn't sum to 1.0 and were rescaled, so the
    UI can say so instead of quietly reinterpreting them.
    """
    from lib.macro_targets import load_macro_targets, load_slot_shares

    vault = paths.vault_root()
    targets = load_macro_targets(vault)
    slot_shares = load_slot_shares(vault)
    return jsonify({
        "daily": None if targets is None else {
            "calories": targets.calories,
            "protein": targets.protein,
            "carbs": targets.carbs,
            "fat": targets.fat,
        },
        "slot_shares": slot_shares.shares,
        "slot_shares_normalized": slot_shares.normalized,
    })


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
    Each at_risk item carries its own coverage-ranked `recipes`; `suggestions`
    is the flat, deduplicated view of the same data. Staples are excluded from
    the at-risk list but count as on-hand; only the actionable expiry window is
    surfaced.

    `limit` caps the flat view. `per_item` caps the recipes shown under each
    item — that is the one the grouped UI actually reads.
    """
    from lib import use_it_up

    limit = request.args.get('limit', type=int) or 10
    per_item = request.args.get('per_item', type=int) or use_it_up.RECIPES_PER_ITEM
    return jsonify(use_it_up.generate(limit=limit, per_item=per_item))


@app.route('/api/cook-now', methods=['GET'])
def api_cook_now():
    """Recipes ranked by how much of what they need is already on hand.

    Returns {recipes: [...]} — see lib/cook_now.generate. Each entry carries a
    `group` (the chip it belongs to); the page filters client-side from this one
    payload, so there is no per-chip round trip and no server-side filtering.
    """
    from lib import cook_now

    limit = request.args.get('limit', type=int)
    if limit is None:
        limit = 30  # absent or unparseable
    elif limit < 0:
        limit = 0  # clamp instead of slicing from the end
    return jsonify(cook_now.generate(limit=limit))


@app.route('/api/cook', methods=['POST'])
@require_token
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
    from lib.storage_locations import place_item

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
        # An explicit one is the caller's stated choice, so it records as manual.
        if raw.get('location'):
            location = normalize_location(raw['location'])
            location_source = 'manual'
        else:
            placement = place_item(name, category)
            location, location_source = placement.location, placement.source
        parsed.append(InventoryItem(
            name=name,
            quantity=quantity,
            unit=(raw.get('unit') or 'ct').strip(),
            category=category,
            location=location,
            location_source=location_source,
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


@app.route('/api/receipt/paste', methods=['POST'])
def api_receipt_paste():
    """Ingest a photographed HEB receipt as pasted schema JSON (preview/commit).

    Body: {json: str, commit?: bool}. The JSON is what the Claude iOS app emits
    from a receipt photo (matching RECEIPT_SCHEMA). commit=false (default)
    dry-runs and returns routed items + reconciliation for confirmation;
    commit=true records the trip + priced purchases + non-fee inventory via the
    shared ``receipt_ingest`` engine. Returns 400 on unparseable JSON.

    The response carries two orthogonal fields: ``mode`` (preview|committed) and
    ``status`` (ingested|needs_review|skipped) from the ingest engine.
    """
    from lib import receipt_ingest

    data = request.get_json(force=True, silent=True) or {}
    text = data.get('json') or data.get('text')
    if not text or not str(text).strip():
        return jsonify({"error": "'json' is required"}), 400

    if data.get('commit'):
        result = receipt_ingest.commit(text)
        if "error" in result:
            return jsonify(result), 400
        return jsonify({"mode": "committed", **result})

    result = receipt_ingest.preview(text)
    if "error" in result:
        return jsonify(result), 400
    return jsonify({"mode": "preview", **result})


@app.route('/api/receipt/prompt', methods=['GET'])
def api_receipt_prompt():
    """The prompt to paste (with a receipt photo) into the Claude iOS app."""
    from prompts.receipt_extraction import build_receipt_photo_prompt

    return build_receipt_photo_prompt(), 200, {'Content-Type': 'text/plain; charset=utf-8'}


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


@app.route('/api/inventory/extend', methods=['POST'])
def api_inventory_extend():
    """Add time to an item's expiry. Body: {name, days, location?}.

    Sets expires = today + days (works on no-expiry items too). Ungated,
    like the sibling add/remove/update routes.
    """
    from lib.inventory import extend_expiry
    from lib.expiry import expiry_status

    data = request.get_json(force=True, silent=True)
    if not data or not data.get('name') or 'days' not in data:
        return jsonify({"error": "'name' and 'days' are required"}), 400
    try:
        days = int(data['days'])
    except (ValueError, TypeError):
        return jsonify({"error": "'days' must be an integer"}), 400

    item = extend_expiry(data['name'], days, data.get('location'))
    if item is None:
        return jsonify({"status": "not_found"}), 404
    d = item.to_dict()
    d["expiry_status"] = expiry_status(d.get("expires"))
    return jsonify({"status": "extended", "item": d})


def _serialize_item(item):
    """An InventoryItem as a dict plus its computed expiry_status."""
    from lib.expiry import expiry_status

    d = item.to_dict()
    d["expiry_status"] = expiry_status(d.get("expires"))
    return d


def _item_response(item, status):
    """Serialize an InventoryItem with computed expiry_status, or 404 if None."""
    if item is None:
        return jsonify({"status": "not_found"}), 404
    return jsonify({"status": status, "item": _serialize_item(item)})


@app.route('/api/inventory/set-expiry', methods=['POST'])
def api_inventory_set_expiry():
    """Set an item's expiry to an absolute date, or clear it.

    Body: {name, expires: "YYYY-MM-DD" | null, location?}. Ungated, like the
    sibling add/remove/update/extend routes.
    """
    from lib.inventory import set_expiry

    data = request.get_json(force=True, silent=True)
    if not data or not data.get('name') or 'expires' not in data:
        return jsonify({"error": "'name' and 'expires' are required"}), 400
    expires = data['expires']
    if expires is not None and not isinstance(expires, str):
        return jsonify({"error": "'expires' must be an ISO date string or null"}), 400

    item = set_expiry(data['name'], expires, data.get('location'))
    return _item_response(item, "expiry_set")


@app.route('/api/inventory/set-category', methods=['POST'])
def api_inventory_set_category():
    """Change an item's category. Body: {name, category, location?}. Ungated."""
    from lib.inventory import set_category

    data = request.get_json(force=True, silent=True)
    if not data or not data.get('name') or not data.get('category'):
        return jsonify({"error": "'name' and 'category' are required"}), 400

    item = set_category(data['name'], data['category'], data.get('location'))
    return _item_response(item, "category_set")


@app.route('/api/inventory/move', methods=['POST'])
def api_inventory_move():
    """Move an item to a new location, merging on collision.

    Body: {name, to_location, location?} where `location` is the current-row
    match filter and `to_location` is the destination. Ungated.
    """
    from lib.inventory import move_item

    data = request.get_json(force=True, silent=True)
    if not data or not data.get('name') or not data.get('to_location'):
        return jsonify({"error": "'name' and 'to_location' are required"}), 400

    item = move_item(data['name'], data['to_location'], data.get('location'))
    return _item_response(item, "moved")


@app.route('/api/inventory/freeze', methods=['POST'])
def api_inventory_freeze():
    """Mark an item as frozen: move to freezer, category=frozen, clear expiry.

    Body: {name, location?}. Ungated.
    """
    from lib.inventory import freeze_item

    data = request.get_json(force=True, silent=True)
    if not data or not data.get('name'):
        return jsonify({"error": "'name' is required"}), 400

    item = freeze_item(data['name'], data.get('location'))
    return _item_response(item, "frozen")


@app.route('/api/inventory/bulk', methods=['POST'])
def api_inventory_bulk():
    """Apply one action to many items in a single write.

    Body: {action, refs, days?, expires?, category?, to_location?} where
    `action` is one of remove | extend | set-expiry | set-category | move |
    freeze, and each ref is {name, unit, location} — the real uniqueness key,
    all three fields required. Ungated, like the sibling /api/inventory/* routes.

    Refs matching nothing come back in `not_found` instead of 404-ing the call:
    the client's list can be stale, and one dead ref must not discard the rest
    of the edits.
    """
    from lib.inventory import bulk_apply

    data = request.get_json(force=True, silent=True) or {}
    if not data.get('action'):
        return jsonify({"error": "'action' is required"}), 400
    refs = data.get('refs')
    if not isinstance(refs, list) or not refs:
        return jsonify({"error": "'refs' must be a non-empty list"}), 400

    params = {k: data[k] for k in ('days', 'expires', 'category', 'to_location')
              if k in data}
    try:
        result = bulk_apply(data['action'], refs, **params)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    return jsonify({
        "status": "applied",
        "applied": result["applied"],
        "items": [_serialize_item(i) for i in result["items"]],
        "removed": [_serialize_item(i) for i in result["removed"]],
        "not_found": result["not_found"],
    })


@app.route('/api/claude-notes', methods=['GET'])
def api_claude_notes_get():
    """Return the shared Claude Notes.md body. Ungated, same-origin widget calls this."""
    from lib.claude_notes import read_notes
    return jsonify({"notes": read_notes()})


@app.route('/api/claude-notes', methods=['POST'])
def api_claude_notes_post():
    """Save the shared Claude Notes.md. Body: {notes: str}. Ungated.

    Returns the normalized body actually stored so the widget can re-sync.
    """
    from lib.claude_notes import read_notes, write_notes

    data = request.get_json(force=True, silent=True)
    if not isinstance(data, dict) or 'notes' not in data:
        return jsonify({"error": "'notes' is required"}), 400
    if not isinstance(data['notes'], str):
        return jsonify({"error": "'notes' must be a string"}), 400

    write_notes(data['notes'])
    return jsonify({"status": "saved", "notes": read_notes()})


@app.route('/api/claude-send', methods=['POST'])
def api_claude_send():
    """Deliver text to Claude. Body: {text: str}. Ungated, like claude-notes.

    Two outcomes, both success:
      - a `ko-claude` session is live  -> injected into it, status "sent"
      - no session                     -> saved as notes, status "queued", and
                                          the next Launch Claude opens with it

    Ungated for the same reason as /api/claude-notes: this is the same-origin
    widget on a tailnet-only server, and both endpoints end at the same place —
    Claude's prompt. Gating one and not the other would be theatre.
    """
    from lib.claude_notes import read_notes, write_notes
    from lib import claude_send

    data = request.get_json(force=True, silent=True)
    if not isinstance(data, dict) or 'text' not in data:
        return jsonify({"error": "'text' is required"}), 400
    if not isinstance(data['text'], str):
        return jsonify({"error": "'text' must be a string"}), 400
    if not data['text'].strip():
        return jsonify({"error": "'text' is empty"}), 400

    # The widget rides on every page, so without this the note loses its subject:
    # "this has a whole greek yogurt, fix it" arrives with no referent for "this".
    message = claude_send.compose(
        data['text'],
        page=str(data.get('page') or ''),
        title=str(data.get('title') or ''),
    )

    if claude_send.send_text(message):
        return jsonify({"status": "sent"})

    write_notes(message)
    return jsonify({"status": "queued", "notes": read_notes()})


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

        implausible_flags = nutrition_quality.implausible(fm)[1]
        rows.append({
            "name": filepath.stem,
            "coverage": coverage,
            "confidence": confidence,
            "calories": fm.get("nutrition_calories"),
            "protein": fm.get("nutrition_protein"),
            "needs_review": bool(needs_review),
            "unmatched": unmatched,
            "flags": implausible_flags,
            "implausibility": nutrition_quality.implausibility_score(fm),
        })

    # Worst-first by how badly the per-serving numbers violate plausible
    # bounds, then by coverage. Sorting on coverage alone put the catastrophes
    # at the *bottom* of the queue built to catch them: every resolution error
    # leaves coverage at 1.0, so a recipe claiming 244 g protein per serving
    # sorted below one that merely failed to match a garnish.
    rows.sort(key=lambda r: (-r["implausibility"], r["coverage"], r["confidence"]))
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


@app.route('/api/recipes/<name>/servings', methods=['POST'])
@require_token
def api_set_servings(name):
    """Set a recipe's servings count and recompute its nutrition per serving.

    This is the fix for the worst ambiguity on a recipe page. The engine derives
    per-serving macros as ``total / servings``; when ``servings`` is missing it
    falls back to 1 and publishes the **whole-batch** total, which the page then
    displays under the same heading as every genuinely per-serving recipe. A
    tray of yogurt pops reads as a 1,339-calorie serving.

    A count typed by a human is a measurement, not an inference, so any
    ``servings_inferred`` / ``servings_needs_review`` flag left by
    ``scripts/backfill_servings.py`` is cleared — the same rule that script uses
    for a yield the recipe states outright.
    """
    from lib import frontmatter

    data = request.get_json(force=True, silent=True) or {}
    raw = data.get("servings")
    try:
        servings = int(raw)
    except (TypeError, ValueError):
        return jsonify({"error": "'servings' must be a whole number"}), 400
    if servings < 1 or servings > 200:
        return jsonify({"error": "'servings' must be between 1 and 200"}), 400

    recipes_dir = paths.recipes_dir()
    filepath = (recipes_dir / f"{name}.md").resolve()
    if not filepath.is_relative_to(recipes_dir.resolve()) or not filepath.exists():
        return jsonify({"error": f"Recipe not found: {name}"}), 404

    create_backup(filepath)
    content = filepath.read_text(encoding="utf-8")
    new = frontmatter.apply(
        content, {"servings": servings},
        ("servings", "servings_inferred", "servings_needs_review"),
        ("servings_inferred", "servings_needs_review"),
    )
    if new is None:
        return jsonify({"error": "Could not update the recipe's frontmatter"}), 500
    filepath.write_text(new, encoding="utf-8")

    # Stored macros were computed against the old servings count, so they are
    # wrong the instant this changes. Recompute rather than leave the page
    # showing batch totals under a now-correct "per serving" label.
    result, error = _recompute_and_write(name)
    if result is None:
        return jsonify({"servings": servings, "nutrition": None,
                        "warning": error or "nutrition could not be recomputed"})
    return jsonify({"servings": servings, **_result_summary(result)})


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
    return _serve_page_with_claude_bar('system_health.html')


@app.route('/nutrition-review', methods=['GET'])
def nutrition_review_page():
    """Human review UI for weak/unresolved nutrition matches."""
    return _serve_page_with_claude_bar('nutrition_review.html')


@app.route('/review')
def review_page():
    """Mobile inventory scan/review page: remove or extend expiry per item."""
    return _serve_page_with_claude_bar('review.html')


@app.route('/cook-now')
def cook_now_page():
    """What you could cook right now, filterable by meal type."""
    return _serve_page_with_claude_bar('cook_now.html')


@app.route('/receipt-paste', methods=['GET'])
def receipt_paste_page():
    """Paste a photographed-receipt JSON (from the Claude app), preview, ingest."""
    return _serve_page_with_claude_bar('receipt_paste.html')


@app.route('/recent', methods=['GET'])
def recent_page():
    """Recipes newest-first by when they arrived — the extraction pipeline's out-tray.

    Ordered by file birth time, not mtime: the nutrition resolver rewrites recipe
    files long after they land, so an mtime ordering would reshuffle this list on
    every backfill and stop meaning "recently added" at all.
    """
    from lib import kitchen_today

    recipes = kitchen_today.recent_recipes()
    newest = recipes[0]["added"] if recipes else None
    sub = (f"{len(recipes)} most recent · newest "
           f"{kitchen_today.arrival_word(newest, date.today()).lower()}"
           if newest else "nothing extracted yet")
    html = _serve_page_with_claude_bar('recent.html', [
        ('<!--SUB-->', sub),
        ('<!--RECENT-->', kitchen_today.render_recent_html(recipes)),
    ])
    return html, 200, {'Content-Type': 'text/html'}


@app.route('/prep', methods=['GET'])
def prep_page():
    """Today's kitchen prep — the panel that used to float on the meal planner.

    Prep is a *today* object; the planner is a *week* screen. It lives here so
    it's reachable from the home page you actually open, and can be pushed to
    Reminders. Unlike the home-page card, this route may regenerate a stale task
    sidecar (an LLM pass) — that cost belongs on the page you opened on purpose.
    """
    from lib import kitchen_today

    prep = kitchen_today.prep_tasks()
    todays, ahead = prep["today"], prep["ahead"]
    undone = [t for t in todays if not t.get("done")]
    if todays:
        sub = (f"{len(undone)} of {len(todays)} left for {prep['day'].lower()}"
               if undone else f"all done for {prep['day'].lower()} 🎉")
    elif ahead:
        sub = f"nothing due today · {len(ahead)} you could pull forward"
    else:
        sub = "nothing planned for this week yet"

    html = _serve_page_with_claude_bar('prep.html', [
        ('<!--SUB-->', sub),
        ('<!--WEEK-->', prep["week"]),
        ('<!--PREP-->', kitchen_today.render_prep_html(prep)),
    ])
    return html, 200, {'Content-Type': 'text/html'}


@app.route('/api/prep/reminders', methods=['POST'])
@require_token
def api_prep_to_reminders():
    """Push prep steps into a Reminders list called 'Prep'.

    A separate list from 'Shopping' on purpose: a grocery run and an afternoon
    of cooking interleaved in one list is neither.

    `scope` is "today" (the default) or "ahead". Today's steps and get-ahead
    steps are never sent together — mixing "do this now" with "you could do this
    for Friday" in one flat list is how a task list stops being trusted.
    """
    from lib import kitchen_today
    from lib.reminders import add_to_reminders

    data = request.get_json(force=True, silent=True) or {}
    scope = "ahead" if data.get("scope") == "ahead" else "today"

    prep = kitchen_today.prep_tasks()
    items = [
        f"{t['text']} — {t['recipe']}" if t.get("recipe") else t.get("text", "")
        for t in prep[scope] if not t.get("done") and t.get("text")
    ]
    if not items:
        return jsonify({"sent": 0, "list": "Prep", "scope": scope})
    try:
        sent = add_to_reminders(items, "Prep")
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502
    return jsonify({"sent": sent, "list": "Prep", "scope": scope})


@app.route('/', methods=['GET'])
def home_page():
    """The web home page: live 'Kitchen Today' cards over the full page registry.

    The cards lead because the home page's job is recall — a list of page names
    can't remind you a feature exists, but "6 recipes need nothing you don't
    have" does. The registry is still here in full, folded into 'All pages', so
    nothing becomes unreachable.
    """
    from lib import kitchen_today, web_dashboard

    today = date.today()
    kicker = f"KitchenOS · {today.strftime('%a %b %-d')}"
    return _serve_page_with_claude_bar('home.html', [
        ('<!--KICKER-->', kicker),
        ('<!--TODAY-->', kitchen_today.render_html()),
        ('<!--SECTIONS-->', web_dashboard.render_html()),
    ])


if __name__ == '__main__':
    try:
        import setproctitle
        setproctitle.setproctitle('kitchenos-api')
    except ImportError:
        pass
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
