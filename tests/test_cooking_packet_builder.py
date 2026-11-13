"""Packet composition uses real W40-shaped cooks without changing source data."""
from copy import deepcopy
from datetime import datetime, timezone
import sqlite3

import pytest

from lib import inventory_db, serving_ledger
from lib.cooking_packet_builder import allocate_pull_sources, build_week_draft
from lib.cooking_packet_store import _validate_generated

WEEK = "2026-W40"
NOW = datetime(2026, 9, 26, 12, tzinfo=timezone.utc)
RECIPE = """---
title: Soup
servings: 4
equipment: [Instant Pot, ladle]
source_url: https://example.test/soup
---

## Ingredients

| Amount | Unit | Ingredient |
|--------|------|------------|
| 2 | can | corn |
| 1 | cup | beans |

## Instructions

### Prep or Flavor Base

1. Soak beans overnight.

### Cook

1. Simmer the soup.

### Freeze and Store

1. Cool then freeze in portions.

### Reheat

1. Warm gently.
"""


def recipe_dir(tmp_vault):
    recipes = tmp_vault / "Recipes"
    recipes.mkdir(parents=True, exist_ok=True)
    (recipes / "Soup.md").write_text(RECIPE, encoding="utf-8")
    return recipes


def stock(row_id, name="corn", amount=1, unit="can", location="pantry", **extra):
    return {"id": row_id, "name": name, "quantity": amount, "unit": unit,
            "location": location, "location_source": "manual", "expires": None, **extra}


def need(item="corn", amount=2, unit="can", **extra):
    return {"item": item, "needed": {"amount": amount, "unit": unit},
            "from_pantry": {"amount": amount, "unit": unit}, **extra}


def test_unassigned_cooks_are_packet_recipes(tmp_db, tmp_vault):
    recipes = recipe_dir(tmp_vault)
    cooks = [serving_ledger.create_cook("Soup", WEEK, servings_produced=4) for _ in range(4)]
    packet = build_week_draft(WEEK, recipes, inventory_rows=[], now=NOW)
    assert [r["recipe"] for r in packet["recipe_cards"]] == ["Soup"]
    assert {c["cook_id"] for c in packet["cooks"]} == {c["id"] for c in cooks}
    assert all(c["unassigned"] == 4 for c in packet["cooks"])
    assert packet["recipe_cards"][0]["scale"] == 4
    assert packet["recipe_cards"][0]["ingredients"][0]["amount"] == "8"


def test_duplicate_inventory_locations_credit_once_and_name_both():
    rows = [stock(1), stock(2, location="garage")]
    pulls = allocate_pull_sources([need()], rows)
    assert sum(float(x["amount"]) for x in pulls) == 2
    assert {x["location"] for x in pulls} == {"pantry", "garage"}
    assert {x["inventory_row_id"] for x in pulls} == {1, 2}


def test_allocation_caps_shared_stock_across_lines_and_preserves_inputs():
    rows = [stock(1, amount=2)]
    lines = [need(amount=1), need(amount=2, item_id="second-demand")]
    before = deepcopy((rows, lines))
    pulls = allocate_pull_sources(lines, rows)
    assert sum(float(x["amount"]) for x in pulls) == 2
    assert (rows, lines) == before
    assert len({p["item_id"] for p in pulls}) == len(pulls)


def test_allocation_uses_expiry_then_row_id_and_retains_uncertainty():
    rows = [stock(4, location="garage", expires="2026-10-03"),
            stock(2, location="fridge", expires="2026-10-01", location_source=None),
            stock(1, location="freezer", expires="2026-10-01", location_source="default")]
    pulls = allocate_pull_sources([need(amount=2)], rows)
    assert [p["inventory_row_id"] for p in pulls] == [1, 2]
    assert all(p["location_source"] == "default" and p["location_uncertain"] for p in pulls)


def test_allocation_converts_units_and_does_not_recredit_consumed_row():
    pulls = allocate_pull_sources(
        [need("beans", 1, "lb"), need("beans", 8, "oz", item_id="more-beans")],
        [stock(1, "beans", 20, "oz")])
    assert [float(p["amount"]) for p in pulls] == [1, 4]
    assert [float(p["inventory_amount"]) for p in pulls] == [16, 4]


