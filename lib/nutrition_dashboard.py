"""Generate nutrition dashboard from meal plans."""

import re
from datetime import datetime, date
from pathlib import Path
from typing import Optional

from lib.nutrition import NutritionData
from lib.macro_targets import load_macro_targets
from lib.meal_plan_parser import parse_meal_plan
from lib.recipe_parser import parse_recipe_file


def get_recipe_nutrition(recipe_name: str, recipes_dir: Path) -> Optional[NutritionData]:
    """Load nutrition data from a recipe file.

    Args:
        recipe_name: Name of the recipe (from [[Recipe Name]] link)
        recipes_dir: Path to the Recipes directory

    Returns:
        NutritionData if recipe has nutrition info, None otherwise
    """
    # Recipe files are stored as "{Recipe Name}.md"
    recipe_file = recipes_dir / f"{recipe_name}.md"

    if not recipe_file.exists():
        return None

    content = recipe_file.read_text(encoding='utf-8')
    parsed = parse_recipe_file(content)
    fm = parsed['frontmatter']

    # Check if recipe has nutrition data
    if 'nutrition_calories' not in fm:
        return None

    return NutritionData(
        calories=int(fm.get('nutrition_calories', 0) or 0),
        protein=int(fm.get('nutrition_protein', 0) or 0),
        carbs=int(fm.get('nutrition_carbs', 0) or 0),
        fat=int(fm.get('nutrition_fat', 0) or 0),
    )


def calculate_daily_nutrition(
    day_data: dict,
    recipes_dir: Path
) -> tuple[NutritionData, list[str]]:
    """Calculate total nutrition for a day.

    Args:
        day_data: Dict with 'breakfast', 'lunch', 'dinner' recipe names
        recipes_dir: Path to the Recipes directory

    Returns:
        Tuple of (NutritionData total, list of missing recipe names)
    """
    total = NutritionData.empty()
    missing = []

    for meal in ['breakfast', 'lunch', 'dinner']:
        recipe_name = day_data.get(meal)
        if not recipe_name:
            continue

        nutrition = get_recipe_nutrition(recipe_name, recipes_dir)
        if nutrition:
            total = total + nutrition
        else:
            missing.append(recipe_name)

    return total, missing


def format_daily_summary_row(
    day_name: str,
    actual: Optional[NutritionData],
    targets: NutritionData,
    has_meals: bool
) -> str:
    """Format a single day's row in the summary table.

    Args:
        day_name: Name of the day (Monday, Tuesday, etc.)
        actual: Actual nutrition consumed, or None if no meals
        targets: Daily targets
        has_meals: Whether this day has any meals planned

    Returns:
        Markdown table row string
    """
    if not has_meals:
        return f"| {day_name} | — | — | — | — |"

    if actual is None:
        actual = NutritionData.empty()

    return (
        f"| {day_name} | {actual.calories} / {targets.calories} | "
        f"{actual.protein} / {targets.protein}g | "
        f"{actual.carbs} / {targets.carbs}g | "
        f"{actual.fat} / {targets.fat}g |"
    )


