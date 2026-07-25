"""Tests for the inventory module."""

from lib.inventory import (
    InventoryItem,
    add_items,
    extend_expiry,
    freeze_item,
    inventory_path,
    move_item,
    normalize_category,
    normalize_location,
    normalize_source,
    parse_inventory_markdown,
    prune_expired,
    read_inventory,
    remove_item,
    seed_pantry_staples,
    set_category,
    set_expiry,
    update_quantity,
    write_inventory,
)


class TestNormalizers:
    def test_normalize_category_known(self):
        assert normalize_category("Dairy") == "dairy"
        assert normalize_category("PRODUCE") == "produce"

    def test_normalize_category_unknown_falls_back_to_other(self):
        assert normalize_category("widgets") == "other"
        assert normalize_category(None) == "other"
        assert normalize_category("") == "other"

    def test_normalize_location_default_is_pantry(self):
        assert normalize_location(None) == "pantry"
        assert normalize_location("") == "pantry"

    def test_normalize_location_known(self):
        assert normalize_location("Fridge") == "fridge"
        assert normalize_location("FREEZER") == "freezer"

    def test_normalize_location_unknown_falls_back_to_other(self):
        assert normalize_location("garage") == "other"

    def test_normalize_source(self):
        assert normalize_source("receipt") == "receipt"
        assert normalize_source("RANDOM") == "manual"
        assert normalize_source(None) == "manual"


class TestRoundtrip:
    def test_read_empty_when_no_data(self, tmp_vault, tmp_db):
        assert read_inventory() == []

    def test_write_then_read_preserves_items(self, tmp_vault, tmp_db):
        items = [
            InventoryItem(
                name="Whole milk", quantity=1, unit="gal",
                category="dairy", location="fridge",
                purchased="2026-04-30", source="receipt",
                notes="GV WHL MLK 1G",
            ),
            InventoryItem(
                name="Bananas", quantity=6, unit="ct",
                category="produce", location="counter",
            ),
        ]
        write_inventory(items)
        loaded = read_inventory()

        assert len(loaded) == 2
        by_name = {i.name: i for i in loaded}
        assert by_name["Whole milk"].quantity == 1.0
        assert by_name["Whole milk"].unit == "gal"
        assert by_name["Whole milk"].category == "dairy"
        assert by_name["Whole milk"].location == "fridge"
        assert by_name["Whole milk"].purchased == "2026-04-30"
        assert by_name["Whole milk"].source == "receipt"
        assert by_name["Whole milk"].notes == "GV WHL MLK 1G"
        assert by_name["Bananas"].quantity == 6.0
        assert by_name["Bananas"].location == "counter"

    def test_fractional_quantity_preserved(self, tmp_vault, tmp_db):
        write_inventory([InventoryItem(name="Olive oil", quantity=0.5, unit="L")])
        loaded = read_inventory()
        assert loaded[0].quantity == 0.5

    def test_inventory_file_lives_at_vault_root(self, tmp_vault, tmp_db):
        write_inventory([InventoryItem(name="Salt", quantity=1, unit="lb")])
        assert (tmp_vault / "Inventory.md").exists()


class TestAddItems:
    def test_add_into_empty_inventory(self, tmp_vault, tmp_db):
        result = add_items([
            InventoryItem(name="Eggs", quantity=12, unit="ct", category="dairy"),
        ])
        assert result == {"added": 1, "merged": 0, "total": 1}
        assert read_inventory()[0].name == "Eggs"

    def test_merge_same_name_unit_location_sums_quantity(self, tmp_vault, tmp_db):
        add_items([InventoryItem(name="Milk", quantity=1, unit="gal", location="fridge")])
        result = add_items([
            InventoryItem(name="Milk", quantity=1, unit="gal", location="fridge"),
        ])
        assert result == {"added": 0, "merged": 1, "total": 1}
        items = read_inventory()
        assert len(items) == 1
        assert items[0].quantity == 2.0

    def test_different_unit_keeps_separate_rows(self, tmp_vault, tmp_db):
        add_items([InventoryItem(name="Milk", quantity=1, unit="gal")])
        add_items([InventoryItem(name="Milk", quantity=8, unit="oz")])
        items = read_inventory()
        assert len(items) == 2

    def test_different_location_keeps_separate_rows(self, tmp_vault, tmp_db):
        add_items([InventoryItem(name="Bread", quantity=1, unit="loaf", location="pantry")])
        add_items([InventoryItem(name="Bread", quantity=1, unit="loaf", location="freezer")])
        items = read_inventory()
        assert len(items) == 2

    def test_merge_is_case_insensitive(self, tmp_vault, tmp_db):
        add_items([InventoryItem(name="Eggs", quantity=12, unit="ct")])
        result = add_items([InventoryItem(name="EGGS", quantity=6, unit="CT")])
        assert result["merged"] == 1
        items = read_inventory()
        assert len(items) == 1
        assert items[0].quantity == 18.0

    def test_merge_updates_purchased_date(self, tmp_vault, tmp_db):
        add_items([
            InventoryItem(name="Yogurt", quantity=1, unit="ct", purchased="2026-04-01"),
        ])
        add_items([
            InventoryItem(name="Yogurt", quantity=1, unit="ct", purchased="2026-04-30"),
        ])
        assert read_inventory()[0].purchased == "2026-04-30"


