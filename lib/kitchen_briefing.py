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
