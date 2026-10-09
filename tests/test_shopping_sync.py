"""Stable source identity, safe completion and migration of shopping notes."""
from dataclasses import replace
from uuid import uuid4

import pytest

from lib import inventory_db as db, paths
from lib.apple_integration import store
from lib.apple_integration.models import RevisionConflict, SourceUnavailable

WEEK = '2026-W41'


def flour(amount='1'):
    return {'item': 'flour', 'needed': {'amount': amount, 'unit': 'cup'},
            'to_buy': {'amount': amount, 'unit': 'cup'}, 'status': 'buy'}


@pytest.fixture
def active(tmp_vault, tmp_db):
    store.register_owner(str(uuid4()))
    store.activate_scope('shopping', WEEK, 'list')
    return paths.shopping_lists_dir() / f'{WEEK}.md'


def saved():
    from lib.shopping_note import save_shopping_note
    return save_shopping_note(WEEK, [flour()], [])


def export():
    from lib.apple_integration import shopping
    return store.refresh_source(shopping.collect(WEEK)[0])


def test_read_does_not_migrate_legacy_and_export_is_unavailable(active):
    from lib.shopping_note import read_shopping_note
    from lib.apple_integration import shopping
    active.parent.mkdir()
    active.write_text('- [ ] flour\n- [x] foil\n')
    before = active.read_bytes()
    assert len(read_shopping_note(WEEK).rows) == 2
    assert active.read_bytes() == before
    with pytest.raises(SourceUnavailable):
        shopping.collect(WEEK)


def test_generated_quantity_change_preserves_identity_and_completion(active):
    from lib.shopping_note import save_shopping_note
    from lib.apple_integration import shopping
    before = saved()
    item = export()
    shopping.apply(item, {'completed': True}, str(uuid4()))
    regenerated = save_shopping_note(WEEK, [flour('2')], [])
    assert before.rows[0].id == regenerated.rows[0].id
    assert regenerated.rows[0].completed is True
    assert regenerated.rows[0].text == '2 cups flour'
    assert shopping.collect(WEEK)[0].state == 'conflict'
    with db.connect() as conn:
        assert conn.execute("SELECT field FROM apple_conflicts WHERE status='open'").fetchone()[0] == 'shopping_amount_changed'


def test_manual_duplicates_remain_distinct_checked_and_marker_free(active, monkeypatch):
    from lib.shopping_note import save_shopping_note
    from lib import shopping_list_generator as generator
    active.parent.mkdir()
    active.write_text('- [ ] foil\n- [x] foil\n')
    first = save_shopping_note(WEEK, [], [])
    second = save_shopping_note(WEEK, [], [])
    assert len({row.id for row in first.rows}) == 2
    assert first.rows == second.rows
    monkeypatch.setattr(generator, 'SHOPPING_LISTS_PATH', active.parent)
    parsed = generator.parse_shopping_list_file(WEEK)
    assert parsed['items'] == ['foil']
    assert parsed['skipped'] == 1


def test_duplicate_markers_never_toggle(active):
    from lib.apple_integration import shopping
    saved()
    item = export()
    text = active.read_text()
    line = next(line for line in text.splitlines() if line.startswith('- [ ]'))
    active.write_text(text + '\n' + line)
    before = active.read_bytes()
    with pytest.raises(RevisionConflict):
        shopping.apply(item, {'completed': True}, str(uuid4()))
    assert active.read_bytes() == before
    with pytest.raises(SourceUnavailable):
        shopping.collect(WEEK)


def test_generated_identity_edit_preserves_content_and_conflicts(active):
    from lib.shopping_note import save_shopping_note
    from lib.apple_integration import shopping
    saved()
    item = export()
    active.write_text(active.read_text().replace('- [ ] 1 cup flour', '- [ ] 2 eggs'))
    before = active.read_bytes()
    with pytest.raises(RevisionConflict):
        shopping.apply(item, {'completed': True}, str(uuid4()))
    with pytest.raises(RevisionConflict):
        save_shopping_note(WEEK, [flour()], [])
    assert active.read_bytes() == before
    assert shopping.collect(WEEK)[0].state == 'conflict'


