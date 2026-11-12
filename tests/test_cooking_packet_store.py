"""Packet repository contracts against an isolated, real SQLite database."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import importlib
import json
import threading

import pytest

from lib import inventory_db


@pytest.fixture
def store(tmp_db):
    return importlib.import_module("lib.cooking_packet_store")


def draft(ids=("cook:58",)):
    return {
        "version": 1,
        "week": "2026-W40",
        "schedule": [{"item_id": key, "text": "Generated", "done": False} for key in ids],
        "recipe_cards": [{"item_id": "recipe:Soup", "recipe": "Soup", "notes": ""}],
    }


def change(item_id="cook:58", field="text", value="Mine"):
    return {"item_id": item_id, "field": field, "value": value}


def test_missing_packet_returns_none(store):
    assert store.get_packet("2026-W40") is None


def test_replace_reads_committed_packet_and_does_not_mutate_input(store):
    generated = draft()
    original = deepcopy(generated)
    saved = store.replace_generated("2026-W40", generated)
    assert saved == store.get_packet("2026-W40")
    assert saved["revision"] == 1
    assert saved["status"] == "draft"
    assert saved["generated_at"] and saved["updated_at"]
    assert generated == original


def test_sparse_edits_follow_stable_id_after_reordering(store):
    first = store.replace_generated("2026-W40", draft(("cook:58", "cook:59")))
    store.patch_packet("2026-W40", first["revision"], [change(), change(field="done", value=True)])
    saved = store.replace_generated("2026-W40", draft(("cook:59", "cook:58")))
    assert saved["schedule"][0]["text"] == "Generated"
    assert saved["schedule"][1]["text"] == "Mine"
    assert saved["schedule"][1]["done"] is True
    assert saved["needs_review"] == []
    with inventory_db.connect() as conn:
        raw = conn.execute("SELECT generated_json FROM cooking_packets").fetchone()[0]
    assert '"Mine"' not in raw


def test_replace_preserves_orphan_edits_until_source_returns(store):
    first = store.replace_generated("2026-W40", draft())
    store.patch_packet("2026-W40", first["revision"], [change()])
    saved = store.replace_generated("2026-W40", draft(("cook:59",)))
    assert saved["needs_review"][0]["item_id"] == "cook:58"
    assert saved["needs_review"][0]["value"] == "Mine"
    assert saved["schedule"][0]["text"] == "Generated"
    again = store.replace_generated("2026-W40", draft(("cook:59",)))
    assert again["needs_review"] == saved["needs_review"]
    restored = store.replace_generated("2026-W40", draft())
    assert restored["schedule"][0]["text"] == "Mine"
    assert restored["needs_review"] == []


def test_null_deletes_active_overrides_and_reload_uses_generated_values(store):
    first = store.replace_generated("2026-W40", draft())
    edited = store.patch_packet("2026-W40", first["revision"], [change(), change(field="done", value=True)])
    saved = store.patch_packet("2026-W40", edited["revision"], [change(value=None), change(field="done", value=None)])
    assert saved["revision"] == edited["revision"] + 1
    assert saved["schedule"][0]["text"] == "Generated"
    assert saved["schedule"][0]["done"] is False
    assert saved["edits"] == []
    assert store.get_packet("2026-W40") == saved
    with inventory_db.connect() as conn:
        assert json.loads(conn.execute("SELECT edits_json FROM cooking_packets").fetchone()[0]) == []
    regenerated = draft()
    regenerated["schedule"][0]["text"] = "New source wording"
    assert store.replace_generated("2026-W40", regenerated)["schedule"][0]["text"] == "New source wording"


def test_null_deletes_specific_orphan_and_source_return_cannot_restore_it(store):
    first = store.replace_generated("2026-W40", draft())
    store.patch_packet("2026-W40", first["revision"], [change(), change(field="done", value=True)])
    orphaned = store.replace_generated("2026-W40", draft(("cook:59",)))
    saved = store.patch_packet("2026-W40", orphaned["revision"], [change(value=None)])
    assert saved["revision"] == orphaned["revision"] + 1
    assert saved["edits"] == [change(field="done", value=True)]
    assert [edit["field"] for edit in saved["needs_review"]] == ["done"]
    assert store.get_packet("2026-W40") == saved
    restored = store.replace_generated("2026-W40", draft())
    assert restored["schedule"][0]["text"] == "Generated"
    assert restored["schedule"][0]["done"] is True
    assert restored["needs_review"] == []


def test_null_deletes_last_orphan_permanently(store):
    first = store.replace_generated("2026-W40", draft())
    store.patch_packet("2026-W40", first["revision"], [change()])
    orphaned = store.replace_generated("2026-W40", draft(()))
    saved = store.patch_packet("2026-W40", orphaned["revision"], [change(value=None)])
    assert saved["needs_review"] == []
    assert saved["edits"] == []
    assert store.get_packet("2026-W40") == saved
    assert store.replace_generated("2026-W40", draft())["schedule"][0]["text"] == "Generated"


@pytest.mark.parametrize("orphan", [False, True])
def test_stale_null_deletion_preserves_current_override(store, orphan):
    first = store.replace_generated("2026-W40", draft())
    edited = store.patch_packet("2026-W40", first["revision"], [change()])
    latest = store.replace_generated("2026-W40", draft(())) if orphan else edited
    with pytest.raises(store.RevisionConflict):
        store.patch_packet("2026-W40", latest["revision"] - 1, [change(value=None)])
    assert store.get_packet("2026-W40") == latest
    assert store.replace_generated("2026-W40", draft())["schedule"][0]["text"] == "Mine"


def test_invalid_batch_rolls_back_null_deletion(store):
    first = store.replace_generated("2026-W40", draft())
    store.patch_packet("2026-W40", first["revision"], [change()])
    orphaned = store.replace_generated("2026-W40", draft(()))
    with pytest.raises(ValueError):
        store.patch_packet("2026-W40", orphaned["revision"], [change(value=None), change(item_id="recipe:Soup", field="recipe", value="Other")])
    assert store.get_packet("2026-W40") == orphaned
    assert store.replace_generated("2026-W40", draft())["schedule"][0]["text"] == "Mine"


def test_null_without_existing_override_still_consumes_patch_revision(store):
    packet = store.replace_generated("2026-W40", draft())
    saved = store.patch_packet("2026-W40", packet["revision"], [change(value=None)])
    assert saved["revision"] == packet["revision"] + 1
    assert saved["edits"] == []
    assert saved["schedule"][0]["text"] == "Generated"
    with pytest.raises(ValueError):
        store.patch_packet("2026-W40", saved["revision"], [change(item_id="missing", value=None)])
    with pytest.raises(ValueError):
        store.patch_packet("2026-W40", saved["revision"], [change(field="recipe", value=None)])
    assert store.get_packet("2026-W40") == saved


def test_stale_revision_cannot_overwrite_newer_edit(store):
    first = store.replace_generated("2026-W40", draft())
    latest = store.patch_packet("2026-W40", first["revision"], [change()])
    with pytest.raises(store.RevisionConflict):
        store.patch_packet("2026-W40", first["revision"], [change(value="Stale")])
    assert store.get_packet("2026-W40") == latest


def test_two_concurrent_edits_with_same_revision_have_one_winner(store):
    first = store.replace_generated("2026-W40", draft())
    barrier = threading.Barrier(2)

    def edit(text):
        barrier.wait(timeout=5)
        try:
            return store.patch_packet("2026-W40", first["revision"], [change(value=text)])
        except store.RevisionConflict:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(edit, ["First", "Second"]))
    winners = [result for result in results if result is not None]
    assert len(winners) == 1
    assert store.get_packet("2026-W40") == winners[0]
    assert winners[0]["revision"] == first["revision"] + 1


def test_review_applies_to_current_revision_and_refresh_clears_it(store):
    packet = store.replace_generated("2026-W40", draft())
    reviewed = store.patch_packet("2026-W40", packet["revision"], [], status="reviewed")
    assert reviewed["status"] == "reviewed" and reviewed["reviewed_at"]
    regenerated = store.replace_generated("2026-W40", draft())
    assert regenerated["status"] == "draft" and regenerated["reviewed_at"] is None
    reviewed = store.patch_packet("2026-W40", regenerated["revision"], [], status="reviewed")
    edited = store.patch_packet("2026-W40", reviewed["revision"], [change()])
    assert edited["status"] == "draft" and edited["reviewed_at"] is None


def test_store_snapshot_preserves_edits_and_checks_revision(store):
    packet = store.replace_generated("2026-W40", draft())
    edited = store.patch_packet("2026-W40", packet["revision"], [change()], status="reviewed")
    snapshot = {"version": 1, "heb": {"products": [{"name": "H-E-B rice"}]}}
    saved = store.replace_store_snapshot("2026-W40", edited["revision"], snapshot)
    assert saved["store_snapshot"] == snapshot
    assert saved["schedule"][0]["text"] == "Mine"
    assert saved["status"] == "draft" and saved["reviewed_at"] is None
    assert saved["store_refreshed_at"]
    with pytest.raises(store.RevisionConflict):
        store.replace_store_snapshot("2026-W40", edited["revision"], {"version": 1})
    assert store.get_packet("2026-W40") == saved
    assert store.replace_generated("2026-W40", draft())["store_snapshot"] == snapshot


def test_repeated_generation_request_does_not_discard_later_edit(store):
    packet = store.replace_generated("2026-W40", draft(), request_id="request-1")
    edited = store.patch_packet("2026-W40", packet["revision"], [change()])
    assert store.replace_generated("2026-W40", draft(("cook:59",)), request_id="request-1") == edited


def test_request_id_stays_idempotent_after_other_refreshes(store):
    store.replace_generated("2026-W40", draft(), request_id="request-1")
    latest = store.replace_generated("2026-W40", draft(("cook:59",)), request_id="request-2")
    assert store.replace_generated("2026-W40", draft(), request_id="request-1") == latest


def test_identical_replacements_do_not_increment_revision(store):
    packet = store.replace_generated("2026-W40", draft())
    assert store.replace_generated("2026-W40", draft()) == packet
    snapshot = {"version": 1, "heb": {"products": []}}
    saved = store.replace_store_snapshot("2026-W40", packet["revision"], snapshot)
    assert store.replace_store_snapshot("2026-W40", saved["revision"], snapshot) == saved


@pytest.mark.parametrize("week", ["2026-W00", "2026-W54", "2021-W53", "2026-W4", "2026-w40", "../2026-W40", None])
def test_invalid_week_is_rejected_before_access(store, week):
    with pytest.raises(ValueError):
        store.get_packet(week)
    with pytest.raises(ValueError):
        store.replace_generated(week, draft())
    assert store.get_packet("2026-W40") is None


@pytest.mark.parametrize("generated", [
    {"version": 2}, {"version": True}, {}, {"version": 1, "week": "2026-W41"},
    {"version": 1, "status": "approved"},
    {"version": 1, "schedule": [{"item_id": "same"}, {"item_id": "same"}]},
    {"version": 1, "notes": "a" * 10001},
    {"version": 1, "schedule": [{"item_id": f"task:{i}"} for i in range(2001)]},
    {"version": 1, "notes": ["a" * 10000] * 220},
    {"version": 1, "amount": float("nan")},
    {"version": 1, "revision": 8},
    {"version": 1, "schedule": [{"item_id": ""}]},
])
def test_invalid_generated_document_rolls_back(store, generated):
    before = store.replace_generated("2026-W40", draft())
    with pytest.raises(ValueError):
        store.replace_generated("2026-W40", generated)
    assert store.get_packet("2026-W40") == before


@pytest.mark.parametrize("changes", [
    [change(field="recipe", value="Another recipe")],
    [change(field="text.html")], [change(field="__proto__")],
    [change(item_id="missing")], [dict(change(), extra=True)],
    [{"item_id": "cook:58", "field": "text"}],
    [change(field="done", value="yes")], [change(value="a" * 10001)],
    [change(value=float("inf"))], [change(field="duration_minutes", value=-1)],
    [change(field="phase", value="unknown")],
])
def test_invalid_patch_rolls_back_all_changes(store, changes):
    before = store.replace_generated("2026-W40", draft())
    with pytest.raises(ValueError):
        store.patch_packet("2026-W40", before["revision"], [change(value="Must roll back")] + changes)
    assert store.get_packet("2026-W40") == before


def test_total_document_size_includes_edits_and_snapshot(store):
    generated = draft()
    generated["notes"] = ["a" * 10000] * 110
    before = store.replace_generated("2026-W40", generated)
    with pytest.raises(ValueError):
        store.replace_store_snapshot("2026-W40", before["revision"], {"version": 1, "notes": ["b" * 10000] * 110})
    assert store.get_packet("2026-W40") == before


@pytest.mark.parametrize("revision", [True, 0, -1, "1", None])
def test_invalid_revision_rejected(store, revision):
    before = store.replace_generated("2026-W40", draft())
    with pytest.raises(ValueError):
        store.patch_packet("2026-W40", revision, [])
    assert store.get_packet("2026-W40") == before


def test_invalid_status_and_snapshot_roll_back(store):
    before = store.replace_generated("2026-W40", draft())
    with pytest.raises(ValueError):
        store.patch_packet("2026-W40", before["revision"], [], status="approved")
    with pytest.raises(ValueError):
        store.replace_store_snapshot("2026-W40", before["revision"], {"version": 2})
    assert store.get_packet("2026-W40") == before


def test_quantity_date_and_phase_edits_are_packet_only(store):
    packet = store.replace_generated("2026-W40", draft())
    saved = store.patch_packet("2026-W40", packet["revision"], [
        change(field="quantity", value=1.5), change(field="date", value="2026-09-27"),
        change(field="phase", value="cook"), change(field="duration_minutes", value=30),
    ])
    assert saved["schedule"][0]["quantity"] == 1.5
    assert saved["schedule"][0]["date"] == "2026-09-27"
    assert saved["schedule"][0]["phase"] == "cook"
    with inventory_db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM cook_schedule").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM inventory").fetchone()[0] == 0


def test_editing_missing_packet_does_not_create_one(store):
    with pytest.raises(KeyError):
        store.patch_packet("2026-W40", 1, [])
    with pytest.raises(KeyError):
        store.replace_store_snapshot("2026-W40", 1, {"version": 1})
    assert store.get_packet("2026-W40") is None


def test_retailer_preferences_expose_explicit_policy(store):
    prefs = store.retailer_preferences()
    assert prefs["heb"]["location_id"] == "425"
    assert prefs["costco"]["location_id"] == "681"
    assert prefs["heb"]["policy"]["prefer_owned_brand"] is True
    assert prefs["heb"]["policy"]["reason"] == "cashback"
    assert prefs["costco"]["policy"]["require_bulk_suitability"] is True
    assert prefs["heb"]["preference_rank"] < prefs["costco"]["preference_rank"]


@pytest.mark.parametrize('stage', ['bag_now', 'prep_then_bag', 'freeze_separately', 'add_at_cook_time',
                                  'finish_after_cooking', 'serve_separately', 'needs_review'])
def test_ingredient_stage_override_uses_exact_sparse_edit_and_null_delete(store, stage):
    generated = draft()
    generated['recipe_cards'][0]['ingredients'] = [{'item_id': 'ingredient:1', 'item': 'cream',
                                                  'prep_stage': 'needs_review', 'needs_review': True}]
    first = store.replace_generated('2026-W40', generated)
    edit = change(item_id='ingredient:1', field='prep_stage', value=stage)
    saved = store.patch_packet('2026-W40', first['revision'], [edit])
    assert saved['recipe_cards'][0]['ingredients'][0]['prep_stage'] == stage
    assert saved['edits'] == [edit] and saved['revision'] == first['revision'] + 1
    with pytest.raises(store.RevisionConflict):
        store.patch_packet('2026-W40', first['revision'], [{**edit, 'value': None}])
    assert store.get_packet('2026-W40') == saved
    deleted = store.patch_packet('2026-W40', saved['revision'], [{**edit, 'value': None}])
    assert deleted['edits'] == [] and deleted['revision'] == saved['revision'] + 1
    assert deleted['recipe_cards'][0]['ingredients'][0]['prep_stage'] == 'needs_review'


@pytest.mark.parametrize('invalid', ['unknown', '', 1, True, [], {}])
def test_invalid_ingredient_stage_rolls_back_entire_patch(store, invalid):
    saved = store.replace_generated('2026-W40', draft())
    with pytest.raises(ValueError):
        store.patch_packet('2026-W40', saved['revision'], [change(), change(field='prep_stage', value=invalid)])
    assert store.get_packet('2026-W40') == saved


def test_reviewing_model_stage_confirms_only_merged_row_and_null_restores_generation(store):
    generated = draft()
    ingredient = {'item_id': 'ingredient:1', 'item': 'cream', 'prep_stage': 'bag_now',
                  'stage_source': 'model', 'stage_reason': 'Model proposal; confirm first.', 'needs_review': True}
    generated['recipe_cards'][0]['ingredients'] = [deepcopy(ingredient)]
    first = store.replace_generated('2026-W40', generated)
    assert first['recipe_cards'][0]['ingredients'][0] == ingredient
    edit = change(item_id='ingredient:1', field='prep_stage', value='bag_now')
    confirmed = store.patch_packet('2026-W40', first['revision'], [edit])
    row = confirmed['recipe_cards'][0]['ingredients'][0]
    assert row['prep_stage'] == 'bag_now' and row['stage_source'] == 'user'
    assert row['needs_review'] is False and 'review' in row['stage_reason'].lower()
    assert confirmed['edits'] == [edit]
    with inventory_db.connect() as conn:
        stored = conn.execute('SELECT generated_json, edits_json FROM cooking_packets').fetchone()
        assert json.loads(stored[0])['recipe_cards'][0]['ingredients'][0] == ingredient
        assert json.loads(stored[1]) == [edit]
    restored = store.patch_packet('2026-W40', confirmed['revision'], [{**edit, 'value': None}])
    assert restored['recipe_cards'][0]['ingredients'][0] == ingredient
    assert restored['edits'] == [] and restored['revision'] == confirmed['revision'] + 1
    assert generated['recipe_cards'][0]['ingredients'][0] == ingredient


def test_stage_confirmation_repartitions_existing_credit_and_null_restores_it(store):
    from tests.test_cooking_packet_builder import partition_fixture
    generated = partition_fixture('bag_now', True)
    generated_before = deepcopy(generated)
    first = store.replace_generated('2026-W40', generated)
    assert first['pull_list'] == [] and len(first['cook_day_pull']) == 1
    original_subpull_id = first['cook_day_pull'][0]['item_id']
    edit = change(item_id='ingredient:test', field='prep_stage', value='bag_now')
    saved = store.patch_packet('2026-W40', first['revision'], [edit])
    assert saved['revision'] == first['revision'] + 1
    assert saved['cook_day_pull'] == [] and len(saved['pull_list']) == 1
    assert saved['pull_list'][0]['item_id'] == original_subpull_id
    assert saved['pull_list'][0]['stage_source'] == 'user' and not saved['pull_list'][0]['needs_review']
    assert saved['pull_list'][0]['amount'] == saved['pull_list'][0]['inventory_amount'] == 1
    assert store.get_packet('2026-W40') == saved
    assert saved['shopping_list'] == first['shopping_list']
    restored = store.patch_packet('2026-W40', saved['revision'], [{**edit, 'value': None}])
    assert restored['revision'] == saved['revision'] + 1
    assert restored['pull_list'] == [] and restored['cook_day_pull'] == first['cook_day_pull']
    assert restored['edits'] == [] and restored['shopping_list'] == first['shopping_list']
    assert store.get_packet('2026-W40') == restored
    with inventory_db.connect() as conn:
        raw = conn.execute('SELECT generated_json FROM cooking_packets').fetchone()[0]
        assert json.loads(raw) == generated_before
        assert conn.execute('SELECT COUNT(*) FROM inventory').fetchone()[0] == 0
    assert generated == generated_before


def test_derived_subpull_checkbox_is_editable_without_rewriting_generated_credit(store):
    from tests.test_cooking_packet_builder import partition_fixture
    generated = partition_fixture('bag_now', False)
    first = store.replace_generated('2026-W40', generated)
    subpull_id = first['pull_list'][0]['item_id']
    edited = store.patch_packet('2026-W40', first['revision'], [change(item_id=subpull_id, field='done', value=True)])
    assert edited['pull_list'][0]['done'] is True
    assert store.get_packet('2026-W40') == edited
    restored = store.patch_packet('2026-W40', edited['revision'], [change(item_id=subpull_id, field='done', value=None)])
    assert restored['pull_list'][0]['done'] is False
    assert restored['needs_review'] == []
    with inventory_db.connect() as conn:
        assert json.loads(conn.execute('SELECT generated_json FROM cooking_packets').fetchone()[0]) == generated


def test_derived_subpull_expansion_revalidates_merged_item_bound(store):
    from tests.test_cooking_packet_builder import partition_fixture
    generated = partition_fixture()
    prototype = generated['recipe_cards'][0]['ingredients'][0]
    generated['recipe_cards'][0]['ingredients'] = [{**prototype, 'item_id': f'ingredient:{i}'} for i in range(1001)]
    generated['shopping_list'][0]['source_ingredient_ids'] = [f'ingredient:{i}' for i in range(1001)]
    generated['shopping_list'][0]['needed']['amount'] = 1001
    generated['shopping_list'][0]['from_pantry']['amount'] = 1001
    generated['pull_list'][0].update(amount=1001, inventory_amount=1001)
    with pytest.raises(ValueError, match='2,000 items'):
        store.replace_generated('2026-W40', generated)
    assert store.get_packet('2026-W40') is None


def test_subpull_quantity_string_edit_preserves_sparse_field_semantics(store):
    from tests.test_cooking_packet_builder import partition_fixture
    from lib.cooking_packet_builder import repartition_packet_pulls
    generated = repartition_packet_pulls(partition_fixture())
    first = store.replace_generated('2026-W40', generated)
    subpull_id = first['pull_list'][0]['item_id']
    edit = change(item_id=subpull_id, field='amount', value='1/2')
    saved = store.patch_packet('2026-W40', first['revision'], [edit])
    assert saved['pull_list'][0]['amount'] == '1/2'
    assert saved['edits'] == [edit] and store.get_packet('2026-W40') == saved
    restored = store.patch_packet('2026-W40', saved['revision'], [{**edit, 'value': None}])
    assert restored['pull_list'][0]['amount'] == 1


def test_confirmation_reprioritizes_limited_credit_and_new_subpull_remains_editable(store):
    from tests.test_cooking_packet_builder import partition_fixture
    from lib.cooking_packet_builder import repartition_packet_pulls
    source = partition_fixture()
    prototype = source['recipe_cards'][0]['ingredients'][0]
    source['recipe_cards'][0]['ingredients'] = [
        {**prototype, 'item_id': 'ingredient:a', 'stage_source': 'model', 'needs_review': True},
        {**prototype, 'item_id': 'ingredient:b'}]
    source['shopping_list'][0]['source_ingredient_ids'] = ['ingredient:a', 'ingredient:b']
    source['shopping_list'][0]['needed']['amount'] = 2
    source['shopping_list'][0]['to_buy'] = {'amount': 1, 'unit': 'cup'}
    generated = repartition_packet_pulls(source)
    first = store.replace_generated('2026-W40', generated)
    assert first['pull_list'][0]['source_ingredient_ids'] == ['ingredient:b']
    saved = store.patch_packet('2026-W40', first['revision'], [change(item_id='ingredient:a', field='prep_stage', value='bag_now')])
    assert saved['pull_list'][0]['source_ingredient_ids'] == ['ingredient:a']
    assert len(saved['pull_list']) == 1 and saved['cook_day_pull'] == []
    assert saved['pull_list'][0]['amount'] == saved['pull_list'][0]['inventory_amount'] == 1
    assert saved['shopping_list'] == first['shopping_list']
    checked = store.patch_packet('2026-W40', saved['revision'], [change(item_id=saved['pull_list'][0]['item_id'], field='done', value=True)])
    assert checked['pull_list'][0]['done'] is True
    assert store.get_packet('2026-W40') == checked


def test_stage_edit_rejects_derived_pull_target_and_only_source_ingredient_can_move_it(store):
    from tests.test_cooking_packet_builder import partition_fixture
    from lib.cooking_packet_builder import repartition_packet_pulls
    generated = repartition_packet_pulls(partition_fixture())
    first = store.replace_generated('2026-W40', generated)
    subpull_id = first['pull_list'][0]['item_id']
    with inventory_db.connect() as conn:
        before_row = tuple(conn.execute('SELECT generated_json, edits_json, revision FROM cooking_packets').fetchone())
    with pytest.raises(ValueError, match='ingredient'):
        store.patch_packet('2026-W40', first['revision'], [
            change(item_id='ingredient:test', field='notes', value='must roll back'),
            change(item_id=subpull_id, field='prep_stage', value='finish_after_cooking')])
    assert store.get_packet('2026-W40') == first
    with inventory_db.connect() as conn:
        assert tuple(conn.execute('SELECT generated_json, edits_json, revision FROM cooking_packets').fetchone()) == before_row
    moved = store.patch_packet('2026-W40', first['revision'], [
        change(item_id='ingredient:test', field='prep_stage', value='finish_after_cooking')])
    assert moved['revision'] == first['revision'] + 1
    assert moved['pull_list'] == [] and len(moved['cook_day_pull']) == 1
    assert moved['cook_day_pull'][0]['item_id'] == subpull_id
    assert moved['cook_day_pull'][0]['prep_stage'] == 'finish_after_cooking'
    assert moved['cook_day_pull'][0]['prep_stage_group'] == 'cook_day'
    with pytest.raises(ValueError, match='ingredient'):
        store.patch_packet('2026-W40', moved['revision'], [
            change(item_id=subpull_id, field='prep_stage', value='bag_now')])
    assert store.get_packet('2026-W40') == moved


@pytest.mark.parametrize('target', ['cook:58', 'recipe:Soup'])
@pytest.mark.parametrize('value', ['bag_now', None])
def test_stage_edits_reject_non_ingredient_targets_even_for_null(store, target, value):
    first = store.replace_generated('2026-W40', draft())
    with pytest.raises(ValueError, match='ingredient'):
        store.patch_packet('2026-W40', first['revision'], [change(item_id=target, field='prep_stage', value=value)])
    assert store.get_packet('2026-W40') == first


def test_old_invalid_pull_stage_override_cannot_override_source_stage_on_read(store):
    from tests.test_cooking_packet_builder import partition_fixture
    from lib.cooking_packet_builder import repartition_packet_pulls
    generated = repartition_packet_pulls(partition_fixture())
    first = store.replace_generated('2026-W40', generated)
    legacy_edit = change(item_id=first['pull_list'][0]['item_id'], field='prep_stage', value='finish_after_cooking')
    with inventory_db.write_transaction() as conn:
        conn.execute('UPDATE cooking_packets SET edits_json = ?', (json.dumps([legacy_edit]),))
    packet = store.get_packet('2026-W40')
    assert packet['pull_list'][0]['prep_stage'] == 'bag_now'
    assert packet['pull_list'][0]['prep_stage_group'] == 'freezer_session'
    assert packet['cook_day_pull'] == []
    assert packet['revision'] == first['revision']
    assert 'ingredient' in packet['needs_review'][0]['reason']


def test_null_can_still_delete_a_previously_valid_orphan_ingredient_stage_override(store):
    from tests.test_cooking_packet_builder import partition_fixture
    generated = partition_fixture()
    first = store.replace_generated('2026-W40', generated)
    edit = change(item_id='ingredient:test', field='prep_stage', value='finish_after_cooking')
    store.patch_packet('2026-W40', first['revision'], [edit])
    vanished = store.replace_generated('2026-W40', draft())
    assert vanished['needs_review'][0]['item_id'] == 'ingredient:test'
    cleared = store.patch_packet('2026-W40', vanished['revision'], [{**edit, 'value': None}])
    assert cleared['edits'] == [] and cleared['needs_review'] == []
    assert cleared['revision'] == vanished['revision'] + 1
