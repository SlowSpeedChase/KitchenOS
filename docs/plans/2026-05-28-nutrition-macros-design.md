# Nutrition Macros: Schema Standardization, Backfill, and Dashboard

**Date:** 2026-05-28
**Branch:** feat/nutrition-macros (to be created)
**Status:** Approved, ready for implementation

---

## Problem

Nutrition macros exist in the codebase but are broken in three ways:

1. **Key name mismatch** — `extract_recipe.py` writes `protein_g`, `carbs_g`, `fat_g` but the template expects `nutrition_protein`, `carbs`, `fat`. Protein, carbs, and fat are silently dropped on every new extraction.
2. **Inconsistent schema** — frontmatter uses a mix of `calories` (no prefix), `nutrition_protein` (prefixed), `carbs`, `fat` (no prefix). The dashboard code already uses `nutrition_calories` etc., so it reads nothing.
3. **No `My Macros.md`** — the macro targets file the dashboard depends on doesn't exist.

Of 267 recipes in the vault, 221 have `nutrition_calories: null` (83%). Even the 46 with calories have `nutrition_protein: null`.

---

## Approach: Standardize Schema + Fix + Backfill (Approach B)

Rename all nutrition frontmatter keys to a consistent `nutrition_` prefix, fix the extraction bugs, backfill existing recipes with USDA + AI estimates, create `My Macros.md`, and add the missing API endpoint.

---

## Section 1: Schema Standardization

### Key renames

| Current key | New key |
|---|---|
| `calories` | `nutrition_calories` |
| `nutrition_protein` | *(no change)* |
| `carbs` | `nutrition_carbs` |
| `fat` | `nutrition_fat` |
| `nutrition_source` | *(no change)* |

`nutrition_dashboard.py`'s `get_recipe_nutrition()` already reads `nutrition_calories`, `nutrition_protein`, `nutrition_carbs`, `nutrition_fat` — the dashboard code needs zero changes after this rename.

### Files changed

- **`templates/recipe_template.py`** — `RECIPE_SCHEMA` dict, `RECIPE_TEMPLATE` frontmatter string, `generate_nutrition_section()` key reads, `format_recipe_markdown()` template kwargs
- **`extract_recipe.py`** — fix `protein_g` → `nutrition_protein`, `carbs_g` → `nutrition_carbs`, `fat_g` → `nutrition_fat`, `calories` → `nutrition_calories`
- **`migrate_recipes.py`** — add a migration pass that renames the 4 keys in all 267 existing recipe files (uses existing `backup.create_backup()` infrastructure)

---

## Section 2: Backfill Script (`backfill_nutrition.py`)

New script that processes all recipes with `nutrition_calories: null`.

### Algorithm per recipe

1. Parse the ingredient list from the recipe frontmatter/body
2. Look up each ingredient via **USDA FoodData Central** (free, no API key) — sum totals
3. Any ingredient that fails USDA falls back to a single **Ollama AI estimate** for the full recipe
4. Divide totals by `servings` for per-serving values (default `servings=1` when null)
5. Write back to recipe file via `backup.create_backup()` + atomic write
6. Set `nutrition_source` to `usda`, `usda+ai`, or `ai`

### CLI interface

```bash
# Preview what would change
.venv/bin/python backfill_nutrition.py --dry-run

# Run backfill
.venv/bin/python backfill_nutrition.py

# Limit to N recipes (useful for testing)
.venv/bin/python backfill_nutrition.py --limit 10

# Re-process even recipes that already have data
.venv/bin/python backfill_nutrition.py --force
```

### Output

Prints a summary: recipes updated, skipped (already had data), failed (no ingredients / lookup error), and source breakdown (usda / usda+ai / ai).

### Serving size handling

Recipes with `servings: null` use `servings=1` and set `serving_size: "1 serving"` if not already set. Accuracy is marked lower in this case since we can't verify serving count.

> **Future feature:** A dedicated workflow to correct serving sizes on recipes (noted for roadmap).

---

## Section 3: Dashboard + `My Macros.md`

### `My Macros.md` (new vault file)

Created at `{vault_root}/My Macros.md` with placeholder targets:

```yaml
---
calories: 2000
protein: 150
carbs: 200
fat: 65
---
# My Macros

Daily macro targets for nutrition dashboard.
```

`lib/macro_targets.py` already reads this exact format — no changes needed.

### Weekly dashboard

`generate_nutrition_dashboard.py` already works conceptually. After the schema rename and backfill:
- Reads each recipe from the week's meal plan
- Loads `nutrition_calories/protein/carbs/fat` from each recipe file
- Compares daily totals against `My Macros.md` targets
- Outputs `Nutrition Dashboard.md` in vault root

No code changes needed to the dashboard generation logic.

### New API endpoint

Add `GET /refresh-nutrition` to `api_server.py` — the dashboard footer already references this URL but the route doesn't exist. Accepts `?week=YYYY-Wnn`, regenerates the dashboard, returns redirect to vault.

---

## Confidence / Accuracy

`nutrition_source` field encodes accuracy tier:

| Value | Meaning |
|---|---|
| `nutritionix` | Per-ingredient lookup from Nutritionix (most accurate) |
| `usda` | Per-ingredient lookup from USDA FoodData Central |
| `usda+ai` | USDA for most ingredients, AI fallback for remainder |
| `ai` | Full Ollama AI estimate |

New recipes continue to use the existing `Nutritionix → USDA → AI` hierarchy in `lib/nutrition_lookup.py`. Backfill uses `USDA → AI` only (no Nutritionix credits spent).

---

## Implementation Order

1. Fix schema in `templates/recipe_template.py` and `extract_recipe.py`
2. Add migration pass to `migrate_recipes.py`
3. Run migration on vault
4. Write `backfill_nutrition.py`
5. Create `My Macros.md` in vault
6. Add `/refresh-nutrition` endpoint to `api_server.py`
7. Smoke-test dashboard end-to-end

---

## Out of Scope

- Per-recipe `% of daily value` display (Approach A — not requested)
- Manual review queue (Approach C — not requested)
- Nutritionix-based backfill (API cost; USDA + AI is sufficient for estimates)
- Serving size correction workflow (future feature)
