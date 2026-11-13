"""Run a Plan through the ledger and inventory code, and undo it.

Every handler calls the same functions the web UI's own endpoints call — this
module adds no new way to write a cook or an inventory row. What it adds is the
record: a before/after snapshot of each row a command touched. Undo restores
"before" and refuses if the row no longer matches "after".
"""
import sqlite3
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from lib import inventory_db
from lib.command import log
from lib.command.planner import Plan, day_text, describe
from lib.command.resolve import Kitchen
from lib.command.slots import iso_week


@dataclass
class Result:
    ok: bool
    lines: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    weeks: set = field(default_factory=set)
    recipes: set = field(default_factory=set)
    navigate: Optional[dict] = None
    undo: Optional[dict] = None
    error: Optional[str] = None


class _Run:
    def __init__(self, kitchen: Kitchen):
        self.kitchen = kitchen
        self.cooks: dict = {}          # str(cook id) -> {"before": snap}
        self.inventory: Optional[dict] = None
        self.new_cooks: dict = {}      # action index -> cook id
        self.result = Result(ok=True)

    def touch_cook(self, cook_id: int) -> None:
        key = str(cook_id)
        if key in self.cooks:
            return
        conn = inventory_db.connect()
        try:
            self.cooks[key] = {"before": log.snap_cook(conn, cook_id)}
        finally:
            conn.close()

    def created_cook(self, cook_id: int) -> None:
        self.cooks[str(cook_id)] = {"before": None}

    def touch_inventory(self) -> None:
        if self.inventory is None:
            self.inventory = {"before": inventory_db.fetch_inventory_rows()}

    def record(self) -> dict:
        conn = inventory_db.connect()
        try:
            for key, entry in self.cooks.items():
                entry["after"] = log.snap_cook(conn, int(key))
        finally:
            conn.close()
        if self.inventory is not None:
            self.inventory["after"] = inventory_db.fetch_inventory_rows()
        return {"cooks": self.cooks, "inventory": self.inventory,
                "weeks": sorted(self.result.weeks), "recipes": sorted(self.result.recipes)}

    def cook_id(self, ref: dict) -> int:
        return self.new_cooks[ref["new"]] if "new" in ref else ref["id"]


def _members(cook_id: int, bundle_id) -> list:
    from lib import serving_ledger
    if not bundle_id:
        return [cook_id]
    bundle = serving_ledger.get_bundle(bundle_id)
    return [c["id"] for c in bundle["cooks"]] if bundle else [cook_id]


def _plan_cook(run, index, action):
    from lib import serving_ledger, week_view
    a = action.args
    week = iso_week(date.fromisoformat(a["date"]))
    servings = week_view.recipe_base_servings(a["recipe"]) * float(a["scale"])
    cook = serving_ledger.create_cook(
        a["recipe"], week, scale=float(a["scale"]), servings_produced=servings,
        date=a["date"], meal=a["meal"], initial_placement_count=1.0)
    run.created_cook(cook["id"])
    run.new_cooks[index] = cook["id"]
    run.result.weeks.add(week)
    run.result.recipes.add(a["recipe"])
    try:
        from lib import dislike_guard
        hits = dislike_guard.warning_for([a["recipe"]])
        if hits:
            run.result.warnings.append(hits)
    except Exception:
        pass
    return describe(action, run.kitchen)


def _place_leftovers(run, index, action):
    from lib import serving_ledger
    a = action.args
    cook_id = run.cook_id(a["cook"])
    run.touch_cook(cook_id)
    serving_ledger.add_placement(cook_id, "slot", float(a["count"]), a["date"], a["meal"])
    run.result.weeks.update({iso_week(date.fromisoformat(a["date"])),
                             serving_ledger.get_cook(cook_id)["week"]})
    return describe(action, run.kitchen)


def _freeze_rest(run, index, action):
    from lib import serving_ledger
    cook_id = run.cook_id(action.args["cook"])
    run.touch_cook(cook_id)
    cook = serving_ledger.get_cook(cook_id)
    left = cook["unassigned"]
    if left <= 0:
        return "Nothing left to freeze"
    serving_ledger.add_placement(cook_id, "freezer", left)
    run.result.weeks.add(cook["week"])
    return f"Freezer — {left:g} servings"


def _move_cook(run, index, action):
    from lib import serving_ledger
    a = action.args
    for member in _members(a["cook_id"], a.get("bundle_id")):
        run.touch_cook(member)
    if a.get("bundle_id"):
        serving_ledger.move_bundle(a["bundle_id"], a["date"], a["meal"])
    else:
        serving_ledger.move_cook(a["cook_id"], a["date"], a["meal"])
    run.result.weeks.update({a["cook_week"], iso_week(date.fromisoformat(a["date"]))})
    return describe(action, run.kitchen)


