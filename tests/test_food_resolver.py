"""Tests for lib/food_resolver.py — constrained LLM jobs (mocked Ollama)."""

from unittest.mock import patch, Mock

from lib.food_resolver import resolve_food_llm, estimate_portion_grams_llm


def _ollama(payload: str):
    return Mock(status_code=200, json=lambda: {"response": payload})


class _Cand:
    def __init__(self, description):
        self.description = description


class TestResolveFoodLlm:
    def test_valid_choice(self):
        cands = [_Cand("Flour, bread"), _Cand("Flour, all-purpose")]
        with patch("lib.food_resolver.requests.post") as p:
            p.return_value = _ollama('{"choice_index": 1, "confidence": 0.9, "reason": "ap"}')
            result = resolve_food_llm("all-purpose flour", cands)
        assert result == (1, 0.9)

    def test_out_of_range_rejected(self):
        cands = [_Cand("Flour")]
        with patch("lib.food_resolver.requests.post") as p:
            p.return_value = _ollama('{"choice_index": 5, "confidence": 0.9}')
            assert resolve_food_llm("flour", cands) is None

    def test_confidence_clamped(self):
        cands = [_Cand("Flour")]
        with patch("lib.food_resolver.requests.post") as p:
            p.return_value = _ollama('{"choice_index": 0, "confidence": 1.7}')
            assert resolve_food_llm("flour", cands) == (0, 1.0)

    def test_empty_candidates(self):
        assert resolve_food_llm("flour", []) is None

    def test_garbage_response(self):
        cands = [_Cand("Flour")]
        with patch("lib.food_resolver.requests.post") as p:
            p.return_value = _ollama("not json at all")
            assert resolve_food_llm("flour", cands) is None


class TestEstimatePortionGramsLlm:
    def test_valid(self):
        with patch("lib.food_resolver.requests.post") as p:
            p.return_value = _ollama('{"grams_per_unit": 40, "confidence": 0.7, "basis": "shallot"}')
            assert estimate_portion_grams_llm("whole", "shallot") == (40.0, 0.7)

    def test_out_of_bounds_rejected(self):
        with patch("lib.food_resolver.requests.post") as p:
            p.return_value = _ollama('{"grams_per_unit": 99999, "confidence": 0.7}')
            assert estimate_portion_grams_llm("whole", "boulder") is None

    def test_non_numeric_rejected(self):
        with patch("lib.food_resolver.requests.post") as p:
            p.return_value = _ollama('{"grams_per_unit": "lots", "confidence": 0.7}')
            assert estimate_portion_grams_llm("whole", "shallot") is None


class TestProviderDispatch:
    def test_none_provider_returns_none(self):
        from lib.food_resolver import resolve_food, estimate_portion_grams
        assert resolve_food("x", [_Cand("y")], "none") is None
        assert estimate_portion_grams("whole", "x", None, "none") is None

    def test_ollama_dispatch(self):
        from lib.food_resolver import estimate_portion_grams
        with patch("lib.food_resolver.requests.post") as p:
            p.return_value = _ollama('{"grams_per_unit": 40, "confidence": 0.7}')
            assert estimate_portion_grams("whole", "shallot", None, "ollama") == (40.0, 0.7)

    def test_claude_dispatch_uses_validation(self):
        from lib.food_resolver import estimate_portion_grams
        # Mock the Claude JSON layer; validation (bounds/clamp) is shared.
        with patch("lib.food_resolver._claude_json",
                   return_value={"grams_per_unit": 40, "confidence": 1.5}):
            assert estimate_portion_grams("whole", "shallot", None, "claude") == (40.0, 1.0)

    def test_claude_resolution_out_of_range_rejected(self):
        from lib.food_resolver import resolve_food
        with patch("lib.food_resolver._claude_json",
                   return_value={"choice_index": 9, "confidence": 0.9}):
            assert resolve_food("flour", [_Cand("Flour")], "claude") is None
