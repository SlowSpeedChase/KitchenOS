# Shopping List Buttons Design

## Overview

Add Obsidian buttons to meal plans that generate shopping lists as markdown files, with a button on those lists to send items to Apple Reminders.

## User Flow

```
Meal Plan (Obsidian)
    │
    ▼ [Generate Shopping List] button
    │
API: POST /generate-shopping-list
    │
    ▼ Creates file
    │
Shopping Lists/2026-W04.md
    │
    ▼ User edits list (optional)
    │
    ▼ [Send to Reminders] button
    │
API: POST /send-to-reminders
    │
    ▼ Appends unchecked items
    │
Apple Reminders "Shopping" list
```

## Components

### 1. API Endpoints

Two new endpoints in `api_server.py`:

#### `POST /generate-shopping-list`

Request:
```json
{"week": "2026-W04"}
```

Response:
```json
{
  "success": true,
  "file": "Shopping Lists/2026-W04.md",
  "item_count": 23,
  "recipes": ["lu-rou-fan", "pasta-aglio-e-olio"]
}
```

Behavior:
- Reads meal plan from `Meal Plans/{week}.md`
- Extracts `[[recipe]]` links, loads ingredient tables
- Aggregates ingredients (combines duplicates)
- Writes checklist to `Shopping Lists/{week}.md`
- Overwrites if file exists (regenerating is idempotent)

#### `POST /send-to-reminders`

Request:
```json
{"week": "2026-W04"}
```

Response:
```json
{
  "success": true,
  "items_sent": 18,
  "items_skipped": 5
}
```

Behavior:
- Reads `Shopping Lists/{week}.md`
- Parses checklist, extracts only unchecked `- [ ]` items
- Appends each to Apple Reminders "Shopping" list
- Returns count of sent vs skipped (checked) items

### 2. Shopping List File Format

**Location:** `Shopping Lists/{week}.md`

```markdown
# Shopping List - Week 04

Generated from [[2026-W04|Meal Plan]]

## Items

- [ ] 2 lbs chicken thighs
- [ ] 1 cup soy sauce
- [ ] 3 eggs
- [ ] 1 bunch green onions
- [ ] 2 cups rice

---

```button
name Send to Reminders
type link
action obsidian://kitchenos/send-to-reminders?week=2026-W04
```
```

Features:
- Header links back to meal plan
- Simple checklist format for easy editing
- Items aggregated and sorted alphabetically
- Button at bottom to send to Reminders

### 3. Meal Plan Button

Added to meal plan template, placed at top:

```markdown
# Meal Plan - Week 04 (Jan 19 - Jan 25, 2026)

```button
name Generate Shopping List
type link
action obsidian://kitchenos/generate-shopping-list?week=2026-W04
```

## Monday (Jan 19)
...
```

### 4. URI Scheme Handler

A lightweight macOS app that:
1. Registers `obsidian://kitchenos/...` URI scheme
2. Parses action and parameters from URI
3. Makes HTTP request to `localhost:5001`
4. Shows macOS notification with result

Located at `scripts/kitchenos-uri-handler/`.

## Error Handling

| Scenario | Behavior |
|----------|----------|
| Meal plan doesn't exist | Return error, notification "No meal plan for week W04" |
| No recipes in meal plan | Return error, "No recipes found in meal plan" |
| Recipe file not found | Skip it, continue with others, include warning |
| Shopping list doesn't exist (send) | Return error, "Generate shopping list first" |
| API server not running | Notification "KitchenOS server not running" |
| Reminders permission denied | Return error with instructions |

Error response format:
```json
{
  "success": false,
  "error": "No meal plan found for week 2026-W04"
}
```

## Files to Create/Modify

| File | Change |
|------|--------|
| `api_server.py` | Add two new endpoints |
| `templates/meal_plan_template.py` | Add button to template |
| `templates/shopping_list_template.py` | New - generates list markdown |
| `scripts/kitchenos-uri-handler/` | New - URI scheme handler app |
| `lib/shopping_list_generator.py` | New - core logic extracted from shopping_list.py |

## Dependencies

- Obsidian Buttons plugin (user must install)
- Existing `api_server.py` LaunchAgent running
- Existing ingredient aggregation and Reminders integration

## What Stays the Same

- `shopping_list.py` CLI continues to work
- Existing ingredient aggregation logic reused
- Existing Reminders integration reused