def test_exact_id_completion_due_and_stale_source_guard(active):
    from lib.apple_integration import shopping
    from lib.shopping_note import save_shopping_note, read_shopping_note
    doc = save_shopping_note(WEEK, [], [], selected_items=['foil', 'foil'])
    item = export()
    with db.write_transaction() as conn:
        conn.execute("INSERT INTO inventory(name, quantity, unit, location_source) VALUES('flour',5,'cup','manual')")
        before = [tuple(row) for row in conn.execute('SELECT * FROM inventory')]
        assert len(before) == 1
    due = {'date': '2026-10-10', 'time': None, 'timezone': None}
    source = shopping.apply(item, {'completed': True, 'due': due}, str(uuid4()))
    after = read_shopping_note(WEEK)
    assert [r.completed for r in after.rows] == [True, False]
    assert source.fields == {'completed': True, 'due': due}
    assert after.rows[0].id == doc.rows[0].id
    with db.connect() as conn:
        assert [tuple(row) for row in conn.execute('SELECT * FROM inventory')] == before
    with pytest.raises(RevisionConflict):
        shopping.apply(item, {'completed': False}, str(uuid4()))


def test_removed_completed_source_is_history_and_readdition_has_new_generation(active):
    from lib.apple_integration import shopping
    from lib.shopping_note import save_shopping_note
    saved()
    item = export()
    source = shopping.apply(item, {'completed': True}, str(uuid4()))
    complete = store.refresh_source(source)
    active.write_text(active.read_text().replace(next(l for l in active.read_text().splitlines() if l.startswith('- [x]')), ''))
    absent = shopping.collect(WEEK)[0]
    assert absent.state == 'history'
    store.refresh_source(absent)
    save_shopping_note(WEEK, [flour()], [])
    replacement = export()
    assert replacement.generation == complete.generation + 1
    assert replacement.token != complete.token


def test_uncompleted_removal_retires_and_suppression_survives_refresh(active):
    from lib.apple_integration import shopping
    saved()
    item = export()
    store.set_suppressed(item.token, True, expected_revision=item.revision)
    assert export().state == 'suppressed'
    active.write_text(active.read_text().replace(next(l for l in active.read_text().splitlines() if l.startswith('- [ ]')), ''))
    assert shopping.collect(WEEK)[0].state == 'retired'


@pytest.mark.parametrize('endpoint', ['/generate-shopping-list', '/api/shopping-list/confirm'])
def test_both_save_endpoints_preserve_checked_rows_and_manual_duplicates(active, monkeypatch, endpoint):
    import api_server
    from lib.shopping_note import read_shopping_note
    from lib.apple_integration import shopping
    saved()
    item = export()
    shopping.apply(item, {'completed': True}, str(uuid4()))
    with active.open('a') as f:
        f.write('\n- [ ] foil\n- [x] foil\n')
    monkeypatch.setattr(api_server, 'SHOPPING_LISTS_PATH', active.parent)
    monkeypatch.setattr(api_server, 'generate_shopping_list', lambda *a, **kw: {
        'success': True, 'items': ['1 cup flour'], 'lines': [flour()], 'recipes': []})
    monkeypatch.setattr(api_server.pantry_module, 'load_pantry', lambda: [])
    with api_server.app.test_client() as client:
        result = client.post(endpoint, json={'week': WEEK, 'items_to_buy': ['1 cup flour']})
    assert result.status_code == 200
    rows = read_shopping_note(WEEK).rows
    assert [(r.text, r.completed) for r in rows] == [('1 cup flour', True), ('foil', False), ('foil', True)]


def test_due_override_unset_clear_and_replacement(active):
    from lib.apple_integration import shopping
    saved()
    item = export()
    assert store.get_due_override(item.token) == (False, None)
    updated = store.set_due_override(item.token, None, expected_revision=item.revision)
    assert store.get_due_override(item.token) == (True, None)
    with pytest.raises(RevisionConflict):
        store.set_due_override(item.token, None, expected_revision=item.revision)
    store.refresh_source(replace(shopping.collect(WEEK)[0], state='retired'))
    replacement = export()
    assert replacement.generation == 2
    assert store.get_due_override(replacement.token) == (False, None)