@pytest.mark.parametrize("row", [stock(1, "corn", 4, "ct"), stock(1, "corn flour", 2, "can")])
def test_uncertain_inventory_match_is_not_a_pull(row):
    assert allocate_pull_sources([need()], [row]) == []


def test_native_phases_schedule_equipment_and_sunday_range(tmp_db, tmp_vault):
    recipes = recipe_dir(tmp_vault)
    cook = serving_ledger.create_cook("Soup", WEEK, servings_produced=4)
    serving_ledger.schedule_cook(cook["id"], date="2026-09-29", meal="dinner",
                                 start="2026-09-29T18:00:00-05:00", timezone="America/Chicago",
                                 duration_minutes=60, servings_to_eat=1)
    packet = build_week_draft(WEEK, recipes, inventory_rows=[], now=NOW)
    card = packet["recipe_cards"][0]
    assert [x["step"] for x in card["instructions"]] == [1, 2, 3, 4]
    assert list(card["instruction_phases"]) == ["prep_or_flavor_base", "cook", "freeze_and_store", "reheat"]
    assert {row["text"] for row in packet["equipment"]} == {"Instant Pot", "ladle"}
    assert {row["phase"] for row in packet["freeze_reheat"]} == {"freeze_and_store", "reheat"}
    scheduled = next(row for row in packet["production_schedule"] if row["source"] == "cook_schedule")
    assert scheduled["cook_id"] == cook["id"] and scheduled["source"] == "cook_schedule"
    assert scheduled["start"] == "2026-09-29T18:00:00-05:00"
    assert packet["date_range"] == {"start": "2026-09-28", "end": "2026-10-04"}
    _validate_generated(WEEK, packet)


def test_missing_and_legacy_recipes_warn_without_losing_cooks(tmp_db, tmp_vault):
    recipes = recipe_dir(tmp_vault)
    (recipes / "Soup.md").write_text(RECIPE.replace("### Prep or Flavor Base\n\n", "").replace(
        "### Cook\n\n", "").replace("### Freeze and Store\n\n", "").replace("### Reheat\n\n", ""))
    serving_ledger.create_cook("Soup", WEEK, servings_produced=4)
    serving_ledger.create_cook("Missing", WEEK, servings_produced=4)
    packet = build_week_draft(WEEK, recipes, inventory_rows=[], now=NOW)
    assert {c["recipe"] for c in packet["recipe_cards"]} == {"Soup", "Missing"}
    soup = next(c for c in packet["recipe_cards"] if c["recipe"] == "Soup")
    assert soup["needs_classification"] is True and len(soup["instructions"]) == 4
    assert any(w["recipe"] == "Missing" for w in packet["warnings"])
    assert all(row["needs_review"] for row in packet["shared_prep"])


def test_recipe_display_changes_do_not_reidentify_card_or_steps(tmp_db, tmp_vault):
    recipes = recipe_dir(tmp_vault)
    serving_ledger.create_cook("Soup", WEEK, servings_produced=4)
    before = build_week_draft(WEEK, recipes, inventory_rows=[], now=NOW)
    (recipes / "Soup.md").write_text(RECIPE.replace("title: Soup", "title: A Better Soup").replace(
        "Simmer the soup.", "Simmer gently."))
    after = build_week_draft(WEEK, recipes, inventory_rows=[], now=NOW)
    assert before["recipe_cards"][0]["item_id"] == after["recipe_cards"][0]["item_id"]
    assert before["recipe_cards"][0]["instruction_phases"]["cook"][0]["item_id"] == after["recipe_cards"][0]["instruction_phases"]["cook"][0]["item_id"]
    _validate_generated(WEEK, after)


