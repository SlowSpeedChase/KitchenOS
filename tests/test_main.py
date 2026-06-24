from main import get_thumbnail_url, instagram_parser


class TestThumbnailURL:
    def test_thumbnail_url_constructed_from_video_id(self):
        """YouTube thumbnails follow a predictable URL pattern"""
        result = get_thumbnail_url("dQw4w9WgXcQ")
        assert result == "https://i.ytimg.com/vi/dQw4w9WgXcQ/maxresdefault.jpg"


class TestInstagramParser:
    def test_reel_url(self):
        assert instagram_parser(
            "https://www.instagram.com/reel/DYzfNncApIv/"
        ) == {"reel_id": "DYzfNncApIv"}

    def test_reels_plural_url(self):
        assert instagram_parser(
            "https://instagram.com/reels/DYzfNncApIv/"
        ) == {"reel_id": "DYzfNncApIv"}

    def test_post_url(self):
        assert instagram_parser(
            "https://www.instagram.com/p/DYzfNncApIv/"
        ) == {"reel_id": "DYzfNncApIv"}

    def test_share_query_string_stripped(self):
        """Share URLs carry an ?igsh=... tracking param that isn't part of the ID."""
        assert instagram_parser(
            "https://www.instagram.com/reel/DYzfNncApIv/?igsh=MWUybnIzNXB1am93dg=="
        ) == {"reel_id": "DYzfNncApIv"}

    def test_youtube_url_returns_none(self):
        assert instagram_parser("https://www.youtube.com/watch?v=dQw4w9WgXcQ") is None

    def test_web_url_returns_none(self):
        assert instagram_parser("https://natashaskitchen.com/some-recipe/") is None

    def test_empty_returns_none(self):
        assert instagram_parser("") is None
