# Recipe Update System Design

**Date**: 2026-01-07
**Status**: Approved
**Purpose**: Enable updating existing recipe files when re-extracting or migrating templates, without duplicating files or losing user content.

## Problem Statement

Currently, KitchenOS creates a new recipe file each time `extract_recipe.py` runs. This causes issues when:

1. **Re-extracting a video**: Running the script on a video you've already extracted creates a duplicate file.
2. **Template changes**: Adding new frontmatter fields or restructuring sections leaves existing recipes outdated.

Users also make manual edits to recipes (fixing AI errors, adding personal notes) that should not be lost during updates.

## Design Goals

- Detect existing recipes and update in place instead of duplicating
- Preserve user-added content during updates
- Provide a safety net for recovering overwritten content
- Enable bulk migration of existing recipes to new template structure
- Keep the system simple and predictable

## Solution Overview

### Two Capabilities

1. **Smart Re-extraction**: `extract_recipe.py` detects existing recipes by video ID and updates them instead of creating duplicates.

2. **Template Migrations**: `migrate_recipes.py` applies schema changes to all existing recipes without re-fetching from YouTube.

### Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Preserve user content | "My Notes" protected section | Simple mental model: user content goes in one place |
| Handle manual fixes | Backup before overwrite | Safety net without adding friction to normal workflow |
| New fields on migration | Add as `null` | Fast, no network calls, avoids unexpected content changes |
| Identify duplicates | Match video ID in `source_url` | Already stored in frontmatter, reliable identifier |
| Backup location | `.history/` inside Recipes | Syncs with vault, hidden in Obsidian, easy to find |

## Detailed Design

### 1. Duplicate Detection

When `extract_recipe.py` runs, it scans all `.md` files in the Recipes folder and extracts the `source_url` from frontmatter. If a file's URL contains the same video ID as the input URL, that file is marked for update instead of creating a new one.

```
Run extract_recipe.py with URL
         ↓
Scan Recipes folder for matching video ID
         ↓
    ┌────┴────┐
    │ Found?  │
    └────┬────┘
   No    │    Yes
    ↓    │     ↓
Create   │   Backup existing file
new file │     ↓
         │   Extract "My Notes" section
         │     ↓
         │   Generate fresh content from YouTube
         │     ↓
         │   Append preserved "My Notes"
         │     ↓
         │   Overwrite file
```

### 2. Protected "My Notes" Section

Every recipe includes a `## My Notes` section at the bottom. This section acts as a boundary marker:

- **Above the heading**: AI-generated content, replaceable on re-extraction
- **Below the heading**: User content, never modified by the system

Template addition to `recipe_template.py`:

```markdown
## My Notes

<!-- Your personal notes, ratings, and modifications go here -->
```

Rules:
- If a recipe has no "My Notes" section, updates append an empty one
- If multiple "My Notes" headings exist, use the first one as the boundary
- Empty sections are fine and expected for most recipes

### 3. Backup System

Before any file is overwritten (re-extraction or migration), a backup is created:

**Location**: `Recipes/.history/`

**Naming**: `{original-filename}_{ISO-timestamp}.md`

**Example**: `.history/2026-01-07-pasta-aglio-e-olio_2026-01-08T14-30-00.md`

**Behavior**:
- If backup creation fails, abort the update entirely
- Never overwrite without a successful backup
- Old backups are retained indefinitely (user can clean up manually)

**Why `.history/` inside Recipes?**
- Syncs via iCloud with the vault
- Hidden in Obsidian (dot-prefix folders are ignored by default)
- Easy to find when recovery is needed
- Excludable from Dataview: `WHERE !contains(file.path, ".history")`

### 4. Template Migrations

**Command**:
```bash
.venv/bin/python migrate_recipes.py
.venv/bin/python migrate_recipes.py --dry-run
```

**Process**:
1. Scan all `.md` files in Recipes folder
2. For each file:
   - Create backup in `.history/`
   - Parse frontmatter and content
   - Add missing frontmatter fields with `null` values
   - Apply structural changes (section renames)
   - Preserve "My Notes" section
   - Write updated file

**Schema Definition** (in `templates/recipe_template.py`):

```python
RECIPE_SCHEMA = {
    "title": str,
    "source_url": str,
    "source_channel": str,
    "date_added": str,
    "prep_time": str,
    "cook_time": str,
    "servings": int,
    "difficulty": str,
    "cuisine": str,
    "protein": str,
    "dish_type": str,
    "dietary": list,
    "equipment": list,
    "needs_review": bool,
}
```

**Migration Logic**:
- Field in schema but missing from file → add with `null`
- Field in file but not in schema → leave alone (no data loss)
- Field exists in both → keep existing value

**Structural Changes** (explicit transformations):

```python
SECTION_RENAMES = {
    "Storage": "Storing & Reheating",
}
```

### 5. Error Handling

| Situation | Behavior |
|-----------|----------|
| File has no frontmatter | Skip with warning |
| File has no `source_url` | Skip with warning |
| Frontmatter parse error | Skip with warning |
| "My Notes" section missing | Add empty one |
| Multiple "My Notes" headings | Use first one as boundary |
| Backup creation fails | Abort update, report error |
| Multiple files match same video | Warn and skip, user resolves manually |

**Summary Output**:

```
Updated: 1 file
  - pasta-aglio-e-olio.md (backup: .history/...2026-01-08T14-30-00.md)

Skipped: 2 files
  - malformed-recipe.md (no frontmatter)
  - old-notes.md (no source_url)
```

## File Structure

### New/Modified Files

```
KitchenOS/
├── extract_recipe.py      # Modified: add duplicate detection + backup
├── migrate_recipes.py     # New: bulk migration command
├── templates/
│   └── recipe_template.py # Modified: schema definition + My Notes section
└── lib/
    ├── recipe_parser.py   # New: parse existing recipe files
    └── backup.py          # New: backup management
```

### Obsidian Vault Structure

```
Recipes/
├── .history/                                    # Backups (hidden in Obsidian)
│   └── 2026-01-07-pasta_2026-01-08T14-30-00.md
├── 2026-01-07-pasta-aglio-e-olio.md
└── 2026-01-07-chicken-tikka.md
```

## Usage

### Re-extract a Recipe

```bash
# Updates existing file if found, otherwise creates new
.venv/bin/python extract_recipe.py "https://www.youtube.com/watch?v=VIDEO_ID"

# Preview mode still works
.venv/bin/python extract_recipe.py --dry-run "VIDEO_URL"
```

### Migrate All Recipes

```bash
# Preview what would change
.venv/bin/python migrate_recipes.py --dry-run

# Apply migrations
.venv/bin/python migrate_recipes.py
```

### Recover from Backup

1. Navigate to `Recipes/.history/`
2. Find the backup by filename and timestamp
3. Copy desired content back to the main recipe file

## Future Considerations

These are explicitly out of scope for the initial implementation but could be added later:

- **Derive fields from existing data**: Compute boolean fields like `has_dairy` by scanning ingredients
- **Selective re-extraction**: Re-extract specific recipes to populate new fields with real data
- **Backup cleanup**: Command to prune old backups (e.g., keep only last 5 per recipe)
- **Conflict detection**: Warn if file was modified more recently than last extraction
