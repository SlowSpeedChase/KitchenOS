"""Tests for extraction pipeline routing.

Regression cover for the 2026-07-29 batch failure where
https://www.heb.com/recipe/recipe-detail/... was sent to the YouTube pipeline
by extract_recipe.py's CLI and failed with "Could not fetch video metadata".

batch_extract.py routed the same URL correctly, so the two disagreed: the CLI
documented in CLAUDE.md as "YouTube, Instagram Reel, or web URL — auto-detected"
had no web branch at all. route_url() is now the single rule both callers use.
"""
import pytest

from main import route_url, is_youtube_url


class TestIsYoutubeUrl:
    """is_youtube_url is the domain test, not a general URL test."""

    @pytest.mark.parametrize("url", [
        "https://www.youtube.com/watch?v=abc123",
        "https://youtu.be/abc123",
        "https://www.youtube.com/shorts/abc123",
        "HTTPS://WWW.YOUTUBE.COM/watch?v=abc123",
        "  https://youtu.be/abc123  ",
    ])
    def test_recognizes_youtube(self, url):
        assert is_youtube_url(url) is True

    @pytest.mark.parametrize("url", [
        "https://www.heb.com/recipe/recipe-detail/thai-style-larb-lettuce-wraps",
        "https://www.instagram.com/reel/DYSU8nkh5fu/",
        "https://www.seriouseats.com/pasta",
        "",
        None,
    ])
    def test_rejects_non_youtube(self, url):
        assert is_youtube_url(url) is False


class TestRouteUrl:
    """route_url classifies an input into exactly one pipeline."""

    def test_heb_recipe_url_routes_to_web(self):
        """The exact URL from the 2026-07-29 failure log must reach the scraper."""
        url = "https://www.heb.com/recipe/recipe-detail/thai-style-larb-lettuce-wraps"
        assert route_url(url) == "web"

    @pytest.mark.parametrize("url", [
        "https://www.seriouseats.com/pasta",
        "https://www.bonappetit.com/recipe/chicken",
        "http://example.com/recipe",
    ])
    def test_generic_web_urls_route_to_web(self, url):
        assert route_url(url) == "web"

    @pytest.mark.parametrize("url", [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ",
        "https://www.youtube.com/shorts/abc123",
    ])
    def test_youtube_urls_route_to_youtube(self, url):
        assert route_url(url) == "youtube"

    @pytest.mark.parametrize("url", [
        "https://www.instagram.com/reel/DYSU8nkh5fu/",
        "https://www.instagram.com/reel/DadGpdwq5od/?igsh=MTdweDRmOWR6emFoNw==",
        "https://www.instagram.com/p/DYSU8nkh5fu/",
        "https://www.instagram.com/reels/DYSU8nkh5fu/",
    ])
    def test_instagram_urls_route_to_instagram(self, url):
        assert route_url(url) == "instagram"

    def test_bare_video_id_still_routes_to_youtube(self):
        """`extract_recipe.py dQw4w9WgXcQ` must keep working — no scheme, not web."""
        assert route_url("dQw4w9WgXcQ") == "youtube"

    @pytest.mark.parametrize("value", ["", "   ", None])
    def test_empty_input_routes_to_youtube(self, value):
        """Degenerate input keeps the historical default rather than crashing."""
        assert route_url(value) == "youtube"

    def test_instagram_wins_over_web(self):
        """An instagram.com URL is http(s) too — the reel branch must win."""
        assert route_url("https://www.instagram.com/reel/ABC/") == "instagram"


class TestRoutersAgree:
    """The CLI and batch must not drift apart again."""

    def test_batch_extract_uses_shared_rule(self):
        """batch_extract must route through main.route_url, not its own copy."""
        import batch_extract
        import main
        assert batch_extract.route_url is main.route_url

    def test_batch_extract_defines_no_local_router(self):
        """A local is_youtube_url here is how the CLI and batch drifted before."""
        import batch_extract
        assert not hasattr(batch_extract, 'is_youtube_url')
