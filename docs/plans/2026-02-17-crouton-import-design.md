# Crouton Import Design

**Date:** 2026-02-17
**Status:** Approved

## Goal

Import 123 recipes from Crouton iOS app (`.crumb` JSON files) into KitchenOS Obsidian vault, preserving source links and enriching with Ollama for missing metadata.

## Source

Crouton export folder: `/Users/chaseeasterling/Documents/Crouton Recipes - Feb 17, 2026/`

123 `.crumb` files — JSON format with structured ingredients, steps, and optional metadata.

## Approach

Standalone `import_crouton.py` script that:
1. Parses `.crumb` JSON files
2. Maps Crouton fields to KitchenOS recipe data dict
3. Calls Ollama to infer missing metadata (cuisine, protein, difficulty, etc.)
4. Reuses existing `format_recipe_markdown()` and `format_recipemd()` templates
5. Writes to Obsidian vault with duplicate handling

## Data Mapping

| Crouton Field | KitchenOS Field | Notes |
|---|---|---|
| `name` | `recipe_name` / `title` | Direct map |
| `webLink` | `source_url` | 90/123 have this |
| URL in `notes` | `source_url` (fallback) | Only if `webLink` is empty |
| `sourceName` | `source_channel` | 87/123 have this |
| `serves` | `servings` | Direct map |
| `duration` | `prep_time` | Minutes → string (e.g., "20 minutes") |
| `cookingDuration` | `cook_time` | Minutes → string |
| `notes` | `## My Notes` section | Preserve all text content |
| `tags` | `tags` | Direct map (most are empty) |
| `steps` | `instructions` | Handle `isSection: true` as section headers |
| `ingredients` | `ingredients` | Map `quantityType` → standard units |
| `neutritionalInfo` | nutrition fields | Only 1 recipe has this, parse if present |

### Unit Mapping

| Crouton `quantityType` | KitchenOS Unit |
|---|---|
| CUP | cup |
| TABLESPOON | tbsp |
| TEASPOON | tsp |
| GRAMS | g |
| OUNCE | oz |
| POUND | lb |
| FLUID_OUNCE | fl oz |
| MILLS | ml |
| KGS | kg |
| CAN | can |
| BUNCH | bunch |
| PACKET | packet |
| PINCH | pinch |
| ITEM | whole |

### Ingredient Name Handling

Some Crouton ingredients bake qualifiers into the name (e.g., "to taste salt", "a little sprinkle Kashmir Chili Pepper"). These get passed through as-is — the ingredient name is the full string.

## Ollama Enrichment

For each recipe, send name + ingredients + steps to Ollama (`mistral:7b`) to infer:
- `description` (1-2 sentence summary)
- `cuisine` (e.g., "Indian", "Mexican")
- `protein` (e.g., "chicken", "tofu", null)
- `difficulty` (easy/medium/hard)
- `dish_type` (e.g., "Main", "Dessert", "Side")
- `meal_occasion` (up to 3 tags)
- `dietary` (e.g., ["vegetarian", "gluten-free"])
- `equipment` (inferred from steps)

Simplified prompt compared to full extraction — we already have structured data, just need classification.

Processing: sequential, one Ollama call per recipe (~5-6 minutes for 123 recipes).

Failure handling: if Ollama fails, set `needs_review: true`, fill fields with null, log and continue.

All imported recipes get:
- `recipe_source: "crouton_import"`
- `needs_review: true`
- `confidence_notes` describing it as a Crouton import with AI enrichment

## Duplicate Handling

- Check if `{Recipe Name}.md` exists in Recipes folder
- If duplicate, save as `{Recipe Name} (Crouton).md`
- The "(Crouton)" suffix is in filename only — `title` frontmatter stays clean
- Purpose: compare Crouton import quality against existing KitchenOS extractions

## File Output

Per recipe, two files:
1. `Recipes/{Recipe Name}.md` — full recipe with YAML frontmatter, Tools callout, ingredients table, instructions, My Notes
2. `Recipes/Cooking Mode/{Recipe Name}.recipe.md` — RecipeMD format for cooking view

