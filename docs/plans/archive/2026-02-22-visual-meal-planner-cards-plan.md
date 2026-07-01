# Visual Meal Planner Cards Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add recipe images (background + gradient overlay) and tap-to-open-in-Obsidian to the meal planner's sidebar and grid cards.

**Architecture:** Three layers: (1) `get_recipe_index()` adds an `image` field by checking if `Recipes/Images/{name}.jpg` exists, (2) Flask gets a `/images/<filename>` route to serve images from the vault, (3) meal planner HTML renders cards with `background-image` + gradient overlay and `obsidian://` links on recipe names.

**Tech Stack:** Python/Flask (backend), vanilla HTML/CSS/JS (frontend), SortableJS (existing)

---

### Task 1: Add `image` field to recipe index

**Files:**
- Modify: `lib/recipe_index.py:7-42`
- Test: `tests/test_recipe_index.py`

**Step 1: Write failing test — image field present when image exists**

Add to `tests/test_recipe_index.py`:

```python
def test_includes_image_when_file_exists(self):
    """Should return image filename when matching .jpg exists in Images/."""
    with tempfile.TemporaryDirectory() as tmpdir:
        recipes_dir = Path(tmpdir)
        (recipes_dir / "Butter Chicken.md").write_text(
            '---\ntitle: "Butter Chicken"\ncuisine: "Indian"\n---\n\n# Butter Chicken'
        )
        images_dir = recipes_dir / "Images"
        images_dir.mkdir()
        (images_dir / "Butter Chicken.jpg").write_text("fake image data")

        result = get_recipe_index(recipes_dir)
        assert result[0]["image"] == "Butter Chicken.jpg"
```

**Step 2: Write failing test — image field null when no image**

```python
def test_image_null_when_no_file(self):
    """Should return image: null when no matching image file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        recipes_dir = Path(tmpdir)
        (recipes_dir / "Plain Pasta.md").write_text(
            '---\ntitle: "Plain Pasta"\ncuisine: "Italian"\n---\n\n# Plain Pasta'
        )
        result = get_recipe_index(recipes_dir)
        assert result[0]["image"] is None
```

**Step 3: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_recipe_index.py -v -k "image"`
Expected: FAIL — KeyError or missing `image` field

**Step 4: Implement — add image check to `get_recipe_index()`**

In `lib/recipe_index.py`, after building the `entry` dict (line ~27-37), add image detection:

```python
# Check for matching image file
images_dir = recipes_dir / "Images"
image_file = images_dir / f"{name}.jpg"
entry["image"] = f"{name}.jpg" if image_file.exists() else None
```

**Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_recipe_index.py -v`
Expected: ALL PASS

**Step 6: Commit**

```bash
git add lib/recipe_index.py tests/test_recipe_index.py
git commit -m "feat: add image field to recipe index metadata"
```

---

### Task 2: Add `/images/<filename>` route to API server

**Files:**
- Modify: `api_server.py:205-212` (add route near /api/recipes)
- Test: `tests/test_api_server.py`

**Step 1: Write failing test — serves existing image**

Add to `tests/test_api_server.py`:

