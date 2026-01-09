# Shopping List Buttons Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add Obsidian buttons to generate shopping lists from meal plans and send items to Apple Reminders.

**Architecture:** Two new API endpoints in existing Flask server. URI scheme handler routes `kitchenos://` URLs to API. Shopping lists stored as markdown in vault.

**Tech Stack:** Python/Flask, AppleScript (notifications + Reminders), Obsidian Buttons plugin

---

## Task 1: Create Shopping List Generator Module

Extract reusable logic from `shopping_list.py` into a library module.

**Files:**
- Create: `lib/shopping_list_generator.py`
- Test: `tests/test_shopping_list_generator.py`

**Step 1: Write the failing test**

```python
# tests/test_shopping_list_generator.py
"""Tests for shopping list generator."""

import pytest
from lib.shopping_list_generator import generate_shopping_list


def test_generate_shopping_list_returns_dict():
    """Generator returns structured result."""
    # This will fail - module doesn't exist yet
    result = generate_shopping_list("2026-W04")
    assert isinstance(result, dict)
    assert "items" in result
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_shopping_list_generator.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'lib.shopping_list_generator'"

**Step 3: Write minimal implementation**

```python
# lib/shopping_list_generator.py
"""Shopping list generation from meal plans.

Core logic extracted from shopping_list.py for API use.
"""

import re
from pathlib import Path

from lib.recipe_parser import parse_recipe_file, parse_ingredient_table
from lib.ingredient_aggregator import aggregate_ingredients, format_ingredient

# Configuration
OBSIDIAN_VAULT = Path("/Users/chaseeasterling/Library/Mobile Documents/iCloud~md~obsidian/Documents/KitchenOS")
MEAL_PLANS_PATH = OBSIDIAN_VAULT / "Meal Plans"
RECIPES_PATH = OBSIDIAN_VAULT / "Recipes"
SHOPPING_LISTS_PATH = OBSIDIAN_VAULT / "Shopping Lists"


def parse_week_string(week_str: str) -> Path:
    """Parse a week string like '2026-W04' into a meal plan path.

    Raises:
        ValueError: If format is invalid or file doesn't exist.
    """
    match = re.match(r'^(\d{4})-W(\d{2})$', week_str)
    if not match:
        raise ValueError(f"Invalid week format: {week_str}. Expected: YYYY-WNN")

    filepath = MEAL_PLANS_PATH / f"{week_str}.md"
    if not filepath.exists():
        raise ValueError(f"Meal plan not found: {week_str}")

    return filepath


def extract_recipe_links(meal_plan_path: Path) -> list[str]:
    """Extract [[recipe]] links from meal plan."""
    content = meal_plan_path.read_text(encoding='utf-8')
    return re.findall(r'\[\[([^\]]+)\]\]', content)


def slugify(text: str) -> str:
    """Convert text to slug format."""
    return re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')


def find_recipe_file(recipe_name: str) -> Path | None:
    """Find recipe file by name."""
    exact = RECIPES_PATH / f"{recipe_name}.md"
    if exact.exists():
        return exact

    slug = slugify(recipe_name)
    for file in RECIPES_PATH.glob("*.md"):
        if slugify(file.stem) == slug:
            return file
    return None


