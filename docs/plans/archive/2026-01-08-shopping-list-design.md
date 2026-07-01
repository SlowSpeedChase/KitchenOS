# Shopping List Generation Design

Date: 2026-01-08
Status: Approved
Priority: Medium

## Problem

No way to generate a combined shopping list from multiple recipes planned for the week. Users must manually compile ingredients across recipes.

## Solution

**Meal Plan note → Python aggregation → Apple Reminders**

1. User creates a Meal Plan note with recipe links
2. Script parses links, loads recipes, aggregates ingredients
3. Pushes combined list to Apple Reminders

## Meal Plan Note Format

Location: `Obsidian Vault/KitchenOS/Meal Plan.md`

```markdown
# Meal Plan

## This Week
- [[Pasta Aglio e Olio]]
- [[Chicken Stir Fry]]
- [[Tacos]]
- [[Pasta Aglio e Olio]]  <!-- duplicates handled -->
```

Optional servings override (future enhancement):
```markdown
- [[Pasta Aglio e Olio]] x2
```

## Ingredient Aggregation

### What We Combine

| Case | Example | Result |
|------|---------|--------|
| Same unit | 1 cup + 2 cups | 3 cups |
| Unit family | 1 tbsp + 2 tsp | 5 tsp |
| Counts | 2 eggs + 3 eggs | 5 eggs |
| No amount duplicates | salt + salt | salt |

### Unit Families

```python
VOLUME_UNITS = {
    'tsp': 1,
    'tbsp': 3,       # 3 tsp
    'cup': 48,       # 48 tsp
    'ml': 0.2029,    # tsp
    'l': 202.9,      # tsp
}

WEIGHT_UNITS = {
    'oz': 1,
    'lb': 16,        # 16 oz
    'g': 0.035274,   # oz
    'kg': 35.274,    # oz
}

COUNT_UNITS = {
    'clove', 'cloves',
    'slice', 'slices',
    'piece', 'pieces',
    'bunch', 'bunches',
    'head', 'heads',
    'can', 'cans',
    'package', 'packages',
}
```

### What We Don't Combine

| Case | Handling |
|------|----------|
| Different unit families | List separately |
| Volume ↔ weight | List separately (future: density conversion) |
| Fuzzy name matching | Exact match only |
| Informal amounts | Keep as-is ("a pinch") |

### Aggregation Algorithm

```python
def aggregate_ingredients(all_ingredients):
    """Combine like ingredients across recipes.

    Args:
        all_ingredients: List of dicts with amount, unit, item

    Returns:
        List of aggregated ingredient dicts
    """
    groups = {}

    for ing in all_ingredients:
        # Normalize item name (lowercase, strip whitespace)
        key = normalize_item_name(ing['item'])

        if key not in groups:
            groups[key] = []
        groups[key].append(ing)

    results = []
    for key, items in groups.items():
        combined = combine_ingredient_group(items)
        results.extend(combined)

    return results


def combine_ingredient_group(items):
    """Combine ingredients with the same item name.

    Groups by unit family, sums within family, returns separate
    entries for incompatible units.
    """
    # Group by unit family
    by_family = {
        'volume': [],
        'weight': [],
        'count': [],
        'other': [],
        'no_amount': [],
    }

    for item in items:
        family = get_unit_family(item['unit'])
        if not item.get('amount'):
            by_family['no_amount'].append(item)
        else:
            by_family[family].append(item)

    results = []

    # Sum each family
    for family, group in by_family.items():
        if not group:
            continue
        if family == 'no_amount':
            # Just keep one copy
            results.append(group[0])
        else:
            results.append(sum_unit_family(group, family))

    return results
```

## Output Format

Simple format for Apple Reminders (Reminders handles its own grouping):

```
3 cups flour
5 eggs
1 lb chicken breast
2 cans diced tomatoes
garlic
salt
```

## Apple Reminders Integration

```python
import subprocess

def add_to_reminders(items, list_name="Shopping"):
    """Add items to Apple Reminders list.

    Args:
        items: List of formatted ingredient strings
        list_name: Name of Reminders list
    """
    for item in items:
        # Escape quotes for AppleScript
        escaped = item.replace('"', '\\"')

        script = f'''
        tell application "Reminders"
            tell list "{list_name}"
                make new reminder with properties {{name:"{escaped}"}}
            end tell
        end tell
        '''
        subprocess.run(['osascript', '-e', script], check=True)


def clear_reminders_list(list_name="Shopping"):
    """Remove all items from a Reminders list."""
    script = f'''
    tell application "Reminders"
        tell list "{list_name}"
            delete every reminder
        end tell
    end tell
    '''
    subprocess.run(['osascript', '-e', script], check=True)
```

## CLI Interface

```bash
# Generate shopping list from default meal plan
python shopping_list.py

# Custom meal plan location
python shopping_list.py --plan "Weekly Menu.md"

# Dry run (preview without adding to Reminders)
python shopping_list.py --dry-run

# Output to file instead of Reminders
python shopping_list.py --output shopping.txt

# Clear existing list before adding
python shopping_list.py --clear
```

