import json

from lib import inventory_db, serving_ledger
from lib.command import executor, planner
from lib.command.decider import NoDecider
from lib.command.planner import Action, Plan
from lib.command.resolve import Kitchen
from tests.gold.kitchen import TODAY


def _dump():
    conn = inventory_db.connect()
    try:
        state = {t: [dict(r) for r in conn.execute(f"SELECT * FROM {t} ORDER BY id")]
                 for t in ("cooks", "placements")}
    finally:
        conn.close()
    state["inventory"] = inventory_db.fetch_inventory_rows()
    return state


def _run(say, context, answers=None):
    kitchen = Kitchen.load(TODAY, [context["week"]] if context.get("week") else [])
    outcome = planner.plan(say, context, kitchen, NoDecider(), answers)
    assert isinstance(outcome, Plan), outcome
    return executor.run(outcome, kitchen)


def test_plan_leftovers_freeze_writes_the_ledger(gold_kitchen):
    result = _run("put this on wednesday, leftovers for lunch the next day and freeze the rest",
                  {"screen": "recipe", "recipe": "Chicken Caldo A"})
    assert result.ok and result.weeks == {"2026-W47"}
    cook = [c for c in serving_ledger.cooks_for_week("2026-W47")
            if c["recipe"] == "Chicken Caldo A"][0]
    placed = {(p["destination"], p["date"], p["meal"]): p["count"] for p in cook["placements"]}
    assert placed == {("slot", "2026-11-18", "dinner"): 1.0,
                      ("slot", "2026-11-19", "lunch"): 1.0,
                      ("freezer", None, None): 4.0}
    assert result.lines == ["Wed Nov 18 dinner — Chicken Caldo A",
                            "Thu Nov 19 lunch — 1 leftover serving(s)",
                            "Freezer — 4 servings"]


def test_undo_restores_the_database_exactly(gold_kitchen):
    before = _dump()
    result = _run("put this on wednesday and freeze the rest",
                  {"screen": "recipe", "recipe": "Chicken Caldo A"})
    assert _dump() != before
    record = json.loads(json.dumps(result.undo))      # as it comes back from the log
    assert executor.undo(record) == (True, "")
    assert _dump() == before


def test_undo_refuses_when_the_cook_changed_afterwards(gold_kitchen):
    result = _run("put this on friday dinner", {"screen": "recipe", "recipe": "Chicken Caldo A"})
    cook_id = int(next(iter(result.undo["cooks"])))
    serving_ledger.add_placement(cook_id, "freezer", 2)
    ok, reason = executor.undo(json.loads(json.dumps(result.undo)))
    assert not ok and "changed" in reason
    assert serving_ledger.get_cook(cook_id) is not None


def test_move_and_remove_and_thaw_are_undoable(gold_kitchen):
    for say, context in [
        ("move the salmon from wednesday to saturday", {"screen": "planner", "week": "2026-W47"}),
        ("take the chili off tuesday", {"screen": "planner", "week": "2026-W47"}),
        ("pull a caldo out of the freezer for friday dinner", {"screen": "home"}),
    ]:
        before = _dump()
        result = _run(say, context)
        assert result.ok, result.error
        assert _dump() != before
        assert executor.undo(json.loads(json.dumps(result.undo))) == (True, "")
        assert _dump() == before


def test_a_bundle_moves_and_is_removed_as_one(gold_kitchen):
    conn = inventory_db.connect()
    try:
        with conn:
            conn.execute("UPDATE cooks SET bundle_id = 'plate1', bundle_name = 'Chili Plate',"
                         " date = '2026-11-17', meal = 'dinner' WHERE id IN (?, ?)",
                         (gold_kitchen["chili"], gold_kitchen["salmon"]))
            conn.execute("UPDATE placements SET date = '2026-11-17' WHERE cook_id = ?",
                         (gold_kitchen["salmon"],))
    finally:
        conn.close()
    before = _dump()
    result = _run("move the chili to thursday", {"screen": "planner", "week": "2026-W47"})
    assert result.ok, result.error
    assert {c["date"] for c in serving_ledger.cooks_for_week("2026-W47")} == {"2026-11-19"}
    assert executor.undo(json.loads(json.dumps(result.undo))) == (True, "")
    assert _dump() == before


def test_inventory_actions_and_their_undo(gold_kitchen):
    before = _dump()
    result = _run("add two cans of chickpeas and a bag of rice", {"screen": "home"})
    names = {r["name"]: r for r in inventory_db.fetch_inventory_rows()}
    assert names["chickpeas"]["quantity"] == 2.0 and names["chickpeas"]["unit"] == "can"
    assert names["chickpeas"]["location_source"] != "manual"   # never a fabricated confirmation
    assert executor.undo(json.loads(json.dumps(result.undo))) == (True, "")
    assert _dump() == before

    result = _run("we're out of eggs", {"screen": "home"})
    assert "eggs" not in {r["name"] for r in inventory_db.fetch_inventory_rows()}
    assert executor.undo(json.loads(json.dumps(result.undo))) == (True, "")
    assert _dump() == before

    result = _run("move the bread to the freezer", {"screen": "home"})
    bread = [r for r in inventory_db.fetch_inventory_rows() if r["name"] == "bread"][0]
    assert bread["location"] == "freezer"
    assert executor.undo(json.loads(json.dumps(result.undo))) == (True, "")


def test_undo_refuses_when_inventory_changed_afterwards(gold_kitchen):
    from lib.inventory import InventoryItem, add_items
    result = _run("we're out of eggs", {"screen": "home"})
    add_items([InventoryItem(name="butter", quantity=1, location="fridge")])
    ok, reason = executor.undo(json.loads(json.dumps(result.undo)))
    assert not ok and "Inventory" in reason


def test_mark_cooked_and_open_page(gold_kitchen):
    result = _run("I cooked this tonight", {"screen": "recipe", "recipe": "Chicken Caldo A"})
    assert result.ok and result.lines == ["Cooked Chicken Caldo A"]
    result = _run("open saturday", {"screen": "home"})
    assert result.ok and result.navigate == {"page": "day", "date": "2026-11-14", "week": "2026-W46"}
    assert not executor.undoable(result.undo)


def test_a_failing_action_rolls_back_the_ones_before_it(gold_kitchen):
    before = _dump()
    kitchen = Kitchen.load(TODAY)
    plan = Plan([
        Action("plan_cook", {"recipe": "Miso Salmon Bowls", "date": "2026-11-13",
                             "meal": "dinner", "scale": 1.0}),
        Action("place_leftovers", {"cook": {"new": 0}, "date": "2026-11-14",
                                   "meal": "lunch", "count": 9.0}),
    ])
    result = executor.run(plan, kitchen)
    assert not result.ok and result.error
    assert _dump() == before
