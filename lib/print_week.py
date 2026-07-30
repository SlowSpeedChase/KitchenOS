"""Assemble and render a printable "week packet".

One print-ready page for an ISO week: the plan grid, each day's macros against
the user's targets, the consolidated shopping list, and the do-ahead prep. It is
pure composition of existing readers — it writes nothing.

The week lives in one of two models, and they must not be mixed:
- **ledger** (cooks/placements in the DB) — authoritative, coverage-aware macros
  via ``serving_ledger.day_totals``; the grid comes from slot placements.
- **markdown** (``Meal Plans/<week>.md``) — macros via
  ``nutrition_dashboard.compute_dashboard`` (handles meal expansion + servings),
  the grid from ``meal_plan_parser.parse_meal_plan``.

``shopping_list_generator.generate_shopping_list`` already decides which model
owns the week (its ``source`` field), so one call yields both the shopping list
and the branch signal — no second, possibly-disagreeing test.
"""

from __future__ import annotations

from datetime import timedelta
from html import escape
from pathlib import Path
from typing import Optional
from urllib.parse import quote

_MEALS = ("breakfast", "lunch", "snack", "dinner")
_MEAL_LABELS = {"breakfast": "Breakfast", "lunch": "Lunch",
                "snack": "Snack", "dinner": "Dinner"}
_DEFAULT_TARGETS = {"calories": 2000, "protein": 150, "carbs": 200, "fat": 65}


# ---- data assembly --------------------------------------------------------

def _entry_slot(entry) -> Optional[dict]:
    """A meal-plan ``MealEntry`` as a render dict, or None for an empty slot."""
    if entry is None or not getattr(entry, "name", None):
        return None
    return {"name": entry.name, "kind": getattr(entry, "kind", "recipe"),
            "servings": float(getattr(entry, "servings", 1) or 1)}


def _markdown_week(week: str, vault_path: Path) -> tuple[list[dict], dict, list[str]]:
    """Days + targets + warnings for a markdown-plan week."""
    from lib import nutrition_dashboard
    from lib.meal_plan_parser import parse_meal_plan

    dash = nutrition_dashboard.compute_dashboard(week, vault_path)  # may raise FileNotFoundError
    content = (vault_path / "Meal Plans" / f"{week}.md").read_text(encoding="utf-8")
    year, week_num = int(week[:4]), int(week.split("-W")[1])
    parsed = parse_meal_plan(content, year, week_num)

    days = []
    for drec, pday in zip(dash["days"], parsed):
        slots = {m: ([_entry_slot(pday.get(m))] if _entry_slot(pday.get(m)) else [])
                 for m in _MEALS}
        macros = None
        if drec["has_meals"]:
            macros = {k: drec[k] for k in ("calories", "protein", "carbs", "fat")}
        days.append({"day": drec["day"], "date": drec["date"],
                     "slots": slots, "macros": macros, "incomplete": False})
    return days, dash["targets"], dash["warnings"]


def _ledger_week(week: str, recipes_dir: Path,
                 targets: dict) -> tuple[list[dict], list[str]]:
    """Days for a ledger-owned week (slot placements + coverage-aware totals)."""
    from lib import serving_ledger
    from lib.meal_plan_parser import get_week_start_date

    year, week_num = int(week[:4]), int(week.split("-W")[1])
    start = get_week_start_date(year, week_num)
    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday",
                 "Friday", "Saturday", "Sunday"]

    placements = serving_ledger.placements_for_week(week)
    totals = serving_ledger.day_totals(week, recipes_dir)

    by_date: dict[str, dict] = {}
    for p in placements:
        slot = by_date.setdefault(p["date"], {m: [] for m in _MEALS})
        meal = p.get("meal")
        if meal in slot:
            slot[meal].append({"name": p["recipe"], "kind": "recipe",
                               "servings": float(p.get("count", 1) or 1)})

    days = []
    for i, day_name in enumerate(day_names):
        date_iso = (start + timedelta(days=i)).isoformat()
        slots = by_date.get(date_iso, {m: [] for m in _MEALS})
        t = totals.get(date_iso)
        macros = None
        incomplete = False
        if t:
            macros = {k: round(t[k]) for k in ("calories", "protein", "carbs", "fat")}
            incomplete = bool(t.get("incomplete"))
        days.append({"day": day_name, "date": date_iso,
                     "slots": slots, "macros": macros, "incomplete": incomplete})
    return days, []


def _targets_dict(vault_path: Path) -> tuple[dict, list[str]]:
    from lib.macro_targets import load_macro_targets
    t = load_macro_targets(vault_path)
    if t is None:
        return dict(_DEFAULT_TARGETS), ["My Macros.md not found, using default targets"]
    return {"calories": t.calories, "protein": t.protein,
            "carbs": t.carbs, "fat": t.fat}, []