class TestRemove:
    def test_remove_existing_item(self, tmp_vault, tmp_db):
        add_items([
            InventoryItem(name="Cheese", quantity=1, unit="lb"),
            InventoryItem(name="Bread", quantity=1, unit="loaf"),
        ])
        assert remove_item("Cheese") is True
        names = [i.name for i in read_inventory()]
        assert "Cheese" not in names
        assert "Bread" in names

    def test_remove_missing_item_returns_false(self, tmp_vault, tmp_db):
        add_items([InventoryItem(name="Bread", quantity=1, unit="loaf")])
        assert remove_item("Cheese") is False
        assert len(read_inventory()) == 1

    def test_remove_filters_by_location(self, tmp_vault, tmp_db):
        add_items([
            InventoryItem(name="Bread", quantity=1, unit="loaf", location="pantry"),
            InventoryItem(name="Bread", quantity=1, unit="loaf", location="freezer"),
        ])
        assert remove_item("Bread", location="freezer") is True
        items = read_inventory()
        assert len(items) == 1
        assert items[0].location == "pantry"


class TestUpdateQuantity:
    def test_update_existing_item(self, tmp_vault, tmp_db):
        add_items([InventoryItem(name="Flour", quantity=5, unit="lb")])
        assert update_quantity("Flour", 2.5) is True
        assert read_inventory()[0].quantity == 2.5

    def test_update_missing_item_returns_false(self, tmp_vault, tmp_db):
        assert update_quantity("Flour", 1) is False


class TestGeneratedView:
    def test_inventory_md_is_generated_view(self, tmp_vault, tmp_db):
        add_items([InventoryItem(name="Milk", quantity=1, unit="gal",
                                 category="dairy", location="fridge")])
        content = inventory_path().read_text(encoding="utf-8")
        assert "| Milk | 1 | gal | dairy | fridge |" in content
        assert "generated" in content.lower()  # view banner present

    def test_hand_edits_to_md_are_invisible(self, tmp_vault, tmp_db):
        add_items([InventoryItem(name="Milk", quantity=1, unit="gal")])
        # simulate a user hand-editing the generated view
        inventory_path().write_text("| Item |...| Beer | 99 | ct |", encoding="utf-8")
        items = read_inventory()
        assert [it.name for it in items] == ["Milk"]


class TestSeedPantryStaples:
    """Staples live in inventory permanently instead of being an invisible
    assumption layered on top of it — on hand, never expiring, never a chore."""

    STAPLES = {"butter", "milk", "eggs", "olive oil", "salt"}

    def test_seeds_missing_staples_as_perpetual_rows(self, tmp_vault, tmp_db):
        seed_pantry_staples(self.STAPLES)
        by_name = {it.name.lower(): it for it in read_inventory()}
        assert "butter" in by_name
        butter = by_name["butter"]
        assert butter.source == "staple"
        assert butter.expires is None  # never ages out

    def test_is_idempotent(self, tmp_vault, tmp_db):
        seed_pantry_staples(self.STAPLES)
        first = {(it.name, it.quantity) for it in read_inventory()}
        result = seed_pantry_staples(self.STAPLES)
        assert result["added"] == []
        assert {(it.name, it.quantity) for it in read_inventory()} == first

    def test_does_not_duplicate_an_equivalent_item_already_stocked(self, tmp_vault,
                                                                   tmp_db):
        add_items([InventoryItem(name="Salted Butter", quantity=1, unit="ct",
                                 category="dairy", location="fridge")])
        seed_pantry_staples(self.STAPLES)
        names = [it.name.lower() for it in read_inventory()]
        assert "salted butter" in names
        assert "butter" not in names  # the stocked one already covers it

    def test_seeded_staples_survive_pruning(self, tmp_vault, tmp_db):
        seed_pantry_staples(self.STAPLES)
        prune_expired()
        assert "butter" in {it.name.lower() for it in read_inventory()}

    def test_skips_things_nobody_stocks(self, tmp_vault, tmp_db):
        seed_pantry_staples({"water", "ice", "butter"})
        names = {it.name.lower() for it in read_inventory()}
        assert names == {"butter"}


