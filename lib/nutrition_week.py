"""The week's nutrition as a web page — each day against your macro targets.

The same numbers live in ``Nutrition Dashboard.md`` at the vault root, but that
file only opens in Obsidian and is rewritten once a day at 06:15. This renders
them on demand from ``print_week.build_week_packet`` (the model the planner,
the plan-week page and the fridge printout already share), so the page can
never disagree with the plan you are looking at.

Pure — no I/O. The route assembles the packet; this turns it into HTML.
"""

from __future__ import annotations

from html import escape
from typing import Optional

from templates.meal_plan_template import format_week_heading, format_week_range

_MACROS = (("calories", "kcal", ""), ("protein", "Protein", "g"),
           ("carbs", "Carbs", "g"), ("fat", "Fat", "g"))

# Within 10% of target reads as "on target". Under and over are both shown —
# protein is a floor you want to reach, calories a ceiling you want to respect,
# and the page states which side you are on instead of colouring both "bad".
_TOLERANCE = 0.10


def macro_state(value: float, target: float) -> str:
    """``under`` / ``on`` / ``over`` for one day's macro against its target."""
    if not target:
        return "on"
    ratio = value / target
    if ratio < 1 - _TOLERANCE:
        return "under"
    return "over" if ratio > 1 + _TOLERANCE else "on"


_STATE_ICON = {"under": "▽", "on": "✓", "over": "△"}
_STATE_WORD = {"under": "under", "on": "on target", "over": "over"}


def _cell(value: float, target: float, unit: str) -> str:
    state = macro_state(value, target)
    pct = min(100, round(100 * value / target)) if target else 0
    return (f"<td class='m {state}'>"
            f"<span class='v'>{round(value)}{unit}</span>"
            f"<span class='t'> / {round(target)}{unit}</span>"
            f"<span class='bar' aria-hidden='true'><span style='width:{pct}%'></span></span>"
            # Icon and word, never colour alone: the bar tint is a hint, not the message.
            f"<span class='s'>{_STATE_ICON[state]} {_STATE_WORD[state]}</span></td>")


def _day_row(d: dict, targets: dict) -> str:
    day = f"<th scope='row' class='day'>{escape(d['day'][:3])}</th>"
    excluded = ", ".join(escape(n) for n in (d.get("excluded") or []))
    note = ""
    if excluded:
        note = f"<tr class='note'><td colspan='5'>⚠ Not counted: {excluded}</td></tr>"
    elif d.get("incomplete"):
        note = ("<tr class='note'><td colspan='5'>⚠ Some of this day's nutrition is "
                "low-confidence</td></tr>")
    if not d.get("macros"):
        return f"<tr>{day}<td class='none' colspan='4'>Nothing planned</td></tr>{note}"
    cells = "".join(_cell(d["macros"][k], targets[k], unit) for k, _label, unit in _MACROS)
    return f"<tr>{day}{cells}</tr>{note}"


def week_average(days: list[dict]) -> Optional[dict]:
    """Mean of each macro over the days that have any — an empty day is not a
    zero-calorie day, and averaging it in would report a plan as a famine."""
    counted = [d["macros"] for d in days if d.get("macros")]
    if not counted:
        return None
    return {k: sum(m[k] for m in counted) / len(counted) for k, _l, _u in _MACROS}


def render_nutrition_week_html(week: str, packet: Optional[dict], targets: dict,
                               base_url: str, prev_week: str, next_week: str) -> str:
    base = base_url.rstrip("/")
    nav = (f"<div class='weeknav'>"
           f"<a href='{base}/nutrition?week={prev_week}'>"
           f"← {escape(format_week_range(prev_week, with_year=False))}</a>"
           f"<span class='cur'>{escape(format_week_heading(week))}</span>"
           f"<a href='{base}/nutrition?week={next_week}'>"
           f"{escape(format_week_range(next_week, with_year=False))} →</a></div>")
    head = "<h1>Nutrition this week</h1>" + nav

    days = (packet or {}).get("days") or []
    avg = week_average(days)
    if avg is None:
        return (head +
                "<p class='empty-week'>Nothing is planned for this week, so there is "
                "nothing to add up yet.</p>"
                f"<p><a class='go' href='{base}/meal-planner?week={week}'>"
                "Fill the week in the planner</a></p>")

    planned = sum(1 for d in days if d.get("macros"))
    header = "<tr><th></th>" + "".join(
        f"<th scope='col'>{label}</th>" for _k, label, _u in _MACROS) + "</tr>"
    rows = "".join(_day_row(d, targets) for d in days)
    avg_cells = "".join(_cell(avg[k], targets[k], unit) for k, _l, unit in _MACROS)
    warnings = "".join(f"<li>{escape(w)}</li>" for w in (packet or {}).get("warnings") or [])
    return (
        head +
        f"<p class='lead'>{planned} of 7 days planned. Each day against your daily target.</p>"
        f"<div class='scroll'><table class='nutri'><thead>{header}</thead>"
        f"<tbody>{rows}</tbody>"
        f"<tfoot><tr><th scope='row' class='day'>Avg</th>{avg_cells}</tr></tfoot></table></div>"
        + (f"<ul class='warnings'>{warnings}</ul>" if warnings else "") +
        f"<p class='links'><a class='go' href='{base}/meal-planner?week={week}'>Adjust the plan</a>"
        f"<a class='go' href='{base}/nutrition-review'>Fix weak recipe nutrition</a></p>"
    )
