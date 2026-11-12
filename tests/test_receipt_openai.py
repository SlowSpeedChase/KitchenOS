"""OpenAI receipt routing and Responses API failure handling."""
import json
from types import SimpleNamespace

import pytest
from lib import receipt_parser as rp


@pytest.fixture(autouse=True)
def enable_llm(monkeypatch):
    monkeypatch.delenv('KITCHENOS_NO_LLM', raising=False)


def test_openai_key_takes_priority(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'test-key')
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    assert rp._default_llm_call() is rp._call_openai


def test_without_openai_preserves_existing_provider_selection(monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    assert rp._default_llm_call() is rp._call_claude
    monkeypatch.delenv('ANTHROPIC_API_KEY')
    assert rp._default_llm_call() is rp._call_ollama


def fake_client(monkeypatch, response):
    import openai
    calls = {}
    def create(**kwargs):
        calls.update(kwargs)
        return response
    def client(**kwargs):
        calls['client'] = kwargs
        return SimpleNamespace(responses=SimpleNamespace(create=create))
    monkeypatch.setattr(openai, 'OpenAI', client)
    return calls


def test_openai_returns_receipt_and_requests_strict_schema(monkeypatch):
    calls = fake_client(monkeypatch, SimpleNamespace(status='completed', output_text='{"items": []}'))
    monkeypatch.setenv('KITCHENOS_RECEIPT_MODEL', 'test-model')
    monkeypatch.setattr(rp.llm_gate, 'budget_s', lambda default: 3.0)
    assert json.loads(rp._call_openai('receipt text')) == {'items': []}
    assert calls['model'] == 'test-model'
    assert calls['input'] == 'receipt text'
    assert calls['store'] is False
    assert calls['client'] == {'timeout': 3.0, 'max_retries': 0}
    fmt = calls['text']['format']
    assert fmt['type'] == 'json_schema' and fmt['strict'] is True
    schema = fmt['schema']
    assert schema['additionalProperties'] is False
    assert set(schema['required']) == {'store', 'date', 'order_type', 'total', 'items'}
    assert schema['properties']['items']['items']['additionalProperties'] is False


@pytest.mark.parametrize('status,text', [('incomplete','{"items": []}'), ('completed','')])
def test_openai_rejects_incomplete_or_refused_response(monkeypatch, status, text):
    fake_client(monkeypatch, SimpleNamespace(status=status, output_text=text))
    with pytest.raises(ValueError):
        rp._call_openai('receipt')


def test_openai_obeys_disable_switch(monkeypatch):
    monkeypatch.setenv('KITCHENOS_NO_LLM', '1')
    with pytest.raises(RuntimeError, match='disabled'):
        rp._call_openai('receipt')


def test_openai_obeys_exhausted_budget(monkeypatch):
    monkeypatch.setattr(rp.llm_gate, 'budget_s', lambda default: 0)
    with pytest.raises(RuntimeError, match='budget'):
        rp._call_openai('receipt')