class TestViewFollowsDatabase:
    """The generated view must render the *committed* DB state.

    Regression: ``write_inventory`` rendered ``Inventory.md`` from the caller's
    list while ``cook_now`` re-read the DB, so the two views could disagree.
    In production this shipped an empty Inventory.md alongside a populated
    Cook Now.md. The DB is the single source of truth for both.
    """

    def test_view_shows_committed_rows_not_caller_list(self, tmp_vault, tmp_db,
                                                       monkeypatch):
        from lib import inventory_db

        real_replace = inventory_db.replace_inventory_rows

        def commits_only_the_first(rows):
            # Stand in for anything that makes the commit differ from the
            # caller's list (constraint, normalization, concurrent writer).
            real_replace(rows[:1])

        monkeypatch.setattr(inventory_db, "replace_inventory_rows",
                            commits_only_the_first)
        write_inventory([
            InventoryItem(name="Milk", quantity=1, unit="gal"),
            InventoryItem(name="Ghost", quantity=1, unit="ct"),
        ])

        content = inventory_path().read_text(encoding="utf-8")
        assert "Milk" in content
        assert "Ghost" not in content

    def test_view_matches_a_fresh_render_of_the_db(self, tmp_vault, tmp_db):
        from lib.inventory import render_inventory_md

        write_inventory([
            InventoryItem(name="Okra", quantity=1, unit="ct", category="produce"),
            InventoryItem(name="Bacon", quantity=1, unit="oz", category="meat"),
        ])
        assert (inventory_path().read_text(encoding="utf-8")
                == render_inventory_md(read_inventory()))


class TestParsing:
    def test_parse_inventory_markdown_still_works(self, tmp_vault, tmp_db):
        md = (
            "| Item | Quantity | Unit | Category | Location | Purchased | Source | Notes |\n"
            "|------|----------|------|----------|----------|-----------|--------|-------|\n"
            "| Eggs | 12 | ct | dairy | fridge | 2026-06-01 | receipt |  |\n"
        )
        items = parse_inventory_markdown(md)
        assert items[0].name == "Eggs"
        assert items[0].quantity == 12.0

    def test_skips_malformed_rows(self, tmp_vault, tmp_db):
        content = (
            "---\n"
            "type: inventory\n"
            "---\n\n"
            "# Pantry Inventory\n\n"
            "| Item | Quantity | Unit | Category | Location | Purchased | Source | Notes |\n"
            "|------|----------|------|----------|----------|-----------|--------|-------|\n"
            "| Milk | 1 | gal | dairy | fridge | 2026-04-30 | receipt |  |\n"
            "|  |  |  |  |  |  |  |  |\n"
            "| Eggs | 12 | ct | dairy | fridge |  | manual |  |\n"
        )
        items = parse_inventory_markdown(content)
        assert len(items) == 2
        names = sorted(i.name for i in items)
        assert names == ["Eggs", "Milk"]


class TestExpiry:
    def test_add_autofills_expires_from_window(self, tmp_vault, tmp_db):
        add_items([
            InventoryItem(name="Milk", quantity=1, unit="gal",
                          category="dairy", purchased="2026-06-01"),
        ])
        item = read_inventory()[0]
        assert item.expires == "2026-06-11"  # milk window = 10 days

    def test_null_window_leaves_expires_none(self, tmp_vault, tmp_db):
        add_items([
            InventoryItem(name="Dish soap", quantity=1, unit="ct",
                          category="household", purchased="2026-06-01"),
        ])
        assert read_inventory()[0].expires is None

    def test_explicit_expires_is_respected(self, tmp_vault, tmp_db):
        add_items([
            InventoryItem(name="Milk", quantity=1, unit="gal", category="dairy",
                          purchased="2026-06-01", expires="2026-06-05"),
        ])
        assert read_inventory()[0].expires == "2026-06-05"

    def test_merge_keeps_earliest_expiry(self, tmp_vault, tmp_db):
        add_items([InventoryItem(name="Milk", quantity=1, unit="gal",
                                 location="fridge", category="dairy",
                                 expires="2026-06-20")])
        add_items([InventoryItem(name="Milk", quantity=1, unit="gal",
                                 location="fridge", category="dairy",
                                 expires="2026-06-10")])
        items = read_inventory()
        assert len(items) == 1
        assert items[0].expires == "2026-06-10"

    def test_render_includes_expiry_warning_section(self, tmp_vault, tmp_db):
        from datetime import date, timedelta
        from lib.inventory import render_inventory_md
        soon = (date.today() + timedelta(days=1)).isoformat()
        items = [InventoryItem(name="Yogurt", quantity=1, unit="ct",
                               category="dairy", expires=soon)]
        md = render_inventory_md(items)
        assert "## ⚠️ Expiring Soon" in md
        assert "Yogurt" in md
        assert "Expires" in md  # table column header