Footer: `*Imported from Crouton on 2026-02-17*` (with source URL linked if available), replacing the usual YouTube attribution.

## CLI

```
import_crouton.py [OPTIONS] <crouton_dir>
```

**Options:**
- `--dry-run` — preview without writing files
- `--no-enrich` — skip Ollama enrichment (fast import, nulls for metadata)

**Progress output:**
```
[  1/123] Butter Chicken ... enriching ... saved
[  2/123] Almond Flour Pancakes ... enriching ... saved
[  3/123] 19 Calorie Fudgy Brownies ... duplicate → (Crouton) ... enriching ... saved
...
Done: 123 imported (5 duplicates), 0 failed
```

## Developer Notes (Crouton `.crumb` Format Reference)

### Full Schema

All top-level fields discovered across 123 files:

| Field | Type | Prevalence | Notes |
|---|---|---|---|
| `name` | string | 123/123 | Recipe title |
| `uuid` | string | 123/123 | Crouton internal ID |
| `ingredients` | array | 123/123 | Structured ingredient objects |
| `steps` | array | 123/123 | Instruction step objects |
| `defaultScale` | number | 123/123 | Usually 1 |
| `isPublicRecipe` | bool | 123/123 | Always false in exports |
| `folderIDs` | array | 123/123 | Crouton folder associations |
| `images` | array | 123/123 | Always empty in export (images are separate?) |
| `tags` | array | 123/123 | Mostly empty |
| `webLink` | string | 90/123 | Source URL — primary link field |
| `sourceName` | string | 87/123 | Creator/website attribution |
| `serves` | number | varies | Not always present |
| `duration` | number | varies | Prep time in minutes |
| `cookingDuration` | number | varies | Cook time in minutes |
| `notes` | string | 10/123 | Free text, occasionally contains URLs |
| `sourceImage` | string | varies | Base64 encoded image |
| `neutritionalInfo` | string | 1/123 | Note the typo — "neutritional" not "nutritional" |
| `duplicatedFromRecipeUUID` | string | varies | Indicates recipe was duplicated in Crouton |

### Ingredient Object Structure

```json
{
  "order": 0,
  "uuid": "...",
  "ingredient": {
    "uuid": "...",
    "name": "chicken breast"
  },
  "quantity": {
    "amount": 1,
    "quantityType": "POUND",
    "secondaryAmount": null
  }
}
```

- `quantity` is optional — some ingredients have no amount (e.g., "to taste salt")
- `quantityType` is one of 14 enum values (see unit mapping above)
- `secondaryAmount` exists but purpose is unclear — possibly for compound quantities
- Ingredient `name` sometimes includes qualifiers baked in (e.g., "to taste fenugreek seeds", "a little sprinkle Kashmir Chili Pepper")

### Step Object Structure

```json
{
  "order": 0,
  "uuid": "...",
  "isSection": false,
  "step": "Marinate the chicken with salt, yogurt, and spices."
}
```

- `isSection: true` indicates a section header (20 steps across all recipes use this)
- Steps should be sorted by `order` field
- Step text is plain string, no markdown

### Quirks & Edge Cases

1. **`neutritionalInfo` typo**: Field is misspelled "neutritional" not "nutritional" — only 1 recipe has data (comma-separated key:value pairs)
2. **Ingredient qualifiers in name**: Crouton doesn't separate "to taste" or "a pinch" from the ingredient name. e.g., "to taste salt" means salt, to taste
3. **Empty `images` array**: Crouton export doesn't include images in the `.crumb` file even when the recipe has photos. `sourceImage` (base64) is separate and only on some recipes
4. **`secondaryAmount`**: Found in at least one recipe. Purpose unclear — possibly for mixed units or ranges
5. **Section steps**: When `isSection: true`, the step text is a section heading (e.g., "For the Sauce"), not an instruction
6. **No description field**: Crouton has no recipe description — this must be AI-generated
7. **Tags mostly empty**: Despite the field existing, tags are empty in nearly all exported recipes
8. **Notes with URLs**: Only 1 recipe has a URL in notes (YouTube link). Most notes are cooking tips or conversion references
