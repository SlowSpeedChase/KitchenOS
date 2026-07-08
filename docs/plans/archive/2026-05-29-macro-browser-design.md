# Recipe Macro Browser Design

**Date:** 2026-05-29
**Branch:** feat/recipe-button-meal-builder
**Status:** Approved, ready for implementation

---

## Problem

No way to browse all recipes by nutritional content. After the nutrition backfill, 164 recipes now have macro data — need a view to sort and filter them.

---

## Approach: Single `dataviewjs` Obsidian Note

One note at vault root (`Macro Browser.md`) with a single `dataviewjs` code block. Queries the `Recipes/` folder, renders an interactive HTML table with sort and range filters. No extra plugins, no server changes.

---

## Note Location

`{vault_root}/Macro Browser.md`

---

## Columns

| Column | Frontmatter field | Notes |
|--------|------------------|-------|
| Name | `file.name` | Wiki-linked |
| Meal | `meal_occasion` | Array joined with `, ` |
| Servings | `servings` | |
| Calories | `nutrition_calories` | |
| Protein | `nutrition_protein` | g |
| Carbs | `nutrition_carbs` | g |
| Fat | `nutrition_fat` | g |

---

## Interactivity

### Sorting
- Click any column header to cycle: unsorted → descending → ascending
- Active sort column shows ▼ (desc) or ▲ (asc)
- Only one column sorted at a time

### Filtering
- Text search input: filters recipe name (case-insensitive substring)
- Min/max numeric inputs above each macro column (calories, protein, carbs, fat)
- Recipes with `null` nutrition values pass through range filters (shown with `—`)
- Live count: `Showing X of Y recipes` updates on every change

### State
- All state in JS variables inside the `dataviewjs` block
- Table re-renders on every input event

---

## Implementation

Single task: write `Macro Browser.md` to vault root. No Python changes, no API changes, no tests needed (it's a Dataview note).

The `dataviewjs` block:
1. Queries `dv.pages('"Recipes"')` for all recipe files
2. Builds a filter bar (name search + 4 × min/max pairs)
3. Applies filters and sort to the page list
4. Renders an HTML table with styled headers (clickable) and rows
5. Attaches `input` event listeners that re-render on change

Inline CSS handles table styling, sort indicators, and filter bar layout.

---

## Out of Scope

- Server-side API changes
- Per-recipe editing from this view
- Export / download