class TestPruneExpired:
    def test_drops_long_expired_perishables(self, tmp_vault, tmp_db):
        from datetime import date, timedelta
        from lib.inventory import add_items, prune_expired, read_inventory
        today = date(2026, 6, 24)
        add_items([
            InventoryItem(name="Old Spinach", quantity=1, unit="ct", category="produce",
                          expires=(today - timedelta(days=10)).isoformat()),
            InventoryItem(name="Fresh Spinach", quantity=1, unit="ct", category="produce",
                          expires=(today - timedelta(days=1)).isoformat()),  # within grace
            InventoryItem(name="Canned Beans", quantity=1, unit="can", category="pantry",
                          expires=(today + timedelta(days=300)).isoformat()),
            InventoryItem(name="Dish Soap", quantity=1, unit="ct", category="household"),  # no expiry
        ])
        removed = prune_expired(today=today)
        assert removed == 1
        names = {i.name for i in read_inventory()}
        assert "Old Spinach" not in names
        assert {"Fresh Spinach", "Canned Beans", "Dish Soap"} <= names

    def test_noop_when_nothing_stale(self, tmp_vault, tmp_db):
        from datetime import date, timedelta
        from lib.inventory import add_items, prune_expired
        today = date(2026, 6, 24)
        add_items([InventoryItem(name="Milk", quantity=1, unit="gal", category="dairy",
                                 expires=(today + timedelta(days=5)).isoformat())])
        assert prune_expired(today=today) == 0


class TestExtendExpiry:
    def test_extends_from_today_not_old_date(self, tmp_vault, tmp_db):
        from datetime import date
        add_items([InventoryItem(name="Milk", quantity=1, unit="ct",
                                 category="dairy", location="fridge",
                                 expires="2026-07-15")])
        item = extend_expiry("Milk", days=3, location="fridge",
                             today=date(2026, 7, 12))
        assert item is not None
        assert item.expires == "2026-07-15"  # today(07-12) + 3 days

    def test_sets_fresh_expiry_on_no_expiry_item(self, tmp_vault, tmp_db):
        from datetime import date
        add_items([InventoryItem(name="Rice", quantity=1, unit="lb",
                                 category="pantry", location="pantry",
                                 expires=None)])
        item = extend_expiry("Rice", days=7, location="pantry",
                             today=date(2026, 7, 12))
        assert item is not None
        assert item.expires == "2026-07-19"

    def test_returns_none_when_not_found(self, tmp_vault, tmp_db):
        assert extend_expiry("Nonexistent", days=3) is None

    def test_preserves_other_fields(self, tmp_vault, tmp_db):
        from datetime import date
        add_items([InventoryItem(name="Yogurt", quantity=2, unit="ct",
                                 category="dairy", location="fridge",
                                 for_recipe="Smoothie", expires="2026-07-14")])
        item = extend_expiry("Yogurt", days=5, location="fridge",
                             today=date(2026, 7, 12))
        assert item.quantity == 2
        assert item.unit == "ct"
        assert item.for_recipe == "Smoothie"


