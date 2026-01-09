"""Tests for creator website search functionality."""

import pytest
from pathlib import Path


class TestLoadCreatorMapping:
    """Tests for load_creator_mapping function."""

    def test_loads_mapping_from_config(self):
        """Should load channel → website mapping from JSON file."""
        from recipe_sources import load_creator_mapping

        mapping = load_creator_mapping()

        assert isinstance(mapping, dict)
        assert mapping.get("feelgoodfoodie") == "feelgoodfoodie.net"

    def test_returns_none_for_channels_without_sites(self):
        """Should return None for channels marked as having no site."""
        from recipe_sources import load_creator_mapping

        mapping = load_creator_mapping()

        # Adam Ragusea is mapped to null (no recipe site)
        assert "adam ragusea" in mapping
        assert mapping["adam ragusea"] is None

    def test_returns_empty_dict_if_config_missing(self, tmp_path, monkeypatch):
        """Should return empty dict and log warning if config file missing."""
        from recipe_sources import load_creator_mapping

        # Point to non-existent directory
        monkeypatch.setattr("recipe_sources.CONFIG_DIR", tmp_path / "nonexistent")

        mapping = load_creator_mapping()

        assert mapping == {}