def test_building_draft_changes_no_database_or_vault_sources(tmp_db, tmp_vault):
    recipes = recipe_dir(tmp_vault)
    serving_ledger.create_cook("Soup", WEEK, servings_produced=4)
    inventory_db.merge_inventory_rows([stock(1), stock(2, location="garage")])
    rows = inventory_db.fetch_inventory_rows_with_ids()
    conn = inventory_db.connect()
    before_db = list(conn.iterdump())
    conn.close()
    before_files = {p: p.read_bytes() for p in tmp_vault.rglob("*") if p.is_file()}
    packet = build_week_draft(WEEK, recipes, now=NOW)
    assert packet["pull_list"] == []
    assert sum(float(p["amount"]) for p in packet["cook_day_pull"]) == 2
    assert any(row["item"] == "beans" for row in packet["shopping_list"])
    assert inventory_db.fetch_inventory_rows_with_ids() == rows
    conn = inventory_db.connect()
    assert list(conn.iterdump()) == before_db
    conn.close()
    assert {p: p.read_bytes() for p in tmp_vault.rglob("*") if p.is_file()} == before_files


def test_raw_inventory_reader_preserves_ids_and_distinct_locations(tmp_db):
    inventory_db.merge_inventory_rows([stock(1), stock(2, location="garage")])
    rows = inventory_db.fetch_inventory_rows_with_ids()
    assert len(rows) == 2 and len({r["id"] for r in rows}) == 2
    assert {r["location"] for r in rows} == {"pantry", "garage"}
    assert inventory_db.fetch_inventory_rows_with_ids() == rows


def test_invalid_week_is_rejected_before_reading_sources(tmp_db, tmp_vault):
    with pytest.raises(ValueError):
        build_week_draft("2026-W54", tmp_vault / "Recipes", inventory_rows=[])


def test_raw_inventory_reader_does_not_backfill_null_provenance(tmp_db):
    inventory_db.merge_inventory_rows([stock(1), stock(2, location="garage")])
    with sqlite3.connect(tmp_db) as conn:
        conn.execute("UPDATE inventory SET location_source = NULL WHERE location = 'garage'")
    rows = inventory_db.fetch_inventory_rows_with_ids()
    assert next(r for r in rows if r["location"] == "garage")["location_source"] is None
    with sqlite3.connect(tmp_db) as conn:
        assert conn.execute("SELECT location_source FROM inventory WHERE location = 'garage'").fetchone()[0] is None


def test_packet_ids_separate_distinct_units_for_same_ingredient(tmp_db, tmp_vault):
    recipes = recipe_dir(tmp_vault)
    (recipes / "Soup.md").write_text(RECIPE.replace("| 1 | cup | beans |", """| 1 | jar | beans |
| 2 | bag | beans |"""))
    serving_ledger.create_cook("Soup", WEEK, servings_produced=4)
    packet = build_week_draft(WEEK, recipes, inventory_rows=[], now=NOW)
    assert len([line for line in packet["shopping_list"] if line["item"] == "beans"]) == 2
    _validate_generated(WEEK, packet)


def test_fractional_allocation_does_not_round_past_stock():
    pulls = allocate_pull_sources([need(amount=1)], [stock(1, amount=0.666666)])
    assert pulls[0]["amount"] == pytest.approx(0.666666)
    assert pulls[0]["inventory_amount"] <= 0.666666


def test_expired_rows_are_not_credited_and_source_row_changes_reidentify_purchase(tmp_db, tmp_vault):
    recipes = recipe_dir(tmp_vault)
    serving_ledger.create_cook("Soup", WEEK, servings_produced=4)
    expired = stock(1, amount=2, expires="2026-09-25")
    packet = build_week_draft(WEEK, recipes, inventory_rows=[expired], now=NOW)
    assert packet["pull_list"] == []
    assert next(line for line in packet["shopping_list"] if line["item"] == "corn")["to_buy"]["amount"] == "2"
    first = build_week_draft(WEEK, recipes, inventory_rows=[stock(1)], now=NOW)
    second = build_week_draft(WEEK, recipes, inventory_rows=[stock(2)], now=NOW)
    first_id = next(line for line in first["shopping_list"] if line["item"] == "corn")["item_id"]
    second_id = next(line for line in second["shopping_list"] if line["item"] == "corn")["item_id"]
    assert first_id != second_id