def extract_ingredient_table(body: str) -> str:
    """Extract ingredient table from recipe body."""
    pattern = r'##\s+Ingredients\s*\n(.*?)(?=\n##|\Z)'
    match = re.search(pattern, body, re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else ""


def load_recipe_ingredients(recipe_name: str) -> tuple[list[dict], str | None]:
    """Load ingredients from a recipe file.

    Returns:
        Tuple of (ingredients list, warning message or None)
    """
    recipe_file = find_recipe_file(recipe_name)
    if not recipe_file:
        return [], f"Recipe not found: {recipe_name}"

    try:
        content = recipe_file.read_text(encoding='utf-8')
        parsed = parse_recipe_file(content)
        table_text = extract_ingredient_table(parsed['body'])
        if not table_text:
            return [], f"No ingredients table in: {recipe_name}"

        ingredients = parse_ingredient_table(table_text)
        return ingredients, None
    except Exception as e:
        return [], f"Could not parse {recipe_name}: {e}"


def generate_shopping_list(week: str) -> dict:
    """Generate shopping list from meal plan.

    Args:
        week: Week identifier like '2026-W04'

    Returns:
        Dict with keys:
            - success: bool
            - items: list of formatted ingredient strings
            - recipes: list of recipe names found
            - warnings: list of warning messages
            - error: error message (if success=False)
    """
    try:
        meal_plan_path = parse_week_string(week)
    except ValueError as e:
        return {"success": False, "error": str(e)}

    recipe_names = extract_recipe_links(meal_plan_path)
    if not recipe_names:
        return {"success": False, "error": "No recipes found in meal plan"}

    all_ingredients = []
    loaded_recipes = []
    warnings = []

    for name in recipe_names:
        ingredients, warning = load_recipe_ingredients(name)
        if warning:
            warnings.append(warning)
        if ingredients:
            all_ingredients.extend(ingredients)
            loaded_recipes.append(name)

    if not all_ingredients:
        return {
            "success": False,
            "error": "No ingredients found in any recipes",
            "warnings": warnings
        }

    aggregated = aggregate_ingredients(all_ingredients)
    formatted = [format_ingredient(ing) for ing in aggregated]

    return {
        "success": True,
        "items": sorted(formatted),
        "recipes": loaded_recipes,
        "warnings": warnings
    }
```

**Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_shopping_list_generator.py -v`
Expected: PASS

**Step 5: Add more comprehensive tests**

```python
# Add to tests/test_shopping_list_generator.py

def test_parse_week_string_valid():
    """Valid week string returns path."""
    from lib.shopping_list_generator import parse_week_string, MEAL_PLANS_PATH
    # Only works if file exists - this is an integration test
    # Skip if no meal plan exists
    import pytest
    try:
        path = parse_week_string("2026-W04")
        assert path == MEAL_PLANS_PATH / "2026-W04.md"
    except ValueError:
        pytest.skip("No meal plan for 2026-W04")


def test_parse_week_string_invalid_format():
    """Invalid format raises ValueError."""
    from lib.shopping_list_generator import parse_week_string
    import pytest
    with pytest.raises(ValueError, match="Invalid week format"):
        parse_week_string("2026-04")


def test_extract_recipe_links():
    """Extracts wiki links from content."""
    from lib.shopping_list_generator import extract_recipe_links
    from pathlib import Path
    from unittest.mock import patch

    content = "# Meal\n## Monday\n[[pasta]]\n[[salad]]\n"

    with patch.object(Path, 'read_text', return_value=content):
        links = extract_recipe_links(Path("/fake/path.md"))

    assert links == ["pasta", "salad"]


def test_slugify():
    """Slugify converts text to lowercase slug."""
    from lib.shopping_list_generator import slugify
    assert slugify("Pasta Aglio e Olio") == "pasta-aglio-e-olio"
    assert slugify("Lu Rou Fan") == "lu-rou-fan"
```

**Step 6: Run all tests**

Run: `.venv/bin/python -m pytest tests/test_shopping_list_generator.py -v`
Expected: All PASS

**Step 7: Commit**

```bash
git add lib/shopping_list_generator.py tests/test_shopping_list_generator.py
git commit -m "feat: add shopping list generator module"
```

---

## Task 2: Create Shopping List Template

Generate markdown format for shopping list files.

**Files:**
- Create: `templates/shopping_list_template.py`
- Test: `tests/test_shopping_list_template.py`

**Step 1: Write the failing test**

```python
# tests/test_shopping_list_template.py
"""Tests for shopping list template."""

from templates.shopping_list_template import generate_shopping_list_markdown


def test_generates_markdown_with_header():
    """Template includes week in header."""
    result = generate_shopping_list_markdown(
        week="2026-W04",
        items=["2 lbs chicken", "1 cup rice"]
    )
    assert "# Shopping List - Week 04" in result
    assert "[[2026-W04|Meal Plan]]" in result
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_shopping_list_template.py -v`
Expected: FAIL with "ModuleNotFoundError"

**Step 3: Write implementation**

```python
# templates/shopping_list_template.py
"""Shopping list template generation.

Creates markdown shopping list files with checkboxes and send button.
"""

import re


def generate_shopping_list_markdown(week: str, items: list[str]) -> str:
    """Generate shopping list markdown.

    Args:
        week: Week identifier like '2026-W04'
        items: List of formatted ingredient strings

    Returns:
        Formatted markdown string
    """
    # Extract week number for display
    match = re.match(r'\d{4}-W(\d{2})', week)
    week_num = int(match.group(1)) if match else 0

    lines = [
        f"# Shopping List - Week {week_num:02d}",
        "",
        f"Generated from [[{week}|Meal Plan]]",
        "",
        "## Items",
        "",
    ]

    # Add checklist items
    for item in items:
        lines.append(f"- [ ] {item}")

    # Add button
    lines.extend([
        "",
        "---",
        "",
        "```button",
        "name Send to Reminders",
        "type link",
        f"action kitchenos://send-to-reminders?week={week}",
        "```",
        "",
    ])

    return '\n'.join(lines)