class TestSetExpiry:
    def test_sets_absolute_date(self, tmp_vault, tmp_db):
        add_items([InventoryItem(name="Milk", quantity=1, unit="gal",
                                 category="dairy", location="fridge")])
        item = set_expiry("Milk", "2026-08-01", location="fridge")
        assert item is not None
        assert item.expires == "2026-08-01"
        assert read_inventory()[0].expires == "2026-08-01"

    def test_clears_expiry_with_none(self, tmp_vault, tmp_db):
        add_items([InventoryItem(name="Milk", quantity=1, unit="gal",
                                 category="dairy", location="fridge",
                                 expires="2026-08-01")])
        item = set_expiry("Milk", None, location="fridge")
        assert item is not None
        assert item.expires is None
        assert read_inventory()[0].expires is None

    def test_returns_none_when_not_found(self, tmp_vault, tmp_db):
        assert set_expiry("Nonexistent", "2026-08-01") is None

    def test_preserves_other_fields(self, tmp_vault, tmp_db):
        add_items([InventoryItem(name="Yogurt", quantity=2, unit="ct",
                                 category="dairy", location="fridge",
                                 for_recipe="Smoothie")])
        item = set_expiry("Yogurt", "2026-08-01", location="fridge")
        assert item.quantity == 2
        assert item.for_recipe == "Smoothie"


class TestSetCategory:
    def test_changes_category(self, tmp_vault, tmp_db):
        add_items([InventoryItem(name="Peas", quantity=1, unit="bag",
                                 category="produce", location="freezer")])
        item = set_category("Peas", "frozen", location="freezer")
        assert item is not None
        assert item.category == "frozen"
        assert read_inventory()[0].category == "frozen"

    def test_normalizes_unknown_category_to_other(self, tmp_vault, tmp_db):
        add_items([InventoryItem(name="Peas", quantity=1, unit="bag")])
        item = set_category("Peas", "widgets")
        assert item.category == "other"

    def test_returns_none_when_not_found(self, tmp_vault, tmp_db):
        assert set_category("Nonexistent", "produce") is None


class TestMoveItem:
    def test_changes_location(self, tmp_vault, tmp_db):
        add_items([InventoryItem(name="Bread", quantity=1, unit="loaf",
                                 location="pantry")])
        item = move_item("Bread", "freezer")
        assert item is not None
        assert item.location == "freezer"
        items = read_inventory()
        assert len(items) == 1
        assert items[0].location == "freezer"

    def test_normalizes_target_location(self, tmp_vault, tmp_db):
        add_items([InventoryItem(name="Bread", quantity=1, unit="loaf",
                                 location="pantry")])
        item = move_item("Bread", "Freezer")
        assert item.location == "freezer"

    def test_merges_into_existing_row_at_target(self, tmp_vault, tmp_db):
        add_items([
            InventoryItem(name="Bread", quantity=1, unit="loaf", location="pantry"),
            InventoryItem(name="Bread", quantity=2, unit="loaf", location="freezer"),
        ])
        item = move_item("Bread", "freezer", location="pantry")
        assert item is not None
        assert item.location == "freezer"
        items = read_inventory()
        assert len(items) == 1
        assert items[0].quantity == 3.0
        assert items[0].location == "freezer"

    def test_move_to_same_location_is_noop(self, tmp_vault, tmp_db):
        add_items([InventoryItem(name="Bread", quantity=1, unit="loaf",
                                 location="pantry")])
        item = move_item("Bread", "pantry", location="pantry")
        assert item is not None
        assert item.location == "pantry"
        assert len(read_inventory()) == 1

    def test_returns_none_when_not_found(self, tmp_vault, tmp_db):
        assert move_item("Nonexistent", "freezer") is None


class TestFreezeItem:
    def test_sets_freezer_frozen_and_clears_expiry(self, tmp_vault, tmp_db):
        add_items([InventoryItem(name="Chicken", quantity=1, unit="lb",
                                 category="meat", location="fridge",
                                 expires="2026-07-25")])
        item = freeze_item("Chicken", location="fridge")
        assert item is not None
        assert item.location == "freezer"
        assert item.category == "frozen"
        assert item.expires is None
        stored = read_inventory()[0]
        assert stored.location == "freezer"
        assert stored.category == "frozen"
        assert stored.expires is None

    def test_merges_into_existing_freezer_row(self, tmp_vault, tmp_db):
        add_items([
            InventoryItem(name="Peas", quantity=1, unit="bag", category="produce",
                          location="fridge", expires="2026-07-25"),
            InventoryItem(name="Peas", quantity=2, unit="bag", category="frozen",
                          location="freezer"),
        ])
        item = freeze_item("Peas", location="fridge")
        assert item is not None
        items = read_inventory()
        assert len(items) == 1
        assert items[0].quantity == 3.0
        assert items[0].location == "freezer"

    def test_returns_none_when_not_found(self, tmp_vault, tmp_db):
        assert freeze_item("Nonexistent") is None