@pytest.mark.parametrize("provenance", [None, "unrecognized"])
def test_full_build_preserves_uncertain_provenance_and_database_bytes(tmp_db, tmp_vault, provenance):
    recipes = recipe_dir(tmp_vault)
    cook = serving_ledger.create_cook("Soup", WEEK, servings_produced=4)
    serving_ledger.schedule_cook(cook["id"], date="2026-09-29", meal="dinner",
                                 start="2026-09-29T18:00:00-05:00", timezone="America/Chicago",
                                 duration_minutes=60, servings_to_eat=1)
    inventory_db.merge_inventory_rows([stock(1, amount=2, location="garage")])
    with sqlite3.connect(tmp_db) as conn:
        conn.execute("UPDATE inventory SET location_source = ?", (provenance,))
    with sqlite3.connect(tmp_db) as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        before_rows = list(conn.iterdump())
    before_bytes = tmp_db.read_bytes()
    packet = build_week_draft(WEEK, recipes, now=NOW)
    assert packet["pull_list"] == []
    assert packet["cook_day_pull"][0]["location_uncertain"] is True
    assert packet["cook_day_pull"][0]["location_source"] == "default"
    assert next(row for row in packet["production_schedule"] if row["source"] == "cook_schedule")["cook_id"] == cook["id"]
    assert tmp_db.read_bytes() == before_bytes
    with sqlite3.connect(tmp_db) as conn:
        assert list(conn.iterdump()) == before_rows
        assert conn.execute("SELECT location_source FROM inventory").fetchone()[0] == provenance


@pytest.mark.parametrize("reverse", [False, True])
def test_build_credits_full_need_across_inventory_units(tmp_db, tmp_vault, reverse):
    recipes = recipe_dir(tmp_vault)
    (recipes / "Soup.md").write_text(RECIPE.replace("| 1 | cup | beans |", "| 1 | lb | beans |"))
    serving_ledger.create_cook("Soup", WEEK, servings_produced=4)
    rows = [stock(1, "beans", 8, "oz", expires="2026-09-30"),
            stock(2, "beans", 1, "lb", location="garage", expires="2026-10-01")]
    packet = build_week_draft(WEEK, recipes, inventory_rows=list(reversed(rows)) if reverse else rows, now=NOW)
    line = next(line for line in packet["shopping_list"] if line["item"] == "beans")
    assert line["from_pantry"] == {"amount": 1, "unit": "lb"}
    assert line["to_buy"] is None
    assert packet["pull_list"] == []
    assert [pull["inventory_amount"] for pull in packet["cook_day_pull"]] == [8, 0.5]
    assert [pull["inventory_row_id"] for pull in packet["cook_day_pull"]] == [1, 2]


def test_insufficient_mixed_units_leave_only_exact_gap_to_buy(tmp_db, tmp_vault):
    recipes = recipe_dir(tmp_vault)
    (recipes / "Soup.md").write_text(RECIPE.replace("| 1 | cup | beans |", "| 1 | lb | beans |"))
    serving_ledger.create_cook("Soup", WEEK, servings_produced=4)
    packet = build_week_draft(WEEK, recipes, inventory_rows=[
        stock(1, "beans", 4, "oz"), stock(2, "beans", 0.5, "lb", location="garage")], now=NOW)
    line = next(line for line in packet["shopping_list"] if line["item"] == "beans")
    assert line["from_pantry"] == {"amount": 0.75, "unit": "lb"}
    assert line["to_buy"] == {"amount": 0.25, "unit": "lb"}


@pytest.mark.parametrize("reverse", [False, True])
def test_allocator_multiple_demands_use_all_units_without_double_credit(reverse):
    lines = [need("beans", 1, "lb", from_pantry={"amount": 0.5, "unit": "lb"}, item_id="first"),
             need("beans", 12, "oz", from_pantry=None, item_id="second")]
    if reverse:
        lines.reverse()
    pulls = allocate_pull_sources(lines, [stock(1, "beans", 8, "oz"), stock(2, "beans", 1, "lb")])
    assert sum(p["inventory_amount"] for p in pulls if p["inventory_unit"] == "oz") == 8
    assert sum(p["inventory_amount"] for p in pulls if p["inventory_unit"] == "lb") == 1
    allocated_oz = sum(p["amount"] * (16 if p["unit"] == "lb" else 1) for p in pulls)
    assert allocated_oz == 24
    assert {p["line_id"] for p in pulls} == {"first", "second"}