def generate_filename(week: str) -> str:
    """Generate filename for shopping list.

    Args:
        week: Week identifier like '2026-W04'

    Returns:
        Filename like '2026-W04.md'
    """
    return f"{week}.md"
```

**Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_shopping_list_template.py -v`
Expected: PASS

**Step 5: Add more tests**

```python
# Add to tests/test_shopping_list_template.py

def test_generates_checklist_items():
    """Template creates checkbox items."""
    result = generate_shopping_list_markdown(
        week="2026-W04",
        items=["chicken", "rice"]
    )
    assert "- [ ] chicken" in result
    assert "- [ ] rice" in result


def test_includes_send_button():
    """Template includes button with correct week."""
    result = generate_shopping_list_markdown(
        week="2026-W04",
        items=["item"]
    )
    assert "```button" in result
    assert "Send to Reminders" in result
    assert "kitchenos://send-to-reminders?week=2026-W04" in result


def test_generate_filename():
    """Filename uses week identifier."""
    from templates.shopping_list_template import generate_filename
    assert generate_filename("2026-W04") == "2026-W04.md"
```

**Step 6: Run all tests**

Run: `.venv/bin/python -m pytest tests/test_shopping_list_template.py -v`
Expected: All PASS

**Step 7: Commit**

```bash
git add templates/shopping_list_template.py tests/test_shopping_list_template.py
git commit -m "feat: add shopping list template"
```

---

## Task 3: Add Generate Shopping List Endpoint

Add `/generate-shopping-list` endpoint to API server.

**Files:**
- Modify: `api_server.py`
- Test: `tests/test_api_endpoints.py`

**Step 1: Write the failing test**

```python
# tests/test_api_endpoints.py
"""Tests for API endpoints."""

import pytest
from api_server import app


@pytest.fixture
def client():
    """Create test client."""
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


def test_generate_shopping_list_requires_week(client):
    """Endpoint requires week parameter."""
    response = client.post('/generate-shopping-list', json={})
    assert response.status_code == 400
    data = response.get_json()
    assert "week" in data.get("error", "").lower()
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_api_endpoints.py::test_generate_shopping_list_requires_week -v`
Expected: FAIL with 404 (endpoint doesn't exist)

**Step 3: Add endpoint to api_server.py**

Add these imports at top of `api_server.py`:

```python
from lib.shopping_list_generator import generate_shopping_list, SHOPPING_LISTS_PATH
from templates.shopping_list_template import generate_shopping_list_markdown, generate_filename as shopping_list_filename
```

Add endpoint after `/extract`:

```python
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

    # Create markdown content
    markdown = generate_shopping_list_markdown(week, result['items'])

    # Ensure Shopping Lists folder exists
    SHOPPING_LISTS_PATH.mkdir(parents=True, exist_ok=True)

    # Write file
    filename = shopping_list_filename(week)
    filepath = SHOPPING_LISTS_PATH / filename
    filepath.write_text(markdown, encoding='utf-8')

    return jsonify({
        'success': True,
        'file': f"Shopping Lists/{filename}",
        'item_count': len(result['items']),
        'recipes': result['recipes'],
        'warnings': result.get('warnings', [])
    })
