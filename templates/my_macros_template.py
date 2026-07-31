"""Template for My Macros.md file."""


def generate_my_macros_markdown(
    calories: int = 2000,
    protein: int = 150,
    carbs: int = 200,
    fat: int = 65,
) -> str:
    """Generate My Macros.md template content.

    Args:
        calories: Daily calorie target
        protein: Daily protein target in grams
        carbs: Daily carbohydrate target in grams
        fat: Daily fat target in grams

    Returns:
        Markdown content for My Macros.md
    """
    return f"""---
calories: {calories}
protein: {protein}
carbs: {carbs}
fat: {fat}
# How the day's target splits across slots — the reference line a meal's macros
# are measured against in the meal planner. Optional; these are the defaults.
# Flat keys, not a nested block: the frontmatter parser reads top-level keys only.
share_breakfast: 0.25
share_lunch: 0.3
share_dinner: 0.35
share_snack: 0.1
---

# My Daily Macros

| Macro    | Target |
|----------|--------|
| Calories | {calories}   |
| Protein  | {protein}g   |
| Carbs    | {carbs}g   |
| Fat      | {fat}g    |

## Notes

<!-- Track why you set these targets, adjustments over time, etc. -->
"""
