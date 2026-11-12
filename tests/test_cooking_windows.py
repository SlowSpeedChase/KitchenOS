import pytest
from lib.cooking_windows import suggest_windows, recipe_duration


def event(start, end, **extra):
    return dict(
        id="b" * 64,
        title="Context",
        start=f"2026-09-22T{start}:00-05:00",
        end=f"2026-09-22T{end}:00-05:00",
        role="firm",
        all_day=False,
        **extra,
    )


def windows(events=(), choices=None, schedules=(), duration=90, day="2026-09-22"):
    return suggest_windows(
        day, "America/Chicago", list(events), choices or {}, list(schedules), duration
    )


def test_all_day_requires_choice_in_both_roles():
    for role in ("firm", "flexible"):
        e = dict(
            id="b" * 64,
            title="Validator",
            start="2026-09-22T00:00:00-05:00",
            end="2026-09-23T00:00:00-05:00",
            all_day=True,
            role=role,
        )
        assert all(w["unresolved_all_day_ids"] == ["b" * 64] for w in windows([e]))
        assert windows([e], {e["id"]: "blocking"}) == []
        assert all(
            not w["unresolved_all_day_ids"]
            for w in windows([e], {e["id"]: "background"})
        )
        assert all(
            not w["unresolved_all_day_ids"] for w in windows([e], day="2026-09-23")
        )


def test_firm_boundary_and_last_start():
    result = windows([event("11:00", "12:00"), event("19:00", "22:00")])
    assert result[0]["start"] == "2026-09-22T12:00:00-05:00"
    assert result[-1]["start"] == "2026-09-22T22:30:00-05:00"
    assert not any(
        "T18:" in w["start"] or "T19:" in w["start"] or "T20:" in w["start"]
        for w in result
    )


def test_flexible_rank_and_cooking_conflict():
    e = event("12:00", "17:00")
    e["role"] = "flexible"
    result = windows(
        [e], schedules=[{"start": "2026-09-22T17:00:00-05:00", "duration_minutes": 90}]
    )
    assert result[0]["start"] == "2026-09-22T18:30:00-05:00"
    assert result[-1]["overlaps_flexible"]
    assert windows([event("12:00", "23:59")], duration=360) == []


@pytest.mark.parametrize(
    "metadata,want",
    [
        ({}, (90, "estimate")),
        ({"total_time": float("nan")}, (90, "estimate")),
        ({"total_time": True}, (90, "estimate")),
        ({"total_time": 61}, (75, "recipe")),
        ({"prep_time": 10, "cook_time": 31}, (45, "recipe")),
        ({"total_time": 999}, (360, "recipe")),
    ],
)
def test_honest_duration(metadata, want):
    assert recipe_duration(metadata) == dict(minutes=want[0], source=want[1])


def test_dst_and_overnight_context():
    e = dict(
        id="x",
        title="Overnight",
        start="2026-10-31T20:00:00-05:00",
        end="2026-11-01T13:00:00-06:00",
        role="firm",
        all_day=False,
    )
    assert windows([e], day="2026-11-01")[0]["start"] == "2026-11-01T13:00:00-06:00"


@pytest.mark.parametrize("duration", [True, 0, 91, float("nan"), 361])
def test_invalid_duration(duration):
    with pytest.raises(ValueError):
        windows(duration=duration)


def test_plain_recipe_duration_strings_without_guessing_prose():
    assert recipe_duration({"total_time": "35 minutes"}) == {
        "minutes": 45,
        "source": "recipe",
    }
    assert recipe_duration({"prep_time": "10 minutes", "cook_time": "1 hour"}) == {
        "minutes": 75,
        "source": "recipe",
    }
    assert recipe_duration(
        {"total_time": "10 minutes for sauce, more time for sides"}
    ) == {"minutes": 90, "source": "estimate"}
