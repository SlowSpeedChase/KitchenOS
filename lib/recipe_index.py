"""Recipe index — scan recipe files and extract frontmatter metadata."""

from datetime import datetime
from pathlib import Path

from lib import short_title
from lib.recipe_parser import parse_recipe_file, parse_recipe_body
from lib.recipe_time import parse_minutes

FILTER_FIELDS = ("cuisine", "protein", "difficulty", "meal_occasion", "dish_type", "peak_months")
NUTRITION_FIELDS = ("nutrition_calories", "nutrition_protein", "nutrition_carbs", "nutrition_fat")


def _added_date(filepath: Path) -> str | None:
    """When this recipe *arrived*, as an ISO date — birth time, not mtime.

    Deliberately not mtime: the nutrition resolver rewrites recipe files long after
    they land, so an mtime-ordered "recently added" list reshuffles itself every time
    a backfill runs and stops meaning anything. macOS/BSD carry `st_birthtime`; Linux
    generally doesn't, so fall back to mtime there rather than lose the field.
    """
    try:
        st = filepath.stat()
    except OSError:
        return None
    stamp = getattr(st, "st_birthtime", None) or st.st_mtime
    try:
        return datetime.fromtimestamp(stamp).date().isoformat()
    except (OSError, OverflowError, ValueError):
        return None


def get_recipe_index(recipes_dir: Path, include_ingredients: bool = False) -> list[dict]:
    """Scan all recipe .md files and return metadata for filtering.

    Args:
        recipes_dir: Path to the Recipes folder in Obsidian vault
        include_ingredients: If True, parse recipe body and include ingredient_items list

    Returns:
        List of dicts sorted by name, each with keys:
            name, cuisine, protein, difficulty, meal_occasion, dish_type, peak_months,
            servings (frontmatter servings count, or None),
            short_title (frontmatter override, or None),
            display_name (short_title or name — what a surface should render),
            added (ISO date the file arrived, or None — see _added_date)
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
            for field in NUTRITION_FIELDS:
                entry[field] = fm.get(field)
            # Coverage gates the macro-eligibility predicate (lib/nutrition_quality.py);
            # surfaced here so the suggester can score without re-reading the file.
            entry["nutrition_coverage"] = fm.get("nutrition_coverage")
            entry["servings"] = fm.get("servings") or None
            entry["short_title"] = fm.get("short_title") or None
            # Parsed here rather than at each consumer: `total_time` is prose
            # ("(estimated) 10-15 minutes for the meatballs…") and 147 of 254
            # recipes have none, so every caller would otherwise reimplement the
            # same lenient read and the same "unknown" handling.
            entry["total_time"] = fm.get("total_time") or None
            entry["total_time_minutes"] = parse_minutes(fm.get("total_time"))
            if include_ingredients:
                body_data = parse_recipe_body(parsed["body"])
                entry["ingredient_items"] = [ing["item"] for ing in body_data.get("ingredients", [])]
        except Exception:
            for field in FILTER_FIELDS:
                entry.setdefault(field, None)
            for field in NUTRITION_FIELDS:
                entry.setdefault(field, None)
            entry.setdefault("nutrition_coverage", None)
            entry.setdefault("servings", None)
            entry.setdefault("short_title", None)
            entry.setdefault("total_time", None)
            entry.setdefault("total_time_minutes", None)
            if include_ingredients:
                entry["ingredient_items"] = []

        # Filesystem metadata, so it's set whether or not the parse above succeeded —
        # a recipe that fails to parse still arrived on a date, and /recent should
        # show it rather than silently drop the one file worth investigating.
        entry["added"] = _added_date(filepath)

        # Set unconditionally, and after the except: every consumer can render
        # display_name without knowing whether the parse succeeded or whether
        # this recipe happens to carry an override. `name` stays the identity —
        # cooks rows, meal plans and task-ID hashes are all keyed on it.
        entry["display_name"] = short_title.display_name(name, entry.get("short_title"))

        # Check for matching image file
        images_dir = recipes_dir / "Images"
        image_file = images_dir / f"{name}.jpg"
        entry["image"] = f"{name}.jpg" if image_file.exists() else None

        recipes.append(entry)

    recipes.sort(key=lambda r: r["name"])
    return recipes
