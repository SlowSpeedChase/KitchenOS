from datetime import date

from lib.command.phrases import split_phrases
from lib.command.slots import extract, item_text, iso_week, week_monday

THU = date(2026, 11, 12)


def test_split_on_and_then_comma():
    assert split_phrases("put this on friday and then freeze the rest, double batch") == [
        "put this on friday", "freeze the rest", "double batch"]


def test_split_protects_recipe_names_containing_and():
    assert split_phrases("put mac and cheese on friday and freeze the rest",
                         protect=["Mac and Cheese"]) == [
        "put mac and cheese on friday", "freeze the rest"]


def test_weekday_when_planning_is_next_occurrence_from_today():
    s = extract("for this wednesday", today=THU)
    assert s.dates == [date(2026, 11, 18)]


def test_weekday_for_navigation_stays_in_this_iso_week():
    s = extract("open wednesday", today=THU)
    assert s.nav_dates == [date(2026, 11, 11)]


def test_weekday_on_planner_uses_the_week_shown():
    s = extract("from wednesday to saturday", today=THU, week_start=date(2026, 11, 16))
    assert s.dates == [date(2026, 11, 18), date(2026, 11, 21)]


def test_today_is_a_valid_weekday_answer():
    assert extract("thursday", today=THU).dates == [THU]


def test_relative_days():
    assert extract("tomorrow lunch", today=THU).dates == [date(2026, 11, 13)]
    assert extract("for lunch the next day", today=THU,
                   prev_date=date(2026, 11, 18)).dates == [date(2026, 11, 19)]
    assert extract("the next day", today=THU).dates == []


def test_next_weekday_is_a_question_not_a_guess():
    s = extract("next friday", today=THU)
    assert s.dates == [] and s.date_options == [date(2026, 11, 13), date(2026, 11, 20)]


def test_next_week_sets_week():
    assert extract("for next week", today=THU).week == "2026-W47"


def test_meal_scale_count_location():
    assert extract("tonight", today=THU).meal == "dinner"
    assert extract("double batch", today=THU).scale == 2.0
    assert extract("two servings for lunch", today=THU).count == 2.0
    assert extract("to the freezer", today=THU).location == "freezer"


def test_quantity_and_unit():
    s = extract("add two cans of chickpeas", today=THU)
    assert (s.quantity, s.unit) == (2.0, "can")
    s = extract("a bag of rice", today=THU)
    assert (s.quantity, s.unit) == (1.0, "bag")


def test_item_text_strips_verbs_numbers_units_places():
    assert item_text("add two cans of chickpeas") == "chickpeas"
    assert item_text("we’re out of eggs") == "eggs"
    assert item_text("move the bread to the freezer") == "bread"
    assert item_text("a bag of rice") == "rice"


def test_week_helpers():
    assert iso_week(THU) == "2026-W46"
    assert week_monday("2026-W47") == date(2026, 11, 16)
