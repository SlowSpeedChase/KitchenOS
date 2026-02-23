"""Tests for meal suggestion engine."""

import json
from pathlib import Path


class TestPantryStaples:
    """Test pantry staples config loading."""

    def test_loads_pantry_staples(self):
        """Pantry staples config loads as a list of strings."""
        config_path = Path(__file__).parent.parent / "config" / "pantry_staples.json"
        with open(config_path) as f:
            staples = json.load(f)
        assert isinstance(staples, list)
        assert "salt" in staples
        assert "olive oil" in staples
        assert len(staples) >= 10
