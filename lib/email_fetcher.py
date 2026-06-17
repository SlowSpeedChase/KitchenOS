"""Fetch grocery receipt emails from Gmail over IMAP.

Credentials come from the environment: GMAIL_ADDRESS + GMAIL_APP_PASSWORD
(a Google "app password" — requires 2-step verification on the account).
Sender domains per store live in config/receipt_senders.json.

Only message *reading* happens here; dedup against already-ingested
Message-IDs is the caller's job (ingest_receipts.py checks
trips.source_id). The mailbox is opened read-only, so messages are never
deleted or even marked seen.
"""
from __future__ import annotations

import email
import email.policy
import imaplib
import json
import os
from datetime import date, timedelta
from email.utils import parseaddr
from pathlib import Path

SENDERS_PATH = Path(__file__).resolve().parent.parent / "config" / "receipt_senders.json"
IMAP_HOST = "imap.gmail.com"


def load_sender_domains() -> list[str]:
    data = json.loads(SENDERS_PATH.read_text(encoding="utf-8"))
    return [d for domains in data.values() for d in domains]


def sender_matches(from_addr: str, domains: list[str]) -> bool:
    addr = (from_addr or "").lower()
    return any(addr.endswith("@" + d) or addr.endswith("." + d) for d in domains)


def extract_email_payload(raw_bytes: bytes) -> dict:
    """Parse a raw RFC822 message into {message_id, from, subject, date, html}."""
    msg = email.message_from_bytes(raw_bytes, policy=email.policy.default)
    body = msg.get_body(preferencelist=("html", "plain"))
    html = body.get_content() if body else ""
    return {
        "message_id": (msg.get("Message-ID") or "").strip(),
        "from": parseaddr(msg.get("From", ""))[1],
        "subject": msg.get("Subject", ""),
        "date": msg.get("Date", ""),
        "html": html,
    }


def fetch_receipt_emails(since_days: int = 14) -> list[dict]:
    """Fetch candidate receipt emails from the last ``since_days`` days."""
    address = os.environ.get("GMAIL_ADDRESS")
    password = os.environ.get("GMAIL_APP_PASSWORD")
    if not address or not password:
        raise RuntimeError("GMAIL_ADDRESS / GMAIL_APP_PASSWORD not set in .env")

    domains = load_sender_domains()
    since = (date.today() - timedelta(days=since_days)).strftime("%d-%b-%Y")

    results: list[dict] = []
    conn = imaplib.IMAP4_SSL(IMAP_HOST)
    try:
        conn.login(address, password)
        conn.select("INBOX", readonly=True)
        for domain in domains:
            status, data = conn.search(
                None, f'(FROM "{domain}" SINCE {since})'
            )
            if status != "OK" or not data or not data[0]:
                continue
            for num in data[0].split():
                status, msg_data = conn.fetch(num, "(RFC822)")
                if status != "OK":
                    continue
                payload = extract_email_payload(msg_data[0][1])
                if sender_matches(payload["from"], domains):
                    results.append(payload)
    finally:
        try:
            conn.logout()
        except Exception:
            pass
    return results
