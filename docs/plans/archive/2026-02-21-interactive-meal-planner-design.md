# Interactive Meal Planner — Design Document

**Date:** 2026-02-21
**Status:** Approved

## Problem

Meal planning on iPad is painful. The current workflow requires editing raw markdown in Obsidian — typing `[[Recipe Name]]` wikilinks into 21 empty slots per week. This needs to feel like an app, not a text editor.

## Solution

A drag-and-drop meal planner board served as a web page from the existing KitchenOS Flask API server. Accessed via Safari on iPad over Tailscale.

**Approach:** Single HTML file with vanilla JS + SortableJS (CDN) for touch-friendly drag-and-drop. No build tools, no frameworks, no npm. Obsidian markdown files remain the source of truth.

## Architecture

```
iPad Safari → GET /meal-planner?week=2026-W09
                ↓
Flask serves HTML (recipe sidebar + 7-day grid)
                ↓
JS fetches GET /api/recipes + GET /api/meal-plan/2026-W09
                ↓
User drags recipe card → day/meal slot
                ↓
JS calls PUT /api/meal-plan/2026-W09 with updated assignments
                ↓
Flask writes updated markdown to Obsidian vault
```

**No database.** The API reads recipe frontmatter from `.md` files and parses/writes meal plan markdown — same files Obsidian uses.

## UI Layout

Sidebar + Grid layout (landscape iPad):

- **Left sidebar (~30% width):** Recipe list with search bar and filter chips (protein, cuisine, meal_occasion). Recipes displayed as draggable cards.
- **Main area (~70% width):** 7-column grid (Mon–Sun), each column has 3 rows (Breakfast / Lunch / Dinner). Drop zones for recipe cards.
- **Header:** Week label with left/right arrows to navigate weeks.

On portrait/smaller screens: sidebar collapses, toggle button to show/hide.

## Interactions

| Action | Behavior |
|--------|----------|
| **Drag recipe → slot** | Drag card from sidebar onto B/L/D cell. SortableJS handles touch. On drop, JS saves via PUT. |
| **Remove from slot** | Tap X on filled slot. Clears to empty, saves. |
| **Move between slots** | Drag filled slot's card to another slot. |
| **Filter recipes** | Search bar filters by name (live). Filter chips toggle by protein/cuisine/meal_occasion. |
| **Navigate weeks** | Left/right arrows in header. Creates meal plan file if needed. |
| **Servings multiplier** | Tap filled slot to reveal x1/x2/x3 picker (maps to existing `xN` suffix). |

## API Endpoints

Three new endpoints on the existing Flask server:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/meal-planner` | GET | Serve the HTML page. `?week=` param, defaults to current week |
| `/api/recipes` | GET | List all recipes with frontmatter metadata |
| `/api/meal-plan/<week>` | GET | Read current meal plan as JSON |
| `/api/meal-plan/<week>` | PUT | Save updated meal plan assignments |

### `GET /api/recipes` response

```json
[
  {
    "name": "Pasta Aglio E Olio",
    "cuisine": "Italian",
    "protein": "none",
    "meal_occasion": ["weeknight-dinner"],
    "difficulty": "easy"
  }
]
```

Built by scanning all `.md` files in `Recipes/` and parsing YAML frontmatter. Cached in memory (cleared after 5 minutes or on PUT).

### `GET /api/meal-plan/<week>` response

```json
{
  "week": "2026-W09",
  "days": [
    {
      "day": "Monday",
      "date": "2026-02-23",
      "breakfast": null,
      "lunch": {"name": "Pasta Aglio E Olio", "servings": 1},
      "dinner": {"name": "Butter Chicken", "servings": 2}
    }
  ]
}
```

Uses existing `parse_meal_plan()` from `lib/meal_plan_parser.py`.

### `PUT /api/meal-plan/<week>` request

Same structure as GET response. Server rebuilds markdown from JSON and writes to file. Creates file using `generate_meal_plan_markdown()` if it doesn't exist.

## Files to Create/Modify

| File | Action | Purpose |
|------|--------|---------|
| `templates/meal_planner.html` | Create | HTML + CSS + JS for the board UI |
| `api_server.py` | Modify | Add `/meal-planner`, `/api/recipes`, `/api/meal-plan/<week>` routes |
| `lib/meal_plan_parser.py` | Modify | Add `meal_plan_to_markdown()` to rebuild markdown from JSON |
| `lib/recipe_index.py` | Create | Scan recipes folder, parse frontmatter, return metadata list |

## Error Handling

- **Concurrent Obsidian edits:** Last writer wins. Next GET picks up Obsidian changes. Fine for single-user.
- **Missing recipe references:** Show grayed out with name visible.
- **Week doesn't exist:** GET auto-creates from template.
- **Network errors:** Toast notification with retry.
- **Large recipe collection:** Frontmatter parsing cached in memory.

## Out of Scope

- Drag between weeks
- Meal prep / batch cooking features
- Nutritional info on the board
- Undo/redo
- Multi-user / auth
- Recipe creation from the board
- Offline support

## Dependencies

- **SortableJS** (~10KB, CDN) — touch-friendly drag-and-drop
- **PyYAML** (already available via existing recipe parsing) — frontmatter parsing