def build_week_packet(week: str, vault_path: Path, recipes_dir: Path, *,
                      pantry: Optional[list[dict]] = None,
                      include_tasks: bool = False) -> dict:
    """Assemble the print packet for ``week``. Pure w.r.t. the vault (no writes).

    Args:
        week: ISO week ``YYYY-Wnn``.
        vault_path / recipes_dir: resolved vault + Recipes dir.
        pantry: pantry rows for the shopping split; loaded from the DB when None.
        include_tasks: when True, regenerate prep tasks if the cache is stale
            (an LLM call). Default False keeps the page read-only/fast — it uses
            only the cached sidecar and flags when none exists.
    """
    from lib import shopping_list_generator, task_extractor

    if pantry is None:
        from lib.pantry import load_pantry
        pantry = load_pantry()

    shop = shopping_list_generator.generate_shopping_list(week, pantry=pantry)
    source = shop.get("source", "links")

    if source == "ledger":
        targets, target_warnings = _targets_dict(vault_path)
        days, warnings = _ledger_week(week, recipes_dir, targets)
        warnings = target_warnings + warnings
    else:
        days, targets, warnings = _markdown_week(week, vault_path)

    tasks_payload = task_extractor.load_cached_tasks(week)
    if tasks_payload is None and include_tasks:
        tasks_payload = task_extractor.extract_tasks(week)
    all_tasks = (tasks_payload or {}).get("tasks", [])
    do_ahead = [t for t in all_tasks if t.get("can_do_ahead") and not t.get("done")]

    week_label = f"{week}  ({days[0]['date']} → {days[-1]['date']})" if days else week
    return {
        "week": week,
        "week_label": week_label,
        "source": source,
        "targets": targets,
        "days": days,
        "shopping": {"items": shop.get("items", []),
                     "warnings": shop.get("warnings", [])},
        "do_ahead": do_ahead,
        "tasks_available": tasks_payload is not None,
        "warnings": warnings,
    }


# ---- rendering ------------------------------------------------------------

def _slot_html(slot_items: list[dict], base_url: str) -> str:
    if not slot_items:
        return "<span class='empty'>—</span>"
    parts = []
    for s in slot_items:
        name = s["name"]
        label = escape(name)
        if s.get("servings", 1) and float(s["servings"]) != 1:
            label += f" <span class='mult'>×{_fmt(s['servings'])}</span>"
        if s.get("kind") == "recipe":
            href = f"{base_url}/recipe-card/{quote(name)}"
            parts.append(f"<a href='{href}'>{label}</a>")
        else:
            parts.append(label)
    return "<br>".join(parts)


def _fmt(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else str(x)


def _macro_cell(macros: Optional[dict], targets: dict, incomplete: bool) -> str:
    if not macros:
        return "<span class='empty'>—</span>"
    warn = " <span class='warn' title='low-confidence or missing nutrition'>⚠</span>" if incomplete else ""
    return (f"{macros['protein']}/{targets['protein']}g P · "
            f"{macros['calories']}/{targets['calories']} kcal{warn}")


def render_packet_html(packet: dict, base_url: str = "") -> str:
    """Render the packet as a self-contained HTML fragment. Pure — no I/O."""
    base_url = base_url.rstrip("/")
    targets = packet["targets"]

    # Plan grid: one row per day, slot columns, then a macros-vs-target column.
    head = ("<tr><th>Day</th>"
            + "".join(f"<th>{_MEAL_LABELS[m]}</th>" for m in _MEALS)
            + "<th>Macros (actual / target)</th></tr>")
    rows = []
    for d in packet["days"]:
        cells = "".join(f"<td>{_slot_html(d['slots'][m], base_url)}</td>" for m in _MEALS)
        macro = _macro_cell(d["macros"], targets, d["incomplete"])
        rows.append(f"<tr><td class='day'>{escape(d['day'])}</td>{cells}"
                    f"<td class='macros'>{macro}</td></tr>")
    grid = (f"<table class='week-grid'><thead>{head}</thead>"
            f"<tbody>{''.join(rows)}</tbody></table>")

    # Shopping list.
    items = packet["shopping"]["items"]
    if items:
        shopping = "<ul class='checklist'>" + "".join(
            f"<li>☐ {escape(i)}</li>" for i in items) + "</ul>"
    else:
        shopping = "<p class='empty'>No items — nothing to buy, or the list isn't generated yet.</p>"

    # Do-ahead prep.
    if packet["do_ahead"]:
        prep = "<ul class='checklist'>" + "".join(
            f"<li>☐ <strong>{escape(t['day'])}:</strong> {escape(t['text'])} "
            f"<span class='meta'>({escape(t.get('recipe', ''))}"
            + (f", {t['time_minutes']} min" if t.get("time_minutes") else "")
            + ")</span></li>"
            for t in packet["do_ahead"]) + "</ul>"
    elif not packet["tasks_available"]:
        prep = ("<p class='empty'>Prep tasks aren't generated for this week yet — "
                "open the planner's Today's Prep panel, or reload with "
                "<code>?tasks=1</code>.</p>")
    else:
        prep = "<p class='empty'>Nothing to get ahead on this week.</p>"

    warnings = ""
    if packet["warnings"]:
        warnings = "<div class='warnings'>" + "".join(
            f"<div>⚠ {escape(w)}</div>" for w in packet["warnings"]) + "</div>"

    t = targets
    return (
        f"<h1>{escape(packet['week_label'])}</h1>"
        f"<p class='targets'>Daily target: <strong>{t['protein']}g</strong> protein · "
        f"<strong>{t['calories']}</strong> kcal · {t['carbs']}g C · {t['fat']}g F</p>"
        f"{warnings}"
        f"<section><h2>The week</h2>{grid}</section>"
        f"<section class='pagebreak'><h2>Shopping list</h2>{shopping}</section>"
        f"<section class='pagebreak'><h2>Get ahead this week</h2>{prep}</section>"
    )