def test_compatible_stock_is_used_after_an_uncertain_first_match(tmp_db, tmp_vault):
    recipes = recipe_dir(tmp_vault)
    serving_ledger.create_cook("Soup", WEEK, servings_produced=4)
    packet = build_week_draft(WEEK, recipes, inventory_rows=[
        stock(1, amount=1, unit="ct"), stock(2, amount=2, location="garage")], now=NOW)
    line = next(line for line in packet["shopping_list"] if line["item"] == "corn")
    assert line["from_pantry"] == {"amount": 2, "unit": "can"}
    assert line["to_buy"] is None
    assert packet["pull_list"] == []
    assert [pull["inventory_row_id"] for pull in packet["cook_day_pull"]] == [2]


def test_empty_build_does_not_create_an_absent_database(tmp_db, tmp_vault):
    packet = build_week_draft(WEEK, recipe_dir(tmp_vault), now=NOW)
    assert packet["cooks"] == [] and packet["production_schedule"] == []
    assert not tmp_db.exists()


def test_legacy_packet_derives_reviewable_phases_without_mutating_flat_steps(tmp_db, tmp_vault):
    recipes = recipe_dir(tmp_vault)
    text = RECIPE.split("## Instructions")[0] + "## Instructions\n\n1. Chop onions.\n2. Simmer for 20 minutes.\n3. Do the usual thing.\n"
    (recipes / "Soup.md").write_text(text)
    serving_ledger.create_cook("Soup", WEEK, servings_produced=4)
    packet = build_week_draft(WEEK, recipes, inventory_rows=[], now=NOW)
    card = packet["recipe_cards"][0]
    assert list(card["instruction_phases"]) == ["prep_or_flavor_base", "cook", "instructions"]
    assert all("phase" not in row for row in card["instructions"])
    assert card["instruction_phases"]["instructions"][0]["needs_review"] is True
    # Unassociated onions cannot become freezer prep while both source
    # ingredients still have unresolved destinations.
    assert packet["shared_prep"] == []
    assert packet["production_schedule"] == []
    assert (recipes / "Soup.md").read_text() == text
    _validate_generated(WEEK, packet)


def test_native_unmolding_is_scheduled_after_source_freezing(tmp_db, tmp_vault):
    recipes = recipe_dir(tmp_vault)
    (recipes / "Soup.md").write_text(RECIPE.replace("1. Cool then freeze in portions.", "1. Freeze in portions.\n2. Unmold and bag."))
    cook = serving_ledger.create_cook("Soup", WEEK, servings_produced=4)
    serving_ledger.schedule_cook(cook["id"], date="2026-09-29", meal="dinner",
                                 start="2026-09-29T18:00:00-05:00", timezone="America/Chicago",
                                 duration_minutes=60, servings_to_eat=1)
    packet = build_week_draft(WEEK, recipes, inventory_rows=[], now=NOW)
    row = next(row for row in packet["production_schedule"] if row.get("text") == "Unmold and bag.")
    assert row["date"] == "2026-09-30"
    _validate_generated(WEEK, packet)


@pytest.mark.parametrize("same_recipe", [False, True])
def test_immediate_prep_stays_with_each_cook_session_and_quantity(tmp_db, tmp_vault, same_recipe):
    recipes = recipe_dir(tmp_vault)
    source = RECIPE.split("## Instructions")[0].replace("| 1 | cup | beans |", "| 1 | lb | black-eyed peas |") + "## Instructions\n\n### Cook\n\n1. Pressure cook 1 lb black-eyed peas for 10 minutes with a 3:1 water-to-bean ratio; natural release; use immediately.\n2. Put black-eyed peas in the freezer bag.\n"
    (recipes / "Soup.md").write_text(source)
    (recipes / "Other.md").write_text(source)
    cooks = []
    for name, day, scale in [("Soup", "2026-09-29", 1), ("Soup" if same_recipe else "Other", "2026-10-01", 2)]:
        row = serving_ledger.create_cook(name, WEEK, scale=scale, servings_produced=4 * scale)
        serving_ledger.schedule_cook(row["id"], date=day, meal="dinner", start=day + "T18:00:00-05:00",
            timezone="America/Chicago", duration_minutes=60, servings_to_eat=1)
        cooks.append(row)
    packet = build_week_draft(WEEK, recipes, inventory_rows=[], now=NOW)
    prep = [row for row in packet["production_schedule"] if row.get("source") == "packet"]
    assert [(row["date"], row["amount"]) for row in prep] == [("2026-09-29", 1), ("2026-10-01", 2)]
    assert {source for row in packet["shared_prep"] for source in row["dependent_cook_ids"]} == {row["id"] for row in cooks}
    source_steps = {card["recipe"]: card["instruction_phases"]["cook"][0]["source_id"] for card in packet["recipe_cards"]}
    assert all(part["recipe_source_id"] == source_steps[part["recipe"]]
               for row in packet["shared_prep"] for part in row["contributions"])
    _validate_generated(WEEK, packet)


