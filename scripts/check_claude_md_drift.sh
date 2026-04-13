#!/usr/bin/env bash
# Warns (non-blocking) when an edit to lib/, templates/, prompts/, or a
# top-level Python script is not reflected in the CLAUDE.md "Key Functions"
# or "Core Components" tables. Reads stdin as JSON from Claude Code.
#
# Exit codes:
#   0 — no warning (file ok, not relevant, or CLAUDE.md mentions it)
#   1 — warning printed to stderr (does not block the tool call)

set -euo pipefail

INPUT=$(cat)
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

# Not a file we care about
case "$FILE" in
    *.py) ;;
    *) exit 0 ;;
esac

# Basename without extension
BASE=$(basename "$FILE")

# Only watch code the Key Functions table covers
case "$FILE" in
    */lib/*|*/templates/*|*/prompts/*|*/KitchenOS/lib/*|*/KitchenOS/templates/*|*/KitchenOS/prompts/*)
        RELEVANT=1 ;;
    */KitchenOS/extract_recipe.py|*/KitchenOS/main.py|*/KitchenOS/api_server.py|*/KitchenOS/batch_extract.py|*/KitchenOS/shopping_list.py|*/KitchenOS/sync_calendar.py|*/KitchenOS/generate_meal_plan.py|*/KitchenOS/generate_nutrition_dashboard.py|*/KitchenOS/migrate_recipes.py|*/KitchenOS/migrate_cuisine.py|*/KitchenOS/mcp_server.py|*/KitchenOS/recipe_sources.py|*/KitchenOS/import_crouton.py)
        RELEVANT=1 ;;
    *) exit 0 ;;
esac

CLAUDE_MD="/Users/chaseeasterling/KitchenOS/CLAUDE.md"
[ -f "$CLAUDE_MD" ] || exit 0

# Skip test files
case "$BASE" in
    test_*) exit 0 ;;
esac

if ! grep -q "$BASE" "$CLAUDE_MD"; then
    echo "⚠️  CLAUDE.md drift: $BASE is not mentioned in CLAUDE.md" >&2
    echo "    Consider adding an entry to the 'Core Components' or 'Key Functions' table." >&2
    echo "    (Warning only — this does not block the edit.)" >&2
fi

exit 0
