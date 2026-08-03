"""Assume a planned cook happened once its day has passed.

The kitchen only stays true if recording a cook is free. It wasn't: marking one
took reopening the planner, finding the card, opening a sheet on touch, tapping
🍳, and accepting a dialog warning that ingredients would be subtracted. Two of
sixteen cooks were ever marked, and inventory had zero rows use-stamped — so
shopping lists went on crediting food eaten weeks ago.

The project's own principle is "additive, never a chore": inventory features
must self-clean rather than require upkeep. Applied here that means the *plan*
is the record. If a cook was on Tuesday and it is now Wednesday, the honest
default is that it happened, because the alternative — believing the pantry is
untouched — is wrong far more often and degrades every downstream surface.

Deleting the card remains the way to say it didn't happen, which is a gesture
the user already makes for other reasons.

Two properties this leans on, both real:

- ``consume_recipe`` is conservative by construction. 188 of 198 count-family
  rows sit at exactly 1.0 meaning "one package", so it use-stamps rather than
  decrements in four separate cases. The usual outcome of a wrong assumption
  here is a ``last_used`` date, not a deleted jar.
- A missed depletion self-heals through the expiry prune. A wrongly deleted row
  does not, which is why the safe direction is to stamp rather than subtract.
"""

from __future__ import annotations

import logging
from datetime import date as _date
from typing import Optional

from lib import cook as cook_module
from lib import inventory_db, serving_ledger

log = logging.getLogger(__name__)


def consume_for_cook(cook: dict) -> Optional[dict]:
    """Spend the pantry for one cook. Never raises.

    Shared by the sweep and by ``PATCH /api/cooks/<id>``'s cooked_at transition
    so the two cannot drift: whichever notices the cook happened, the pantry is
    spent the same way, once, with the same failure behaviour.

    Returns ``consume_recipe``'s summary, or ``None`` if it raised. A failure is
    logged and swallowed because the cook record is the user's memory of what
    happened and inventory is derived from it — losing the record over a
    decrement error is the worse outcome.

    The summary is returned rather than a bool so the PATCH can report what it
    spent. The board used to get that summary by POSTing ``/api/cook`` right
    after its PATCH, which spent the pantry a *second* time — ``consume_recipe``
    is not idempotent. Callers must treat ``None`` as "nothing to show", never
    as an empty spend.
    """
    try:
        return cook_module.consume_recipe(
            cook["recipe"], servings=float(cook.get("scale") or 1.0))
    except Exception:
        log.exception("consume_recipe failed for cook %s (%s); cook still recorded",
                      cook.get("id"), cook.get("recipe"))
        return None


def due_cooks(today: Optional[str] = None) -> list[dict]:
    """Planned cooks whose day has passed and that nobody marked cooked.

    Strictly *before* today: a cook planned for this evening has not happened
    yet at the moment the nightly job runs. Undated cooks are never swept —
    there is no day to have passed, and the unscheduled tray is a parking space,
    not a claim about the past.
    """
    cutoff = today or _date.today().isoformat()
    conn = inventory_db.read_conn()
    rows = conn.execute(
        "SELECT id FROM cooks"
        " WHERE cooked_at IS NULL AND date IS NOT NULL AND date < ?"
        " ORDER BY date, id",
        (cutoff,),
    ).fetchall()
    return [c for c in (serving_ledger.get_cook(r["id"]) for r in rows) if c]


def sweep(today: Optional[str] = None) -> dict:
    """Mark every due cook as cooked and spend the pantry for it.

    Returns ``{"marked": [...], "consumed": int, "failed": int}``. Idempotent:
    a swept cook has a ``cooked_at`` and so is not due again.
    """
    marked: list[str] = []
    consumed = 0
    failed = 0

    for cook in due_cooks(today):
        # Stamp at the planned day's end rather than "now", so `last_cooked`
        # reflects when it was eaten and not when the job noticed.
        stamp = f"{cook['date']}T20:00:00Z"
        try:
            updated = serving_ledger.update_cook(cook["id"], cooked_at=stamp)
        except Exception:
            log.exception("could not mark cook %s cooked", cook.get("id"))
            failed += 1
            continue
        marked.append(updated["recipe"])
        # `is not None`: the summary is a dict now, and "ran but decremented
        # nothing" is a success, not a failure.
        if consume_for_cook(updated) is not None:
            consumed += 1
        else:
            failed += 1

    return {"marked": marked, "consumed": consumed, "failed": failed}
