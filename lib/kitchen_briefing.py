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

WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday",
            "Friday", "Saturday", "Sunday")


def plate(today: date, cooks: list[dict]) -> list[dict]:
    """Today's placed servings, in meal order.

    A placement whose parent cook's ``date`` is strictly earlier than today
    is a leftover. This is simpler than ``lib/week_view.py``'s rule — that
    module treats *any* placement outside the cook's own ``(date, meal)`` as
    a leftover, so a same-day placement in a different meal slot counts there
    too. Here there is only one day in view, so "earlier date" is the whole
    story; ``cooks`` passed in must already be the union of this week's cooks
    and any cook whose leftovers land in this week (see ``build``), or a
    leftover from a prior ISO week would be invisible.
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

        today_idx = WEEKDAYS.index(day_name)

        def _days_ahead(t):
            """Ordinal distance to a *future* weekday this week, or None to
            exclude.

            The sidecar covers a single Monday-Sunday plan, not a rolling
            calendar, so this is a plain ordinal difference — no wraparound.
            A day this endpoint doesn't recognise (bad data) is skipped
            rather than crashing the whole block, and a day at or before
            today is not "ahead" of anything.
            """
            day = t.get("day")
            if day not in WEEKDAYS:
                return None
            delta = WEEKDAYS.index(day) - today_idx
            return delta if delta > 0 else None

        ahead = sorted(
            (t for t in tasks if t.get("can_do_ahead") and not t.get("done")
             and _days_ahead(t) is not None),
            key=_days_ahead,
        )
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
    # cook_now.generate defaults to limit=30 and sorts by score, not coverage —
    # and its scoring demotes exactly the recipes most likely to be fully
    # covered (all-staples and dessert-tier weighting). Measured against the
    # real library: 3 fully-covered recipes visible at the default limit, 21
    # at limit=1000. kitchen_today._cook_card passes limit=60 for the same
    # reason; this reason needs the whole library, so it goes further still.
    ranked = cook_now.generate(items=items, recipe_index=recipe_index,
                               today=today, limit=1000).get("recipes") or []
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


def look(recipe_index, items, today: date,
        degraded: Optional[list[str]] = None) -> list[dict]:
    """Three reasons to open the library, one recipe each.

    Never blended into a single score: "never made it", "you have the
    ingredients" and "it is August" are incommensurable, and any weighting
    would be invented rather than tuned. Each item carries its own reason
    instead, and a reason that yields nothing is simply absent.

    Each reason is computed under its own guard, labelled ``look:<reason>``
    in ``degraded`` when one is supplied — ``_fully_covered`` is by far the
    heaviest of the three, and must not take the other two down with it if it
    raises. With no ``degraded`` list (direct calls, e.g. from tests) a
    component failure propagates normally.
    """
    def _run(reason, build):
        if degraded is None:
            return build()
        return _safe(f"look:{reason}", [], degraded, build)

    picks = [
        ("never-cooked",
         _run("never-cooked", lambda: _never_cooked(recipe_index, 1)), True),
        ("on-hand",
         _run("on-hand", lambda: _fully_covered(recipe_index, items, today)), False),
        ("seasonal",
         _run("seasonal", lambda: _in_season(recipe_index, today)), False),
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


# Loader seams — one per data source, so `build` can be tested without a vault,
# a DB or a sidecar, and so every real call site lives in exactly one place.

def _load_recipe_index():
    from lib import paths
    from lib.recipe_index import get_recipe_index
    return get_recipe_index(paths.recipes_dir(), include_ingredients=True)


def _load_inventory():
    from lib.inventory import read_inventory
    return read_inventory()


def _load_cooks(week: str):
    """This week's cooks, plus any cook from another ISO week whose leftovers
    land in this week.

    A cook made Sunday (ISO week N) can have a slot placement on Monday
    (week N+1) — ``cooks.week`` alone would make that leftover invisible on
    Monday's briefing, which is the whole point of the plate line. Same
    pattern ``lib/week_view.py::render_week_markdown`` uses to fold foreign
    placements onto a week's board; ``plate`` itself stays a pure function
    over whatever cooks it is handed.
    """
    from lib import serving_ledger
    cooks = serving_ledger.cooks_for_week(week)
    known_ids = {c["id"] for c in cooks}
    extra = serving_ledger.placements_for_week(week)
    foreign_ids = {p["cook_id"] for p in extra if p["cook_id"] not in known_ids}
    cooks += [serving_ledger.get_cook(cid) for cid in sorted(foreign_ids)]
    return cooks


def _load_sidecar(week: str):
    """``(payload, is_fresh)``. NEVER regenerates — see the module docstring."""
    from lib import task_extractor
    cached = task_extractor.load_cached_tasks(week)
    if cached is None:
        return None, False
    return cached, task_extractor._is_cache_fresh(week, cached)


def _load_verdict(today: date):
    from lib import kitchen_today
    return kitchen_today.verdict_prompt(today)


def _safe(label: str, fallback, degraded: list[str], build):
    """Run one component, or record why it is missing.

    A block that quietly drops a line is indistinguishable from a day with
    nothing to say, so every failure names itself in ``degraded`` rather than
    vanishing.
    """
    try:
        return build()
    except Exception:
        if label not in degraded:
            degraded.append(label)
        return fallback


def _display_map(recipe_index: list[dict]) -> dict:
    """Ledger basename -> `short_title` override, for every recipe that has one."""
    return {r.get("name"): r.get("display_name") for r in recipe_index}


def _apply_display_names(plate_items: list[dict], recipe_index: list[dict]) -> None:
    """Rewrite plate recipe names to their `short_title` override, in place."""
    display = _display_map(recipe_index)
    for item in plate_items:
        item["recipe"] = display.get(item["recipe"]) or item["recipe"]


def build(today: Optional[date] = None) -> dict:
    """Assemble the whole kitchen block for one day."""
    from lib import plan_week

    today = today or date.today()
    week = plan_week.current_week(today)
    degraded: list[str] = []

    recipe_index = _safe("recipe-index", [], degraded, _load_recipe_index)
    inventory = _safe("inventory", [], degraded, _load_inventory)
    cooks = _safe("ledger", [], degraded, lambda: _load_cooks(week))
    cached, fresh = _safe("tasks-sidecar", (None, False), degraded,
                          lambda: _load_sidecar(week))
    if cached is not None and not fresh:
        degraded.append("tasks-sidecar-stale")
    verdict = _safe("verdict", None, degraded, lambda: _load_verdict(today))
    if verdict:
        # Same basename/display-name split as the plate: the ledger names the
        # note, the block names what a surface should show. 70 of 411 recipes
        # carry a `short_title`, so left unmapped the verdict rung could name
        # the same dish differently from the plate line above it.
        display = _display_map(recipe_index)
        verdict = {**verdict,
                   "recipe": display.get(verdict.get("recipe")) or verdict.get("recipe")}

    plate_items = _safe("plate", [], degraded, lambda: plate(today, cooks))
    # The ledger stores the note basename; the block renders what a surface
    # should show. Resolved here because this is where the index is already in
    # hand — `plate` itself stays index-free and therefore trivially testable.
    _safe("plate-names", None, degraded,
          lambda: _apply_display_names(plate_items, recipe_index))

    return {
        "date": today.isoformat(),
        "week": week,
        "plate": plate_items,
        "next": _safe("next", None, degraded,
                      lambda: next_action(today, week, cached, fresh,
                                          plate_items, verdict)),
        "at_risk": _safe("at-risk", [], degraded,
                         lambda: at_risk(inventory, today)),
        "look": look(recipe_index, inventory, today, degraded),
        "degraded": degraded,
    }
