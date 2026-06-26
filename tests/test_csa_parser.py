"""Tests for the CSA newsletter parser and ingester."""

from lib import csa_parser
import ingest_csa


# Mirrors the real "Week N(A/B)" newsletter structure after email_to_text():
# a "For this week's share" marker, then tier headings, then a terminator.
NEWSLETTER_TEXT = """\
Happy Week 13(A)
This Week's Shares
For this week's share we have:
Individual
Storage Onions
Purple Potatoes
Fresh Carrots
Sunflower Sprouts
Paste Tomatoes
Bountiful
Storage Onions
Purple Potatoes
Fresh Carrots
Eggplant
Ripe sweet peppers
Sunflower Sprouts
Paste Tomatoes
As Always....
Beef, Pork, Chicken from regenerative farms.
This week's contributing farms are:
Land of Ages Farm
"""

NEWSLETTER_HTML = (
    "<html><body><p>For this week's share we have:</p>"
    "<p>Individual</p><p>Beets</p><p>Leeks</p><p>Celery</p>"
    "<p>Bountiful</p><p>Beets</p><p>Leeks</p><p>Celery</p><p>Tomatoes</p>"
    "<p>As Always....</p></body></html>"
)


class TestParseWeekLabel:
    def test_parens_form(self):
        assert csa_parser.parse_week_label("Week 13(A)") == {
            "number": 13, "letter": "A", "label": "13(A)"}

    def test_newsletter_suffix(self):
        assert csa_parser.parse_week_label("Week 9(A) Newsletter")["label"] == "9(A)"

    def test_no_parens(self):
        assert csa_parser.parse_week_label("Week 1A Newsletter")["letter"] == "A"

    def test_b_week(self):
        assert csa_parser.parse_week_label("Week 10(B)")["letter"] == "B"

    def test_non_matching(self):
        assert csa_parser.parse_week_label("CSA Delivery Reminder") is None


class TestParseShareItems:
    def test_individual_tier_stops_at_bountiful(self):
        items = csa_parser.parse_share_items(NEWSLETTER_TEXT, "Individual")
        assert items == ["Storage Onions", "Purple Potatoes", "Fresh Carrots",
                         "Sunflower Sprouts", "Paste Tomatoes"]

    def test_bountiful_tier_stops_at_terminator(self):
        items = csa_parser.parse_share_items(NEWSLETTER_TEXT, "Bountiful")
        assert items[-1] == "Paste Tomatoes"
        assert "Eggplant" in items
        assert "As Always...." not in items
        assert "Land of Ages Farm" not in items

    def test_html_input_is_flattened(self):
        items = csa_parser.parse_share_items(NEWSLETTER_HTML, "Individual")
        assert items == ["Beets", "Leeks", "Celery"]

    def test_missing_tier_returns_empty(self):
        assert csa_parser.parse_share_items(NEWSLETTER_TEXT, "Family") == []


class TestParseNewsletter:
    def test_full_parse(self):
        result = csa_parser.parse_newsletter("Week 13(A)", NEWSLETTER_TEXT, "Individual")
        assert result["week"] == "13(A)"
        assert result["week_letter"] == "A"
        assert result["items"][0] == "Storage Onions"


class TestIngestFiltering:
    """process_newsletter routing (dry-run, no DB writes)."""

    _CONFIG = {"tier": "Individual", "week_letter": "A",
               "store": "Central Texas Farmers Co-op", "category": "produce"}

    def test_skips_other_week_letter(self, tmp_db, tmp_vault):
        payload = {"subject": "Week 10(B)", "html": NEWSLETTER_TEXT,
                   "message_id": "<b@x>", "date": "Tue, 02 Jun 2026 00:00:00 +0000"}
        result = ingest_csa.process_newsletter(payload, self._CONFIG, dry_run=True)
        assert result["status"] == "not_my_week"

    def test_ingests_my_week(self, tmp_db, tmp_vault):
        payload = {"subject": "Week 13(A)", "html": NEWSLETTER_TEXT,
                   "message_id": "<a@x>", "date": "Wed, 24 Jun 2026 00:00:00 +0000"}
        result = ingest_csa.process_newsletter(payload, self._CONFIG, dry_run=True)
        assert result["status"] == "ingested"
        assert "Storage Onions" in result["items"]

    def test_no_items_when_tier_absent(self, tmp_db, tmp_vault):
        payload = {"subject": "Week 13(A)", "html": "<p>no shares listed</p>",
                   "message_id": "<c@x>", "date": "Wed, 24 Jun 2026 00:00:00 +0000"}
        result = ingest_csa.process_newsletter(payload, self._CONFIG, dry_run=True)
        assert result["status"] == "no_items"