def _remove_cook(run, index, action):
    from lib import serving_ledger
    a = action.args
    for member in _members(a["cook_id"], a.get("bundle_id")):
        run.touch_cook(member)
    if a.get("bundle_id"):
        removed = serving_ledger.delete_bundle(a["bundle_id"])
        run.result.recipes.update(c["recipe"] for c in removed)
    else:
        serving_ledger.delete_cook(a["cook_id"])
        run.result.recipes.add(a["recipe"])
    run.result.weeks.add(a["cook_week"])
    return f"Removed {run.kitchen.display(a['recipe'])} from {day_text(a['date'])}"


def _thaw(run, index, action):
    from lib import serving_ledger
    a = action.args
    run.touch_cook(a["cook_id"])
    serving_ledger.move_servings(a["placement_id"], float(a["count"]), "slot",
                                 a["date"], a["meal"])
    run.result.weeks.update({a["cook_week"], iso_week(date.fromisoformat(a["date"]))})
    return describe(action, run.kitchen)


def _mark_cooked(run, index, action):
    from lib.cook import consume_recipe
    a = action.args
    run.touch_inventory()
    summary = consume_recipe(a["recipe"], servings=float(a["batches"]))
    if summary.get("error"):
        raise ValueError(summary["error"])
    run.result.recipes.add(a["recipe"])
    return describe(action, run.kitchen)


def _inventory_add(run, index, action):
    from lib.inventory import InventoryItem, add_items
    from lib.storage_locations import place_item
    a = action.args
    run.touch_inventory()
    # The user did not say where it goes, so the storage table decides and the
    # row records that as a guess — never as a confirmed placement.
    placement = place_item(a["item"], "other")
    add_items([InventoryItem(name=a["item"], quantity=float(a["quantity"]), unit=a["unit"],
                             category="other", location=placement.location,
                             location_source=placement.source, source="manual")])
    return describe(action, run.kitchen)


def _inventory_remove(run, index, action):
    from lib.inventory import remove_item
    run.touch_inventory()
    if not remove_item(action.args["name"]):
        raise ValueError(f"There's no {action.args['name']} in the inventory.")
    return f"Removed {action.args['name']} from inventory"


def _inventory_move(run, index, action):
    from lib.inventory import move_item
    run.touch_inventory()
    if move_item(action.args["name"], action.args["location"]) is None:
        raise ValueError(f"There's no {action.args['name']} in the inventory.")
    return describe(action, run.kitchen)


def _open_page(run, index, action):
    run.result.navigate = dict(action.args)
    return describe(action, run.kitchen)


_HANDLERS = {
    "plan_cook": _plan_cook, "place_leftovers": _place_leftovers, "freeze_rest": _freeze_rest,
    "move_cook": _move_cook, "remove_cook": _remove_cook, "thaw": _thaw,
    "mark_cooked": _mark_cooked, "inventory_add": _inventory_add,
    "inventory_remove": _inventory_remove, "inventory_move": _inventory_move,
    "open_page": _open_page,
}


def run(plan: Plan, kitchen: Kitchen) -> Result:
    state = _Run(kitchen)
    try:
        for index, action in enumerate(plan.actions):
            state.result.lines.append(_HANDLERS[action.type](state, index, action))
    except (ValueError, TypeError, sqlite3.Error) as exc:
        # OverplacementError is a ValueError. Put back whatever already ran.
        undo(state.record(), force=True)
        return Result(ok=False, error=str(exc), weeks=state.result.weeks,
                      recipes=state.result.recipes)
    state.result.undo = state.record()
    return state.result


def undoable(record: Optional[dict]) -> bool:
    return bool(record and (record.get("cooks") or record.get("inventory")))


def undo(record: dict, force: bool = False) -> tuple:
    """Restore every "before". Returns (ok, reason). ``force`` skips the changed-since check."""
    from lib.inventory import refresh_inventory_views

    cooks = record.get("cooks") or {}
    inventory = record.get("inventory")
    conn = inventory_db.connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        if not force:
            for key, entry in cooks.items():
                if log.snap_cook(conn, int(key)) != entry.get("after"):
                    conn.rollback()
                    return False, "The meal plan has changed since then, so I left it alone."
            if inventory and inventory_db.inventory_rows_in(conn) != inventory.get("after"):
                conn.rollback()
                return False, "Inventory has changed since then, so I left it alone."
        for key in reversed(list(cooks)):
            log.restore_cook(conn, int(key), cooks[key]["before"])
        if inventory:
            inventory_db.replace_inventory_rows_in(conn, inventory["before"])
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    if inventory:
        refresh_inventory_views()
    return True, ""
