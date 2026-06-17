# Home Canvas Dashboard — Design

**Date:** 2026-06-15  
**Status:** Approved

## Problem

The existing `KitchenOS Dashboard.canvas` mixes recipe browsing, meal plans, and shopping lists into one crowded space. There's no dedicated "home screen" for at-a-glance weekly meal context and recipe discovery.

## Goal

A `Home.canvas` with two focused cards:
1. **Weekly Grid** — two-week Kanban-style schedule (Mon–Sun columns, this week on top, next week below)
2. **Discover** — recently added recipes, in-season picks, and quick meals

## Components

### `Dashboards/Weekly Grid.md`

DataviewJS note that:
- Calculates the current and next ISO week numbers from `new Date()`
- Reads `Meal Plans/2026-Wxx.md` for each week
- Parses the markdown: splits on `## Monday` … `## Sunday` headings, extracts content under `### Breakfast`, `### Lunch`, `### Dinner`
- Renders two 7-column tables (Mon–Sun), labeled **This Week** and **Next Week**
- Each cell stacks Breakfast / Lunch / Dinner; wiki links stay clickable
- Empty slots show a faint em-dash — no errors if a meal isn't planned
- Auto-refreshes on note navigation; no script or LaunchAgent needed

### `Dashboards/Discover.md`

Three compact Dataview sections, each capped at 5 results:

| Section | Source | Sort |
|---------|--------|------|
| Recently Added | All recipes, `!contains(file.name, ".recipe")` | `file.mtime DESC` |
| In Season Now | Recipes where `peak_months` includes current month | `file.mtime DESC` |
| Quick Meals | Recipes where `total_time ≤ 30 min` | `file.mtime DESC` |

All titles are clickable wiki links. Sections collapse gracefully when empty.

### `Home.canvas`

New canvas file at vault root. Layout:

```
┌────────────────────────────────────────────────────┐  ┌──────────────────┐
│  Dashboards/Weekly Grid.md  (~900px wide)          │  │  Dashboards/     │
│                                                    │  │  Discover.md     │
│  This Week   Mon Tue Wed Thu Fri Sat Sun           │  │  (~400px wide)   │
│  Next Week   Mon Tue Wed Thu Fri Sat Sun           │  │                  │
└────────────────────────────────────────────────────┘  └──────────────────┘
```

- Weekly Grid: `x=0, y=0, width=900, height=600`
- Discover: `x=940, y=0, width=400, height=600`
- Existing `KitchenOS Dashboard.canvas` left untouched

## Files Created

| File | Type | Notes |
|------|------|-------|
| `Dashboards/Weekly Grid.md` | Vault note | DataviewJS, auto-updating |
| `Dashboards/Discover.md` | Vault note | Dataview + DataviewJS, auto-updating |
| `Home.canvas` | Vault canvas | Embeds both notes, sits at vault root |

## Out of Scope

- Editing meals from the canvas (use the meal planner UI at `/meal-planner`)
- Shopping list card (exists in the current canvas)
- System health card (accessible at `/system-health`)
