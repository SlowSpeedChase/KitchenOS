# Ingredient Parsing Fix Design

**Date:** 2026-01-08
**Status:** Approved
**Problem:** AI extraction incorrectly splits ingredients (e.g., "neutral oil" as unit, "oil" as item)

## Summary

Replace LLM-based ingredient splitting with a dedicated ML parser ([ingredient-parser-nlp](https://github.com/strangetom/ingredient-parser)) that has 95% accuracy on 81,000 training sentences.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Recipe Extraction                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  1. EXTRACTION (AI)           2. PARSING (ML)      3. TEMPLATE  │
│  ┌─────────────────┐         ┌──────────────┐     ┌──────────┐  │
│  │ Ollama returns  │         │ ingredient-  │     │ Format   │  │
│  │ raw strings:    │────────▶│ parser-nlp   │────▶│ markdown │  │
│  │ "1 quart        │         │ splits into  │     │ with     │  │
│  │  neutral oil"   │         │ amount/unit/ │     │ validated│  │
│  └─────────────────┘         │ item         │     │ data     │  │
│                              └──────────────┘     └──────────┘  │
│                                     │                           │
│                              ┌──────▼──────┐                    │
│                              │ Validation  │                    │
│                              │ - confidence│                    │
│                              │ - unit check│                    │
│                              └─────────────┘                    │
└─────────────────────────────────────────────────────────────────┘
```

## Changes Required

### 1. AI Prompt Changes (`prompts/recipe_extraction.py`)

**Current schema (error-prone):**
```json
"ingredients": [
  {"amount": "1 quart", "unit": "neutral oil", "item": "oil", "inferred": false}
]
```

**New schema (simpler for AI):**
```json
"ingredients": [
  {"text": "1 quart neutral oil", "inferred": false}
]
```

Remove unit-splitting instructions from prompt. AI just returns raw ingredient strings.

### 2. New Module (`lib/ingredient_normalizer.py`)

Wraps ML parser with validation and fallback:

```python
from ingredient_parser import parse_ingredient

LOW_CONFIDENCE_THRESHOLD = 0.8

def normalize_ingredient(text: str) -> dict:
    """
    Parse ingredient string into structured data.

    Returns:
        {
            "amount": "1",
            "unit": "quart",
            "item": "neutral oil",
            "preparation": "minced",  # optional
            "confidence": 0.95,
            "low_confidence": False
        }
    """
    parsed = parse_ingredient(text)
    # Extract and validate fields...
    # Fallback to regex parser if confidence too low
```

### 3. Integration Points

Call normalizer in three places:

1. **`extract_recipe.py`** - After Ollama returns recipe JSON
2. **`recipe_sources.py`** - After `parse_recipe_from_description()`
3. **`recipe_sources.py`** - After `scrape_recipe_from_url()`

```python
from lib.ingredient_normalizer import normalize_ingredients

recipe["ingredients"], low_confidence = normalize_ingredients(
    recipe.get("ingredients", [])
)

if low_confidence:
    recipe["needs_review"] = True
```

### 4. Migration Script (`migrate_ingredients.py`)

Fix existing recipes by reconstructing and re-parsing:

```python
def reconstruct_ingredient_string(amount: str, unit: str, item: str) -> str:
    """
    ("1 quart", "neutral oil", "oil") → "1 quart neutral oil"
    ("2", "cinnamon sticks", "cinnamon") → "2 cinnamon sticks"
    """
```

Features:
- `--dry-run` preview mode
- Automatic backup via `lib/backup.py`
- Per-file tracking of changes

### 5. Python Upgrade (3.9 → 3.11)

Required for ingredient-parser-nlp dependency.

```bash
brew install python@3.11
rm -rf .venv
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Update LaunchAgent to use new Python path.

## Files Affected

| File | Change |
|------|--------|
| `prompts/recipe_extraction.py` | Simplify ingredient schema |
| `lib/ingredient_normalizer.py` | New - wraps ML parser |
| `lib/ingredient_parser.py` | Keep as fallback |
| `extract_recipe.py` | Call normalizer after AI extraction |
| `recipe_sources.py` | Call normalizer for webpage/description |
| `migrate_ingredients.py` | New - fix existing recipes |
| `requirements.txt` | Add ingredient-parser-nlp>=2.4.0 |
| `~/Library/LaunchAgents/com.kitchenos.api.plist` | Update Python path |

## Dependencies

```
ingredient-parser-nlp>=2.4.0  # ~50MB model download
```

## Success Criteria

- [ ] New extractions parse ingredients correctly (manual spot check)
- [ ] Existing recipes migrated without data loss
- [ ] Low-confidence parses flagged with `needs_review: true`
- [ ] API server works after Python upgrade

## References

- [ingredient-parser-nlp on PyPI](https://pypi.org/project/ingredient-parser-nlp/)
- [GitHub - strangetom/ingredient-parser](https://github.com/strangetom/ingredient-parser)
- [Ingredient Parser Documentation](https://ingredient-parser.readthedocs.io/en/latest/)
