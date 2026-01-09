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


class TestSearchCreatorWebsite:
    """Tests for search_creator_website orchestrator."""

    def test_uses_mapped_domain_for_known_creator(self, mocker):
        """Should use domain from mapping for known creators."""
        from recipe_sources import search_creator_website

        # Mock the mapping
        mocker.patch("recipe_sources.load_creator_mapping", return_value={
            "feelgoodfoodie": "feelgoodfoodie.net"
        })
        mock_search = mocker.patch("recipe_sources.search_for_recipe_url")
        mock_search.return_value = "https://feelgoodfoodie.net/recipe/test/"

        result = search_creator_website("Feelgoodfoodie", "Test Recipe")

        mock_search.assert_called_once_with(
            channel="Feelgoodfoodie",
            title="Test Recipe",
            site="feelgoodfoodie.net"
        )
        assert result == "https://feelgoodfoodie.net/recipe/test/"

    def test_skips_search_for_null_mapped_creators(self, mocker):
        """Should return None without searching for creators mapped to null."""
        from recipe_sources import search_creator_website

        mocker.patch("recipe_sources.load_creator_mapping", return_value={
            "adam ragusea": None
        })
        mock_search = mocker.patch("recipe_sources.search_for_recipe_url")

        result = search_creator_website("Adam Ragusea", "Some Recipe")

        mock_search.assert_not_called()
        assert result is None

    def test_searches_without_site_for_unknown_creators(self, mocker):
        """Should search without site restriction for unmapped creators."""
        from recipe_sources import search_creator_website

        mocker.patch("recipe_sources.load_creator_mapping", return_value={})
        mock_search = mocker.patch("recipe_sources.search_for_recipe_url")
        mock_search.return_value = "https://example.com/recipe/"

        result = search_creator_website("Unknown Creator", "Test Recipe")

        mock_search.assert_called_once_with(
            channel="Unknown Creator",
            title="Test Recipe",
            site=None
        )

    def test_normalizes_channel_name_for_lookup(self, mocker):
        """Should normalize channel name (lowercase, strip) for mapping lookup."""
        from recipe_sources import search_creator_website

        mocker.patch("recipe_sources.load_creator_mapping", return_value={
            "feelgoodfoodie": "feelgoodfoodie.net"
        })
        mock_search = mocker.patch("recipe_sources.search_for_recipe_url")

        # Test with different casing and whitespace
        search_creator_website("  FeelGoodFoodie  ", "Test")

        mock_search.assert_called_once()
        assert mock_search.call_args[1]["site"] == "feelgoodfoodie.net"