def test_interrupted_combined_patch_recovers_before_refresh(active, monkeypatch):
    from lib.apple_integration import shopping
    saved()
    item = export()
    due = {'date': '2026-10-10', 'time': None, 'timezone': None}
    setter = store.set_due_override
    def interrupt(*args, **kwargs):
        raise OSError('simulated termination after file replacement')
    monkeypatch.setattr(store, 'set_due_override', interrupt)
    operation = str(uuid4())
    with pytest.raises(OSError):
        shopping.apply(item, {'completed': True, 'due': due}, operation)
    assert store.pending_source_patches('shopping')[0]['operation_id'] == operation
    monkeypatch.setattr(store, 'set_due_override', setter)
    assert shopping.recover_pending() == []
    assert store.pending_source_patches('shopping') == []
    assert shopping.collect(WEEK)[0].fields == {'completed': True, 'due': due}
    # Exactly the same operation may be retried; it must not double-apply.
    assert shopping.apply(item, {'completed': True, 'due': due}, operation).fields['due'] == due


def test_interrupted_patch_with_external_edit_becomes_conflict(active, monkeypatch):
    from lib.apple_integration import shopping
    saved()
    item = export()
    setter = store.set_due_override
    monkeypatch.setattr(store, 'set_due_override', lambda *a, **kw: (_ for _ in ()).throw(OSError('crash')))
    operation = str(uuid4())
    with pytest.raises(OSError):
        shopping.apply(item, {'completed': True, 'due': None}, operation)
    active.write_text(active.read_text() + '\nexternal edit\n')
    before = active.read_bytes()
    monkeypatch.setattr(store, 'set_due_override', setter)
    assert shopping.recover_pending() == [operation]
    assert active.read_bytes() == before
    assert store.get_due_override(item.token) == (False, None)


def test_replaced_generation_cannot_resume_reserved_patch(active, monkeypatch):
    from lib.apple_integration import shopping
    saved()
    item = export()
    setter = store.set_due_override
    monkeypatch.setattr(store, 'set_due_override', lambda *a, **kw: (_ for _ in ()).throw(OSError('crash')))
    op = str(uuid4())
    with pytest.raises(OSError):
        shopping.apply(item, {'completed': True, 'due': None}, op)
    store.refresh_source(replace(shopping.collect(WEEK)[0], state='retired'))
    assert export().generation == 2
    before = active.read_bytes()
    monkeypatch.setattr(store, 'set_due_override', setter)
    assert shopping.recover_pending() == [op]
    assert active.read_bytes() == before


def test_retirement_revision_stays_stable(active):
    from lib.apple_integration import shopping
    saved()
    export()
    active.write_text(active.read_text().replace(next(l for l in active.read_text().splitlines() if l.startswith('- [ ]')), ''))
    first = shopping.collect(WEEK)[0]
    store.refresh_source(first)
    assert shopping.collect(WEEK)[0].source_revision == first.source_revision


def test_empty_unmigrated_note_is_unavailable(active):
    from lib.apple_integration import shopping
    active.parent.mkdir()
    active.write_text('')
    with pytest.raises(SourceUnavailable):
        shopping.collect(WEEK)


def test_completed_save_retry_does_not_claim_external_edits_are_synced(active):
    from lib.apple_integration import shopping
    saved()
    item = export()
    op = str(uuid4())
    shopping.apply(item, {'completed': True}, op)
    active.write_text(active.read_text().replace('- [x]', '- [ ]'))
    with pytest.raises(RevisionConflict):
        shopping.apply(item, {'completed': True}, op)


def test_marker_free_legacy_send(active, monkeypatch):
    import api_server
    from lib import reminders, shopping_list_generator
    saved()
    sent = []
    monkeypatch.setattr(shopping_list_generator, 'SHOPPING_LISTS_PATH', active.parent)
    monkeypatch.setattr(reminders, 'add_to_reminders', lambda items, name: sent.extend(items) or len(items))
    with api_server.app.test_client() as client:
        result = client.post('/send-to-reminders', json={'week': WEEK})
    assert result.status_code == 200
    assert sent == ['1 cup flour']


def test_hidden_markers_do_not_show_in_phone_note(active):
    from lib.note_view import render
    saved()
    html = render(active.read_text(), week=WEEK)
    assert 'kitchenos-item' not in html
    assert 'kitchenos-shopping-v3' not in html
    assert 'kitchenos-generated-items' not in html
    assert '1 cup flour' in html


@pytest.mark.parametrize('marker', ['gen:' + 'a' * 65, 'bad:abc', 'manual:../outside'])
def test_malformed_markers_are_unavailable_and_never_rewritten(active, marker):
    from lib.apple_integration import shopping
    from lib.shopping_note import save_shopping_note
    active.parent.mkdir()
    active.write_text(f'- [ ] flour <!-- kitchenos-item:{marker} -->\n')
    before = active.read_bytes()
    with pytest.raises(SourceUnavailable):
        shopping.collect(WEEK)
    with pytest.raises(RevisionConflict):
        save_shopping_note(WEEK, [flour()], [])
    assert active.read_bytes() == before


