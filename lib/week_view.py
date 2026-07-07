"""Render a week's meal-plan Markdown from the serving ledger.

The ledger (SQLite) is authoritative; this module regenerates the weekly
Markdown as a human-readable Obsidian view after every ledger mutation.
Weeks the ledger has never owned (no rows AND no plan file) are left
alone so legacy hand-edited plans and the link-scan shopping fallback
keep working; ``import_legacy_week`` converts a hand-edited week into
ledger cooks before the first mutation renders over it.
"""
from __future__ import annotations

from datetime import timedelta

from lib import paths, serving_ledger
from lib.meal_plan_parser import get_week_start_date, fmt_mult

MEALS = ("breakfast", "lunch", "snack", "dinner")
MEAL_LABELS = {"breakfast": "Breakfast", "lunch": "Lunch",
               "snack": "Snack", "dinner": "Dinner"}
DAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday",
             "Friday", "Saturday", "Sunday")


def _slot_lines(date_iso: str, meal: str, cooks: list[dict]) -> list[str]:
    lines: list[str] = []
    for cook in cooks:
        if cook["date"] == date_iso and cook["meal"] == meal:
            lines.append(f"[[{cook['recipe']}]] x{fmt_mult(cook['scale'])}")
            frozen = sum(p["count"] for p in cook["placements"]
                         if p["destination"] == "freezer")
            trashed = sum(p["count"] for p in cook["placements"]
                          if p["destination"] == "trash")
            summary = []
            if frozen:
                summary.append(f"Freezer: {fmt_mult(frozen)}")
            if trashed:
                summary.append(f"Trash: {fmt_mult(trashed)}")
            if cook["unassigned"] > 0:
                summary.append(f"Unassigned: {fmt_mult(cook['unassigned'])}")
            if summary:
                lines.append("> " + " · ".join(summary))
    # NOTE: "(leftover xN)" is display text; parse_meal_plan sees the link but not N — leftover-only slots round-trip with servings=1. Ledger weeks are re-rendered from the DB, so nothing is lost.
    for cook in cooks:
        for p in cook["placements"]:
            if (p["destination"] == "slot" and p["date"] == date_iso
                    and p["meal"] == meal
                    and not (cook["date"] == date_iso and cook["meal"] == meal)):
                lines.append(
                    f"[[{cook['recipe']}]] (leftover x{fmt_mult(p['count'])})")
    return lines


def render_week_markdown(week: str, recipes_dir) -> str:
    year, week_num = int(week[:4]), int(week.split("-W")[1])
    start = get_week_start_date(year, week_num)
    cooks = serving_ledger.cooks_for_week(week)
    # Leftovers from other weeks placed into this week's days:
    extra = serving_ledger.placements_for_week(week)
    known_ids = {c["id"] for c in cooks}
    foreign_cook_ids = {p["cook_id"] for p in extra
                        if p["cook_id"] not in known_ids}
    cooks += [serving_ledger.get_cook(cid) for cid in sorted(foreign_cook_ids)]
    totals = serving_ledger.day_totals(week, recipes_dir)

    def fmt_date(d):
        return d.strftime("%b %-d")

    end = start + timedelta(days=6)
    lines = [
        f"# Meal Plan - Week {week_num:02d}"
        f" ({fmt_date(start)} - {fmt_date(end)}, {year})",
        "",
        "```button",
        "name Generate Shopping List",
        "type link",
        f"action kitchenos://generate-shopping-list?week={week}",
        "```",
        "",
    ]
    for i, day_name in enumerate(DAY_NAMES):
        d = start + timedelta(days=i)
        date_iso = d.isoformat()
        lines.append(f"## {day_name} ({fmt_date(d)})")
        for meal in MEALS:
            lines.append(f"### {MEAL_LABELS[meal]}")
            lines.extend(_slot_lines(date_iso, meal, cooks))
        lines.append("### Notes")
        t = totals.get(date_iso)
        if t and any(t[k] for k in ("calories", "protein", "carbs", "fat")):
            flag = " ⚠" if t["incomplete"] else ""
            lines.append(
                f"Totals: {round(t['calories'])} kcal ·"
                f" {round(t['protein'])}p / {round(t['carbs'])}c /"
                f" {round(t['fat'])}f{flag}")
        lines.append("")
        lines.append("")
    return "\n".join(lines)


def write_week_markdown(week: str) -> None:
    """Regenerate the week's Markdown view from the ledger.

    A week the ledger has never owned (no rows AND no plan file) is
    skipped. When the plan file exists but the ledger just emptied (last
    cook deleted), the clean empty skeleton is written so stale cards and
    [[links]] don't linger (the link-scan grocery fallback would see
    phantom recipes). This is only called (via ``_regen_weeks``) for weeks
    a mutation touched, and the pre-mutation legacy import converts
    hand-edited files first, so untouched legacy weeks are never clobbered.
    """
    cooks = serving_ledger.cooks_for_week(week)
    placements = serving_ledger.placements_for_week(week)
    plans_dir = paths.meal_plans_dir()
    plan_file = plans_dir / f"{week}.md"
    if not cooks and not placements and not plan_file.exists():
        return
    plans_dir.mkdir(parents=True, exist_ok=True)
    content = render_week_markdown(week, paths.recipes_dir())
    plan_file.write_text(content, encoding="utf-8")


def recipe_base_servings(recipe_name: str) -> float:
    """Per-recipe servings from frontmatter, falling back to 4.

    Reads via a fresh ``paths.recipes_dir()`` call so tests that
    monkeypatch ``KITCHENOS_VAULT`` after import see the right directory.
    """
    from lib.recipe_parser import parse_recipe_file
    path = paths.recipes_dir() / f"{recipe_name}.md"
    if not path.exists():
        return 4.0
    try:
        fm = parse_recipe_file(path.read_text(encoding="utf-8"))["frontmatter"]
        servings = fm.get("servings")
        return float(servings) if servings else 4.0
    except Exception:
        return 4.0


def import_legacy_week(week: str) -> list[int]:
    """One-time conversion of a hand-edited week's Markdown to ledger cooks.

    Walks the week's plan file (if any) via parse_meal_plan and creates one
    cook per filled slot: scale = the entry's servings multiplier,
    servings_produced = recipe frontmatter servings x scale (fallback 4),
    all of it placed at that slot (legacy assumption: eaten there).
    Lines containing ``(leftover`` are display text this module renders
    for slot placements — they never represent a cook, so they are
    dropped before parsing. Callers must guard against weeks that already
    have ledger rows (cooks or placements); this function does not.
    Returns the created cook ids.
    """
    from lib.meal_plan_parser import parse_meal_plan, flatten_to_recipes
    plan_file = paths.meal_plans_dir() / f"{week}.md"
    imported: list[int] = []
    if not plan_file.exists():
        return imported
    year, week_num = int(week[:4]), int(week.split("-W")[1])
    content = plan_file.read_text(encoding="utf-8")
    content = "\n".join(line for line in content.splitlines()
                        if "(leftover" not in line)
    for day_data in parse_meal_plan(content, year, week_num):
        date_iso = day_data["date"].isoformat()
        for meal in MEALS:
            entry = day_data.get(meal)
            if entry is None:
                continue
            for sub in flatten_to_recipes(entry, meals_dir=paths.meals_dir()):
                scale = float(sub.servings)
                servings_produced = recipe_base_servings(sub.name) * scale
                cook = serving_ledger.create_cook(
                    recipe=sub.name, week=week, scale=scale,
                    servings_produced=servings_produced,
                    date=date_iso, meal=meal,
                    initial_placement_count=servings_produced)
                imported.append(cook["id"])
    return imported
