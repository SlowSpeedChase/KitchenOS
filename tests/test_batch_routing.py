"""batch_extract URL routing precedence: youtube -> instagram -> web."""

from batch_extract import is_youtube_url, resolve_reminder_url
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


# --- resolve_reminder_url: iOS share-sheet reminders store the page title as
# the title and the link in the reminder URL field or notes. ---

def test_resolve_url_when_title_is_a_url():
    assert resolve_reminder_url(WEB) == WEB


def test_resolve_url_from_embedded_url_in_title():
    title = "Check out https://example.com/recipe today"
    assert resolve_reminder_url(title) == "https://example.com/recipe"


def test_resolve_url_from_url_field_when_title_is_page_name():
    # The reported failure: title is just the page name.
    title = "Chopped Italian Sliders on Hawaiian Rolls - Simply Made Eats"
    assert resolve_reminder_url(title, url_field=WEB) == WEB


def test_resolve_url_from_notes_when_title_and_field_empty():
    title = "Chopped Italian Sliders on Hawaiian Rolls - Simply Made Eats"
    notes = "Saved from Safari\nhttps://simplymadeeats.com/chopped-italian-sliders/"
    assert (
        resolve_reminder_url(title, notes=notes)
        == "https://simplymadeeats.com/chopped-italian-sliders/"
    )


def test_resolve_url_field_takes_precedence_over_notes():
    assert resolve_reminder_url("A title", url_field=WEB, notes="http://other.com/x") == WEB


def test_resolve_url_field_accepts_nsurl_like_object():
    class FakeNSURL:
        def absoluteString(self):
            return WEB

    assert resolve_reminder_url("A title", url_field=FakeNSURL()) == WEB


def test_resolve_url_none_when_no_url_anywhere():
    assert resolve_reminder_url("Just a plain recipe name", url_field=None, notes="no link here") is None


def test_resolve_url_handles_none_inputs():
    assert resolve_reminder_url(None, None, None) is None