```

**Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_api_endpoints.py::test_generate_shopping_list_requires_week -v`
Expected: PASS

**Step 5: Add success case test**

```python
# Add to tests/test_api_endpoints.py

def test_generate_shopping_list_invalid_week(client):
    """Invalid week format returns error."""
    response = client.post('/generate-shopping-list', json={'week': 'invalid'})
    assert response.status_code == 400
    data = response.get_json()
    assert data['success'] is False
```

**Step 6: Run tests**

Run: `.venv/bin/python -m pytest tests/test_api_endpoints.py -v`
Expected: All PASS

**Step 7: Commit**

```bash
git add api_server.py tests/test_api_endpoints.py
git commit -m "feat: add /generate-shopping-list endpoint"
```

---

## Task 4: Add Send to Reminders Endpoint

Add `/send-to-reminders` endpoint to API server.

**Files:**
- Modify: `api_server.py`
- Modify: `tests/test_api_endpoints.py`

**Step 1: Write the failing test**

```python
# Add to tests/test_api_endpoints.py

def test_send_to_reminders_requires_week(client):
    """Endpoint requires week parameter."""
    response = client.post('/send-to-reminders', json={})
    assert response.status_code == 400
    data = response.get_json()
    assert "week" in data.get("error", "").lower()
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_api_endpoints.py::test_send_to_reminders_requires_week -v`
Expected: FAIL with 404

**Step 3: Add helper function to parse shopping list**

Add to `lib/shopping_list_generator.py`:

```python
def parse_shopping_list_file(week: str) -> dict:
    """Parse shopping list file and extract unchecked items.

    Args:
        week: Week identifier like '2026-W04'

    Returns:
        Dict with keys:
            - success: bool
            - items: list of unchecked item strings
            - skipped: count of checked items
            - error: error message (if success=False)
    """
    filepath = SHOPPING_LISTS_PATH / f"{week}.md"

    if not filepath.exists():
        return {"success": False, "error": f"Shopping list not found: {week}. Generate it first."}

    content = filepath.read_text(encoding='utf-8')

    unchecked = []
    checked_count = 0

    for line in content.split('\n'):
        # Match unchecked: - [ ] item
        if re.match(r'^- \[ \] ', line):
            item = line[6:].strip()  # Remove "- [ ] " prefix
            if item:
                unchecked.append(item)
        # Match checked: - [x] item
        elif re.match(r'^- \[x\] ', line, re.IGNORECASE):
            checked_count += 1

    return {
        "success": True,
        "items": unchecked,
        "skipped": checked_count
    }
```

**Step 4: Add endpoint to api_server.py**

Update imports:

```python
from lib.shopping_list_generator import generate_shopping_list, parse_shopping_list_file, SHOPPING_LISTS_PATH
```

Add endpoint:

```python
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
```

**Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_api_endpoints.py::test_send_to_reminders_requires_week -v`
Expected: PASS

**Step 6: Add test for parse function**

```python
# Add to tests/test_shopping_list_generator.py

def test_parse_shopping_list_extracts_unchecked():
    """Parser extracts only unchecked items."""
    from lib.shopping_list_generator import parse_shopping_list_file, SHOPPING_LISTS_PATH
    from pathlib import Path
    from unittest.mock import patch

    content = """# Shopping List
- [ ] chicken
- [x] rice
- [ ] onions
"""

    with patch.object(Path, 'exists', return_value=True):
        with patch.object(Path, 'read_text', return_value=content):
            result = parse_shopping_list_file("2026-W04")

    assert result['success'] is True
    assert result['items'] == ['chicken', 'onions']
    assert result['skipped'] == 1
