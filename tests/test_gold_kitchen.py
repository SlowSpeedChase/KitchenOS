"""The gold kitchen is the fixture every command feature is run through."""
import json
from pathlib import Path

GOLD = Path(__file__).parent / "gold" / "commands.json"
STATUSES = {"done", "ask", "confirm", "failed"}


def test_gold_kitchen_builds(gold_kitchen):
    from lib import inventory_db, paths, serving_ledger

    assert (paths.recipes_dir() / "Chicken Caldo A.md").exists()
    assert (paths.recipes_dir() / "Chicken Caldo B.md").exists()
    planned = [c["recipe"] for c in serving_ledger.cooks_for_week("2026-W47")]
    assert planned == ["Black Bean Chili", "Miso Salmon Bowls"]
    frozen = {r["recipe"]: r["count"] for r in serving_ledger.freezer_contents()}
    assert frozen == {"Chicken Caldo A": 3.0, "Black Bean Chili": 2.0}
    names = [r["name"] for r in inventory_db.fetch_inventory_rows()]
    assert names.count("milk") == 2 and "eggs" in names and "bread" in names
    assert set(gold_kitchen) == {"chili", "salmon", "frozen_caldo", "frozen_chili"}


def test_gold_commands_are_well_formed():
    cases = json.loads(GOLD.read_text())
    ids = [c["id"] for c in cases]
    assert len(ids) == len(set(ids)) and len(ids) >= 19
    for c in cases:
        assert c["say"].strip() and c["context"]["screen"]
        assert c["expect"]["status"] in STATUSES
