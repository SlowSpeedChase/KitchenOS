"""Generate nutrition dashboard from meal plans."""

import re
from datetime import datetime, date
from pathlib import Path
from typing import Optional

from lib.nutrition import NutritionData
from lib.macro_targets import load_macro_targets
from lib.meal_plan_parser import parse_meal_plan, MealEntry, flatten_to_recipes
from lib.recipe_parser import parse_recipe_file

#: The four slots a planned day can fill. One authority, so "is this day
#: planned" and "how much of it is planned" cannot drift apart.
MEAL_SLOTS = ('breakfast', 'lunch', 'snack', 'dinner')


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

    # A present-but-empty key is an absence, not a zero. Testing only for the
    # key's presence and then reading it as `int(x or 0)` turned a recipe with
    # no macros into a 0 kcal one, so instead of being reported as missing data
    # it silently *lowered* the day's total — and the day still counted as
    # planned. Zero stays a legitimate answer (black coffee); null does not.
    calories = fm.get('nutrition_calories')
    if calories is None or calories == '':
        return None

    def _int(key):
        return int(fm.get(key) or 0)

    return NutritionData(
        calories=_int('nutrition_calories'),
        protein=_int('nutrition_protein'),
        carbs=_int('nutrition_carbs'),
        fat=_int('nutrition_fat'),
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

    for meal in MEAL_SLOTS:
        entry = day_data.get(meal)
        if not entry:
            continue

        # Expand meal bundles to their sub-recipes so each contributes nutrition.
        if isinstance(entry, MealEntry):
            recipes = flatten_to_recipes(entry)
        else:
            recipes = [MealEntry(name=str(entry), servings=1)]

        for recipe_entry in recipes:
            nutrition = get_recipe_nutrition(recipe_entry.name, recipes_dir)
            if nutrition:
                total = total + nutrition * recipe_entry.servings
            else:
                missing.append(recipe_entry.name)

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


def compute_dashboard(
    week: str,
    vault_path: Path,
) -> dict:
    """Compute structured nutrition-dashboard data (no markdown).

    Pure data projection shared by the markdown generator and the
    `GET /api/nutrition/<week>` JSON endpoint.

    Returns a dict:
        {
          "week": str, "week_label": str,
          "targets": {calories, protein, carbs, fat},
          "days": [{day, date(iso), has_meals, slots_filled, slots_total,
                    calories, protein, carbs, fat}],
          "averages": {calories, protein, carbs, fat},
          "days_planned": int, "days_total": int,
          "slots_planned": int, "slots_total": int,
          "warnings": [str],
        }
    Days without meals have null macros.

    ``averages`` is per *planned* day and always has been. The counts beside it
    are the denominator it was missing: a week with one Sunday dinner on it
    averaged 715 kcal against a 2300 target, which reads as a starvation week
    rather than an unplanned one — the less you plan, the more alarming the
    dashboard gets. Redefining the average would trade one wrong number for
    another, so the fix is to say what it covers.
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

    # How much of each day is actually planned, not just whether anything is.
    # One filled slot used to count as a day's eating, which is what made an
    # unplanned week read as a starvation week.
    slots_per_day = []

    for day_data in days:
        filled = sum(1 for m in MEAL_SLOTS if day_data.get(m))
        slots_per_day.append(filled)
        if filled:
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

    # State the denominator. The averages are still "per planned day" — the
    # arithmetic is not silently redefined — but a reader comparing 715 kcal
    # against a 2300 target deserves to know it describes one Sunday rather
    # than a week of eating.
    days_planned = len(days_with_meals)
    days_total = len(days)
    slots_planned = sum(slots_per_day)
    if days_planned and days_planned < days_total:
        warnings.append(
            f"Averages cover {days_planned} of {days_total} days — the ones "
            f"with meals planned, not the whole week."
        )

    # Format week dates
    first_date = days[0]['date']
    last_date = days[6]['date']
    week_label = f"{first_date.strftime('%b %-d')} - {last_date.strftime('%b %-d')}, {first_date.year}"

    day_records = []
    for day_data, nutrition, filled in zip(days, daily_nutrition, slots_per_day):
        day_records.append({
            "day": day_data['day'],
            "date": day_data['date'].isoformat(),
            "has_meals": bool(filled),
            "slots_filled": filled,
            "slots_total": len(MEAL_SLOTS),
            "calories": nutrition.calories if nutrition else None,
            "protein": nutrition.protein if nutrition else None,
            "carbs": nutrition.carbs if nutrition else None,
            "fat": nutrition.fat if nutrition else None,
        })

    return {
        "week": week,
        "week_label": week_label,
        "targets": {
            "calories": targets.calories, "protein": targets.protein,
            "carbs": targets.carbs, "fat": targets.fat,
        },
        "days": day_records,
        "averages": {
            "calories": avg.calories, "protein": avg.protein,
            "carbs": avg.carbs, "fat": avg.fat,
        },
        # The denominator behind `averages`, so a surface can say what the
        # number covers instead of implying it covers the week.
        "days_planned": days_planned,
        "days_total": days_total,
        "slots_planned": slots_planned,
        "slots_total": days_total * len(MEAL_SLOTS),
        "warnings": warnings,
    }


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
    data = compute_dashboard(week, vault_path)
    targets = data["targets"]
    avg = data["averages"]
    warnings = data["warnings"]
    week_label = data["week_label"]

    # Generate markdown rows from the structured days.
    daily_rows = []
    for d in data["days"]:
        if not d["has_meals"]:
            daily_rows.append(f"| {d['day']} | — | — | — | — |")
        else:
            daily_rows.append(
                f"| {d['day']} | {d['calories']} / {targets['calories']} | "
                f"{d['protein']} / {targets['protein']}g | "
                f"{d['carbs']} / {targets['carbs']}g | "
                f"{d['fat']} / {targets['fat']}g |"
            )

    # Calculate differences for averages
    cal_diff = avg['calories'] - targets['calories']
    protein_diff = avg['protein'] - targets['protein']
    carbs_diff = avg['carbs'] - targets['carbs']
    fat_diff = avg['fat'] - targets['fat']

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
| Calories | {avg['calories']} | {targets['calories']} | {format_diff(cal_diff, False)} |
| Protein  | {avg['protein']}g | {targets['protein']}g | {format_diff(protein_diff)} |
| Carbs    | {avg['carbs']}g | {targets['carbs']}g | {format_diff(carbs_diff)} |
| Fat      | {avg['fat']}g | {targets['fat']}g | {format_diff(fat_diff)} |
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