## Script Structure

```python
#!/usr/bin/env python3
"""Generate shopping list from meal plan."""

import argparse
import re
from pathlib import Path

from lib.recipe_parser import parse_recipe_file
from lib.ingredient_aggregator import aggregate_ingredients, format_ingredient
from lib.reminders import add_to_reminders, clear_reminders_list

# Configuration
OBSIDIAN_VAULT = Path("/Users/chaseeasterling/Library/Mobile Documents/iCloud~md~obsidian/Documents/KitchenOS")
MEAL_PLAN_PATH = OBSIDIAN_VAULT / "Meal Plan.md"
RECIPES_PATH = OBSIDIAN_VAULT / "Recipes"
REMINDERS_LIST = "Shopping"


def parse_meal_plan(meal_plan_path):
    """Extract recipe links from meal plan note.

    Returns:
        List of recipe names (without [[brackets]])
    """
    content = meal_plan_path.read_text(encoding='utf-8')

    # Find all [[wiki links]]
    links = re.findall(r'\[\[([^\]]+)\]\]', content)

    return links


def find_recipe_file(recipe_name, recipes_path):
    """Find recipe file by name.

    Tries exact match, then slugified match.
    """
    # Try exact match
    exact = recipes_path / f"{recipe_name}.md"
    if exact.exists():
        return exact

    # Try slugified
    slug = slugify(recipe_name)
    for file in recipes_path.glob("*.md"):
        if slugify(file.stem) == slug:
            return file

    return None


def main():
    parser = argparse.ArgumentParser(description="Generate shopping list from meal plan")
    parser.add_argument('--plan', type=Path, default=MEAL_PLAN_PATH, help='Meal plan file')
    parser.add_argument('--dry-run', action='store_true', help='Preview without adding to Reminders')
    parser.add_argument('--output', type=Path, help='Output to file instead of Reminders')
    parser.add_argument('--clear', action='store_true', help='Clear list before adding')
    args = parser.parse_args()

    # Parse meal plan
    recipe_names = parse_meal_plan(args.plan)
    print(f"Found {len(recipe_names)} recipes in meal plan")

    # Load all ingredients
    all_ingredients = []
    for name in recipe_names:
        recipe_file = find_recipe_file(name, RECIPES_PATH)
        if recipe_file:
            content = recipe_file.read_text(encoding='utf-8')
            parsed = parse_recipe_file(content)
            ingredients = parsed['frontmatter'].get('ingredients', [])
            all_ingredients.extend(ingredients)
        else:
            print(f"Warning: Recipe not found: {name}")

    # Aggregate
    aggregated = aggregate_ingredients(all_ingredients)
    formatted = [format_ingredient(ing) for ing in aggregated]

    print(f"Aggregated to {len(formatted)} items")

    if args.dry_run:
        print("\nShopping List:")
        for item in formatted:
            print(f"  - {item}")
        return

    if args.output:
        args.output.write_text('\n'.join(formatted), encoding='utf-8')
        print(f"Saved to {args.output}")
        return

    # Add to Reminders
    if args.clear:
        clear_reminders_list(REMINDERS_LIST)
        print(f"Cleared {REMINDERS_LIST} list")

    add_to_reminders(formatted, REMINDERS_LIST)
    print(f"Added {len(formatted)} items to {REMINDERS_LIST}")


if __name__ == "__main__":
    main()
```

## Files to Create

| File | Purpose |
|------|---------|
| `shopping_list.py` | Main CLI script |
| `lib/ingredient_aggregator.py` | Aggregation logic, unit conversion |
| `lib/reminders.py` | Apple Reminders AppleScript integration |

## Dependencies on Existing Code

- `lib/recipe_parser.py` - Parse frontmatter and body
- `lib/ingredient_parser.py` - Unit normalization (may extend)

## Future Enhancements

| Feature | Notes |
|---------|-------|
| Volume → weight conversion | Requires ingredient density database |
| Servings multiplier | `[[Recipe]] x2` syntax in meal plan |
| Aisle grouping | Add category field to ingredients |
| Pantry tracking | Exclude items you already have |
| Fuzzy name matching | "garlic, minced" = "garlic cloves" |

## Test Cases

**Input recipes:**

Recipe A:
```yaml
ingredients:
  - {amount: 1, unit: cup, item: flour}
  - {amount: 2, unit: '', item: eggs}
  - {amount: '', unit: '', item: salt}
```

Recipe B:
```yaml
ingredients:
  - {amount: 2, unit: cups, item: flour}
  - {amount: 3, unit: '', item: eggs}
  - {amount: 1, unit: tsp, item: salt}
```

**Expected output:**
```
3 cups flour
5 eggs
1 tsp salt
```

## Error Handling

| Error | Handling |
|-------|----------|
| Meal plan not found | Exit with clear error message |
| Recipe not found | Warn and continue with others |
| Reminders list doesn't exist | AppleScript creates it |
| Parse error in recipe | Warn and skip that recipe |