def test_immediate_prep_can_merge_two_recipes_in_one_authoritative_session(tmp_db, tmp_vault):
    recipes = recipe_dir(tmp_vault)
    source = RECIPE.split("## Instructions")[0].replace("| 1 | cup | beans |", "| 1 | lb | black-eyed peas |") + "## Instructions\n\n### Cook\n\n1. Pressure cook 1 lb black-eyed peas for 10 minutes with a 3:1 water-to-bean ratio; natural release; use immediately.\n2. Put black-eyed peas in the freezer bag.\n"
    for name in ("Soup", "Other"):
        (recipes / f"{name}.md").write_text(source)
        row = serving_ledger.create_cook(name, WEEK, servings_produced=4)
        serving_ledger.schedule_cook(row["id"], date="2026-09-29", meal="dinner", start="2026-09-29T18:00:00-05:00",
            timezone="America/Chicago", duration_minutes=60, servings_to_eat=1)
    packet = build_week_draft(WEEK, recipes, inventory_rows=[], now=NOW)
    assert len(packet["shared_prep"]) == 1
    assert packet["shared_prep"][0]["amount"] == 2
    assert len(packet["shared_prep"][0]["dependent_cook_ids"]) == 2
    _validate_generated(WEEK, packet)


def test_packet_stages_every_ingredient_keeps_shopping_and_excludes_cook_day_prep(tmp_db, tmp_vault):
    recipes = recipe_dir(tmp_vault)
    source = '''---
title: Soup
servings: 4
---
## Ingredients

| Amount | Unit | Ingredient |
| --- | --- | --- |
| 1 | cup | carrots |
| 1 | cup | cream |
| 1 | cup | rice |
| 1 | cup | cilantro |
| 1 | cup | stock |
| 1 | cup | salt |
| 1 | cup | onion |

## Instructions

1. Chop carrots, then add them to the freezer bag.
2. Add cream after pressure release.
3. Freeze rice separately.
4. Serve with cilantro.
5. Add stock when cooking.
6. Put onion in the freezer bag.
7. Chop cilantro finely.
8. Mix cream and stock.
9. Wash and chop cilantro.
10. Wash rice.
11. Measure salt.
12. Chop carrots.
'''
    (recipes / 'Soup.md').write_text(source)
    serving_ledger.create_cook('Soup', WEEK, scale=2, servings_produced=8)
    packet = build_week_draft(WEEK, recipes, inventory_rows=[], now=NOW)
    card = packet['recipe_cards'][0]
    assert [row['prep_stage'] for row in card['ingredients']] == [
        'prep_then_bag', 'finish_after_cooking', 'freeze_separately', 'serve_separately',
        'add_at_cook_time', 'needs_review', 'bag_now']
    assert {row['item'] for row in packet['shopping_list']} == {
        'carrots', 'cream', 'rice', 'cilantro', 'stock', 'salt', 'onion'}
    assert {row['item_id'] for row in card['ingredients']} == {
        source_id for row in packet['shopping_list'] for source_id in row['source_ingredient_ids']}
    assert all(float(row['needed']['amount']) == 2 for row in packet['shopping_list'])
    assert [row['text'] for row in packet['shared_prep']] == ['Chop carrots.']
    assert not any(row.get('text') in ('Chop cilantro finely.', 'Mix cream and stock.',
                   'Wash and chop cilantro.', 'Wash rice.', 'Measure salt.',
                   'Chop carrots, then add them to the freezer bag.') for row in packet['production_schedule'])
    assert all('prep_stage' not in row for row in card['instructions'])
    assert (recipes / 'Soup.md').read_text() == source
    _validate_generated(WEEK, packet)
    again = build_week_draft(WEEK, recipes, inventory_rows=[], now=NOW)
    assert again == packet


