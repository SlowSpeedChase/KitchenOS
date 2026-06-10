"""Tests for lib/item_aliases.py."""
import json

from lib import item_aliases


def test_canonicalize_prefers_saved_alias(tmp_path, monkeypatch):
    p = tmp_path / "aliases.json"
    p.write_text(json.dumps({"hcf bnls sknls brst": "chicken breast"}))
    monkeypatch.setattr(item_aliases, "ALIASES_PATH", p)
    # saved alias wins over the model's suggestion
    assert item_aliases.canonicalize("HCF BNLS SKNLS BRST", "chicken") == "chicken breast"


def test_canonicalize_caches_model_suggestion(tmp_path, monkeypatch):
    p = tmp_path / "aliases.json"
    monkeypatch.setattr(item_aliases, "ALIASES_PATH", p)
    assert item_aliases.canonicalize("GV WHL MLK 1G", "whole milk") == "whole milk"
    assert json.loads(p.read_text())["gv whl mlk 1g"] == "whole milk"


def test_canonicalize_falls_back_to_cleaned_raw(tmp_path, monkeypatch):
    monkeypatch.setattr(item_aliases, "ALIASES_PATH", tmp_path / "a.json")
    assert item_aliases.canonicalize("  Bananas ", None) == "bananas"
