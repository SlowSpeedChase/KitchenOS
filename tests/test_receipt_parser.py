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


def test_parse_receipt_text_uses_injected_llm():
    calls = {}

    def fake_llm(prompt):
        calls["prompt"] = prompt
        return json.dumps(PARSED_OK)

    parsed = rp.parse_receipt_text("some receipt text", llm_call=fake_llm)
    assert parsed["date"] == "2026-06-09"
    assert len(parsed["items"]) == 4
    assert "some receipt text" in calls["prompt"]


def test_parse_receipt_text_rejects_non_object():
    with pytest.raises(ValueError):
        rp.parse_receipt_text("x", llm_call=lambda p: "[1, 2]")


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


def test_extract_json_object_strips_fences_and_prose():
    assert json.loads(rp._extract_json_object('```json\n{"a": 1}\n```'))["a"] == 1
    assert json.loads(rp._extract_json_object('Here you go:\n{"b": 2}\nDone'))["b"] == 2
    assert json.loads(rp._extract_json_object('{"c": 3}'))["c"] == 3


def test_default_llm_call_prefers_claude_when_key_set(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert rp._default_llm_call() is rp._call_claude
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert rp._default_llm_call() is rp._call_ollama
