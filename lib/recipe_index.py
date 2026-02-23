"""Recipe index — scan recipe files and extract frontmatter metadata."""

from pathlib import Path

from lib.recipe_parser import parse_recipe_file, parse_recipe_body

FILTER_FIELDS = ("cuisine", "protein", "difficulty", "meal_occasion", "dish_type", "peak_months")


def get_recipe_index(recipes_dir: Path, include_ingredients: bool = False) -> list[dict]:
    """Scan all recipe .md files and return metadata for filtering.

    Args:
        recipes_dir: Path to the Recipes folder in Obsidian vault
        include_ingredients: If True, parse recipe body and include ingredient_items list

    Returns:
        List of dicts sorted by name, each with keys:
            name, cuisine, protein, difficulty, meal_occasion, dish_type, peak_months
            Optionally includes ingredient_items (list of item strings) when include_ingredients=True
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
            if include_ingredients:
                body_data = parse_recipe_body(parsed["body"])
                entry["ingredient_items"] = [ing["item"] for ing in body_data.get("ingredients", [])]
        except Exception:
            for field in FILTER_FIELDS:
                entry.setdefault(field, None)
            if include_ingredients:
                entry["ingredient_items"] = []

        # Check for matching image file
        images_dir = recipes_dir / "Images"
        image_file = images_dir / f"{name}.jpg"
        entry["image"] = f"{name}.jpg" if image_file.exists() else None

        recipes.append(entry)

    recipes.sort(key=lambda r: r["name"])
    return recipes
