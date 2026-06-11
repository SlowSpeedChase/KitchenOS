"""Tests for lib/receipt_parser.py with a mocked Ollama call."""
import json
from pathlib import Path

import pytest

from lib import receipt_parser as rp

FIXTURES = Path(__file__).parent / "fixtures"

PARSED_OK = json.loads((FIXTURES / "parsed_ereceipt.json").read_text())


def test_email_to_text_strips_html():
    html = (FIXTURES / "heb_ereceipt.html").read_text()
    text = rp.email_to_text(html)
    assert "<td>" not in text
    assert "HCF BNLS SKNLS BRST" in text
    assert "TOTAL: $17.00" in text


def test_to_cents():
    assert rp.to_cents(11.53) == 1153
    assert rp.to_cents("3.98") == 398
    assert rp.to_cents(None) is None
    assert rp.to_cents(-2.00) == -200


def test_parse_receipt_text_uses_ollama():
    calls = {}

    def fake_ollama(prompt):
        calls["prompt"] = prompt
        return json.dumps(PARSED_OK)

    parsed = rp.parse_receipt_text("some receipt text", ollama_call=fake_ollama)
    assert parsed["date"] == "2026-06-09"
    assert len(parsed["items"]) == 4
    assert "some receipt text" in calls["prompt"]


def test_parse_receipt_text_rejects_non_object():
    with pytest.raises(ValueError):
        rp.parse_receipt_text("x", ollama_call=lambda p: "[1, 2]")


def test_validate_receipt_ok():
    ok, problems = rp.validate_receipt(PARSED_OK)
    assert ok is True
    assert problems == []


def test_validate_receipt_total_mismatch():
    bad = dict(PARSED_OK, total=99.99)
    ok, problems = rp.validate_receipt(bad)
    assert ok is False
    assert any("total" in p for p in problems)


def test_validate_receipt_missing_date():
    bad = dict(PARSED_OK, date=None)
    ok, problems = rp.validate_receipt(bad)
    assert ok is False


def test_validate_receipt_rejects_non_iso_date():
    bad = dict(PARSED_OK, date="06/09/2026")
    ok, problems = rp.validate_receipt(bad)
    assert ok is False
    assert any("format" in p or "YYYY" in p for p in problems)


def test_validate_receipt_no_items():
    bad = dict(PARSED_OK, items=[])
    ok, problems = rp.validate_receipt(bad)
    assert ok is False


def test_build_purchases_canonicalizes(tmp_path, monkeypatch):
    from lib import item_aliases
    monkeypatch.setattr(item_aliases, "ALIASES_PATH", tmp_path / "a.json")
    purchases = rp.build_purchases(PARSED_OK)
    assert purchases[0]["canonical_name"] == "chicken breast"
    assert purchases[0]["unit_price_cents"] == 549
    assert purchases[0]["total_cents"] == 1153
    assert purchases[3]["category"] == "fee"
