"""Render a week's meal-plan Markdown from the serving ledger.

The ledger (SQLite) is authoritative; this module regenerates the weekly
Markdown as a human-readable Obsidian view after every ledger mutation.
Weeks with no ledger rows are left alone so legacy hand-edited plans and
the link-scan shopping fallback keep working.
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
    """Regenerate the week's Markdown, only if the ledger owns that week."""
    cooks = serving_ledger.cooks_for_week(week)
    placements = serving_ledger.placements_for_week(week)
    if not cooks and not placements:
        return
    plans_dir = paths.meal_plans_dir()
    plans_dir.mkdir(parents=True, exist_ok=True)
    content = render_week_markdown(week, paths.recipes_dir())
    (plans_dir / f"{week}.md").write_text(content, encoding="utf-8")