```

**Step 7: Commit**

```bash
git add api_server.py lib/shopping_list_generator.py tests/
git commit -m "feat: add /send-to-reminders endpoint"
```

---

## Task 5: Update Meal Plan Template with Button

Add the generate button to new meal plans.

**Files:**
- Modify: `templates/meal_plan_template.py`
- Modify: `tests/test_meal_plan_template.py` (if exists, otherwise create)

**Step 1: Write the failing test**

```python
# tests/test_meal_plan_template.py
"""Tests for meal plan template."""

from templates.meal_plan_template import generate_meal_plan_markdown


def test_includes_generate_button():
    """Template includes shopping list button."""
    result = generate_meal_plan_markdown(2026, 4)
    assert "```button" in result
    assert "Generate Shopping List" in result
    assert "kitchenos://generate-shopping-list?week=2026-W04" in result
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_meal_plan_template.py::test_includes_generate_button -v`
Expected: FAIL (no button in output)

**Step 3: Update meal_plan_template.py**

Modify `generate_meal_plan_markdown` function:

```python
def generate_meal_plan_markdown(year: int, week: int) -> str:
    """Generate a meal plan markdown file for a given week.

    Args:
        year: ISO year
        week: ISO week number

    Returns:
        Formatted markdown string
    """
    start_date, end_date = get_week_date_range(year, week)
    week_id = f"{year}-W{week:02d}"

    lines = [
        f"# Meal Plan - Week {week:02d} ({format_date_short(start_date)} - {format_date_short(end_date)}, {year})",
        "",
        "```button",
        "name Generate Shopping List",
        "type link",
        f"action kitchenos://generate-shopping-list?week={week_id}",
        "```",
        "",
    ]

    for i, day in enumerate(DAYS_OF_WEEK):
        day_date = start_date + timedelta(days=i)
        lines.extend([
            f"## {day} ({format_date_short(day_date)})",
            "### Breakfast",
            "",
            "### Lunch",
            "",
            "### Dinner",
            "",
            "### Notes",
            "",
            "",
        ])

    return '\n'.join(lines)
```

**Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_meal_plan_template.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add templates/meal_plan_template.py tests/test_meal_plan_template.py
git commit -m "feat: add shopping list button to meal plan template"
```

---

## Task 6: Create URI Scheme Handler

Create macOS app to handle `kitchenos://` URIs.

**Files:**
- Create: `scripts/kitchenos-uri-handler/handler.sh`
- Create: `scripts/kitchenos-uri-handler/KitchenOSHandler.app/` (Automator app)
- Create: `scripts/kitchenos-uri-handler/README.md`

**Step 1: Create handler shell script**

```bash
# scripts/kitchenos-uri-handler/handler.sh
#!/bin/bash
# KitchenOS URI Handler
# Handles kitchenos:// URLs and calls the local API server

set -e

URI="$1"
API_BASE="http://localhost:5001"

# Parse the URI: kitchenos://action?param=value
ACTION=$(echo "$URI" | sed -E 's|kitchenos://([^?]+).*|\1|')
QUERY=$(echo "$URI" | sed -E 's|.*\?(.*)|\1|')

# Extract week parameter
WEEK=$(echo "$QUERY" | sed -E 's|.*week=([^&]+).*|\1|')

# Function to show notification
notify() {
    local title="$1"
    local message="$2"
    osascript -e "display notification \"$message\" with title \"$title\""
}

# Check if API server is running
if ! curl -s "$API_BASE/health" > /dev/null 2>&1; then
    notify "KitchenOS" "Server not running. Start it first."
    exit 1
fi

case "$ACTION" in
    "generate-shopping-list")
        RESPONSE=$(curl -s -X POST "$API_BASE/generate-shopping-list" \
            -H "Content-Type: application/json" \
            -d "{\"week\": \"$WEEK\"}")

        SUCCESS=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('success', False))")

        if [ "$SUCCESS" = "True" ]; then
            COUNT=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('item_count', 0))")
            notify "KitchenOS" "Shopping list created with $COUNT items"
        else
            ERROR=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('error', 'Unknown error'))")
            notify "KitchenOS Error" "$ERROR"
        fi
        ;;

    "send-to-reminders")
        RESPONSE=$(curl -s -X POST "$API_BASE/send-to-reminders" \
            -H "Content-Type: application/json" \
            -d "{\"week\": \"$WEEK\"}")

        SUCCESS=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('success', False))")

        if [ "$SUCCESS" = "True" ]; then
            SENT=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('items_sent', 0))")
            SKIPPED=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('items_skipped', 0))")
            notify "KitchenOS" "Sent $SENT items to Reminders ($SKIPPED already checked)"
        else
            ERROR=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('error', 'Unknown error'))")
            notify "KitchenOS Error" "$ERROR"
        fi
        ;;

    *)
        notify "KitchenOS Error" "Unknown action: $ACTION"
        exit 1
        ;;
esac
```

