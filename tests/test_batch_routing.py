"""batch_extract URL routing precedence: youtube -> instagram -> web."""

from batch_extract import is_youtube_url
from main import instagram_parser


REEL = "https://www.instagram.com/reel/DYzfNncApIv/"
YT = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
WEB = "https://natashaskitchen.com/some-recipe/"


def test_instagram_reel_routes_to_reel_pipeline():
    # Not youtube (so it skips the youtube branch) and matches instagram
    # (so it hits the reel branch before falling through to the web scraper).
    assert not is_youtube_url(REEL)
    assert instagram_parser(REEL)


def test_youtube_takes_precedence_over_instagram():
    assert is_youtube_url(YT)


def test_web_url_falls_through_to_scraper():
    assert not is_youtube_url(WEB)
    assert instagram_parser(WEB) is None
