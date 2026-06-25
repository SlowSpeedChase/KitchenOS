"""Tests for lib.expiry default-window resolution and status."""

from datetime import date

from lib.expiry import default_expiry_days, compute_expires, expiry_status


class TestDefaultExpiryDays:
    def test_exact_item_override(self):
        assert default_expiry_days("milk", "dairy") == 10

    def test_word_subset_item_match(self):
        # "chicken" override (2d) should match "boneless chicken breast"
        assert default_expiry_days("boneless chicken breast", "meat") == 2

    def test_falls_back_to_category(self):
        # No item override for "asparagus" -> produce default (7)
        assert default_expiry_days("asparagus", "produce") == 7

    def test_null_window_returns_none(self):
        assert default_expiry_days("dish soap", "household") is None

    def test_unknown_category_returns_none(self):
        assert default_expiry_days("mystery", "widgets") is None


class TestComputeExpires:
    def test_uses_purchased_plus_window(self):
        assert compute_expires("2026-06-01", "milk", "dairy") == "2026-06-11"

    def test_falls_back_to_today_when_no_purchased(self):
        assert compute_expires(None, "milk", "dairy", today=date(2026, 6, 1)) == "2026-06-11"

    def test_bad_purchased_falls_back_to_today(self):
        assert compute_expires("not-a-date", "milk", "dairy", today=date(2026, 6, 1)) == "2026-06-11"

    def test_no_window_returns_none(self):
        assert compute_expires("2026-06-01", "dish soap", "household") is None


class TestExpiryStatus:
    def test_expired(self):
        assert expiry_status("2026-06-01", today=date(2026, 6, 10)) == "expired"

    def test_soon_within_threshold(self):
        assert expiry_status("2026-06-12", today=date(2026, 6, 10)) == "soon"

    def test_ok_beyond_threshold(self):
        assert expiry_status("2026-06-30", today=date(2026, 6, 10)) == "ok"

    def test_today_is_soon(self):
        assert expiry_status("2026-06-10", today=date(2026, 6, 10)) == "soon"

    def test_none_or_bad(self):
        assert expiry_status(None) is None
        assert expiry_status("garbage") is None