class TestReviewLink:
    def test_inventory_md_has_review_link(self):
        from lib.inventory import render_inventory_md
        md = render_inventory_md([])
        assert "/review" in md
        assert "Open Review" in md

    def test_inventory_md_has_launch_claude_link(self):
        from lib.inventory import render_inventory_md
        md = render_inventory_md([])
        assert "Launch Claude" in md
        assert "ssh://chase@chases-mac-mini.taila69703.ts.net" in md
        assert "[[Claude Notes]]" in md
        # Regression: ensure Open Review is still there
        assert "Open Review" in md

    def test_launch_claude_link_respects_ssh_target_env(self, monkeypatch):
        from lib.inventory import render_inventory_md
        monkeypatch.setenv("KITCHENOS_SSH_TARGET", "u@h.ts.net")
        md = render_inventory_md([])
        assert "ssh://u@h.ts.net" in md
        assert "Launch Claude" in md


class TestPureMutators:
    """The _apply_* helpers mutate in memory and do no I/O."""

    def _items(self):
        return [
            InventoryItem(name="Bread", quantity=1, unit="loaf",
                          category="bakery", location="pantry"),
            InventoryItem(name="Bread", quantity=2, unit="loaf",
                          category="bakery", location="counter"),
            InventoryItem(name="Milk", quantity=1, unit="gal",
                          category="dairy", location="fridge",
                          expires="2026-09-15"),
        ]

    def test_drop_removes_by_identity_not_value(self):
        from lib.inventory import _drop
        a = InventoryItem(name="Egg", quantity=1, unit="ct", location="fridge")
        b = InventoryItem(name="Egg", quantity=1, unit="ct", location="fridge")
        items = [a, b]
        assert a == b  # dataclass equality is by value
        _drop(items, b)
        assert len(items) == 1
        assert items[0] is a

    def test_match_by_name_returns_every_match(self):
        from lib.inventory import _match_by_name
        items = self._items()
        assert len(_match_by_name(items, "Bread", None)) == 2
        assert len(_match_by_name(items, "bread", "counter")) == 1
        assert _match_by_name(items, "Nope", None) == []

    def test_apply_remove_drops_all_matches_and_returns_them(self):
        from lib.inventory import _apply_remove
        items = self._items()
        removed = _apply_remove(items, [items[0], items[2]])
        assert len(items) == 1
        assert items[0].name == "Bread" and items[0].location == "counter"
        assert [r.name for r in removed] == ["Bread", "Milk"]

    def test_apply_extend_sets_expiry_from_today(self):
        from datetime import date
        from lib.inventory import _apply_extend
        items = self._items()
        out = _apply_extend(items, items[:2], 7, today=date(2026, 7, 25))
        assert [i.expires for i in out] == ["2026-08-01", "2026-08-01"]
        assert items[2].expires == "2026-09-15"  # untouched row keeps its own

    def test_apply_set_expiry_sets_and_clears(self):
        from lib.inventory import _apply_set_expiry
        items = self._items()
        _apply_set_expiry(items, [items[0]], "2026-09-09")
        assert items[0].expires == "2026-09-09"
        _apply_set_expiry(items, [items[2]], None)
        assert items[2].expires is None

    def test_apply_set_category_normalizes(self):
        from lib.inventory import _apply_set_category
        items = self._items()
        _apply_set_category(items, items[:2], "Produce")
        assert [i.category for i in items[:2]] == ["produce", "produce"]
        _apply_set_category(items, [items[2]], "widgets")
        assert items[2].category == "other"

    def test_apply_move_changes_location(self):
        from lib.inventory import _apply_move
        items = self._items()
        out = _apply_move(items, [items[2]], "Freezer")
        assert out[0].location == "freezer"
        assert len(items) == 3

    def test_apply_move_merges_two_selected_rows_into_one_destination(self):
        from lib.inventory import _apply_move
        items = self._items()
        out = _apply_move(items, [items[0], items[1]], "freezer")
        assert len(items) == 2          # the two Bread rows collapsed into one
        assert len(out) == 1            # and the result is reported once
        assert out[0].quantity == 3.0
        assert out[0].location == "freezer"

    def test_apply_move_to_same_location_is_a_noop(self):
        from lib.inventory import _apply_move
        items = self._items()
        out = _apply_move(items, [items[0]], "pantry")
        assert out == [items[0]]
        assert len(items) == 3

    def test_apply_freeze_moves_sets_category_and_clears_expiry(self):
        from lib.inventory import _apply_freeze
        items = self._items()
        out = _apply_freeze(items, [items[2]])
        assert out[0].location == "freezer"
        assert out[0].category == "frozen"
        assert out[0].expires is None