**Step 2: Make executable**

Run: `chmod +x scripts/kitchenos-uri-handler/handler.sh`

**Step 3: Create Automator app**

This must be done manually via Automator:

1. Open Automator
2. Create new "Application"
3. Add "Run Shell Script" action
4. Set shell to `/bin/bash`
5. Set "Pass input" to "as arguments"
6. Add script content:
   ```bash
   /Users/chaseeasterling/KitchenOS/scripts/kitchenos-uri-handler/handler.sh "$1"
   ```
7. Save as `KitchenOSHandler.app` in `scripts/kitchenos-uri-handler/`
8. Edit `Info.plist` inside app bundle to add URL scheme

**Step 4: Add URL scheme to Info.plist**

Add to `KitchenOSHandler.app/Contents/Info.plist`:

```xml
<key>CFBundleURLTypes</key>
<array>
    <dict>
        <key>CFBundleURLName</key>
        <string>KitchenOS Handler</string>
        <key>CFBundleURLSchemes</key>
        <array>
            <string>kitchenos</string>
        </array>
    </dict>
</array>
```

**Step 5: Create README**

```markdown
# KitchenOS URI Handler

Handles `kitchenos://` URLs from Obsidian buttons.

## Installation

1. Copy `KitchenOSHandler.app` to `/Applications/` or `~/Applications/`
2. Double-click to register the URL scheme
3. macOS may ask to allow the app - click Open

## Testing

Run in terminal:
```bash
open "kitchenos://generate-shopping-list?week=2026-W04"
```

## Supported URLs

- `kitchenos://generate-shopping-list?week=YYYY-WNN`
- `kitchenos://send-to-reminders?week=YYYY-WNN`
```

**Step 6: Commit**

```bash
git add scripts/kitchenos-uri-handler/
git commit -m "feat: add URI scheme handler for Obsidian buttons"
```

---

## Task 7: Create Shopping Lists Folder

Ensure the Shopping Lists folder exists in the vault.

**Files:**
- Create: `{Obsidian Vault}/Shopping Lists/.gitkeep` (optional marker)

**Step 1: Create folder**

Run: `mkdir -p "/Users/chaseeasterling/Library/Mobile Documents/iCloud~md~obsidian/Documents/KitchenOS/Shopping Lists"`

**Step 2: Verify**

Run: `ls -la "/Users/chaseeasterling/Library/Mobile Documents/iCloud~md~obsidian/Documents/KitchenOS/Shopping Lists"`

**Step 3: Note**

The API endpoint also creates this folder if missing, but having it exist makes the vault structure clearer.

---

## Task 8: Migrate Existing Meal Plans

Add button to existing meal plan files.

**Files:**
- Modify: Existing meal plans in vault

**Step 1: Create migration script**

```python
# scripts/add_button_to_meal_plans.py
#!/usr/bin/env python3
"""Add shopping list button to existing meal plans."""

import re
from pathlib import Path

VAULT = Path("/Users/chaseeasterling/Library/Mobile Documents/iCloud~md~obsidian/Documents/KitchenOS")
MEAL_PLANS = VAULT / "Meal Plans"

BUTTON_TEMPLATE = '''```button
name Generate Shopping List
type link
action kitchenos://generate-shopping-list?week={week}
```

'''

