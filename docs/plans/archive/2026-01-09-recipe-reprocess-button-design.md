# Recipe Reprocess Button Design

## Overview

Add two buttons to each recipe in Obsidian that regenerate the file without leaving the app:

- **Re-extract** - Full pipeline: fetch fresh YouTube data, run through Ollama, regenerate file. Use when the original extraction was wrong or AI prompts have improved.
- **Refresh Template** - Keep existing recipe data, just regenerate markdown with current template. Use after template/formatting updates.

Both buttons:
- Preserve the `## My Notes` section
- Create a backup in `.history/` before overwriting
- Appear in a collapsible callout block (hidden by default)

A daily cleanup job removes backups older than 30 days.

## User Flow

1. Open recipe in Obsidian
2. Expand the "Tools" callout
3. Click "Re-extract" or "Refresh Template"
4. Button triggers local API server
5. File regenerates in place, notes preserved

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Obsidian                                               │
│  ┌───────────────────────────────────────────────────┐  │
│  │  Recipe.md                                        │  │
│  │  > [!tools]- Tools                                │  │
│  │  > ```button                                      │  │
│  │  > name Re-extract                                │  │
│  │  > type link                                      │  │
│  │  > url http://localhost:5001/reprocess?file=...   │  │
│  │  > ```                                            │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│  api_server.py (existing)                               │
│  ├── GET  /reprocess?file=<path>    ← full re-extract   │
│  └── GET  /refresh?file=<path>      ← template only     │
└─────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│  Processing                                             │
│  1. Read file, extract source_url from frontmatter      │
│  2. Extract "My Notes" content                          │
│  3. Create backup in .history/                          │
│  4. Run extraction (full or template-only)              │
│  5. Inject preserved notes into new file                │
│  6. Overwrite original file                             │
└─────────────────────────────────────────────────────────┘
```

## API Endpoints

### `GET /reprocess?file=<filename>`

Full re-extraction pipeline:
1. Parse frontmatter to get `source_url`
2. Extract `## My Notes` content
3. Backup current file to `.history/<filename>.<timestamp>.md`
4. Call `extract_recipe.py` with the YouTube URL
5. Inject preserved notes into regenerated file
6. Return HTML page: "Recipe re-extracted successfully" or error message

### `GET /refresh?file=<filename>`

Template-only refresh:
1. Parse existing frontmatter and body (ingredients, instructions, etc.)
2. Extract `## My Notes` content
3. Backup current file
4. Regenerate markdown using `format_recipe_markdown()` with existing data
5. Inject preserved notes
6. Return HTML page: "Template refreshed successfully" or error message

### Parameter

- `file` - Just the filename (e.g., `pasta-aglio-e-olio.md`), not full path. Server knows the Obsidian vault location.

### Response

Simple HTML page with:
- Green banner for success
- Red banner for error
- Link: "Return to Obsidian" (uses `obsidian://open?vault=KitchenOS`)

## Button Markup

```markdown
---
title: "Pasta Aglio e Olio"
source_url: "https://www.youtube.com/watch?v=bJUiWdM__Qw"
...
---

> [!tools]- Tools
> ```button
> name Re-extract
> type link
> url http://localhost:5001/reprocess?file=pasta-aglio-e-olio.md
> ```
> ```button
> name Refresh Template
> type link
> url http://localhost:5001/refresh?file=pasta-aglio-e-olio.md
> ```

# Pasta Aglio e Olio
...
```

- Collapsed by default (the `-` after `[!tools]`)
- Click to expand, reveals two styled buttons
- Buttons open URL in browser, triggering the API

## Backup & Cleanup

### Backup Location

```
{Obsidian Vault}/Recipes/.history/
├── pasta-aglio-e-olio.2026-01-09T14-30-00.md
├── pasta-aglio-e-olio.2026-01-09T16-45-00.md
└── chicken-tikka-masala.2026-01-08T10-00-00.md
```

### Backup Naming

`<original-filename>.<ISO-timestamp>.md`

The `.history/` folder is inside `Recipes/` to keep backups with the recipes, but the dot-prefix hides it from Obsidian's file browser by default.

### Cleanup

Add to existing `com.kitchenos.mealplan.plist` LaunchAgent (runs daily at 6am):
```bash
find "{vault}/Recipes/.history" -name "*.md" -mtime +30 -delete
```

Deletes backups older than 30 days.

## My Notes Preservation

### Extraction

The `## My Notes` section sits between the heading and the footer (`---\n*Extracted from...`). Use existing `lib/recipe_parser.py` with `extract_my_notes()`.

### Logic

1. Before reprocessing, call `extract_my_notes(file_path)`
2. Returns everything between `## My Notes` and the closing `---`
3. After regeneration, the template outputs a fresh `## My Notes` with placeholder comment
4. Replace the placeholder section with the preserved content
5. If preserved notes were empty (just the comment), keep the fresh placeholder

### Edge Case

If user deleted the `## My Notes` heading entirely, skip preservation and let the template create a fresh one.

## Error Handling

| Error | Response | Recovery |
|-------|----------|----------|
| File not found | "Recipe not found: {filename}" | User checks filename |
| No `source_url` in frontmatter | "Cannot reprocess: no source URL in recipe" | User adds URL manually |
| YouTube video unavailable | "Video unavailable or deleted" | Backup preserved, original unchanged |
| Ollama not running | "Extraction failed: Ollama not responding" | User starts Ollama, retries |
| Backup failed | Abort reprocess, "Could not create backup" | Original file protected |

**Key principle:** Never overwrite the original file unless backup succeeded first.

## Implementation Summary

### Files to Modify

| File | Changes |
|------|---------|
| `api_server.py` | Add `/reprocess` and `/refresh` endpoints |
| `templates/recipe_template.py` | Add Tools callout block with buttons |
| `lib/recipe_parser.py` | Ensure `extract_my_notes()` handles edge cases |
| `lib/backup.py` | Add `cleanup_old_backups()` function |
| `com.kitchenos.mealplan.plist` | Add cleanup command to daily run |

### New Files

None - all functionality fits in existing modules.

### Existing Recipes

Run `migrate_recipes.py` to add the Tools callout block to all existing recipes.

### Dependencies

- User installs Obsidian Buttons plugin (community plugins)

## Testing

1. Install Buttons plugin
2. Restart API server
3. Open a recipe, expand Tools callout
4. Click "Refresh Template" (safer test)
5. Verify file regenerated with notes preserved
6. Click "Re-extract" on a test recipe
7. Verify full re-extraction works
