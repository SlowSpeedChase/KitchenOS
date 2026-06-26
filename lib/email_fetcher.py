"""Fetch grocery receipt emails from Gmail over IMAP.

Credentials come from the environment. The primary account is
GMAIL_ADDRESS + GMAIL_APP_PASSWORD (a Google "app password" — requires
2-step verification on the account). Additional accounts are read from
numbered vars: GMAIL_ADDRESS_2 / GMAIL_APP_PASSWORD_2,
GMAIL_ADDRESS_3 / GMAIL_APP_PASSWORD_3, … — so receipts that arrive in
more than one inbox (e.g. HEB in one, a farm co-op in another) are all
pulled in a single run. Sender domains per store live in
config/receipt_senders.json.

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


def load_sender_rules() -> list[dict]:
    """Per-store match rules from config/receipt_senders.json.

    Two config shapes are accepted per store:
      "STORE": ["domain", ...]                                  (no subject filter)
      "STORE": {"domains": [...], "subject_includes": [...]}    (subject filter)

    ``subject_includes`` (case-insensitive substrings) keeps only emails whose
    subject matches at least one keyword — used to ingest HEB's actual
    "...order receipt" while skipping its "We received your order" confirmation.
    Returns ``[{"domains": [...], "subject_includes": [...]}, ...]``.
    """
    data = json.loads(SENDERS_PATH.read_text(encoding="utf-8"))
    rules: list[dict] = []
    for value in data.values():
        if isinstance(value, dict):
            domains = [d.lower() for d in value.get("domains", [])]
            subject = [s.lower() for s in value.get("subject_includes", [])]
        else:  # bare list — back-compatible, no subject filter
            domains = [d.lower() for d in value]
            subject = []
        if domains:
            rules.append({"domains": domains, "subject_includes": subject})
    return rules


def load_sender_domains() -> list[str]:
    """Flat list of every configured sender domain (across all stores)."""
    return [d for rule in load_sender_rules() for d in rule["domains"]]


def subject_allowed(subject: str, subject_includes: list[str]) -> bool:
    """True if no filter is set, or the subject contains a keyword."""
    if not subject_includes:
        return True
    low = (subject or "").lower()
    return any(kw in low for kw in subject_includes)


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


def load_accounts() -> list[tuple[str, str]]:
    """Gmail ``(address, app_password)`` pairs to scan, primary first.

    Reads GMAIL_ADDRESS / GMAIL_APP_PASSWORD, then GMAIL_ADDRESS_2 /
    GMAIL_APP_PASSWORD_2, GMAIL_ADDRESS_3 / … until a numbered address is
    missing. An address with no matching password (or vice versa) is skipped.
    """
    accounts: list[tuple[str, str]] = []
    primary = os.environ.get("GMAIL_ADDRESS")
    primary_pw = os.environ.get("GMAIL_APP_PASSWORD")
    if primary and primary_pw:
        accounts.append((primary, primary_pw))

    n = 2
    while True:
        addr = os.environ.get(f"GMAIL_ADDRESS_{n}")
        if not addr:
            break
        pw = os.environ.get(f"GMAIL_APP_PASSWORD_{n}")
        if pw:
            accounts.append((addr, pw))
        n += 1
    return accounts


def _fetch_from_account(address: str, password: str, rules: list[dict],
                        since: str, seen_ids: set[str]) -> list[dict]:
    """Scan one mailbox for receipts, skipping Message-IDs already in seen_ids."""
    results: list[dict] = []
    conn = imaplib.IMAP4_SSL(IMAP_HOST)
    try:
        conn.login(address, password)
        conn.select("INBOX", readonly=True)
        for rule in rules:
            domains = rule["domains"]
            subject_includes = rule["subject_includes"]
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
                    if not sender_matches(payload["from"], domains):
                        continue
                    if not subject_allowed(payload["subject"], subject_includes):
                        continue
                    mid = payload["message_id"]
                    if mid and mid in seen_ids:
                        continue
                    if mid:
                        seen_ids.add(mid)
                    payload["account"] = address
                    results.append(payload)
    finally:
        try:
            conn.logout()
        except Exception:
            pass
    return results


def fetch_receipt_emails(since_days: int = 14) -> list[dict]:
    """Fetch candidate receipt emails from the last ``since_days`` days.

    Scans every configured Gmail account (see :func:`load_accounts`) and merges
    the results, de-duplicating by Message-ID across accounts.
    """
    accounts = load_accounts()
    if not accounts:
        raise RuntimeError("GMAIL_ADDRESS / GMAIL_APP_PASSWORD not set in .env")

    rules = load_sender_rules()
    since = (date.today() - timedelta(days=since_days)).strftime("%d-%b-%Y")

    results: list[dict] = []
    seen_ids: set[str] = set()
    for address, password in accounts:
        results.extend(_fetch_from_account(address, password, rules, since, seen_ids))
    return results
