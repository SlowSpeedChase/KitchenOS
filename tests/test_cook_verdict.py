"""Cook verdicts: was this worth making again, and what did you notice?

The ledger records what a cook *yielded*; without a verdict it can never learn
what was *liked*. The verdict deliberately attaches to the cook rather than the
recipe — the same recipe goes well one week and badly the next, and averaging
that away loses the signal.

Binary by design. A 1-5 scale asks for a judgement call at the exact moment it
is least wanted (tired, mid-cleanup), which is how rating systems go unused.
"""
import pytest

from lib import serving_ledger as sl


def _mk_cook(**over):
    kw = dict(recipe="Chili", week="2026-W28", scale=1.0,
              servings_produced=4.0, date="2026-07-07", meal="dinner")
    kw.update(over)
    return sl.create_cook(**kw)


def test_new_cook_has_no_verdict(tmp_db):
    """Absence is meaningful: un-judged is not the same as judged badly."""
    cook = _mk_cook()
    assert cook["make_again"] is None
    assert cook["cook_note"] is None


def test_records_make_again(tmp_db):
    cook = _mk_cook()
    updated = sl.update_cook(cook["id"], make_again=True)
    assert updated["make_again"] is True


def test_records_never_again(tmp_db):
    cook = _mk_cook()
    assert sl.update_cook(cook["id"], make_again=False)["make_again"] is False


def test_note_is_optional_and_independent(tmp_db):
    """A note without a verdict is allowed — skipping the tap must stay cheap."""
    cook = _mk_cook()
    updated = sl.update_cook(cook["id"], cook_note="too much cleanup")
    assert updated["cook_note"] == "too much cleanup"
    assert updated["make_again"] is None


def test_records_both_together(tmp_db):
    cook = _mk_cook()
    updated = sl.update_cook(cook["id"], make_again=True,
                             cook_note="double the sauce next time")
    assert updated["make_again"] is True
    assert updated["cook_note"] == "double the sauce next time"


def test_verdict_can_be_cleared(tmp_db):
    """Mis-taps happen; clearing must return to un-judged, not to False."""
    cook = _mk_cook()
    sl.update_cook(cook["id"], make_again=True)
    assert sl.update_cook(cook["id"], make_again=None)["make_again"] is None


def test_rejects_non_boolean_verdict(tmp_db):
    """Guard the binary contract — a 4 here would silently read as True."""
    cook = _mk_cook()
    with pytest.raises(ValueError):
        sl.update_cook(cook["id"], make_again=4)


def test_verdict_is_per_cook_not_per_recipe(tmp_db):
    """The same recipe can go well once and badly the next time."""
    good = _mk_cook(date="2026-07-07")
    bad = _mk_cook(date="2026-07-14", week="2026-W29")
    sl.update_cook(good["id"], make_again=True)
    sl.update_cook(bad["id"], make_again=False, cook_note="rushed it")

    assert sl.get_cook(good["id"])["make_again"] is True
    assert sl.get_cook(bad["id"])["make_again"] is False


def test_verdict_survives_other_updates(tmp_db):
    """Correcting the yield must not wipe the judgement."""
    cook = _mk_cook()
    sl.update_cook(cook["id"], make_again=True, cook_note="great")
    updated = sl.update_cook(cook["id"], servings_produced=6.0)
    assert updated["servings_produced"] == 6.0
    assert updated["make_again"] is True
    assert updated["cook_note"] == "great"
