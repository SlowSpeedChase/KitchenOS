# Visual Meal Planner Cards

**Status:** Approved
**Date:** 2026-02-22

## Problem

The meal planner sidebar shows recipe cards as plain text (name + cuisine/protein). When browsing 156+ recipes to plan a week, it's hard to quickly identify recipes visually. Additionally, there's no way to tap through to the full recipe in Obsidian from the meal planner.

## Solution

Add recipe images and tap-to-open behavior to meal planner cards.

### Changes

#### 1. Backend: Image Serving

**`lib/recipe_index.py`** — Add `image` field to recipe metadata returned by `get_recipe_index()`. Check if `Recipes/Images/{name}.jpg` exists on disk, return the filename or `null`.

**`api_server.py`** — Add `/images/<filename>` route serving files from the Obsidian vault's `Recipes/Images/` directory. Validate filename to prevent path traversal.

#### 2. Sidebar Recipe Cards

Background image with dark gradient overlay:

- `background-image` with `object-fit: cover` on the card
- Bottom gradient: `linear-gradient(transparent, rgba(0,0,0,0.7))`
- Recipe name + meta text rendered in white over the gradient
- Recipes without images: solid subtle background, text-only (current look)
- Tapping recipe name opens `obsidian://open?vault=KitchenOS&file=Recipes/{name}`
- Dragging still works via SortableJS (drag gesture distinct from tap)

#### 3. Grid Cards (Placed Recipes)

Same background-image + overlay style, scaled to fit smaller grid cells. Remove button and servings button overlay on the image. Tapping recipe name opens in Obsidian.

#### 4. No-Image Fallback

Recipes without images render as clean solid cards (similar to current design). No broken image icons or placeholders.

#### 5. Performance

- Images use `loading="lazy"` attribute
- `/api/recipes` returns image filename strings, not image data
- Images loaded as separate HTTP requests only when cards are visible

## Decisions

| Decision | Choice | Reasoning |
|----------|--------|-----------|
| Image serving | Direct file serving via Flask route | Simple, no file duplication, images already web-ready JPEGs |
| Card style | Background image + gradient overlay | Most visual, Pinterest-style browsing experience |
| Grid cards | Same style as sidebar | Consistent look, week grid becomes a visual meal board |
| Tap action | Open in Obsidian via URI scheme | Direct, no intermediate preview needed |
| No-image fallback | Solid card (current look) | Graceful, no visual noise for recipes without images |
