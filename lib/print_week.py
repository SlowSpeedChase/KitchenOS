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

import re

from datetime import timedelta
from html import escape
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from templates.meal_plan_template import format_week_heading

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
    # all_entries: the default parse keeps only a slot's FIRST entry, which
    # printed one of two planned breakfasts while the macros counted both.
    parsed = parse_meal_plan(content, year, week_num, all_entries=True)

    days = []
    for drec, pday in zip(dash["days"], parsed):
        slots = {m: [s for s in map(_entry_slot, pday.get(m) or []) if s]
                 for m in _MEALS}
        macros = None
        if drec["has_meals"]:
            macros = {k: drec[k] for k in ("calories", "protein", "carbs", "fat")}
        days.append({"day": drec["day"], "date": drec["date"], "slots": slots,
                     "macros": macros, "incomplete": False, "excluded": []})
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
        excluded: list[str] = []
        if t:
            macros = {k: round(t[k]) for k in ("calories", "protein", "carbs", "fat")}
            incomplete = bool(t.get("incomplete"))
            # Carried through so the packet can NAME the untrusted recipes. This
            # is printed and read away from the screen, so a bare ⚠ is the one
            # warning a reader cannot go and investigate.
            excluded = list(t.get("excluded") or [])
        days.append({"day": day_name, "date": date_iso, "slots": slots,
                     "macros": macros, "incomplete": incomplete,
                     "excluded": excluded})
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
                      include_tasks: bool = False,
                      include_recipes: bool = True) -> dict:
    """Assemble the print packet for ``week``. Pure w.r.t. the vault (no writes).

    Args:
        week: ISO week ``YYYY-Wnn``.
        vault_path / recipes_dir: resolved vault + Recipes dir.
        pantry: pantry rows for the shopping split; loaded from the DB when None.
        include_tasks: when True, regenerate prep tasks if the cache is stale
            (an LLM call). Default False keeps the page read-only/fast — it uses
            only the cached sidecar and flags when none exists.
        include_recipes: append each planned recipe's ingredients and steps
            (``packet["recipes"]``), one page per recipe. On by default: a
            printed week is cooked from, and a packet without steps sends you
            back to a screen at the stove.
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

    # The printed page goes on the fridge — "2026-W31" on it helps nobody.
    week_label = format_week_heading(week)
    return {
        "week": week,
        "week_label": week_label,
        "source": source,
        "targets": targets,
        "days": days,
        "shopping": {"items": shop.get("items", []),
                     "warnings": shop.get("warnings", [])},
        # Every ingredient, owned or not, grouped by where it lives. Print
        # only: `items` stays the purchase-only contract every other consumer
        # (Reminders, confirm, MCP) relies on.
        "shopping_by_location": shopping_by_location(
            shop.get("lines", []), _recipe_ingredients(shop.get("recipes", [])),
            _inventory_rows()),
        "do_ahead": do_ahead,
        "tasks_available": tasks_payload is not None,
        "warnings": warnings,
        "recipes": _recipe_pages(days, recipes_dir) if include_recipes else [],
    }


def _recipe_pages(days: list[dict], recipes_dir: Path) -> list[dict]:
    """Each recipe on the week's grid, once, in the order it first appears.

    Leftover placements repeat a recipe across days; it is printed once. Meal
    bundles in a markdown week (``kind != "recipe"``) are skipped, as are names
    with no recipe file — the grid already shows them, and an empty page helps
    nobody at the stove.
    """
    from lib.recipe_parser import parse_recipe_file, parse_recipe_body

    seen: list[str] = []
    for d in days:
        for meal in _MEALS:
            for item in d["slots"].get(meal, []):
                if item.get("kind") == "recipe" and item["name"] not in seen:
                    seen.append(item["name"])

    pages = []
    for name in seen:
        path = (recipes_dir / f"{name}.md").resolve()
        if not path.is_relative_to(recipes_dir.resolve()) or not path.exists():
            continue
        try:
            parsed = parse_recipe_file(path.read_text(encoding="utf-8"))
            body = parse_recipe_body(parsed["body"])
        except Exception:
            continue
        fm = parsed["frontmatter"]
        pages.append({
            "name": name,
            "title": fm.get("title") or name,
            "servings": fm.get("servings"),
            "total_time": fm.get("total_time"),
            "ingredients": body.get("ingredients", []),
            "instructions": body.get("instructions", []),
        })
    return pages


# ---- shopping list by location -----------------------------------------------

# Kitchen-walk order: cold first (it's what you check before leaving), then
# the cupboards. Anything else lands last.
_LOCATION_ORDER = ("fridge", "freezer", "pantry", "counter", "other")
_LOCATION_LABELS = {"fridge": "Fridge", "freezer": "Freezer", "pantry": "Pantry",
                    "counter": "Counter", "other": "Not sure where it goes"}


def _recipe_ingredients(recipe_names: list[str]) -> dict[str, list[dict]]:
    from lib.shopping_list_generator import load_recipe_ingredients
    out = {}
    for name in recipe_names:
        try:
            ingredients, _warning = load_recipe_ingredients(name)
        except Exception:
            ingredients = []
        out[name] = ingredients or []
    return out


def _inventory_rows():
    try:
        from lib.inventory import read_inventory
        return read_inventory()
    except Exception:
        return []


def _default_place(name: str) -> Optional[str]:
    """The storage table's answer, or None when it only shrugged.

    ``place_item``'s ``default`` tier is "pantry" for anything it doesn't know
    — yogurt and mozzarella included — so a shrug is reported as unknown
    rather than printed as a confident wrong shelf.
    """
    from lib.grocery_catalog import assign_category
    from lib.storage_locations import place_item
    placed = place_item(name, assign_category(name))
    return None if placed.source == "default" else placed.location


def _head(name: str) -> str:
    return _head_pair(name)[0]


def _head_pair(name: str) -> tuple[str, str]:
    from lib.fdc_local import query_head
    try:
        head, qualifier = query_head(name)
        return head or "", qualifier or ""
    except Exception:
        return "", ""


# Words that make a different product of the same head noun. One side naming
# one and the other not ("unsweetened nondairy milk" vs "whole milk") is a
# different food even though both are milk.
_PRODUCT_WORDS = frozenset({
    "nondairy", "non-dairy", "dairy-free", "vegan", "plant", "plant-based",
    "almond", "oat", "soy", "coconut", "rice", "cashew", "gluten-free",
    "sugar-free", "decaf", "low-sodium", "reduced-sodium", "lite", "light",
    "fat-free", "nonfat", "powdered", "dried", "dry", "canned", "smoked",
})


def same_food(wanted: str, owned: str) -> bool:
    """True when an inventory row is the same food the recipe asks for.

    Same head noun, qualifiers that don't contradict (equal, or one side
    unqualified), and no product-changing word on only one side. Used to tick
    a ``review`` match on paper: frozen blueberries are blueberries and
    Celtic sea salt is sea salt, but oat flour is not all-purpose flour and
    nondairy milk is not whole milk. A miss leaves the box unticked with a
    note, the safe direction.
    """
    (h1, q1), (h2, q2) = _head_pair(wanted), _head_pair(owned)
    if not h1 or h1 != h2 or (q1 and q2 and q1 != q2):
        return False
    w1 = set(re.findall(r"[a-z][a-z-]*", wanted.lower())) & _PRODUCT_WORDS
    w2 = set(re.findall(r"[a-z][a-z-]*", owned.lower())) & _PRODUCT_WORDS
    return w1 == w2


def shopping_by_location(lines: list[dict], recipe_ingredients: dict[str, list[dict]],
                         inventory, *, place=_default_place, head=_head) -> list[dict]:
    """Every ingredient of the week, grouped by kitchen location. Pure.

    ``lines`` are the generator's aggregated lines; their ``item`` is the
    ``normalize_item_name`` key, so each recipe's raw ingredients are keyed the
    same way to say which recipes need it. An owned item is filed where the
    inventory says it is. Anything to buy goes where you already keep that
    food (same head noun in inventory, majority location), else where the
    storage table puts it, else under "Not sure where it goes".

    ☑ means the inventory covers it: an exact match (``on_hand`` or a full
    ``credited``), or a ``review`` match that ``same_food`` confirms (the
    generator flags frozen blueberries for differing units). Any other related
    item (oat flour against all-purpose flour, pumpkin seeds against a
    pumpkin) stays ☐ with what you have, since a wrong tick is how you get
    home without the oat flour. A partial credit
    stays ☐ with how much more to buy.
    """
    from lib.ingredient_aggregator import format_ingredient, normalize_item_name

    used_by: dict[str, set] = {}
    for recipe, ingredients in recipe_ingredients.items():
        for ing in ingredients:
            key = normalize_item_name(ing.get("item", ""))
            if key:
                used_by.setdefault(key, set()).add(recipe)

    from collections import Counter
    where = {it.name.strip().lower(): it.location for it in inventory}
    by_head: dict[str, Counter] = {}
    for it in inventory:
        h = head(it.name)
        if h:
            by_head.setdefault(h, Counter())[it.location] += 1
    groups: dict[str, list[dict]] = {}
    for line in lines:
        status = line.get("status")
        if status == "excluded":
            continue
        matched = line.get("matched_inventory") or None
        to_buy = line.get("to_buy")
        owned = f"{matched.get('item')} ({format_ingredient({'amount': matched.get('amount', ''), 'unit': matched.get('unit', ''), 'item': ''}).strip()})" if matched else ""
        verify = False
        if status == "on_hand" or (matched and status == "credited" and not to_buy):
            have, note = True, f"have {owned}"
        elif status == "credited" and to_buy:
            more = format_ingredient({"amount": to_buy.get("amount", ""),
                                      "unit": to_buy.get("unit", ""), "item": ""}).strip()
            have, note = False, f"have {owned}; buy {more} more"
        elif matched and same_food(line.get("item", ""), matched.get("item", "")):
            have, note = True, f"have {owned}"
        elif matched:
            have, verify, note = False, True, f"you have {owned}; same thing?"
        else:
            have, note = False, ""
        item = line.get("item", "")
        location = where.get((matched.get("item") or "").strip().lower()) if matched else None
        if not location and by_head.get(head(item)):
            location = by_head[head(item)].most_common(1)[0][0]
        location = location or place(item)
        if location not in _LOCATION_LABELS:
            location = "other"
        groups.setdefault(location, []).append({
            "text": line.get("needed_display") or line.get("display") or line.get("item", ""),
            "have": have, "verify": verify, "note": note,
            "recipes": sorted(used_by.get(line.get("item", ""), ()), key=str.lower),
        })

    return [{"location": loc, "label": _LOCATION_LABELS[loc],
             "items": sorted(groups[loc], key=lambda i: (i["have"], i["text"].lower()))}
            for loc in _LOCATION_ORDER if loc in groups]


def render_shopping_html(groups: list[dict]) -> str:
    """Location sections of ☑/☐ rows. Plain HTML, never Markdown checkboxes."""
    if not groups:
        return "<p class='empty'>No ingredients — nothing planned, or recipes have no ingredient tables.</p>"
    out = []
    for g in groups:
        need = sum(1 for i in g["items"] if not i["have"])
        rows = []
        for i in g["items"]:
            box = "☑" if i["have"] else "☐"
            cls = "have" if i["have"] else "buy"
            note = (f" <span class='{'warn' if i['verify'] else 'meta'}'>{escape(i['note'])}</span>"
                    if i["note"] else "")
            recipes = (f"<span class='for'>{escape(', '.join(i['recipes']))}</span>"
                       if i["recipes"] else "")
            rows.append(f"<li class='{cls}'><span class='box'>{box}</span> "
                        f"<span class='what'>{escape(i['text'])}{note}</span>{recipes}</li>")
        out.append(f"<div class='loc'><h3>{escape(g['label'])} "
                   f"<span class='meta'>· {need} to buy</span></h3>"
                   f"<ul class='shop'>{''.join(rows)}</ul></div>")
    return "".join(out)


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


def _macro_cell(macros: Optional[dict], targets: dict, incomplete: bool,
                excluded: Optional[list] = None) -> str:
    """The day's macros against target, naming anything left out of them.

    `excluded` is rendered rather than folded into the ⚠, because this page is
    printed: a warning glyph on paper cannot be hovered, clicked, or chased back
    to the recipe that caused it. A day whose only recipe was excluded has no
    macros at all, so the exclusion is the entire content of the cell.
    """
    names = ", ".join(escape(n) for n in (excluded or []))
    note = f" <span class='warn'>excludes {names}</span>" if names else ""
    if not macros:
        return note.strip() or "<span class='empty'>—</span>"
    warn = " <span class='warn' title='low-confidence or missing nutrition'>⚠</span>" if incomplete else ""
    return (f"{macros['protein']}/{targets['protein']}g P · "
            f"{macros['calories']}/{targets['calories']} kcal{warn}{note}")


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
        macro = _macro_cell(d["macros"], targets, d["incomplete"],
                            d.get("excluded"))
        rows.append(f"<tr><td class='day'>{escape(d['day'])}</td>{cells}"
                    f"<td class='macros'>{macro}</td></tr>")
    grid = (f"<table class='week-grid'><thead>{head}</thead>"
            f"<tbody>{''.join(rows)}</tbody></table>")

    # Shopping list.
    shopping = render_shopping_html(packet.get("shopping_by_location") or [])

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

    recipe_pages = "".join(_recipe_page_html(r) for r in packet.get("recipes", []))

    t = targets
    return (
        f"<h1>{escape(packet['week_label'])}</h1>"
        f"<p class='targets'>Daily target: <strong>{t['protein']}g</strong> protein · "
        f"<strong>{t['calories']}</strong> kcal · {t['carbs']}g C · {t['fat']}g F</p>"
        f"{warnings}"
        f"<section><h2>The week</h2>{grid}</section>"
        f"<section class='shopping-page pagebreak'><h2>Shopping list</h2>{shopping}</section>"
        f"<section class='pagebreak'><h2>Get ahead this week</h2>{prep}</section>"
        f"{recipe_pages}"
    )


def _recipe_page_html(r: dict) -> str:
    """One recipe on its own printed page: ingredients, then numbered steps."""
    meta = " · ".join(escape(str(v)) for v in (
        f"{r['servings']} servings" if r.get("servings") else None,
        r.get("total_time")) if v)
    ings = "".join(
        "<li>☐ " + escape(" ".join(str(x) for x in (i.get("amount"), i.get("unit")) if x))
        + (" " if i.get("amount") or i.get("unit") else "") + escape(str(i.get("item", ""))) + "</li>"
        for i in r.get("ingredients", []))
    steps = "".join(f"<li>{escape(str(s.get('text', '')))}</li>"
                    for s in r.get("instructions", []))
    return (
        f"<section class='recipe-page pagebreak'><h2>{escape(str(r['title']))}</h2>"
        + (f"<p class='recipe-meta'>{meta}</p>" if meta else "")
        + (f"<h3>Ingredients</h3><ul class='checklist'>{ings}</ul>" if ings else "")
        + (f"<h3>Steps</h3><ol class='steps'>{steps}</ol>" if steps else "")
        + ("" if ings or steps else "<p class='empty'>No ingredients or steps in this recipe file.</p>")
        + "</section>"
    )