def staged_pair(tmp_vault, first=(1, 'cup'), second=(1, 'cup')):
    recipes = tmp_vault / 'Recipes'
    recipes.mkdir(parents=True, exist_ok=True)
    for name, (amount, unit), instruction in [
        ('Bag carrots', first, 'Put carrots in the freezer bag.'),
        ('Finish carrots', second, 'Add carrots after pressure release.'),
    ]:
        (recipes / f'{name}.md').write_text(f'''---
title: {name}
servings: 4
---
## Ingredients

| Amount | Unit | Ingredient |
| --- | --- | --- |
| {amount} | {unit} | carrots |

## Instructions

1. {instruction}
''')
        serving_ledger.create_cook(name, WEEK, servings_produced=4)
    return recipes


@pytest.mark.parametrize('available, now_amount, later_amount, buy', [
    (0.5, 0.5, 0, 1.5), (1.5, 1, 0.5, 0.5), (3, 1, 1, 0),
])
def test_staged_inventory_pulls_prioritize_freezer_demand_without_recrediting(tmp_db, tmp_vault,
                                                                          available, now_amount, later_amount, buy):
    recipes = staged_pair(tmp_vault)
    packet = build_week_draft(WEEK, recipes, inventory_rows=[stock(7, 'carrots', available, 'cup')], now=NOW)
    assert sum(row['amount'] for row in packet['pull_list']) == pytest.approx(now_amount)
    assert sum(row['amount'] for row in packet['cook_day_pull']) == pytest.approx(later_amount)
    pulls = packet['pull_list'] + packet['cook_day_pull']
    line = packet['shopping_list'][0]
    assert line['needed'] == {'amount': '2', 'unit': 'cup'}
    assert sum(row['amount'] for row in pulls) == pytest.approx(line['from_pantry']['amount'])
    assert line['from_pantry']['amount'] == pytest.approx(min(2, available))
    assert sum(row['inventory_amount'] for row in pulls) == pytest.approx(min(2, available))
    assert (line['to_buy']['amount'] if line['to_buy'] else 0) == pytest.approx(buy)
    assert {row['inventory_row_id'] for row in pulls} == {7}
    assert {row['line_id'] for row in pulls} == {line['item_id']}
    assert all(row['prep_stage_group'] == 'freezer_session' and row['prep_stage'] == 'bag_now' for row in packet['pull_list'])
    assert all(row['prep_stage_group'] == 'cook_day' and row['prep_stage'] == 'finish_after_cooking' for row in packet['cook_day_pull'])
    assert len({row['item_id'] for row in pulls}) == len(pulls)
    _validate_generated(WEEK, packet)
    again = build_week_draft(WEEK, recipes, inventory_rows=[stock(7, 'carrots', available, 'cup')], now=NOW)
    assert again == packet


def test_staged_mixed_unit_subpulls_keep_expiry_order_locations_and_exact_container_credit(tmp_db, tmp_vault):
    recipes = staged_pair(tmp_vault, (1, 'lb'), (8, 'oz'))
    rows = [stock(3, 'carrots', 1, 'lb', location='garage', expires='2026-10-02', location_source=None),
            stock(1, 'carrots', 12, 'oz', location='fridge', expires='2026-10-01')]
    before = deepcopy(rows)
    packet = build_week_draft(WEEK, recipes, inventory_rows=rows, now=NOW)
    assert [row['inventory_row_id'] for row in packet['pull_list']] == [1, 3]
    assert [row['inventory_amount'] for row in packet['pull_list']] == [12, 0.25]
    assert [row['inventory_amount'] for row in packet['cook_day_pull']] == [0.5]
    assert [row['location'] for row in packet['pull_list']] == ['fridge', 'garage']
    assert packet['pull_list'][1]['location_source'] == 'default' and packet['pull_list'][1]['location_uncertain']
    assert packet['cook_day_pull'][0]['expires'] == '2026-10-02'
    assert packet['cook_day_pull'][0]['location_source'] == 'default' and packet['cook_day_pull'][0]['location_uncertain']
    assert sum(row['inventory_amount'] for row in packet['pull_list'] + packet['cook_day_pull']
               if row['inventory_row_id'] == 3) == 0.75
    assert packet['shopping_list'][0]['from_pantry'] == {'amount': 1.5, 'unit': 'lb'}
    assert packet['shopping_list'][0]['to_buy'] is None
    assert rows == before
    _validate_generated(WEEK, packet)