def add_button_to_meal_plan(filepath: Path) -> bool:
    """Add button to meal plan if not present.

    Returns True if modified, False if already has button.
    """
    content = filepath.read_text(encoding='utf-8')

    # Skip if already has button
    if '```button' in content:
        return False

    # Extract week from filename (2026-W04.md -> 2026-W04)
    week = filepath.stem

    # Insert button after first heading
    lines = content.split('\n')
    new_lines = []
    button_inserted = False

    for i, line in enumerate(lines):
        new_lines.append(line)
        # Insert after the # heading line and blank line
        if not button_inserted and line.startswith('# Meal Plan'):
            new_lines.append('')
            new_lines.append(BUTTON_TEMPLATE.format(week=week).rstrip())
            button_inserted = True

    if button_inserted:
        filepath.write_text('\n'.join(new_lines), encoding='utf-8')
        return True
    return False


def main():
    for filepath in MEAL_PLANS.glob("*.md"):
        if add_button_to_meal_plan(filepath):
            print(f"Updated: {filepath.name}")
        else:
            print(f"Skipped: {filepath.name} (already has button)")


if __name__ == "__main__":
    main()
```

**Step 2: Run migration**

Run: `.venv/bin/python scripts/add_button_to_meal_plans.py`

**Step 3: Verify**

Check a meal plan file in Obsidian to confirm button appears.

**Step 4: Commit migration script**

```bash
git add scripts/add_button_to_meal_plans.py
git commit -m "feat: add migration script for meal plan buttons"
```

---

## Task 9: Update Documentation

Update CLAUDE.md with new endpoints and scripts.

**Files:**
- Modify: `CLAUDE.md`

**Step 1: Add to Architecture section**

Under "Core Components" table, add:

| File | Purpose |
|------|---------|
| `lib/shopping_list_generator.py` | Core logic for generating shopping lists from meal plans |
| `templates/shopping_list_template.py` | Markdown template for shopping list files |
| `scripts/kitchenos-uri-handler/` | macOS URI scheme handler for Obsidian buttons |

**Step 2: Add API endpoints table**

Under "API Server" section, update endpoints table:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/generate-shopping-list` | POST | Generate shopping list markdown from meal plan |
| `/send-to-reminders` | POST | Send unchecked items to Apple Reminders |

**Step 3: Add usage section**

Under "Running Commands", add:

```markdown
### Generate Shopping List (API)

The Obsidian button calls this endpoint, but you can also test directly:

```bash
curl -X POST http://localhost:5001/generate-shopping-list \
  -H "Content-Type: application/json" \
  -d '{"week": "2026-W04"}'
```

### Send to Reminders (API)

```bash
curl -X POST http://localhost:5001/send-to-reminders \
  -H "Content-Type: application/json" \
  -d '{"week": "2026-W04"}'
```
```

**Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add shopping list button documentation"
```

---

## Task 10: End-to-End Test

Manually verify the complete flow.

**Steps:**

1. Ensure API server is running: `curl http://localhost:5001/health`
2. Ensure Obsidian Buttons plugin is installed
3. Open a meal plan with recipes in Obsidian
4. Click "Generate Shopping List" button
5. Verify notification appears
6. Verify `Shopping Lists/2026-W04.md` was created
7. Open shopping list, check a few items
8. Click "Send to Reminders" button
9. Verify notification shows correct counts
10. Open Reminders app, verify items in "Shopping" list

**Final commit:**

```bash
git add -A
git commit -m "feat: complete shopping list buttons feature"
```

---

## Summary

| Task | Description | Est. Complexity |
|------|-------------|-----------------|
| 1 | Shopping list generator module | Medium |
| 2 | Shopping list template | Simple |
| 3 | /generate-shopping-list endpoint | Medium |
| 4 | /send-to-reminders endpoint | Medium |
| 5 | Meal plan template button | Simple |
| 6 | URI scheme handler | Complex |
| 7 | Create Shopping Lists folder | Simple |
| 8 | Migrate existing meal plans | Simple |
| 9 | Update documentation | Simple |
| 10 | End-to-end test | Manual |

**Dependencies:**
- Task 1 must complete before Tasks 3, 4
- Task 2 must complete before Task 3
- Task 6 must complete before Task 10
- Task 5 should complete before Task 8
