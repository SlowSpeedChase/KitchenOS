"""Tests for migrate_inventory_db.py."""
from lib.inventory import inventory_path, read_inventory
from migrate_inventory_db import migrate

LEGACY_MD = """---
type: inventory
last_updated: 2026-06-01
---

# Pantry Inventory

| Item | Quantity | Unit | Category | Location | Purchased | Source | Notes |
|------|----------|------|----------|----------|-----------|--------|-------|
| Eggs | 12 | ct | dairy | fridge | 2026-06-01 | receipt |  |
| Rice | 2 | lb | pantry | pantry |  | manual |  |
"""


def test_migrate_imports_legacy_rows(tmp_vault, tmp_db):
    inventory_path().write_text(LEGACY_MD, encoding="utf-8")
    result = migrate()
    assert result["imported"] == 2
    names = {it.name for it in read_inventory()}
    assert names == {"Eggs", "Rice"}
    # backup left behind, view regenerated with banner
    assert inventory_path().with_suffix(".md.bak").exists()
    assert "generated" in inventory_path().read_text(encoding="utf-8").lower()


def test_migrate_no_file_is_noop(tmp_vault, tmp_db):
    result = migrate()
    assert result["imported"] == 0
