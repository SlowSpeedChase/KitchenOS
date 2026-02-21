from main import get_thumbnail_url


class TestThumbnailURL:
    def test_thumbnail_url_constructed_from_video_id(self):
        """YouTube thumbnails follow a predictable URL pattern"""
        result = get_thumbnail_url("dQw4w9WgXcQ")
        assert result == "https://i.ytimg.com/vi/dQw4w9WgXcQ/maxresdefault.jpg"
