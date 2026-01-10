"""Parser for user macro targets from My Macros.md file."""

from pathlib import Path
from typing import Optional

from lib.nutrition import NutritionData
from lib.recipe_parser import parse_recipe_file


def load_macro_targets(vault_path: Path) -> Optional[NutritionData]:
    """Load daily macro targets from My Macros.md file.

    Args:
        vault_path: Path to the Obsidian vault root

    Returns:
        NutritionData with daily targets, or None if file not found
    """
    macros_file = vault_path / "My Macros.md"

    if not macros_file.exists():
        return None

    content = macros_file.read_text(encoding='utf-8')
    parsed = parse_recipe_file(content)
    frontmatter = parsed['frontmatter']

    # Extract macro values from frontmatter
    calories = frontmatter.get('calories', 0)
    protein = frontmatter.get('protein', 0)
    carbs = frontmatter.get('carbs', 0)
    fat = frontmatter.get('fat', 0)

    # Ensure all values are integers
    return NutritionData(
        calories=int(calories) if calories else 0,
        protein=int(protein) if protein else 0,
        carbs=int(carbs) if carbs else 0,
        fat=int(fat) if fat else 0,
    )
