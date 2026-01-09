# Recipe Dashboard Design

## Overview

An Obsidian dashboard using Dataview to navigate the recipe vault. Provides quick access to recent recipes, filtered views, and browsing by cuisine.

## Requirements

- **Primary view:** Recent additions (last 10 recipes)
- **Filtered tables:** Quick meals (<30 min), needs review
- **Browse by category:** Auto-generated cuisine sections
- **Table columns:** Title (linked), cuisine, protein, difficulty, total time

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Hero section | Recent additions | Growing collection - see what's new |
| Cuisine browsing | DataviewJS auto-generated | No maintenance when new cuisines added |
| Collapsible sections | No (always visible) | Dataview can't dynamically create HTML details |
| .recipe.md files | Filtered out | These are RecipeMD exports, not primary files |

## Dashboard Structure

```
# Recipe Dashboard

## Recent Additions        <- Last 10 recipes, sorted by date_added DESC
## Quick Meals             <- total_time <= 30 minutes
## Needs Review            <- needs_review = true, shows confidence_notes
## Browse by Cuisine       <- Auto-grouped by cuisine field
```

## Dataview Queries

### Recent Additions

```dataview
TABLE WITHOUT ID
  link(file.name, title) AS "Recipe",
  cuisine AS "Cuisine",
  protein AS "Protein",
  difficulty AS "Difficulty",
  total_time AS "Time"
FROM "Recipes"
WHERE !contains(file.name, ".recipe")
  AND file.name != "Dashboard"
SORT date_added DESC
LIMIT 10
```

### Quick Meals

```dataview
TABLE WITHOUT ID
  link(file.name, title) AS "Recipe",
  cuisine AS "Cuisine",
  protein AS "Protein",
  total_time AS "Time"
FROM "Recipes"
WHERE total_time != null
  AND !contains(file.name, ".recipe")
  AND number(replace(total_time, " minutes", "")) <= 30
SORT total_time ASC
```

### Needs Review

```dataview
TABLE WITHOUT ID
  link(file.name, title) AS "Recipe",
  cuisine AS "Cuisine",
  confidence_notes AS "Issue"
FROM "Recipes"
WHERE needs_review = true
  AND !contains(file.name, ".recipe")
SORT date_added DESC
```

### Browse by Cuisine (DataviewJS)

```dataviewjs
const cuisines = dv.pages('"Recipes"')
  .where(p => p.cuisine && !p.file.name.includes(".recipe"))
  .groupBy(p => p.cuisine)
  .sort(g => g.key, 'asc');

for (let group of cuisines) {
  dv.header(4, `${group.key} (${group.rows.length})`);
  dv.table(
    ["Recipe", "Protein", "Difficulty", "Time"],
    group.rows.map(p => [p.file.link, p.protein, p.difficulty, p.total_time])
  );
}
```

## Dependencies

- Dataview plugin (community plugin)
- DataviewJS enabled in Dataview settings

## File Location

`Recipes/Dashboard.md` in the Obsidian vault

## Future Enhancements

- Add "By Protein" section if collection grows
- Add search/filter input (requires Dataview + Buttons or Meta Bind plugin)
- Add meal planning section with checkboxes
