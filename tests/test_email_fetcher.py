"""Tests for lib/email_fetcher.py message parsing and sender matching."""
from email.message import EmailMessage

from lib import email_fetcher as ef


def _make_email(from_addr: str, html: str, msg_id: str = "<m1@heb.com>"):
    msg = EmailMessage()
    msg["From"] = f"H-E-B <{from_addr}>"
    msg["Subject"] = "Your H-E-B eReceipt"
    msg["Message-ID"] = msg_id
    msg["Date"] = "Mon, 09 Jun 2026 18:00:00 -0500"
    msg.set_content("plain fallback")
    msg.add_alternative(html, subtype="html")
    return msg.as_bytes()


def test_extract_email_payload_prefers_html():
    raw = _make_email("receipts@heb.com", "<p>RECEIPT HTML</p>")
    payload = ef.extract_email_payload(raw)
    assert payload["message_id"] == "<m1@heb.com>"
    assert "RECEIPT HTML" in payload["html"]
    assert payload["from"] == "receipts@heb.com"


def test_sender_matches_domains():
    assert ef.sender_matches("receipts@heb.com", ["heb.com"]) is True
    assert ef.sender_matches("no-reply@hebtoyou.net", ["heb.com", "hebtoyou.net"]) is True
    assert ef.sender_matches("spam@hebx.com", ["heb.com"]) is False


def test_load_sender_domains():
    domains = ef.load_sender_domains()
    assert "heb.com" in domains


def test_load_sender_domains_includes_hebdigital():
    domains = ef.load_sender_domains()
    assert "hebdigital.com" in domains  # curbside receipts come from here


def test_load_sender_rules_parses_subject_filter():
    rules = ef.load_sender_rules()
    heb = next(r for r in rules if "hebdigital.com" in r["domains"])
    assert "receipt" in heb["subject_includes"]


def test_load_sender_rules_back_compat_list_form(tmp_path, monkeypatch):
    cfg = tmp_path / "senders.json"
    cfg.write_text('{"FOO": ["foo.com"]}', encoding="utf-8")
    monkeypatch.setattr(ef, "SENDERS_PATH", cfg)
    rules = ef.load_sender_rules()
    assert rules == [{"domains": ["foo.com"], "subject_includes": []}]


class TestLoadAccounts:
    """Multi-account credential loading (primary + numbered extras)."""

    def test_primary_only(self, monkeypatch):
        monkeypatch.setenv("GMAIL_ADDRESS", "a@gmail.com")
        monkeypatch.setenv("GMAIL_APP_PASSWORD", "pw1")
        monkeypatch.delenv("GMAIL_ADDRESS_2", raising=False)
        assert ef.load_accounts() == [("a@gmail.com", "pw1")]

    def test_second_account(self, monkeypatch):
        monkeypatch.setenv("GMAIL_ADDRESS", "a@gmail.com")
        monkeypatch.setenv("GMAIL_APP_PASSWORD", "pw1")
        monkeypatch.setenv("GMAIL_ADDRESS_2", "b@gmail.com")
        monkeypatch.setenv("GMAIL_APP_PASSWORD_2", "pw2")
        monkeypatch.delenv("GMAIL_ADDRESS_3", raising=False)
        assert ef.load_accounts() == [("a@gmail.com", "pw1"), ("b@gmail.com", "pw2")]

    def test_skips_account_missing_password(self, monkeypatch):
        monkeypatch.setenv("GMAIL_ADDRESS", "a@gmail.com")
        monkeypatch.setenv("GMAIL_APP_PASSWORD", "pw1")
        monkeypatch.setenv("GMAIL_ADDRESS_2", "b@gmail.com")
        monkeypatch.delenv("GMAIL_APP_PASSWORD_2", raising=False)
        monkeypatch.delenv("GMAIL_ADDRESS_3", raising=False)
        assert ef.load_accounts() == [("a@gmail.com", "pw1")]

    def test_empty_when_unset(self, monkeypatch):
        monkeypatch.delenv("GMAIL_ADDRESS", raising=False)
        monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)
        monkeypatch.delenv("GMAIL_ADDRESS_2", raising=False)
        assert ef.load_accounts() == []


class TestSubjectAllowed:
    def test_no_filter_allows_all(self):
        assert ef.subject_allowed("anything", []) is True

    def test_keeps_matching_subject(self):
        assert ef.subject_allowed("Here's your curbside order receipt", ["receipt"]) is True

    def test_drops_confirmation_subject(self):
        # HEB's "We received your curbside order" confirmation has no "receipt"
        assert ef.subject_allowed("We received your curbside order", ["receipt"]) is False

    def test_case_insensitive(self):
        assert ef.subject_allowed("YOUR RECEIPT", ["receipt"]) is True
