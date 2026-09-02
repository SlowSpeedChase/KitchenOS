"""Contract tests for the shopping-list CLI's Reminders boundary."""

from shopping_list import prompt_pantry_decisions


def test_prompt_skips_unconfirmed_inventory_candidates():
    buy, decisions = prompt_pantry_decisions([
        {"item": "flour", "needed": {"amount": "1", "unit": "cup"},
         "from_pantry": None, "to_buy": {"amount": "1", "unit": "cup"},
         "matched_inventory": None},
        {"item": "shelled pistachios",
         "needed": {"amount": "0.33", "unit": "cup"},
         "from_pantry": None,
         "to_buy": {"amount": "0.33", "unit": "cup"},
         "matched_inventory": {"item": "Pistachios", "amount": "1", "unit": "ct"}},
    ])

    assert buy == [{"amount": "1", "unit": "cup", "item": "flour"}]
    assert decisions == []


def test_buy_fresh_uses_full_needed_amount(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt: "none")

    buy, decisions = prompt_pantry_decisions([
        {"item": "flaxseed", "needed": {"amount": "2", "unit": "cup"},
         "from_pantry": {"amount": "0.5", "unit": "cup"},
         "to_buy": {"amount": "1.5", "unit": "cup"},
         "matched_inventory": {"item": "Flaxseed", "amount": "0.5", "unit": "cup"}},
    ])

    assert buy == [{"amount": "2", "unit": "cup", "item": "flaxseed"}]
    assert decisions == []


def test_use_pantry_targets_the_matched_inventory_alias(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt: "all")

    buy, decisions = prompt_pantry_decisions([
        {"item": "mayonnaise", "needed": {"amount": "1", "unit": "cup"},
         "from_pantry": {"amount": "1", "unit": "cup"},
         "to_buy": None,
         "matched_inventory": {"item": "mayo", "amount": "2", "unit": "cup"}},
    ])

    assert buy == []
    assert decisions == [{"item": "mayo", "amount": "1", "unit": "cup"}]