class TestBulkApply:
    def _seed(self):
        add_items([
            InventoryItem(name="Kale", quantity=1, unit="bunch",
                          category="produce", location="fridge",
                          expires="2026-07-26"),
            InventoryItem(name="Milk", quantity=1, unit="gal",
                          category="dairy", location="fridge",
                          expires="2026-07-28"),
            InventoryItem(name="Rice", quantity=2, unit="lb",
                          category="pantry", location="pantry"),
        ])

    def _ref(self, name, unit, location):
        return {"name": name, "unit": unit, "location": location}

    def test_bulk_remove_removes_all_and_returns_rows(self, tmp_vault, tmp_db):
        from lib.inventory import bulk_apply
        self._seed()
        out = bulk_apply("remove", [
            self._ref("Kale", "bunch", "fridge"),
            self._ref("Milk", "gal", "fridge"),
        ])
        assert out["applied"] == 2
        assert out["items"] == []
        assert sorted(r.name for r in out["removed"]) == ["Kale", "Milk"]
        assert [i.name for i in read_inventory()] == ["Rice"]

    def test_bulk_extend_sets_all_expiries_in_one_write(self, tmp_vault, tmp_db):
        from datetime import date
        from lib.inventory import bulk_apply
        self._seed()
        out = bulk_apply("extend", [
            self._ref("Kale", "bunch", "fridge"),
            self._ref("Rice", "lb", "pantry"),
        ], days=7, today=date(2026, 7, 25))
        assert out["applied"] == 2
        assert out["removed"] == []
        assert {i.expires for i in out["items"]} == {"2026-08-01"}
        stored = {i.name: i.expires for i in read_inventory()}
        assert stored["Kale"] == "2026-08-01"
        assert stored["Rice"] == "2026-08-01"
        assert stored["Milk"] == "2026-07-28"  # unselected row untouched

    def test_bulk_set_expiry_clears(self, tmp_vault, tmp_db):
        from lib.inventory import bulk_apply
        self._seed()
        bulk_apply("set-expiry", [self._ref("Kale", "bunch", "fridge")],
                   expires=None)
        assert {i.name: i.expires for i in read_inventory()}["Kale"] is None

    def test_bulk_set_category_normalizes(self, tmp_vault, tmp_db):
        from lib.inventory import bulk_apply
        self._seed()
        bulk_apply("set-category", [self._ref("Rice", "lb", "pantry")],
                   category="Produce")
        assert {i.name: i.category for i in read_inventory()}["Rice"] == "produce"

    def test_bulk_move_merges_two_selected_rows_into_one_destination(
        self, tmp_vault, tmp_db
    ):
        from lib.inventory import bulk_apply
        add_items([
            InventoryItem(name="Peas", quantity=1, unit="bag", location="fridge"),
            InventoryItem(name="Peas", quantity=2, unit="bag", location="pantry"),
        ])
        out = bulk_apply("move", [
            self._ref("Peas", "bag", "fridge"),
            self._ref("Peas", "bag", "pantry"),
        ], to_location="freezer")
        assert out["applied"] == 2
        assert len(out["items"]) == 1
        items = read_inventory()
        assert len(items) == 1
        assert items[0].quantity == 3.0
        assert items[0].location == "freezer"

    def test_bulk_move_merges_into_preexisting_unselected_row(
        self, tmp_vault, tmp_db
    ):
        """The classic single-item collision case: only ONE row is selected,
        but the destination already stocks the same (name, unit) — the most
        common real bulk-move scenario (newly-received items moving into a
        location that already has that product)."""
        from lib.inventory import bulk_apply
        add_items([
            InventoryItem(name="Peas", quantity=1, unit="bag", location="fridge"),
            InventoryItem(name="Peas", quantity=2, unit="bag", location="pantry"),
        ])
        out = bulk_apply("move", [
            self._ref("Peas", "bag", "fridge"),
        ], to_location="pantry")
        assert out["applied"] == 1
        assert len(out["items"]) == 1
        items = read_inventory()
        assert len(items) == 1
        assert items[0].quantity == 3.0
        assert items[0].location == "pantry"

    def test_bulk_freeze_sets_category_and_clears_expiry(self, tmp_vault, tmp_db):
        from lib.inventory import bulk_apply
        self._seed()
        out = bulk_apply("freeze", [self._ref("Kale", "bunch", "fridge")])
        assert out["items"][0].location == "freezer"
        assert out["items"][0].category == "frozen"
        assert out["items"][0].expires is None

    def test_unit_is_part_of_the_address(self, tmp_vault, tmp_db):
        """The whole point of the fix: same name, different unit, different row."""
        from lib.inventory import bulk_apply
        add_items([
            InventoryItem(name="Flour", quantity=1, unit="lb", location="pantry"),
            InventoryItem(name="Flour", quantity=1, unit="bag", location="pantry"),
        ])
        out = bulk_apply("remove", [self._ref("Flour", "lb", "pantry")])
        assert out["applied"] == 1
        remaining = read_inventory()
        assert len(remaining) == 1
        assert remaining[0].unit == "bag"

    def test_partial_not_found_still_applies_the_rest(self, tmp_vault, tmp_db):
        from lib.inventory import bulk_apply
        self._seed()
        out = bulk_apply("remove", [
            self._ref("Kale", "bunch", "fridge"),
            self._ref("Ghost", "ct", "fridge"),
        ])
        assert out["applied"] == 1
        assert out["not_found"] == [self._ref("Ghost", "ct", "fridge")]
        assert len(read_inventory()) == 2

    def test_all_refs_missing_writes_nothing(self, tmp_vault, tmp_db, monkeypatch):
        import lib.inventory as inventory_module
        from lib.inventory import bulk_apply
        self._seed()

        calls = []
        monkeypatch.setattr(
            inventory_module, "write_inventory", lambda items: calls.append(items)
        )

        out = bulk_apply("remove", [self._ref("Ghost", "ct", "fridge")])
        assert out["applied"] == 0
        assert len(out["not_found"]) == 1
        # A round-tripped-but-unmutated write would leave the DB looking
        # identical to a skipped write, so assert the skip directly rather
        # than only inferring it from row count.
        assert calls == []
        assert len(read_inventory()) == 3

    def test_matching_is_case_insensitive(self, tmp_vault, tmp_db):
        from lib.inventory import bulk_apply
        self._seed()
        out = bulk_apply("remove", [self._ref("KALE", "Bunch", "Fridge")])
        assert out["applied"] == 1

    def test_unknown_action_raises(self, tmp_vault, tmp_db):
        import pytest
        from lib.inventory import bulk_apply
        with pytest.raises(ValueError, match="unknown action"):
            bulk_apply("explode", [self._ref("Kale", "bunch", "fridge")])

    def test_ref_missing_unit_raises(self, tmp_vault, tmp_db):
        import pytest
        from lib.inventory import bulk_apply
        with pytest.raises(ValueError, match="unit"):
            bulk_apply("remove", [{"name": "Kale", "location": "fridge"}])

    def test_ref_missing_location_raises(self, tmp_vault, tmp_db):
        import pytest
        from lib.inventory import bulk_apply
        with pytest.raises(ValueError, match="location"):
            bulk_apply("remove", [{"name": "Kale", "unit": "bunch"}])

    def test_missing_action_parameter_raises(self, tmp_vault, tmp_db):
        import pytest
        from lib.inventory import bulk_apply
        with pytest.raises(ValueError, match="days"):
            bulk_apply("extend", [self._ref("Kale", "bunch", "fridge")])
        with pytest.raises(ValueError, match="to_location"):
            bulk_apply("move", [self._ref("Kale", "bunch", "fridge")])
        with pytest.raises(ValueError, match="category"):
            bulk_apply("set-category", [self._ref("Kale", "bunch", "fridge")])
        with pytest.raises(ValueError, match="expires"):
            bulk_apply("set-expiry", [self._ref("Kale", "bunch", "fridge")])

    def test_missing_parameter_raises_even_when_nothing_matches(
        self, tmp_vault, tmp_db
    ):
        """Validation is about the request, not about what happens to match."""
        import pytest
        from lib.inventory import bulk_apply
        self._seed()
        with pytest.raises(ValueError, match="days"):
            bulk_apply("extend", [self._ref("Ghost", "ct", "fridge")])

    def test_non_integer_days_raises(self, tmp_vault, tmp_db):
        import pytest
        from lib.inventory import bulk_apply
        with pytest.raises(ValueError, match="days"):
            bulk_apply("extend", [self._ref("Kale", "bunch", "fridge")],
                       days="soon")
