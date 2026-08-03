"""Reading a cook time out of free text.

`total_time` is LLM-extracted prose, not a number: 147 of 254 recipes have none
at all, and the rest range over "5 minutes", "(estimated) 1 hour",
"10-15 minutes (for air fryer chicken)" and "2.5 hours". Anything ranking on
speed has to survive all of it and say "I don't know" for the majority.
"""

import pytest

from lib.recipe_time import parse_minutes


class TestPlainDurations:
    @pytest.mark.parametrize("text,minutes", [
        ("5 minutes", 5),
        ("10 minutes", 10),
        ("45 minutes", 45),
        ("1 hour", 60),
        ("2 hours", 120),
        ("2.5 hours", 150),
        ("1 hr", 60),
        ("90 min", 90),
    ])
    def test_it_reads_the_common_shapes(self, text, minutes):
        assert parse_minutes(text) == minutes


class TestMessyRealValues:
    """Every one of these is in the live corpus."""

    def test_an_estimate_prefix_is_ignored(self):
        assert parse_minutes("(estimated) 20 minutes") == 20

    def test_a_trailing_estimate_is_ignored(self):
        assert parse_minutes("15 minutes (estimated)") == 15

    def test_a_range_takes_the_longer_end(self):
        """Conservative: don't promise a weeknight it's the fast number."""
        assert parse_minutes("(estimated) 10-15 minutes (for air fryer chicken)") == 15

    def test_trailing_prose_does_not_derail_it(self):
        assert parse_minutes(
            "(estimated) 10-15 minutes for the meatballs, "
            "additional time for sides if needed") == 15

    def test_hours_and_minutes_combine(self):
        assert parse_minutes("1 hour 30 minutes") == 90

    def test_seconds_are_ignored_rather_than_counted_as_minutes(self):
        assert parse_minutes("2 minutes 15 seconds (with checking every 30 seconds)") == 2


class TestUnknown:
    @pytest.mark.parametrize("text", [None, "", "   ", "null", "varies", "overnight"])
    def test_unreadable_values_are_unknown_not_zero(self, text):
        """Zero would read as "instant" and win every speed ranking."""
        assert parse_minutes(text) is None

    def test_a_number_with_no_unit_is_read_as_minutes(self):
        assert parse_minutes("25") == 25

    def test_an_implausible_duration_is_refused(self):
        """A 3-day ferment isn't a weeknight signal; better to say nothing."""
        assert parse_minutes("72 hours") is None

    def test_it_never_raises_on_junk(self):
        for junk in (123, [], {}, object()):
            assert parse_minutes(junk) is None
