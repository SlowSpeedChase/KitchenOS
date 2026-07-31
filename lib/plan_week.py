"""The Sunday-planning "command center" — one calm front door for the week.

Collapses the five surfaces into a single, guided page for one ISO week: a
glanceable per-day status (slots filled, protein vs target) built from
``print_week.build_week_packet``, then three big actions — fill the week,
review nutrition, print the week. The point is to remove the "where do I even
start" friction: open one page, follow three steps.
"""

from __future__ import annotations

from datetime import date, timedelta
from html import escape
from typing import Optional

from lib.meal_plan_parser import get_week_start_date

_MEALS = ("breakfast", "lunch", "snack", "dinner")


def shift_week(week: str, delta_weeks: int) -> str:
    """Return the ISO week ``delta_weeks`` away from ``week`` (handles year rollover)."""
    year, week_num = int(week[:4]), int(week.split("-W")[1])
    monday = get_week_start_date(year, week_num) + timedelta(weeks=delta_weeks)
    iso = monday.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def default_week(today: Optional[date] = None) -> str:
    """The week the Sunday ritual plans: next week (today + 7 days)."""
    d = (today or date.today()) + timedelta(days=7)
    iso = d.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def current_week(today: Optional[date] = None) -> str:
    """The week you are *in* — distinct from :func:`default_week`, which is the
    week you are planning.

    Anything about what to do right now (today's prep) needs this one; putting
    ``default_week`` there would report next week's tasks as today's.
    """
    iso = (today or date.today()).isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _day_status_row(d: dict, targets: dict, base_url: str) -> str:
    filled = sum(1 for m in _MEALS if d["slots"].get(m))
    dots = "".join("●" if d["slots"].get(m) else "○" for m in _MEALS)
    dot_cls = "full" if filled == len(_MEALS) else ("some" if filled else "empty")
    if d["macros"]:
        p, tp = d["macros"]["protein"], targets["protein"]
        ok = tp and p >= 0.9 * tp
        macro = (f"<span class='p {'ok' if ok else 'low'}'>{p}/{tp}g protein</span>")
    else:
        macro = "<span class='p empty'>—</span>"
    return (f"<tr><td class='day'>{escape(d['day'])}</td>"
            f"<td class='dots {dot_cls}' title='{filled}/4 slots filled'>{dots}</td>"
            f"<td class='macro'>{macro}</td></tr>")


def render_plan_center_html(week: str, packet: Optional[dict], targets: dict,
                            base_url: str, prev_week: str, next_week: str) -> str:
    """Render the plan-week command center. Pure — no I/O."""
    base = base_url.rstrip("/")
    t = targets

    nav = (f"<div class='weeknav'>"
           f"<a href='{base}/plan-week?week={prev_week}'>← {prev_week}</a>"
           f"<span class='cur'>{escape(week)}</span>"
           f"<a href='{base}/plan-week?week={next_week}'>{next_week} →</a></div>")

    if packet and any(d["macros"] for d in packet["days"]):
        rows = "".join(_day_status_row(d, t, base) for d in packet["days"])
        status = (f"<table class='status'><tbody>{rows}</tbody></table>")
        planned_days = sum(1 for d in packet["days"] if any(d["slots"].get(m) for m in _MEALS))
        lead = f"<p class='lead'>{planned_days}/7 days have meals. Fill the gaps, then print.</p>"
    else:
        status = ("<p class='empty-week'>This week is empty. Start by filling it "
                  "in the planner — tap an empty slot and hit <em>suggest</em> to "
                  "hit your macros.</p>")
        lead = "<p class='lead'>Nothing planned yet — three steps below.</p>"

    actions = (
        f"<div class='actions'>"
        f"<a class='action fill' href='{base}/meal-planner?week={week}'>"
        f"<span class='n'>1</span><span class='t'>🍳 Fill the week</span>"
        f"<span class='d'>drag recipes on, or tap a blank slot → suggest (hits your macros)</span></a>"
        f"<a class='action macros' href='{base}/nutrition-review'>"
        f"<span class='n'>2</span><span class='t'>🥗 Review nutrition</span>"
        f"<span class='d'>fix any weak recipe macros so the numbers are trustworthy</span></a>"
        f"<a class='action print' href='{base}/print/week?week={week}'>"
        f"<span class='n'>3</span><span class='t'>🖨️ Print the week</span>"
        f"<span class='d'>one page for the fridge: plan, macros, shopping, prep</span></a>"
        f"</div>")

    return (
        f"<h1>Plan your week</h1>"
        f"{nav}"
        f"<p class='targets'>Daily target: <strong>{t['protein']}g</strong> protein · "
        f"<strong>{t['calories']}</strong> kcal</p>"
        f"{lead}"
        f"<section class='status-wrap'>{status}</section>"
        f"{actions}"
    )
