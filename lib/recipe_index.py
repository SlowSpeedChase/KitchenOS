"""Recipe index — scan recipe files and extract frontmatter metadata."""

from pathlib import Path

from lib.recipe_parser import parse_recipe_file

FILTER_FIELDS = ("cuisine", "protein", "difficulty", "meal_occasion", "dish_type", "peak_months")


def get_recipe_index(recipes_dir: Path) -> list[dict]:
    """Scan all recipe .md files and return metadata for filtering.

    Args:
        recipes_dir: Path to the Recipes folder in Obsidian vault

    Returns:
        List of dicts sorted by name, each with keys:
            name, cuisine, protein, difficulty, meal_occasion, dish_type, peak_months
    """
    recipes = []

    for filepath in recipes_dir.iterdir():
        if not filepath.is_file() or filepath.suffix != ".md":
            continue

        name = filepath.stem
        entry = {"name": name}

        try:
            content = filepath.read_text(encoding="utf-8")
            parsed = parse_recipe_file(content)
            fm = parsed["frontmatter"]
            for field in FILTER_FIELDS:
                entry[field] = fm.get(field)
        except Exception:
            for field in FILTER_FIELDS:
                entry.setdefault(field, None)

        recipes.append(entry)

    recipes.sort(key=lambda r: r["name"])
    return recipes
