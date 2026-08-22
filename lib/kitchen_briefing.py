"""The kitchen block Selene's morning briefing carries.

Assembled here rather than in Selene so that inventory coverage, expiry
ranking and seasonality have exactly one implementation. Selene renders; this
module decides.

Two disciplines are copied from ``lib/kitchen_today.py``, both learned the
hard way there:

**The recipe library is parsed once.** ``cook_now`` and ``use_it_up`` each fall
back to reading and parsing every recipe file when called bare. ``build`` loads
the index and inventory once and injects them.

**No component can take the block down.** Every part is computed under
``_safe`` and degrades to absence, with the reason named in ``degraded`` so a
missing line is never mistaken for a quiet day.

The block is also *cheap by contract*: it is fetched at 06:00 by a job whose
other work is already done, so it must never trigger the LLM task-classification
pass. It reads the sidecar only when already fresh — the same rule
``kitchen_today._prep_card`` follows, and for the same reason.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

MEAL_ORDER = ("breakfast", "lunch", "snack", "dinner")


def plate(today: date, cooks: list[dict]) -> list[dict]:
    """Today's placed servings, in meal order.

    A placement whose parent cook sits on an *earlier* date is a leftover —
    the same distinction ``lib/week_view.py`` draws when it renders
    ``(leftover xN)``.
    """
    iso = today.isoformat()
    rows = []
    for cook in cooks:
        for p in cook.get("placements") or []:
            if p.get("destination") != "slot" or p.get("date") != iso:
                continue
            if not p.get("count"):
                continue
            cook_date = cook.get("date")
            rows.append({
                "meal": p.get("meal"),
                "recipe": cook.get("recipe"),
                "leftover": bool(cook_date and cook_date < iso),
            })

    def _rank(row):
        meal = row["meal"]
        return MEAL_ORDER.index(meal) if meal in MEAL_ORDER else len(MEAL_ORDER)

    rows.sort(key=_rank)

    seen, out = set(), []
    for row in rows:
        key = (row["meal"], row["recipe"], row["leftover"])
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def next_action(today: date, week: str, cached: Optional[dict], fresh: bool,
                plate_items: list[dict], verdict: Optional[dict]) -> Optional[dict]:
    """The one thing to do about the kitchen today.

    A strict ladder, not a ranking: today's prep step, then a do-ahead worth
    pulling forward, then the pending verdict, then — only when nothing is
    planned at all — planning the week. When every rung is empty the line is
    omitted rather than filled with something weaker.

    ``cached``/``fresh`` come from ``task_extractor.load_cached_tasks`` and
    ``_is_cache_fresh``. A stale or missing sidecar simply skips the first two
    rungs: regenerating it is an LLM pass this endpoint must never make.
    """
    if fresh and cached:
        tasks = cached.get("tasks") or []
        day_name = today.strftime("%A")

        todays = [t for t in tasks
                  if t.get("day") == day_name and not t.get("done")]
        if todays:
            return {"kind": "prep", "text": todays[0].get("text") or "",
                    "detail": None}

        ahead = [t for t in tasks
                 if t.get("day") != day_name
                 and t.get("can_do_ahead")
                 and not t.get("done")]
        if ahead:
            return {"kind": "ahead", "text": ahead[0].get("text") or "",
                    "detail": f"do-ahead for {ahead[0].get('day')}"}

    if verdict:
        return {"kind": "verdict",
                "text": f"how did {verdict.get('recipe')} go?",
                "detail": verdict.get("when")}

    if not plate_items:
        return {"kind": "plan-week", "text": "plan the week", "detail": week}

    return None


# Seams. Each wraps one existing library call so the assembly logic above can be
# tested without a vault, and so the real call sites stay in exactly one place.

def _at_risk_items(items, today):
    from lib.use_it_up import at_risk_items
    return at_risk_items(items, today=today)


def _never_cooked(recipe_index, limit):
    from lib import cook_history
    return cook_history.never_cooked(recipe_index, limit=limit)


def _fully_covered(recipe_index, items, today):
    """Recipes whose every non-staple ingredient is already in inventory.

    ``cook_now.generate`` returns ``{"recipes": [...]}`` and keys each entry's
    name as ``recipe``, so results are mapped back onto index entries here.
    All three seams then return the same shape and ``look`` stays uniform.
    """
    from lib import cook_now
    ranked = cook_now.generate(items=items, recipe_index=recipe_index,
                               today=today).get("recipes") or []
    by_name = {r.get("name"): r for r in recipe_index}
    out = []
    for entry in ranked:
        if entry.get("missing"):
            continue
        name = entry.get("recipe")
        out.append(by_name.get(name) or {"name": name, "display_name": name})
    return out


def _in_season(recipe_index, today):
    """Recipes whose frontmatter peak_months includes this month.

    Read straight off the index — `get_recipe_index` already carries
    `peak_months`, so no ingredient re-matching is needed.
    """
    month = today.month
    return [r for r in recipe_index if month in (r.get("peak_months") or [])]


_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _saved_on(added: Optional[str]) -> Optional[str]:
    """`2026-04-12` -> `saved 12 Apr`. None for an undated arrival."""
    if not added:
        return None
    try:
        d = date.fromisoformat(added[:10])
    except ValueError:
        return None
    return f"saved {d.day} {_MONTHS[d.month - 1]}"


def at_risk(items, today: date) -> list[dict]:
    """Inventory in the actionable expiry window, most urgent first.

    The window itself is KitchenOS's (-2/+3 days, staples excluded); this only
    reshapes it. Items are named, never counted: "3 items expiring" is not
    something anyone can act on.

    ``at_risk_items`` yields ``(status, item)`` — status first. Unpacking that
    backwards put the status string in the name field, which is invisible in a
    monkeypatched test and obvious on a real fridge.
    """
    return [
        {
            "item": getattr(item, "name", None),
            "status": status,
            "expires": getattr(item, "expires", None),
        }
        for status, item in _at_risk_items(items, today)
    ]


def look(recipe_index, items, today: date) -> list[dict]:
    """Three reasons to open the library, one recipe each.

    Never blended into a single score: "never made it", "you have the
    ingredients" and "it is August" are incommensurable, and any weighting
    would be invented rather than tuned. Each item carries its own reason
    instead, and a reason that yields nothing is simply absent.
    """
    picks = [
        ("never-cooked", _never_cooked(recipe_index, 1), True),
        ("on-hand", _fully_covered(recipe_index, items, today), False),
        ("seasonal", _in_season(recipe_index, today), False),
    ]
    details = {"on-hand": "all on hand", "seasonal": "peak now"}

    out, seen = [], set()
    for reason, candidates, dated in picks:
        for candidate in candidates:
            name = candidate.get("display_name") or candidate.get("name")
            if not name or name in seen:
                continue
            seen.add(name)
            out.append({
                "reason": reason,
                "recipe": name,
                "detail": _saved_on(candidate.get("added")) if dated
                          else details[reason],
            })
            break
    return out