def partition_fixture(stage='bag_now', review=False):
    return {'version': 1, 'week': WEEK,
            'recipe_cards': [{'item_id': 'recipe:test', 'ingredients': [
                {'item_id': 'ingredient:test', 'item': 'carrots', 'amount': 1, 'unit': 'cup',
                 'prep_stage': stage, 'stage_source': 'model' if review else 'recipe',
                 'stage_reason': 'Source destination', 'needs_review': review}]}],
            'shopping_list': [{'item_id': 'shopping:test', 'item': 'carrots',
                               'needed': {'amount': 1, 'unit': 'cup'},
                               'from_pantry': {'amount': 1, 'unit': 'cup'}, 'to_buy': None,
                               'source_ingredient_ids': ['ingredient:test']}],
            'pull_list': [{'item_id': 'pull:test', 'line_id': 'shopping:test', 'item': 'carrots',
                           'amount': 1, 'unit': 'cup', 'inventory_amount': 1, 'inventory_unit': 'cup',
                           'inventory_row_id': 9, 'location': 'pantry', 'location_source': 'manual',
                           'location_uncertain': False, 'expires': None, 'done': False}]}


@pytest.mark.parametrize('stage, review, expected', [
    ('bag_now', False, 'pull_list'), ('prep_then_bag', False, 'pull_list'),
    ('freeze_separately', False, 'pull_list'), ('add_at_cook_time', False, 'cook_day_pull'),
    ('finish_after_cooking', False, 'cook_day_pull'), ('serve_separately', False, 'cook_day_pull'),
    ('needs_review', False, 'cook_day_pull'), ('bag_now', True, 'cook_day_pull'),
    ('freeze_separately', True, 'cook_day_pull'), ('', False, 'cook_day_pull'),
    (None, False, 'cook_day_pull'), ('unknown', False, 'cook_day_pull'),
])
def test_pull_partition_uses_confirmed_stages_and_keeps_unknowns_later(stage, review, expected):
    from lib import cooking_packet_builder as builder
    source = partition_fixture(stage, review)
    before = deepcopy(source)
    packet = builder.repartition_packet_pulls(source)
    other = 'cook_day_pull' if expected == 'pull_list' else 'pull_list'
    assert len(packet[expected]) == 1 and packet[other] == []
    assert packet['shopping_list'] == source['shopping_list']
    assert source == before
    assert builder.repartition_packet_pulls(packet) == packet
    if review or stage not in {'bag_now', 'prep_then_bag', 'freeze_separately', 'add_at_cook_time',
                              'finish_after_cooking', 'serve_separately'}:
        assert packet[expected][0]['needs_review'] and packet[expected][0]['stage_reason']
    _validate_generated(WEEK, packet)


from lib.cooking_packet_builder import _settle_line


def test_settle_keeps_on_hand_lines_off_the_buy_list():
    line = {"status": "on_hand", "needed": {"amount": "1", "unit": "tsp"},
            "from_pantry": None, "to_buy": None, "warning": None}
    _settle_line(line, 0.0)
    assert line["status"] == "on_hand"
    assert line["to_buy"] is None


def test_settle_uncredited_line_still_buys():
    line = {"status": "buy", "needed": {"amount": "2", "unit": ""},
            "from_pantry": None, "to_buy": None, "warning": None}
    _settle_line(line, 0.0)
    assert line["status"] == "buy"
    assert line["to_buy"] == {"amount": "2", "unit": ""}