def generate_dashboard(
    week: str,
    vault_path: Path,
) -> tuple[str, list[str]]:
    """Generate nutrition dashboard markdown.

    Args:
        week: Week identifier (e.g., "2026-W03")
        vault_path: Path to the Obsidian vault

    Returns:
        Tuple of (markdown content, list of warnings)
    """
    warnings = []

    # Parse week identifier
    match = re.match(r'(\d{4})-W(\d{2})', week)
    if not match:
        raise ValueError(f"Invalid week format: {week}. Expected YYYY-Wnn")

    year = int(match.group(1))
    week_num = int(match.group(2))

    # Load macro targets
    targets = load_macro_targets(vault_path)
    if targets is None:
        warnings.append("My Macros.md not found, using default targets")
        targets = NutritionData(calories=2000, protein=150, carbs=200, fat=65)

    # Load meal plan
    meal_plans_dir = vault_path / "Meal Plans"
    meal_plan_file = meal_plans_dir / f"{week}.md"

    if not meal_plan_file.exists():
        raise FileNotFoundError(f"Meal plan not found: {meal_plan_file}")

    meal_plan_content = meal_plan_file.read_text(encoding='utf-8')
    days = parse_meal_plan(meal_plan_content, year, week_num)

    # Calculate nutrition for each day
    recipes_dir = vault_path / "Recipes"
    daily_nutrition = []
    all_missing = []

    for day_data in days:
        has_meals = any(day_data.get(m) for m in ['breakfast', 'lunch', 'dinner'])
        if has_meals:
            nutrition, missing = calculate_daily_nutrition(day_data, recipes_dir)
            daily_nutrition.append(nutrition)
            all_missing.extend(missing)
        else:
            daily_nutrition.append(None)

    # Add warnings for missing recipe nutrition
    if all_missing:
        unique_missing = list(set(all_missing))
        for recipe in unique_missing:
            warnings.append(f"Recipe '{recipe}' missing nutrition data")

    # Calculate week averages (only for days with meals)
    days_with_meals = [n for n in daily_nutrition if n is not None]
    if days_with_meals:
        total = NutritionData.empty()
        for n in days_with_meals:
            total = total + n
        count = len(days_with_meals)
        avg = NutritionData(
            calories=total.calories // count,
            protein=total.protein // count,
            carbs=total.carbs // count,
            fat=total.fat // count,
        )
    else:
        avg = NutritionData.empty()

    # Format week dates
    first_date = days[0]['date']
    last_date = days[6]['date']
    week_label = f"Week {week_num} ({first_date.strftime('%b %d')} - {last_date.strftime('%b %d')})"

    # Generate markdown
    daily_rows = []
    for day_data, nutrition in zip(days, daily_nutrition):
        has_meals = any(day_data.get(m) for m in ['breakfast', 'lunch', 'dinner'])
        row = format_daily_summary_row(day_data['day'], nutrition, targets, has_meals)
        daily_rows.append(row)

    # Calculate differences for averages
    cal_diff = avg.calories - targets.calories
    protein_diff = avg.protein - targets.protein
    carbs_diff = avg.carbs - targets.carbs
    fat_diff = avg.fat - targets.fat

    def format_diff(val: int, is_macro: bool = True) -> str:
        sign = "+" if val > 0 else ""
        suffix = "g" if is_macro else ""
        return f"{sign}{val}{suffix}"

    # Build warnings section
    warnings_section = ""
    if warnings:
        warnings_lines = "\n".join(f"- {w}" for w in warnings)
        warnings_section = f"\n## Warnings\n\n{warnings_lines}\n"

    markdown = f"""---
week: {week}
generated: {datetime.now().isoformat(timespec='seconds')}
---

# Nutrition Dashboard

**Week:** [[{week}|{week_label}]]
**Targets:** [[My Macros]]

## Daily Summary

| Day       | Calories     | Protein    | Carbs      | Fat       |
|-----------|--------------|------------|------------|-----------|
{chr(10).join(daily_rows)}

## Week Averages

| Macro    | Average | Target | Difference |
|----------|---------|--------|------------|
| Calories | {avg.calories} | {targets.calories} | {format_diff(cal_diff, False)} |
| Protein  | {avg.protein}g | {targets.protein}g | {format_diff(protein_diff)} |
| Carbs    | {avg.carbs}g | {targets.carbs}g | {format_diff(carbs_diff)} |
| Fat      | {avg.fat}g | {targets.fat}g | {format_diff(fat_diff)} |
{warnings_section}
---
*Generated by KitchenOS • [Refresh](http://localhost:5001/refresh-nutrition?week={week})*
"""

    return markdown, warnings


def save_dashboard(
    week: str,
    vault_path: Path,
    dry_run: bool = False
) -> tuple[str, list[str]]:
    """Generate and save nutrition dashboard.

    Args:
        week: Week identifier (e.g., "2026-W03")
        vault_path: Path to the Obsidian vault
        dry_run: If True, don't write file

    Returns:
        Tuple of (file path, list of warnings)
    """
    markdown, warnings = generate_dashboard(week, vault_path)
    output_path = vault_path / "Nutrition Dashboard.md"

    if not dry_run:
        output_path.write_text(markdown, encoding='utf-8')

    return str(output_path), warnings
