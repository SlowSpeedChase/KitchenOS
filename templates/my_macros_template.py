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
