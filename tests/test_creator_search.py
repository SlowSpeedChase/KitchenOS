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


class TestSearchForRecipeUrl:
    """Tests for search_for_recipe_url function."""

    def test_constructs_site_restricted_query(self, mocker):
        """Should search with site: restriction when domain provided."""
        from recipe_sources import search_for_recipe_url

        # Mock DDGS
        mock_ddgs = mocker.patch("recipe_sources.DDGS")
        mock_instance = mock_ddgs.return_value.__enter__.return_value
        mock_instance.text.return_value = [
            {"href": "https://feelgoodfoodie.net/recipe/chocolate-peanut-butter-bars/"}
        ]

        result = search_for_recipe_url(
            channel="feelgoodfoodie",
            title="Chocolate Peanut Butter Bars",
            site="feelgoodfoodie.net"
        )

        # Check query includes site restriction
        call_args = mock_instance.text.call_args
        query = call_args[0][0]
        assert "site:feelgoodfoodie.net" in query
        assert result == "https://feelgoodfoodie.net/recipe/chocolate-peanut-butter-bars/"

    def test_constructs_open_query_without_site(self, mocker):
        """Should search without site restriction when domain not provided."""
        from recipe_sources import search_for_recipe_url

        mock_ddgs = mocker.patch("recipe_sources.DDGS")
        mock_instance = mock_ddgs.return_value.__enter__.return_value
        mock_instance.text.return_value = [
            {"href": "https://example.com/some-recipe/"}
        ]

        result = search_for_recipe_url(
            channel="unknown channel",
            title="Some Recipe"
        )

        call_args = mock_instance.text.call_args
        query = call_args[0][0]
        assert "site:" not in query
        assert "unknown channel" in query.lower()

    def test_filters_excluded_domains(self, mocker):
        """Should skip results from excluded domains like youtube.com."""
        from recipe_sources import search_for_recipe_url

        mock_ddgs = mocker.patch("recipe_sources.DDGS")
        mock_instance = mock_ddgs.return_value.__enter__.return_value
        mock_instance.text.return_value = [
            {"href": "https://www.youtube.com/watch?v=123"},
            {"href": "https://pinterest.com/pin/123"},
            {"href": "https://feelgoodfoodie.net/recipe/good-one/"}
        ]

        result = search_for_recipe_url(channel="test", title="test")

        assert result == "https://feelgoodfoodie.net/recipe/good-one/"

    def test_returns_none_on_no_results(self, mocker):
        """Should return None when search returns no valid results."""
        from recipe_sources import search_for_recipe_url

        mock_ddgs = mocker.patch("recipe_sources.DDGS")
        mock_instance = mock_ddgs.return_value.__enter__.return_value
        mock_instance.text.return_value = []

        result = search_for_recipe_url(channel="test", title="test")

        assert result is None

    def test_returns_none_on_timeout(self, mocker):
        """Should return None and not crash on timeout."""
        from recipe_sources import search_for_recipe_url

        mock_ddgs = mocker.patch("recipe_sources.DDGS")
        mock_instance = mock_ddgs.return_value.__enter__.return_value
        mock_instance.text.side_effect = Exception("Timeout")

        result = search_for_recipe_url(channel="test", title="test")

        assert result is None
