"""Tests for meal plan template."""

import pytest

from templates.meal_plan_template import (
    generate_meal_plan_markdown,
    parse_week_id,
    format_week_range,
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