```python
class TestServeImages:
    """Tests for GET /images/<filename> endpoint."""

    def test_serves_existing_image(self, tmp_path):
        """Should serve image file from Recipes/Images/ directory."""
        import api_server

        recipes_path = tmp_path / "Recipes"
        images_path = recipes_path / "Images"
        images_path.mkdir(parents=True)
        (images_path / "Test Recipe.jpg").write_bytes(b'\xff\xd8\xff\xe0fake-jpeg')

        with patch.object(api_server, 'OBSIDIAN_RECIPES_PATH', recipes_path):
            with app.test_client() as c:
                response = c.get('/images/Test%20Recipe.jpg')

        assert response.status_code == 200
        assert response.content_type.startswith('image/')

    def test_returns_404_for_missing_image(self, tmp_path):
        """Should return 404 when image doesn't exist."""
        import api_server

        recipes_path = tmp_path / "Recipes"
        images_path = recipes_path / "Images"
        images_path.mkdir(parents=True)

        with patch.object(api_server, 'OBSIDIAN_RECIPES_PATH', recipes_path):
            with app.test_client() as c:
                response = c.get('/images/Missing.jpg')

        assert response.status_code == 404

    def test_blocks_path_traversal(self, tmp_path):
        """Should reject filenames with path traversal."""
        import api_server

        recipes_path = tmp_path / "Recipes"
        (recipes_path / "Images").mkdir(parents=True)

        with patch.object(api_server, 'OBSIDIAN_RECIPES_PATH', recipes_path):
            with app.test_client() as c:
                response = c.get('/images/..%2F..%2Fetc%2Fpasswd')

        assert response.status_code == 404
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_api_server.py::TestServeImages -v`
Expected: FAIL — 404 for all (route doesn't exist)

**Step 3: Implement — add `/images/<filename>` route**

Add to `api_server.py` after the `/api/recipes` route (around line 213):

```python
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
```

**Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_api_server.py::TestServeImages -v`
Expected: ALL PASS

**Step 5: Run full API server test suite**

Run: `.venv/bin/python -m pytest tests/test_api_server.py -v`
Expected: ALL PASS (no regressions)

**Step 6: Commit**

```bash
git add api_server.py tests/test_api_server.py
git commit -m "feat: add /images/ route to serve recipe images"
```

---

### Task 3: Update sidebar recipe cards with images + tap-to-open

**Files:**
- Modify: `templates/meal_planner.html` (CSS + JS)

**Step 1: Add CSS for image-backed recipe cards**

Add these styles to the `<style>` block (after `.recipe-card.hidden` rule, around line 213):

```css
.recipe-card.has-image {
    background-size: cover;
    background-position: center;
    min-height: 100px;
    border: none;
    overflow: hidden;
    position: relative;
}

.recipe-card.has-image::after {
    content: '';
    position: absolute;
    inset: 0;
    background: linear-gradient(transparent 30%, rgba(0, 0, 0, 0.7) 100%);
    border-radius: 10px;
    pointer-events: none;
}

.recipe-card.has-image .recipe-name,
.recipe-card.has-image .recipe-meta {
    position: relative;
    z-index: 1;
    color: #ffffff;
    text-shadow: 0 1px 3px rgba(0, 0, 0, 0.5);
}

.recipe-card.has-image .recipe-meta {
    color: rgba(255, 255, 255, 0.85);
}

.recipe-card .recipe-name-link {
    color: inherit;
    text-decoration: none;
}

.recipe-card .recipe-name-link:active {
    text-decoration: underline;
}
```

**Step 2: Update `renderRecipes()` to show images and add tap-to-open link**

In the `renderRecipes()` function (around line 1000-1039), update the card rendering:

Replace the card innerHTML block with:

```javascript
// Apply background image if available
if (recipe.image) {
    card.classList.add('has-image');
    card.style.backgroundImage = `url(/images/${encodeURIComponent(recipe.image)})`;
}

const obsidianUrl = `obsidian://open?vault=KitchenOS&file=${encodeURIComponent('Recipes/' + recipe.name)}`;

card.innerHTML = `
    <a href="${obsidianUrl}" class="recipe-name recipe-name-link">${escapeHtml(recipe.name)}</a>
    ${metaParts.length ? `<div class="recipe-meta">${escapeHtml(metaParts.join(' \u00b7 '))}</div>` : ''}
`;
```

**Step 3: Test manually in browser**

Open: `http://localhost:5001/meal-planner`
Verify:
- Recipes with images show background image + gradient + white text
- Recipes without images look like before (solid white card)
- Tapping recipe name opens Obsidian to the recipe file
- Dragging still works (drag gesture vs tap are distinct)
- Search and filter chips still work
- Recipe count updates correctly

**Step 4: Commit**

```bash
git add templates/meal_planner.html
git commit -m "feat: add images and tap-to-open to sidebar recipe cards"
```

---

### Task 4: Update grid cards with images + tap-to-open

**Files:**
- Modify: `templates/meal_planner.html` (CSS + JS)

**Step 1: Add CSS for image-backed grid cards**

Add after the sidebar card image styles:

```css
.grid-card.has-image {
    background-size: cover;
    background-position: center;
    border: none;
    overflow: hidden;
    min-height: 60px;
}

.grid-card.has-image::after {
    content: '';
    position: absolute;
    inset: 0;
    background: linear-gradient(transparent 10%, rgba(0, 0, 0, 0.65) 100%);
    border-radius: 8px;
    pointer-events: none;
}

.grid-card.has-image .grid-card-name {
    position: relative;
    z-index: 1;
    color: #ffffff;
    text-shadow: 0 1px 3px rgba(0, 0, 0, 0.5);
}

.grid-card.has-image .remove-btn {
    z-index: 1;
}

.grid-card.has-image .servings-btn {
    z-index: 1;
    background: rgba(0, 0, 0, 0.4);
    border-color: rgba(255, 255, 255, 0.3);
    color: #ffffff;
}

.grid-card .grid-card-name-link {
    color: inherit;
    text-decoration: none;
}

.grid-card .grid-card-name-link:active {
    text-decoration: underline;
}
```

**Step 2: Update `createGridCard()` to use images and add tap-to-open**

In `createGridCard()` (around line 842-884), update to accept and use image data:

Change the function signature and body:

```javascript
function createGridCard(name, servings) {
    const card = document.createElement('div');
    card.className = 'grid-card';
    card.dataset.name = name;
    card.dataset.servings = servings || 1;

    // Find image from recipe data
    const recipe = allRecipes.find(r => r.name === name);
    if (recipe && recipe.image) {
        card.classList.add('has-image');
        card.style.backgroundImage = `url(/images/${encodeURIComponent(recipe.image)})`;
    }

    const obsidianUrl = `obsidian://open?vault=KitchenOS&file=${encodeURIComponent('Recipes/' + name)}`;

    const nameEl = document.createElement('a');
    nameEl.className = 'grid-card-name grid-card-name-link';
    nameEl.href = obsidianUrl;
    nameEl.textContent = name;

    const removeBtn = document.createElement('button');
    removeBtn.className = 'remove-btn';
    removeBtn.innerHTML = '&times;';
    removeBtn.setAttribute('aria-label', 'Remove recipe');
    removeBtn.addEventListener('click', function(e) {
        e.stopPropagation();
        e.preventDefault();
        const parentCell = card.parentElement;
        card.remove();
        updateCellState(parentCell);
        debounceSave();
    });

    const servingsBtn = document.createElement('button');
    servingsBtn.className = 'servings-btn';
    servingsBtn.textContent = `\u00d7${servings || 1}`;
    servingsBtn.setAttribute('aria-label', 'Change servings');
    servingsBtn.addEventListener('click', function(e) {
        e.stopPropagation();
        e.preventDefault();
        let s = parseInt(card.dataset.servings) || 1;
        s = s >= 3 ? 1 : s + 1;
        card.dataset.servings = s;
        servingsBtn.textContent = `\u00d7${s}`;
        debounceSave();
    });

    card.appendChild(nameEl);
    card.appendChild(removeBtn);
    card.appendChild(servingsBtn);

    return card;
}
```

**Step 3: Test manually in browser**

Open: `http://localhost:5001/meal-planner`
Verify:
- Drop a recipe with an image into a grid cell — shows background image
- Drop a recipe without an image — shows plain text card
- Tapping recipe name in grid opens Obsidian
- Remove button works
- Servings button works
- Drag between cells works
- Grid save/load roundtrip works (navigate away and back)

**Step 4: Commit**

```bash
git add templates/meal_planner.html
git commit -m "feat: add images and tap-to-open to grid cards"
```

---

### Task 5: Update CLAUDE.md documentation

**Files:**
- Modify: `CLAUDE.md`

**Step 1: Update "Key Functions" section for recipe_index.py**

In the `lib/recipe_index.py` entry, update the description to mention the image field:

```
- `get_recipe_index()` - Scans recipes folder, returns sorted list of recipe metadata dicts (includes image filename)
```

**Step 2: Update "Endpoints" table**

Add the `/images/<filename>` endpoint:

```
| `/images/<filename>` | GET | Serve recipe image from vault |
```

**Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md with image serving endpoint and recipe index changes"
```
