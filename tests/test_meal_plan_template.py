"""Tests for meal plan template."""

import pytest

from datetime import date

from templates.meal_plan_template import (
    format_week_heading,
    format_week_range,
    generate_meal_plan_markdown,
    parse_week_id,
    week_relative_label,
)


def test_includes_generate_button():
    """Template includes shopping list button."""
    result = generate_meal_plan_markdown(2026, 4)
    assert "```button" in result
    assert "Generate Shopping List" in result
    assert "kitchenos://generate-shopping-list?week=2026-W04" in result


class TestParseWeekId:
    def test_valid(self):
        assert parse_week_id("2026-W04") == (2026, 4)

    def test_tolerates_whitespace(self):
        assert parse_week_id("  2026-W26 ") == (2026, 26)

    @pytest.mark.parametrize("bad", ["", "2026", "2026-04", "W04", "2026-Wxx", None])
    def test_invalid_raises(self, bad):
        with pytest.raises(ValueError):
            parse_week_id(bad)


class TestFormatWeekRange:
    def test_with_year(self):
        # ISO week 4 of 2026 is Mon Jan 19 – Sun Jan 25.
        assert format_week_range("2026-W04") == "Jan 19 - Jan 25, 2026"

    def test_without_year(self):
        assert format_week_range("2026-W04", with_year=False) == "Jan 19 - Jan 25"

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            format_week_range("not-a-week")


# ---- Human week labels (dates, not week numbers) ----

class TestWeekRelativeLabel:
    """The orientation a week number was standing in for, said in words."""

    # Wed 2026-07-29 sits inside ISO week 31.
    TODAY = date(2026, 7, 29)

    def test_this_week(self):
        assert week_relative_label("2026-W31", self.TODAY) == "This week"

    def test_next_and_last_week(self):
        assert week_relative_label("2026-W32", self.TODAY) == "Next week"
        assert week_relative_label("2026-W30", self.TODAY) == "Last week"

    def test_distant_weeks_get_no_label(self):
        assert week_relative_label("2026-W33", self.TODAY) == ""
        assert week_relative_label("2026-W29", self.TODAY) == ""
        assert week_relative_label("2025-W31", self.TODAY) == ""

    def test_works_on_a_monday_and_a_sunday(self):
        """Week boundaries are ISO Monday-start, not 'seven days from today'."""
        assert week_relative_label("2026-W31", date(2026, 7, 27)) == "This week"  # Mon
        assert week_relative_label("2026-W31", date(2026, 8, 2)) == "This week"   # Sun
        assert week_relative_label("2026-W31", date(2026, 8, 3)) == "Last week"   # next Mon

    def test_crosses_a_year_boundary(self):
        # 2026-12-28 is the Monday of ISO week 53; 2027-W01 follows it.
        assert week_relative_label("2027-W01", date(2026, 12, 28)) == "Next week"

    def test_malformed_id_is_empty_not_an_error(self):
        assert week_relative_label("nonsense", self.TODAY) == ""
        assert week_relative_label("", self.TODAY) == ""


class TestFormatWeekHeading:
    TODAY = date(2026, 7, 29)

    def test_prefixes_the_relative_label_when_adjacent(self):
        assert format_week_heading("2026-W31", today=self.TODAY) == \
            "This week · Jul 27 - Aug 2, 2026"

    def test_bare_range_for_a_distant_week(self):
        assert format_week_heading("2026-W40", today=self.TODAY) == "Sep 28 - Oct 4, 2026"

    def test_without_year(self):
        assert format_week_heading("2026-W40", with_year=False, today=self.TODAY) == \
            "Sep 28 - Oct 4"


def test_plan_title_is_the_date_range():
    """REGRESSION: the note led with 'Week 09', which identifies nothing."""
    title = generate_meal_plan_markdown(2026, 9).split("\n")[0]
    assert title == "# Meal Plan - Feb 23 - Mar 1, 2026"
    assert "Week" not in title.replace("Meal Plan", "")