def test_generated_family_distinguishes_same_ingredient(active):
    from lib.shopping_note import save_shopping_note
    by_weight = {'item': 'flour', 'needed': {'amount': '100', 'unit': 'g'},
                 'to_buy': {'amount': '100', 'unit': 'g'}, 'status': 'buy'}
    doc = save_shopping_note(WEEK, [flour(), by_weight], [])
    assert len({r.id for r in doc.rows}) == 2


def test_confirm_conflict_prevents_explicit_pantry_spend(active, monkeypatch):
    import api_server
    saved()
    text = active.read_text()
    line = next(line for line in text.splitlines() if line.startswith('- [ ]'))
    active.write_text(text + '\n' + line)
    before = active.read_bytes()
    spent = []
    monkeypatch.setattr(api_server, 'generate_shopping_list', lambda *a, **kw: {'success': True, 'lines': [flour()]})
    monkeypatch.setattr(api_server.pantry_module, 'load_pantry', lambda: [])
    monkeypatch.setattr(api_server.pantry_module, 'apply_decisions', lambda *args: spent.append(args))
    with api_server.app.test_client() as client:
        response = client.post('/api/shopping-list/confirm', json={
            'week': WEEK, 'items_to_buy': ['1 cup flour'], 'decisions': [{'item': 'flour', 'amount': '1', 'unit': 'cup'}]})
    assert response.status_code == 409
    assert active.read_bytes() == before
    assert spent == []


def test_generation_without_export_also_preserves_quantity_conflict(active):
    from lib.shopping_note import save_shopping_note
    from lib.apple_integration import shopping
    saved()
    active.write_text(active.read_text().replace('- [ ]', '- [x]'))
    save_shopping_note(WEEK, [flour('2')], [])
    assert shopping.collect(WEEK)[0].state == 'conflict'


def test_changing_item_name_after_completed_save_does_not_inherit_export(active):
    from lib.apple_integration import shopping
    saved()
    item = export()
    shopping.apply(item, {'completed': True}, str(uuid4()))
    active.write_text(active.read_text().replace('- [x] 1 cup flour', '- [x] 2 eggs'))
    assert shopping.collect(WEEK)[0].state == 'conflict'
    assert store.get_item(item.token).title == '1 cup flour'


def test_paused_scope_rejects_new_source_import(active):
    from lib.apple_integration import shopping
    from lib.apple_integration.models import ScopeRequest
    saved()
    item = export()
    before = active.read_bytes()
    store.update_scope(ScopeRequest('shopping', WEEK, 'list', 'paused', 1))
    with pytest.raises(RevisionConflict):
        shopping.apply(item, {'completed': True}, str(uuid4()))
    assert active.read_bytes() == before


def test_structured_inventory_matches_remain_plain_bullets(active):
    from lib.shopping_note import save_shopping_note
    match = {**flour(), 'matched_inventory': {'item': 'flour', 'amount': '3', 'unit': 'cup'}, 'status': 'credited', 'to_buy': None}
    doc = save_shopping_note(WEEK, [], [match])
    assert doc.rows == []
    assert '- 1 cup flour → flour (3 cup)' in active.read_text()
    assert '- [ ]' not in active.read_text()


def test_malformed_legacy_provenance_fails_closed(active):
    import base64
    from lib.shopping_note import save_shopping_note
    active.parent.mkdir()
    payload = base64.urlsafe_b64encode(b'{"flour":"bad"}').decode()
    active.write_text(f'<!-- kitchenos-generated-items-v2:{payload} -->\n- [ ] flour\n')
    before = active.read_bytes()
    with pytest.raises(RevisionConflict):
        save_shopping_note(WEEK, [flour()], [])
    assert active.read_bytes() == before


def test_checked_history_from_common_payload_survives_source_row_removal(active):
    from lib.apple_integration import shopping
    saved()
    item = export()
    with db.write_transaction() as conn:
        conn.execute('UPDATE apple_items SET common_payload=? WHERE token=?', ('{"completed":true,"due":null}', item.token))
    active.write_text(active.read_text().replace(next(l for l in active.read_text().splitlines() if l.startswith('- [ ]')), ''))
    assert shopping.collect(WEEK)[0].state == 'history'
