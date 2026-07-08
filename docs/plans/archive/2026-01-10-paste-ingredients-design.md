# Paste Ingredients to Shopping List

## Overview

Add a button to shopping list notes that allows pasting plaintext ingredient lists and converts them to checkbox format. Pasted items persist through shopping list regeneration.

## User Workflow

1. User views their shopping list (e.g., `Shopping Lists/2026-W02.md`)
2. Clicks "Add Ingredients" button
3. QuickAdd opens a multi-line text prompt
4. User pastes ingredient list like:
   ```
   Chinese black vinegar - 1 ½ tsp
   Soy sauce - 1 ½ TBSP
   Creamy almond butter - ¼ cup + 1 TBSP
   ```
5. Clicks OK
6. Each line becomes `- [ ] {line}` appended to the note

## Implementation

### 1. QuickAdd Capture

Create a Capture in QuickAdd called "Add Ingredients to Shopping List":

- **Capture To:** Active file
- **Insert at:** Bottom of file
- **Capture format:** Enabled with transformation

Format template:
```
{{VALUE:Paste ingredients (one per line):}}
```

JavaScript format function (if using Capture with JS):
```javascript
return value
  .split('\n')
  .map(line => line.trim())
  .filter(line => line.length > 0)
  .map(line => `- [ ] ${line}`)
  .join('\n');
```

### 2. Button in Shopping List Template

Add to `templates/shopping_list_template.py` in the `generate_shopping_list_markdown()` function:

```markdown
```button
name Add Ingredients
type command
action QuickAdd: Add Ingredients to Shopping List
```
```

### 3. Merge Logic on Regeneration

Modify `/generate-shopping-list` endpoint in `api_server.py`:

**Before:**
- Generate items from meal plan
- Overwrite file with new items

**After:**
- Generate items from meal plan
- If file exists, read current unchecked items
- Identify manual items (items not in fresh generation)
- Write file with: generated items + manual items section

```python
def extract_manual_items(existing_items: list[str], generated_items: list[str]) -> list[str]:
    """Find items that were manually added (not from generation)."""
    generated_set = set(generated_items)
    return [item for item in existing_items if item not in generated_set]
```

## Files to Modify

| File | Change |
|------|--------|
| `templates/shopping_list_template.py` | Add "Add Ingredients" button to template |
| `api_server.py` | Add merge logic to `/generate-shopping-list` endpoint |
| `lib/shopping_list_generator.py` | Add `extract_manual_items()` helper |

## User Setup Required

User must configure QuickAdd in Obsidian:

1. Settings → QuickAdd → Add Choice → "Add Ingredients to Shopping List" (Capture)
2. Configure: Capture to active file, insert at bottom
3. Enable format with transformation to add checkboxes

## Edge Cases

- **Recipe removed from meal plan:** Its ingredients will appear as "manual" items and be preserved. This is acceptable behavior.
- **Empty paste:** Filter out empty lines, no items added.
- **Regenerate with no existing file:** No merge needed, just generate fresh.

## Testing

1. Generate a shopping list for a week
2. Use the button to paste additional ingredients
3. Regenerate the shopping list
4. Verify pasted items are preserved at the bottom
