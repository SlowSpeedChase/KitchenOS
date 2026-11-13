from lib import inventory_db, serving_ledger
from lib.command import log


def test_create_get_update_round_trip(tmp_db):
    cid = log.create("put this on friday", {"screen": "recipe", "recipe": "Chili"})
    row = log.get(cid)
    assert row["status"] == "new" and row["context"]["recipe"] == "Chili" and row["answers"] == {}
    log.update(cid, status="done", response={"status": "done"}, undo={"cooks": {}})
    row = log.get(cid)
    assert row["status"] == "done" and row["response"] == {"status": "done"}
    assert log.get(9999) is None


def test_recent_duplicate_only_matches_done_commands(tmp_db):
    context = {"screen": "home"}
    cid = log.create("we're out of eggs", context)
    assert log.recent_duplicate("we're out of eggs", context, 5.0) is None
    log.update(cid, status="done", response={"status": "done"})
    assert log.recent_duplicate("we're out of eggs", context, 5.0)["id"] == cid
    assert log.recent_duplicate("we're out of eggs", {"screen": "recipe"}, 5.0) is None
    assert log.recent_duplicate("we're out of eggs", context, 0) is None


def test_snapshot_and_restore_a_changed_cook(tmp_db):
    cook = serving_ledger.create_cook("Chili", "2026-W47", servings_produced=6.0,
                                      date="2026-11-17", meal="dinner")
    conn = inventory_db.connect()
    try:
        before = log.snap_cook(conn, cook["id"])
    finally:
        conn.close()
    serving_ledger.add_placement(cook["id"], "freezer", 4)
    serving_ledger.move_cook(cook["id"], "2026-11-19", "lunch")

    conn = inventory_db.connect()
    try:
        with conn:
            log.restore_cook(conn, cook["id"], before)
        assert log.snap_cook(conn, cook["id"]) == before
    finally:
        conn.close()
    assert serving_ledger.get_cook(cook["id"])["date"] == "2026-11-17"


def test_restore_recreates_a_deleted_cook_and_deletes_a_created_one(tmp_db):
    cook = serving_ledger.create_cook("Chili", "2026-W47", servings_produced=6.0,
                                      date="2026-11-17", meal="dinner")
    conn = inventory_db.connect()
    try:
        before = log.snap_cook(conn, cook["id"])
        assert log.snap_cook(conn, 9999) is None
    finally:
        conn.close()
    serving_ledger.delete_cook(cook["id"])

    conn = inventory_db.connect()
    try:
        with conn:
            log.restore_cook(conn, cook["id"], before)
        assert log.snap_cook(conn, cook["id"]) == before
        with conn:
            log.restore_cook(conn, cook["id"], None)
        assert log.snap_cook(conn, cook["id"]) is None
    finally:
        conn.close()


def test_inventory_helpers_round_trip(tmp_db):
    from lib.inventory import InventoryItem, add_items
    add_items([InventoryItem(name="eggs", quantity=12, location="fridge")])
    conn = inventory_db.connect()
    try:
        rows = inventory_db.inventory_rows_in(conn)
        with conn:
            inventory_db.replace_inventory_rows_in(conn, [])
        assert inventory_db.inventory_rows_in(conn) == []
        with conn:
            inventory_db.replace_inventory_rows_in(conn, rows)
        assert inventory_db.inventory_rows_in(conn) == rows
    finally:
        conn.close()
