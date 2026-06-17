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
